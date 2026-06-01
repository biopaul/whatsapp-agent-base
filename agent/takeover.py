# agent/takeover.py — Cliente del endpoint /takeover del plugin WP + cache local

"""
Maneja dos flags ortogonales del plugin WP, ambos servidos por GET /takeover/{chat_id}:

1) mode=manual: cuando un humano toma una conversacion desde Seguimiento, el agente
   Python deja de responder hasta que el TTL vence.

2) is_customer: cuando un humano marca el contacto como cliente convertido. El
   agente sigue respondiendo pero cambia su filosofia (soporte vs venta).

Cache in-memory con TTL diferenciado:
- Positivos (manual): trust until expires_at, no se re-pollea.
- Negativos (auto):   trust por POLL_INTERVAL_AUTO segundos, despues re-poll.
- Customer cache se actualiza en el mismo poll que el takeover cache.

Modo no-op: si TAKEOVER_URL_BASE no esta seteado, el modulo retorna False siempre
(util para dev local sin plugin desplegado).
"""

import os
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

import httpx

logger = logging.getLogger("agentkit")

# Configuracion
TAKEOVER_URL_BASE = os.getenv("TAKEOVER_URL_BASE", "")
POLL_INTERVAL_AUTO = int(os.getenv("TAKEOVER_POLL_AUTO_TTL", "30"))  # segundos
AWARENESS_LOOKBACK_MIN = int(os.getenv("TAKEOVER_AWARENESS_LOOKBACK", "60"))  # minutos
HTTP_TIMEOUT = float(os.getenv("TAKEOVER_HTTP_TIMEOUT", "5"))  # segundos
# Default TTL (en minutos) usado solo si el POST /manual responde sin expires_at
# parseable. El plugin WP define el TTL real (actualmente 40min).
MANUAL_FALLBACK_TTL_MIN = int(os.getenv("TAKEOVER_MANUAL_TTL_MIN", "40"))


def _resolve_takeover_base() -> str:
    """
    Resuelve la URL base de /takeover/{token}. Prioridad:
      1. TAKEOVER_URL_BASE explicito (env existente).
      2. Derivacion desde CONFIG_URL (...wp-json/gowap/v1/config/{token}
         -> ...wp-json/gowap/v1/takeover/{token}).
    Retorna string vacio si ninguno disponible.
    """
    if TAKEOVER_URL_BASE:
        return TAKEOVER_URL_BASE.rstrip("/")
    config_url = os.getenv("CONFIG_URL", "").strip()
    if "/config/" not in config_url:
        return ""
    prefix, token = config_url.rsplit("/config/", 1)
    token = token.rstrip("/")
    if not token:
        return ""
    return f"{prefix}/takeover/{token}"


@dataclass
class TakeoverEntry:
    mode: Literal["auto", "manual"]
    expires_at: Optional[datetime] = None
    last_polled: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_manual_until: Optional[datetime] = None


@dataclass
class CustomerEntry:
    """Estado de cliente convertido. Poblado desde la misma llamada GET /takeover/{chat_id}."""
    is_customer: bool
    customer_since: Optional[datetime] = None
    # Marcamos cuando observamos transicion False -> True. None significa: estado inicial,
    # no hubo conversion observada (puede ser un cliente preexistente cargado por preload).
    customer_converted_at: Optional[datetime] = None
    last_polled: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_cache: dict[str, TakeoverEntry] = {}
_customer_cache: dict[str, CustomerEntry] = {}
_token_invalid: bool = False  # set True tras un 401; se limpia en restart


