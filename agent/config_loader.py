# agent/config_loader.py — Carga config remota desde WP REST API con cache y fallback local

import os
import time
import logging
import yaml
import httpx

logger = logging.getLogger("agentkit")

CONFIG_URL = os.getenv("CONFIG_URL", "")
CACHE_TTL = int(os.getenv("CONFIG_CACHE_TTL", "300"))

_cache: dict | None = None
_cache_ts: float = 0.0
_local_config: dict | None = None


def _fetch_remote() -> dict | None:
    if not CONFIG_URL:
        return None
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(CONFIG_URL)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("$schema") == "config-v1":
                return data
            logger.warning(f"Remote config: schema desconocido {data.get('$schema')}")
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
    global _cache, _cache_ts, _local_config

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

    _cache = config
    _cache_ts = now
    return config


def get_system_prompt() -> str:
    return get_config().get("prompts", {}).get("system_prompt", "")


def get_fallback_message() -> str:
    return get_config().get("prompts", {}).get("fallback_message", "Disculpa, no entendi.")


def get_error_message() -> str:
    return get_config().get("prompts", {}).get("error_message", "Problema tecnico.")


def get_notify_phone() -> str:
    return get_config().get("notifications", {}).get("notify_phone", "")


def get_notify_name() -> str:
    return get_config().get("notifications", {}).get("notify_name", "")


def get_tz_offset() -> int:
    return get_config().get("timezone", {}).get("tz_offset", -3)


def invalidate_cache() -> None:
    global _cache, _cache_ts
    _cache = None
    _cache_ts = 0.0
