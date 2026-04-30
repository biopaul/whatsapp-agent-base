# agent/config_loader.py — Carga config remota desde WP REST API con cache y fallback local

import os
import re
import time
import logging
import yaml
import httpx
from datetime import datetime, timedelta, timezone
from html import unescape

logger = logging.getLogger("agentkit")

CONFIG_URL = os.getenv("CONFIG_URL", "")

# TTL corto (60s) para capturar cambios de plan/pausa rapidamente.
# Ajustable via env var si se necesita mas agresividad o menos carga.
CACHE_TTL = int(os.getenv("CONFIG_CACHE_TTL", "60"))

_cache: dict | None = None
_cache_ts: float = 0.0
_local_config: dict | None = None

# Estado de pausa en memoria — actualizable inmediatamente desde /usage
# sin esperar al proximo GET /config.
_agent_paused: bool = False
_pause_reason: str | None = None

# Modelos por defecto para cada tier (OpenRouter model IDs).
# Se usan cuando el plan no tiene modelos configurados.
_DEFAULT_MODELS_QUICK = [
    "anthropic/claude-3-5-haiku",
    "openai/gpt-4o-mini",
]
_DEFAULT_MODELS_FULL = [
    "anthropic/claude-3-5-sonnet",
    "openai/gpt-4o",
]


def _fetch_remote() -> dict | None:
    if not CONFIG_URL:
        return None
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(CONFIG_URL)
        if resp.status_code == 200:
            data = resp.json()
            # Aceptar ambos schemas: config-v1 (actual) y config-v2 (nuevo con planes)
            schema = data.get("$schema", "")
            if schema in ("config-v1", "config-v2") or "system_prompt" in data or "prompts" in data:
                return data
            logger.warning(f"Remote config: schema desconocido {schema!r}")
            return None
        logger.warning(f"Remote config: HTTP {resp.status_code}")
        return None
    except Exception as e:
        logger.error(f"Remote config fetch failed: {e}")
        return None


def _load_local_yaml() -> dict:
    config: dict = {
        "$schema": "local",
        "agent": {"name": "", "tone": ""},
        "business": {"name": "", "description": "", "hours": "", "website": ""},
        "prompts": {
            "system_prompt": "Sos una asistente util. Responde en espanol.",
            "fallback_message": "Disculpa, no entendi tu mensaje.",
            "error_message": "Lo siento, problema tecnico.",
        },
        "notifications": {
            "notify_phone": os.getenv("NOTIFY_PHONE", ""),
            "notify_name": os.getenv("NOTIFY_NAME", ""),
        },
        "timezone": {
            "tz_offset": int(os.getenv("TZ_OFFSET", "-3")),
        },
    }
    try:
        with open("config/prompts.yaml", "r", encoding="utf-8") as f:
            prompts = yaml.safe_load(f) or {}
        config["prompts"]["system_prompt"] = prompts.get("system_prompt", config["prompts"]["system_prompt"])
        config["prompts"]["fallback_message"] = prompts.get("fallback_message", config["prompts"]["fallback_message"])
        config["prompts"]["error_message"] = prompts.get("error_message", config["prompts"]["error_message"])
    except FileNotFoundError:
        logger.warning("config/prompts.yaml no encontrado, usando defaults")
    try:
        with open("config/business.yaml", "r", encoding="utf-8") as f:
            biz = yaml.safe_load(f) or {}
        negocio = biz.get("negocio", {})
        config["business"]["name"] = negocio.get("nombre", "")
        config["business"]["description"] = negocio.get("descripcion", "")
        config["business"]["hours"] = negocio.get("horario", "")
        config["business"]["website"] = negocio.get("sitio_web", "")
        agente = biz.get("agente", {})
        config["agent"]["name"] = agente.get("nombre", "")
        config["agent"]["tone"] = agente.get("tono", "")
    except FileNotFoundError:
        logger.warning("config/business.yaml no encontrado, usando defaults")
    return config