def _is_enabled() -> bool:
    return bool(_resolve_takeover_base()) and not _token_invalid


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def is_chat_in_manual_mode(chat_id: str) -> bool:
    """
    Retorna True si el chat esta en manual mode segun el plugin.
    Politica de cache:
    - Manual con expires_at futuro: trust until expires.
    - Auto: trust POLL_INTERVAL_AUTO segundos.
    - Sin cache o cache vencida: re-poll.
    - Fail-open: si la red falla y no hay cache util, asume auto.
    """
    if not _is_enabled():
        return False

    now = _now()
    entry = _cache.get(chat_id)

    # Cache hit valido?
    if entry is not None:
        if entry.mode == "manual" and entry.expires_at and entry.expires_at > now:
            return True
        if entry.mode == "auto" and (now - entry.last_polled).total_seconds() < POLL_INTERVAL_AUTO:
            return False

    # Necesitamos pollear
    new_entry = await _poll_chat(chat_id)
    if new_entry is None:
        # Network error o token invalido: usar stale si existe
        if entry is not None:
            return entry.mode == "manual" and bool(entry.expires_at) and entry.expires_at > now
        return False  # fail-open sin cache previa

    # Si veniamos de manual y ahora es auto, guardamos last_manual_until
    if entry is not None and entry.mode == "manual" and new_entry.mode == "auto":
        new_entry.last_manual_until = entry.expires_at
    elif entry is not None and entry.last_manual_until is not None:
        new_entry.last_manual_until = entry.last_manual_until

    _cache[chat_id] = new_entry

    if new_entry.mode == "manual" and new_entry.expires_at and new_entry.expires_at > now:
        return True
    return False


def is_chat_customer(chat_id: str) -> tuple[bool, Optional[datetime]]:
    """
    Lectura sync del estado de cliente. Retorna (is_customer, customer_since).
    Si el chat no esta en la cache, asume (False, None) — fail-open consistente.
    Se asume que el caller ya invoco is_chat_in_manual_mode() previamente para
    refrescar la cache (ambas caches se actualizan en el mismo poll).
    """
    entry = _customer_cache.get(chat_id)
    if entry is None:
        return (False, None)
    return (entry.is_customer, entry.customer_since)


def was_recently_converted(chat_id: str) -> bool:
    """
    True si observamos una transicion False -> True para este chat dentro de los
    ultimos AWARENESS_LOOKBACK_MIN minutos. Sirve para inyectar la linea extra al
    system prompt cuando el cliente se convirtio mid-stream.
    """
    entry = _customer_cache.get(chat_id)
    if entry is None or entry.customer_converted_at is None:
        return False
    cutoff = _now() - timedelta(minutes=AWARENESS_LOOKBACK_MIN)
    return entry.customer_converted_at > cutoff


def was_recently_manual(chat_id: str) -> Optional[tuple[datetime, datetime]]:
    """
    Si el chat estuvo (o esta) en manual en los ultimos AWARENESS_LOOKBACK_MIN minutos,
    retorna (start, end) del periodo.

    - Si esta actualmente en manual: end = now, start = last_polled (aprox).
    - Si volvio a auto pero last_manual_until esta dentro del window: end = last_manual_until,
      start = end - (AWARENESS_LOOKBACK_MIN minutos) (aprox conservadora).
    - Sino: None.
    """
    entry = _cache.get(chat_id)
    if entry is None:
        return None

    now = _now()
    cutoff = now - timedelta(minutes=AWARENESS_LOOKBACK_MIN)

    # Caso 1: actualmente en manual
    if entry.mode == "manual" and entry.expires_at and entry.expires_at > now:
        return (entry.last_polled, now)

    # Caso 2: volvio a auto pero hubo manual reciente
    if entry.last_manual_until is not None and entry.last_manual_until > cutoff:
        start = entry.last_manual_until - timedelta(minutes=AWARENESS_LOOKBACK_MIN)
        return (start, entry.last_manual_until)

    return None


