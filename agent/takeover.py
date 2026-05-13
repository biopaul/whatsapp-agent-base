# agent/takeover.py — Cliente del endpoint /takeover del plugin WP + cache local

"""
Maneja el flag mode=manual del plugin WP: cuando un humano toma una conversacion
desde Seguimiento, el agente Python deja de responder hasta que el TTL vence.

Cache in-memory con TTL diferenciado:
- Positivos (manual): trust until expires_at, no se re-pollea.
- Negativos (auto):   trust por POLL_INTERVAL_AUTO segundos, despues re-poll.

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


@dataclass
class TakeoverEntry:
    mode: Literal["auto", "manual"]
    expires_at: Optional[datetime] = None
    last_polled: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_manual_until: Optional[datetime] = None


_cache: dict[str, TakeoverEntry] = {}
_token_invalid: bool = False  # set True tras un 401; se limpia en restart


def _is_enabled() -> bool:
    return bool(TAKEOVER_URL_BASE) and not _token_invalid


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
        logger.info("Takeover: TAKEOVER_URL_BASE vacio - modo no-op, skipping preload")
        return

    url = f"{TAKEOVER_URL_BASE}/active"
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
    loaded = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        chat_id = item.get("chat_id")
        raw_exp = item.get("expires_at")
        if not isinstance(chat_id, str) or not isinstance(raw_exp, str):
            continue
        expires_at = _parse_iso(raw_exp)
        if expires_at is None or expires_at <= now:
            continue
        _cache[chat_id] = TakeoverEntry(
            mode="manual",
            expires_at=expires_at,
            last_polled=now,
        )
        loaded += 1
    logger.info(f"Takeover preload: {loaded} chats en manual mode cargados")


async def _poll_chat(chat_id: str) -> Optional[TakeoverEntry]:
    """
    Hace GET al endpoint /takeover/{chat_id}. Retorna TakeoverEntry o None si error.
    None significa: error de red/HTTP recuperable, el caller decide fail-open vs cache stale.
    """
    global _token_invalid
    url = f"{TAKEOVER_URL_BASE}/{chat_id}"
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

    return TakeoverEntry(mode=mode, expires_at=expires_at, last_polled=_now())


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