def get_config() -> dict:
    """Config actual con cache. Prioridad: remoto > local YAML > defaults."""
    global _cache, _cache_ts, _local_config, _agent_paused, _pause_reason

    now = time.time()
    if _cache is not None and (now - _cache_ts) < CACHE_TTL:
        return _cache

    remote = _fetch_remote()
    if remote is not None:
        config = remote
    else:
        if _local_config is None:
            _local_config = _load_local_yaml()
        config = _local_config.copy()

    # Env vars siempre tienen prioridad (backward compat)
    if os.getenv("NOTIFY_PHONE"):
        config.setdefault("notifications", {})["notify_phone"] = os.getenv("NOTIFY_PHONE")
    if os.getenv("NOTIFY_NAME"):
        config.setdefault("notifications", {})["notify_name"] = os.getenv("NOTIFY_NAME")
    if os.getenv("TZ_OFFSET"):
        config.setdefault("timezone", {})["tz_offset"] = int(os.getenv("TZ_OFFSET"))

    # Sincronizar estado de pausa desde el config remoto
    if "agent_paused" in config:
        _agent_paused = bool(config["agent_paused"])
        _pause_reason = config.get("pause_reason")
        if _agent_paused:
            logger.info(f"Config: agente pausado — razon={_pause_reason!r}")

    _cache = config
    _cache_ts = now
    return config


# ---------------------------------------------------------------------------
# Pausa suave — actualizable sin esperar TTL (se llama desde usage_reporter)
# ---------------------------------------------------------------------------

def set_paused_state(paused: bool, reason: str | None = None) -> None:
    """Actualiza el estado de pausa en memoria de forma inmediata."""
    global _agent_paused, _pause_reason
    if paused and not _agent_paused:
        logger.warning(f"Agente pausado inmediatamente por respuesta /usage — razon={reason!r}")
    elif not paused and _agent_paused:
        logger.info("Agente reactivado via set_paused_state")
    _agent_paused = paused
    _pause_reason = reason


def is_agent_paused() -> bool:
    """True si el agente debe ignorar mensajes entrantes (soft pause)."""
    # Refrescar config si el cache expiro (sin bloquear)
    get_config()
    return _agent_paused


def get_pause_reason() -> str | None:
    return _pause_reason


# ---------------------------------------------------------------------------
# Helpers de configuracion
# ---------------------------------------------------------------------------

