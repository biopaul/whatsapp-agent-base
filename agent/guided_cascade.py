# agent/guided_cascade.py — Cascada de envio: buttons -> list -> texto numerado

"""
Aplica la cascada de presentacion segun el doc v0.3:
1. Si la sesion supports_buttons o should_probe_buttons, intentar buttons (max 3 opciones).
   - Si 200: ok, marcar supports=True. Si 501: marcar False, seguir.
2. Si la plantilla tiene <=10 opciones y should_probe_lists/supports_lists, intentar list.
   - Si 200: ok. Si error: seguir.
3. Caer a texto numerado con emojis 1-10 (siempre funciona).

Retorna dict {format_used, mensaje_id, error?}.
"""

import logging
from typing import Any

from agent import memory, waha_capabilities

logger = logging.getLogger("agentkit")

# Emojis numericos 1-10
_NUMERIC_EMOJIS = ["1⃣", "2⃣", "3⃣", "4⃣", "5⃣", "6⃣", "7⃣", "8⃣", "9⃣", "\U0001f51f"]


def render_texto_numerado(template: dict) -> str:
    """Render fallback de plantilla a texto numerado con emojis."""
    body = template.get("body_text", "")
    options = template.get("options", []) or []
    lines = [body, ""]
    for i, opt in enumerate(options[: len(_NUMERIC_EMOJIS)]):
        lines.append(f"{_NUMERIC_EMOJIS[i]} {opt.get('visible_text', '')}")
    footer = template.get("footer_text")
    if footer:
        lines.append("")
        lines.append(footer)
    return "\n".join(lines)


async def enviar_con_cascada(provider: Any, session_id: str, chat_id: str, template: dict) -> dict:
    """
    Aplica cascada de envio. Retorna {format_used, mensaje_id, error?}.

    format_used: "buttons" | "list" | "numbered_text"
    mensaje_id: id del proveedor (str) o None
    """
    options = template.get("options", []) or []
    body = template.get("body_text", "")
    footer = template.get("footer_text") or None

    # 1) BUTTONS (max 3)
    if len(options) <= 3:
        caps = await memory.get_waha_capabilities(session_id)
        try_buttons = caps["supports_buttons"] or await waha_capabilities.should_probe_buttons(session_id)
        if try_buttons:
            buttons = [{"id": f"opt_{o['id']}", "title": o.get("visible_text", "")[:20]} for o in options]
            try:
                ok, status, msg_id = await provider.enviar_buttons(chat_id, body, buttons, footer)
            except NotImplementedError:
                ok, status, msg_id = (False, None, None)

            if ok:
                await waha_capabilities.mark_capability(session_id, "supports_buttons", True)
                return {"format_used": "buttons", "mensaje_id": msg_id}
            if status == 501:
                await waha_capabilities.mark_capability(session_id, "supports_buttons", False)
                # seguir a list
            else:
                logger.warning(f"Buttons fail status={status}, fallback to list")

    # 2) LIST (max 10)
    if len(options) <= 10:
        caps = await memory.get_waha_capabilities(session_id)
        try_list = caps["supports_lists"] or await waha_capabilities.should_probe_lists(session_id)
        if try_list:
            rows = [
                {"id": f"opt_{o['id']}", "title": o.get("visible_text", "")[:24], "description": ""}
                for o in options
            ]
            sections = [{"title": "Opciones", "rows": rows}]
            try:
                ok, status, msg_id = await provider.enviar_list(chat_id, body, "Ver opciones", sections, footer)
            except NotImplementedError:
                ok, status, msg_id = (False, None, None)

            if ok:
                await waha_capabilities.mark_capability(session_id, "supports_lists", True)
                return {"format_used": "list", "mensaje_id": msg_id}
            if status is not None:
                await waha_capabilities.mark_capability(session_id, "supports_lists", False)

    # 3) TEXTO NUMERADO (siempre funciona)
    text = render_texto_numerado(template)
    msg_id = await provider.enviar_mensaje_returning_id(chat_id, text)
    return {"format_used": "numbered_text", "mensaje_id": msg_id}