async def preload_active() -> None:
    """
    Al startup, fetch la lista de chats actualmente en manual y los carga en cache.
    Si falla, log warning y sigue (cache se va poblando on-demand).
    """
    global _token_invalid
    if not _is_enabled():
        logger.info("Takeover: URL base vacia - modo no-op, skipping preload")
        return

    url = f"{_resolve_takeover_base()}/active"
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.get(url)
    except Exception as e:
        logger.warning(f"Takeover preload: red error {type(e).__name__} - {e}")
        return

    if r.status_code == 401:
        logger.error("Takeover preload: token invalido (401). Modulo deshabilitado.")
        _token_invalid = True
        return

    if r.status_code != 200:
        logger.warning(f"Takeover preload: HTTP {r.status_code}")
        return

    try:
        items = r.json()
    except Exception as e:
        logger.warning(f"Takeover preload: JSON invalido - {e}")
        return

    if not isinstance(items, list):
        logger.warning("Takeover preload: response no es una lista")
        return

    now = _now()
    loaded_manual = 0
    loaded_customer = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        chat_id = item.get("chat_id")
        if not isinstance(chat_id, str):
            continue

        # Manual takeover: solo carga si mode=manual y expires_at vigente.
        if item.get("mode") == "manual":
            raw_exp = item.get("expires_at")
            expires_at = _parse_iso(raw_exp) if isinstance(raw_exp, str) else None
            if expires_at is not None and expires_at > now:
                _cache[chat_id] = TakeoverEntry(
                    mode="manual",
                    expires_at=expires_at,
                    last_polled=now,
                )
                loaded_manual += 1

        # Customer flag: ortogonal al manual, mismo entry puede traer ambos.
        if item.get("is_customer"):
            _update_customer_cache_from_response(chat_id, item)
            loaded_customer += 1

    logger.info(
        f"Takeover preload: {loaded_manual} chats en manual mode, "
        f"{loaded_customer} chats marcados como cliente cargados"
    )


async def _poll_chat(chat_id: str) -> Optional[TakeoverEntry]:
    """
    Hace GET al endpoint /takeover/{chat_id}. Retorna TakeoverEntry o None si error.
    None significa: error de red/HTTP recuperable, el caller decide fail-open vs cache stale.
    """
    global _token_invalid
    base = _resolve_takeover_base()
    if not base:
        return None
    # URL-encode chat_id para path-safe (chat ids contienen @).
    from urllib.parse import quote
    url = f"{base}/{quote(chat_id, safe='')}"
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.get(url)
    except (httpx.TimeoutException, httpx.HTTPError, httpx.NetworkError) as e:
        logger.warning(f"Takeover poll {chat_id}: red error {type(e).__name__} - {e}")
        return None
    except Exception as e:
        logger.warning(f"Takeover poll {chat_id}: error inesperado {e}")
        return None

    if r.status_code == 401:
        logger.error("Takeover poll: token invalido (401). Modulo deshabilitado hasta restart.")
        _token_invalid = True
        return None

    if r.status_code == 404:
        # Chat desconocido para el plugin = mode=auto
        return TakeoverEntry(mode="auto", last_polled=_now())

    if r.status_code != 200:
        logger.warning(f"Takeover poll {chat_id}: HTTP {r.status_code} - {r.text[:200]}")
        return None

    try:
        body = r.json()
    except Exception as e:
        logger.warning(f"Takeover poll {chat_id}: JSON invalido - {e}")
        return None

    mode = body.get("mode", "auto")
    if mode not in ("auto", "manual"):
        logger.warning(f"Takeover poll {chat_id}: mode desconocido '{mode}' - tratando como auto")
        mode = "auto"

    expires_at = None
    if mode == "manual":
        raw = body.get("expires_at")
        if isinstance(raw, str) and raw:
            expires_at = _parse_iso(raw)
        if expires_at is None:
            logger.warning(f"Takeover poll {chat_id}: manual sin expires_at valido - tratando como auto")
            mode = "auto"

    # Update customer cache (mismo poll, response extendida con is_customer/customer_since)
    _update_customer_cache_from_response(chat_id, body)

    return TakeoverEntry(mode=mode, expires_at=expires_at, last_polled=_now())


