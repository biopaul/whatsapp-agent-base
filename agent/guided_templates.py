# agent/guided_templates.py — Cliente del endpoint /guided de WP + cache + tracking

"""
Lee plantillas guiadas activas del cliente desde WordPress.
TTL configurable (default 5min). Stale-while-revalidate ante errores de red.

Tambien expone funciones para registrar dispatches (POST) y selecciones (POST).
Estas son fire-and-forget — si fallan, loguean pero no rompen el flujo.
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

logger = logging.getLogger("agentkit")

GUIDED_URL_BASE = os.getenv("GUIDED_URL_BASE", "")
CACHE_TTL_SEC = int(os.getenv("GUIDED_CACHE_TTL", "300"))
HTTP_TIMEOUT = float(os.getenv("GUIDED_HTTP_TIMEOUT", "5"))

_cache: list[dict] = []
_cache_at: Optional[datetime] = None


def _is_enabled() -> bool:
    return bool(GUIDED_URL_BASE)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def invalidate_cache() -> None:
    global _cache, _cache_at
    _cache = []
    _cache_at = None


async def get_active() -> list[dict]:
    """
    Retorna lista de plantillas activas. Cache TTL CACHE_TTL_SEC.
    Stale-while-revalidate: si la red falla y hay cache previa, retorna stale.
    """
    global _cache, _cache_at
    if not _is_enabled():
        return []

    now = _now()
    if _cache_at is not None and (now - _cache_at).total_seconds() < CACHE_TTL_SEC:
        return _cache

    url = f"{GUIDED_URL_BASE}/active"
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.get(url)
    except Exception as e:
        logger.warning(f"Guided fetch: red error {type(e).__name__} - {e}")
        return _cache  # stale

    if r.status_code != 200:
        logger.warning(f"Guided fetch: HTTP {r.status_code}")
        return _cache  # stale

    try:
        data = r.json()
    except Exception as e:
        logger.warning(f"Guided fetch: JSON invalido - {e}")
        return _cache

    if not isinstance(data, list):
        logger.warning("Guided fetch: response no es lista")
        return _cache

    _cache = data
    _cache_at = now
    logger.info(f"Guided fetch: {len(data)} plantillas activas cargadas")
    return _cache


def find_by_name(name: str) -> Optional[dict]:
    """Busca una plantilla por name en el cache. Retorna None si no esta."""
    name = (name or "").strip()
    if not name:
        return None
    for t in _cache:
        if (t.get("name") or "").strip() == name:
            return t
    return None


def find_by_id(template_id: int) -> Optional[dict]:
    """Busca una plantilla por id en el cache."""
    for t in _cache:
        if int(t.get("id", -1)) == template_id:
            return t
    return None


async def register_dispatch(
    template_id: int, session_id: str, chat_id: str,
    format_used: str, dispatched_at: datetime
) -> Optional[int]:
    """
    POST al endpoint dispatch. Retorna dispatch_id o None si falla.
    Fire-and-forget — no rompe flujo si el plugin esta caido.
    """
    if not _is_enabled():
        return None
    url = f"{GUIDED_URL_BASE}/dispatch"
    payload = {
        "template_id": template_id,
        "session_id": session_id,
        "chat_id": chat_id,
        "format_used": format_used,
        "dispatched_at": dispatched_at.isoformat().replace("+00:00", "Z"),
    }
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.post(url, json=payload)
    except Exception as e:
        logger.warning(f"Guided register_dispatch: red error - {e}")
        return None
    if r.status_code != 200:
        logger.warning(f"Guided register_dispatch: HTTP {r.status_code}")
        return None
    try:
        data = r.json()
    except Exception:
        return None
    did = data.get("dispatch_id")
    return int(did) if isinstance(did, int) else None


async def register_selection(
    dispatch_id: int, option_id: int, selected_at: datetime
) -> bool:
    """POST selection. Retorna True si OK, False si falla. Fire-and-forget."""
    if not _is_enabled():
        return False
    url = f"{GUIDED_URL_BASE}/dispatch/{dispatch_id}/selection"
    payload = {
        "option_id": option_id,
        "selected_at": selected_at.isoformat().replace("+00:00", "Z"),
    }
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.post(url, json=payload)
    except Exception as e:
        logger.warning(f"Guided register_selection: red error - {e}")
        return False
    return r.status_code == 200
