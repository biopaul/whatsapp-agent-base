# agent/outbound.py — Rastrea envios recientes del agente via WAHA API
#
# Sirve para distinguir el eco WAHA fromMe del agente (mensaje que el agente
# acaba de mandar, llega de vuelta como webhook) vs un humano escribiendo
# desde WhatsApp Web/app cuando WAHA no envia el campo `source`.
#
# Ventana corta (45s) - los webhooks de eco generalmente llegan en <5s.

import time

WINDOW_SEC = 45
_recent: dict[str, float] = {}


def register_agent_outbound(chat_id: str) -> None:
    """Marca que el agente acaba de enviar un mensaje a este chat."""
    if not chat_id:
        return
    _recent[chat_id] = time.time()


def is_recent_agent_outbound(chat_id: str) -> bool:
    """True si el agente envio algo a este chat en los ultimos WINDOW_SEC."""
    if not chat_id:
        return False
    ts = _recent.get(chat_id)
    if ts is None:
        return False
    if (time.time() - ts) > WINDOW_SEC:
        _recent.pop(chat_id, None)
        return False
    return True


def clear_outbound(chat_id: str | None = None) -> None:
    """Limpia el registro (util para tests)."""
    if chat_id:
        _recent.pop(chat_id, None)
    else:
        _recent.clear()