def _html_to_text(html: str) -> str:
    """Convierte HTML simple del editor WP a texto plano legible por la IA."""
    if "<" not in html:
        return html
    text = html
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</p>\s*<p[^>]*>", "\n\n", text)
    text = re.sub(r"</?p[^>]*>", "\n", text)
    text = re.sub(r"<li[^>]*>", "- ", text)
    text = re.sub(r"</li>", "\n", text)
    text = re.sub(r"</?[uo]l[^>]*>", "\n", text)
    text = re.sub(r"<strong[^>]*>(.*?)</strong>", r"**\1**", text)
    text = re.sub(r"<em[^>]*>(.*?)</em>", r"*\1*", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def get_system_prompt() -> str:
    cfg = get_config()
    # Nuevo schema: system_prompt a nivel raiz
    raw = cfg.get("system_prompt") or cfg.get("prompts", {}).get("system_prompt", "")
    return _html_to_text(raw)


def get_fallback_message() -> str:
    cfg = get_config()
    return cfg.get("prompts", {}).get("fallback_message", "Disculpa, no entendi.")


def get_error_message() -> str:
    cfg = get_config()
    return cfg.get("prompts", {}).get("error_message", "Problema tecnico.")


def get_notify_phone() -> str:
    return get_config().get("notifications", {}).get("notify_phone", "")


def get_notify_name() -> str:
    return get_config().get("notifications", {}).get("notify_name", "")


def get_tz_offset() -> int:
    """Offset en horas. Fallback a TZ_OFFSET env si no hay config remota."""
    cfg = get_config()
    tz = cfg.get("timezone", {})
    # Nuevo schema: timezone es string (IANA). Viejo: dict con tz_offset.
    if isinstance(tz, dict):
        return tz.get("tz_offset", int(os.getenv("TZ_OFFSET", "-3")))
    # Si es string IANA, intentar con zoneinfo; caer a env si falla
    if isinstance(tz, str) and tz:
        try:
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo(tz))
            return int(now.utcoffset().total_seconds() // 3600)
        except Exception:
            pass
    return int(os.getenv("TZ_OFFSET", "-3"))


def get_ai_models() -> dict:
    """
    Retorna listas de modelos OpenRouter para cada tier: quick (rapido/barato) y full (capaz).
    Prioridad: config remoto > defaults hardcoded.
    Si el config remoto no tiene modelos configurados, intenta backward compat con ai_model.
    """
    cfg = get_config()
    quick = cfg.get("models_quick") or []
    full = cfg.get("models_full") or []

    # Backward compat: si el config solo tiene ai_model (string viejo), usarlo en ambos tiers
    if not quick and not full:
        legacy = (cfg.get("ai_model") or os.getenv("AI_MODEL", "")).strip()
        if legacy:
            quick = [legacy]
            full = [legacy]

    return {
        "quick": quick if quick else _DEFAULT_MODELS_QUICK,
        "full": full if full else _DEFAULT_MODELS_FULL,
    }


def get_ai_model() -> str:
    """Backward compat: retorna el primer modelo full configurado."""
    return get_ai_models()["full"][0]


def get_capabilities() -> dict:
    """
    Retorna las capacidades habilitadas del agente.
    Defaults seguros: capabilities de texto on, media off (requieren config explicita).
    """
    defaults = {
        # Ya existentes
        "reactions":      True,
        "read_receipts":  True,
        # Nuevas — off por default hasta que el plan las habilite
        "audio_receive":  True,   # backward compat: ya teniamos audio
        "audio_send":     False,
        "image_receive":  False,
        "image_send":     False,
        "stickers":       False,
    }
    caps = get_config().get("capabilities", {})
    return {k: bool(caps.get(k, v)) for k, v in defaults.items()}


def get_limits() -> dict:
    """Retorna los limites del plan actual. 0 = sin limite."""
    defaults: dict = {
        "max_messages_month": 0,
        "max_chats_month":    0,
        "max_storage_mb":     0,
        "messages_used":      0,
        "chats_used":         0,
        "storage_used_bytes": 0,
        "period_start":       None,
        "period_end":         None,
    }
    limits = get_config().get("limits", {})
    return {**defaults, **{k: limits[k] for k in defaults if k in limits}}


def get_hours_slots() -> list[bool]:
    """
    Retorna lista de 24 booleanos desde business.hours_slots del config remoto.
    Fallback: todos True (24/7).
    """
    slots = get_config().get("business", {}).get("hours_slots")
    if (
        isinstance(slots, list)
        and len(slots) == 24
        and all(isinstance(v, bool) for v in slots)
    ):
        return slots
    return [True] * 24


def is_within_business_hours() -> bool:
    """True si la hora actual (segun tz del config) esta dentro del horario habilitado."""
    slots = get_hours_slots()
    tz_off = get_tz_offset()
    now_local = datetime.now(timezone(timedelta(hours=tz_off)))
    return slots[now_local.hour]


def get_out_of_hours_message() -> str:
    hours_str = get_config().get("business", {}).get("hours", "").strip()
    if hours_str:
        return f"Estamos fuera de horario de atencion. Nuestro horario es: {hours_str}. Deja tu consulta y te respondemos pronto."
    return "Estamos fuera de horario de atencion automatica. Deja tu consulta y te respondemos pronto."


def get_config_updated_at() -> str | None:
    """Fecha/hora de la ultima actualizacion de config en WP (UTC, formato MySQL)."""
    return get_config().get("config_updated_at") or None


def invalidate_cache() -> None:
    global _cache, _cache_ts
    _cache = None
    _cache_ts = 0.0


def get_active_connectors() -> list[dict]:
    """
    Retorna la lista de conectores activos para este agente.

    Cada item es un dict con: slug, enabled, configured, config_summary.
    Si no hay conectores en la config remota (caso de agentes sin connector framework),
    retorna lista vacía. Esto preserva backward compat: los agentes sin conectores
    pasan tools=None al LLM y se comportan idéntico a antes.
    """
    cfg = get_config()
    connectors = cfg.get("connectors", [])
    if not isinstance(connectors, list):
        return []
    return connectors