def _update_customer_cache_from_response(chat_id: str, body: dict) -> None:
    """
    Actualiza _customer_cache a partir del body del endpoint /takeover/{chat_id} o
    de un item de /active. Detecta transicion False -> True para marcar
    customer_converted_at y permitir el aviso "recien convertido" al LLM.
    """
    is_customer = bool(body.get("is_customer", False))
    customer_since = None
    raw_since = body.get("customer_since")
    if isinstance(raw_since, str) and raw_since:
        customer_since = _parse_iso(raw_since)

    now = _now()
    prev = _customer_cache.get(chat_id)

    converted_at: Optional[datetime] = None
    if prev is not None:
        if not prev.is_customer and is_customer:
            # Transicion observada en esta sesion del agente.
            converted_at = now
        elif prev.is_customer and is_customer:
            # Preservar el marcador previo si existia.
            converted_at = prev.customer_converted_at
        # Si is_customer paso a False, converted_at queda en None.
    # Si no habia entry previa, no marcamos converted_at (puede ser cliente preexistente).

    _customer_cache[chat_id] = CustomerEntry(
        is_customer=is_customer,
        customer_since=customer_since,
        customer_converted_at=converted_at,
        last_polled=now,
    )


def _parse_iso(s: str) -> Optional[datetime]:
    """Parsea ISO 8601 con sufijo Z o +HH:MM. Retorna timezone-aware UTC."""
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# External takeover registration (POST /takeover/{token}/manual)
#
# Se invoca cuando el parser WAHA detecta un mensaje fromMe con source=app
# (humano escribiendo desde WhatsApp Web/app nativa fuera del agente).
# WordPress actualiza el takeover a manual con TTL del lado plugin.
# ---------------------------------------------------------------------------


async def register_manual_takeover(chat_id: str) -> bool:
    """
    Activa takeover manual en WP via POST /takeover/{token}/manual.
    En exito, refresca el cache local a manual=True con el expires_at del response
    (o un default fallback) para que la proxima lectura sea inmediata sin re-poll.
    Fail-open: si la red/HTTP falla, retorna False y loggea warning; no crashea.
    """
    global _token_invalid
    if not _is_enabled():
        return False

    base = _resolve_takeover_base()
    if not base:
        return False

    url = f"{base}/manual"
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.post(url, json={"chat_id": chat_id})
    except Exception as e:
        logger.warning(f"Takeover register_manual {chat_id}: red error {type(e).__name__} - {e}")
        return False

    if r.status_code == 401:
        logger.error("Takeover register_manual: token invalido (401). Modulo deshabilitado.")
        _token_invalid = True
        return False

    if r.status_code != 200:
        logger.warning(f"Takeover register_manual {chat_id}: HTTP {r.status_code} - {r.text[:200]}")
        return False

    # Parsear expires_at del response, con fallback al TTL configurado.
    expires_at = None
    try:
        body = r.json()
        raw_exp = body.get("expires_at")
        if isinstance(raw_exp, str) and raw_exp:
            expires_at = _parse_iso(raw_exp)
    except Exception:
        pass

    if expires_at is None:
        expires_at = _now() + timedelta(minutes=MANUAL_FALLBACK_TTL_MIN)

    _cache[chat_id] = TakeoverEntry(
        mode="manual",
        expires_at=expires_at,
        last_polled=_now(),
    )
    logger.info(f"Takeover manual registrado por envio externo: {chat_id} hasta {expires_at.isoformat()}")
    return True


def should_register_external_takeover(msg) -> bool:
    """
    Heuristica para mensajes salientes (fromMe=True):
      - source == "app"  -> True  (WhatsApp Web / app nativa, humano)
      - source == "api"  -> False (eco WAHA: agente o Seguimiento; WP ya marca manual
                                   desde Seguimiento, el agente no necesita duplicar)
      - source vacio     -> True solo si NO hay envio reciente del agente en ventana
                            y hay contenido (texto o media). Conservador.

    Importa outbound lazy para evitar ciclos.
    """
    from agent import outbound

    if not getattr(msg, "es_propio", False):
        return False

    source = (getattr(msg, "source", "") or "").lower()
    if source == "app":
        return True
    if source == "api":
        return False

    # Source vacio (WAHA antiguo / engines sin source): usar tracker outbound.
    if outbound.is_recent_agent_outbound(getattr(msg, "telefono", "")):
        return False
    return bool(getattr(msg, "texto", "") or getattr(msg, "tiene_media", False))


# Alias para alinear nombre con la spec del brief sin romper call-sites existentes.
is_manual_takeover = is_chat_in_manual_mode
