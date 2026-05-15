# agent/guided_actions.py — Ejecuta la accion asociada a una opcion seleccionada

"""
Catalogo de acciones (per doc v0.3):
- text: el sistema simula que el usuario escribio action_payload['text'].
        Se devuelve injected_text al caller para que lo reinyecte al LLM.
- handoff: TODO real — por ahora envia mensaje "te paso con un humano" y loguea.
- template: dispara la sub-plantilla nombrada en action_payload['template_name'].
- calendar: STUB — envia mensaje descriptivo, deja TODO para integracion gcal.
- mercadopago: STUB — idem.
"""

import logging
from typing import Any

logger = logging.getLogger("agentkit")


async def ejecutar_accion(
    option: dict, chat_id: str, session_id: str, provider: Any,
    parent_dispatch_local_id: int | None = None,
) -> dict:
    """
    Ejecuta la accion de una opcion seleccionada.
    Retorna dict con kind y datos para el caller.

    kind values:
    - "text_injection" — caller debe reinyectar injected_text al LLM como user message
    - "handoff" — accion ejecutada (mensaje al user enviado)
    - "template" — sub-plantilla disparada
    - "calendar_stub" / "mercadopago_stub" — stub ejecutado
    - "unknown" — action_type desconocido
    """
    action_type = (option.get("action_type") or "text").lower()
    payload = option.get("action_payload") or {}

    if action_type == "text":
        text = payload.get("text") or option.get("visible_text") or ""
        return {"kind": "text_injection", "injected_text": text}

    if action_type == "handoff":
        msg = payload.get("message") or "Te paso con una persona en un momento."
        await provider.enviar_mensaje_returning_id(chat_id, msg)
        logger.info(f"Guided action handoff: chat={chat_id} opt={option.get('id')}")
        # TODO: integrar con plugin endpoint para marcar takeover desde aca
        return {"kind": "handoff"}

    if action_type == "template":
        # Import local para evitar ciclos
        from agent import guided_dispatcher
        sub_name = payload.get("template_name")
        if not sub_name:
            logger.warning("Guided action template: action_payload sin template_name")
            return {"kind": "template", "ok": False}
        result = await guided_dispatcher.dispatch_plantilla(
            provider=provider, session_id=session_id,
            chat_id=chat_id, name=sub_name,
            parent_local_id=parent_dispatch_local_id,
        )
        return {"kind": "template", "ok": result.get("ok", False)}

    if action_type == "calendar":
        msg = payload.get("message") or "Te paso al flujo de agendamiento. (Pronto disponible.)"
        await provider.enviar_mensaje_returning_id(chat_id, msg)
        logger.info(f"Guided action calendar STUB: chat={chat_id} opt={option.get('id')} payload={payload}")
        # TODO: integrar con connector gcal cuando este cableado
        return {"kind": "calendar_stub"}

    if action_type == "mercadopago":
        msg = payload.get("message") or "Te paso al flujo de pago. (Pronto disponible.)"
        await provider.enviar_mensaje_returning_id(chat_id, msg)
        logger.info(f"Guided action mercadopago STUB: chat={chat_id} opt={option.get('id')} payload={payload}")
        # TODO: integrar con MercadoPago cuando exista
        return {"kind": "mercadopago_stub"}

    logger.warning(f"Guided action: action_type desconocido '{action_type}'")
    return {"kind": "unknown"}
