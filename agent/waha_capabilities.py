# agent/waha_capabilities.py — Cache + probe periodico de capabilities WAHA por sesion

"""
Trackea por session_id si WAHA soporta sendButtons / sendList.

Defaults (per doc 0.3, mayo 2026):
- supports_buttons=False (GOWS actual devuelve 501)
- supports_lists=True (WAHA 2025.8+ lo soporta en GOWS Plus)

Probe automatico: cada 24h, en el primer intento de envio, reintentamos el
nivel superior aunque este en False. Si funciona, marcamos True permanente.
"""

import logging
from datetime import datetime, timedelta, timezone

from agent import memory

logger = logging.getLogger("agentkit")

PROBE_INTERVAL_HOURS = 24


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def should_probe_buttons(session_id: str) -> bool:
    """
    True si conviene intentar buttons:
    - Nunca probado: True (queremos saber).
    - Marcado True: False (ya sabemos que funcionan, no hace falta probe).
    - Marcado False + paso >24h del ultimo probe: True (probe periodico).
    - Marcado False + <24h: False (respetar cache).
    """
    caps = await memory.get_waha_capabilities(session_id)
    if caps["supports_buttons"]:
        return False
    last = caps["last_buttons_probe"]
    if last is None:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (_now() - last) >= timedelta(hours=PROBE_INTERVAL_HOURS)


async def should_probe_lists(session_id: str) -> bool:
    """Analogo a should_probe_buttons pero para lists."""
    caps = await memory.get_waha_capabilities(session_id)
    if caps["supports_lists"]:
        # Default es True; reprobamos solo si alguna vez fue marcado False
        last = caps["last_lists_probe"]
        return last is None  # primera vez = probar (caso default v1+)
    last = caps["last_lists_probe"]
    if last is None:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (_now() - last) >= timedelta(hours=PROBE_INTERVAL_HOURS)


async def mark_capability(session_id: str, capability: str, value: bool) -> None:
    """
    Marca el resultado de un probe. capability: 'supports_buttons' o 'supports_lists'.
    """
    await memory.set_waha_capability(session_id, capability, value, probe_at=_now())
    logger.info(f"WAHA caps: session={session_id} {capability}={value}")
