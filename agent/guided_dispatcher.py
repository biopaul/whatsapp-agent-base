# agent/guided_dispatcher.py — Parsea respuesta del LLM y dispatcha plantillas

"""
Cuando el LLM responde con <plantilla>nombre</plantilla>, este modulo:
1. Extrae el nombre.
2. Busca la plantilla en el cache de guided_templates.
3. Aplica la cascada de envio via guided_cascade.
4. Registra dispatch remoto (POST a WP) + local (memory.guardar_dispatch_local).
"""

import os
import re
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from agent import guided_cascade, guided_templates, memory

logger = logging.getLogger("agentkit")

SELECTION_WINDOW_MIN = int(os.getenv("GUIDED_SELECTION_WINDOW_MIN", "10"))

_PLANTILLA_RE = re.compile(r"<plantilla>\s*([^<]+?)\s*</plantilla>", re.IGNORECASE)


def parse_plantilla_invocation(text: str) -> Optional[str]:
    """Extrae el nombre de plantilla de un texto del LLM, o None si no hay."""
    if not text:
        return None
    m = _PLANTILLA_RE.search(text)
    if not m:
        return None
    name = m.group(1).strip()
    return name if name else None


async def dispatch_plantilla(
    provider, session_id: str, chat_id: str, name: str,
    parent_local_id: int | None = None,
) -> dict:
    """
    Dispara una plantilla guiada por nombre.
    Retorna {ok, format_used?, reason?, dispatch_local_id?}.
    """
    template = guided_templates.find_by_name(name)
    if template is None:
        # Forzar refresh por si fue editada hace poco
        await guided_templates.get_active()
        template = guided_templates.find_by_name(name)
    if template is None:
        logger.warning(f"Dispatch plantilla: nombre '{name}' no encontrado")
        return {"ok": False, "reason": "template_not_found"}

    # Verificar limite de anidamiento si es sub-plantilla
    depth = int(template.get("depth_level") or 1)
    if parent_local_id is not None and depth > 3:
        logger.warning(f"Dispatch plantilla: depth {depth} > 3, abortar")
        return {"ok": False, "reason": "depth_exceeded"}

    # Cascada
    result = await guided_cascade.enviar_con_cascada(provider, session_id, chat_id, template)

    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=SELECTION_WINDOW_MIN)

    # Registrar local
    local_id = await memory.guardar_dispatch_local(
        template_id=int(template["id"]),
        chat_id=chat_id,
        dispatched_at=now,
        expires_at=expires,
        format_used=result["format_used"],
        options_snapshot=template.get("options", []),
        parent_id=parent_local_id,
    )

    # Registrar remoto (fire-and-forget)
    remote_id = await guided_templates.register_dispatch(
        template_id=int(template["id"]),
        session_id=session_id,
        chat_id=chat_id,
        format_used=result["format_used"],
        dispatched_at=now,
    )
    if remote_id is not None:
        await memory.actualizar_remote_dispatch_id(local_id, remote_id)

    return {
        "ok": True,
        "format_used": result["format_used"],
        "dispatch_local_id": local_id,
        "dispatch_remote_id": remote_id,
    }


def render_plantillas_prompt_block(templates: list[dict]) -> str:
    """
    Renderiza el bloque de plantillas para inyectar en el system prompt del LLM.
    Solo incluye plantillas de nivel 1 (las raices) — las anidadas se invocan internamente
    via action_type=template.
    """
    raices = [t for t in templates if not t.get("parent_template_id")]
    if not raices:
        return ""

    lines = [
        "\n\nRESPUESTAS GUIADAS DISPONIBLES",
        "",
        "Ademas de tu base de conocimiento, podes invocar las siguientes",
        "plantillas pre-configuradas cuando el contexto lo amerite:",
        "",
    ]
    for t in raices:
        lines.append(f"NOMBRE: {t.get('name', '')}")
        lines.append(f"  TRIGGER: {t.get('trigger_description', '')}")
        body = (t.get("body_text") or "").replace("\n", " ")[:120]
        lines.append(f"  CONTENIDO: {body}")
        opts = t.get("options") or []
        if opts:
            lines.append("  OPCIONES:")
            for i, o in enumerate(opts[:10], start=1):
                lines.append(f"    {i}. {o.get('visible_text', '')} -> {o.get('action_type', '')}")
        lines.append("")

    lines.extend([
        "Reglas:",
        "- Si el mensaje del usuario encaja claramente con un TRIGGER, respondé invocando la plantilla",
        "  con este formato exacto: <plantilla>nombre_plantilla</plantilla>",
        "- Si la pregunta es abierta sin opciones obvias, respondé con texto libre normal (RAG).",
        "- NUNCA inventes plantillas que no esten listadas arriba.",
        "- Si dudás entre dos, elegí la mas especifica.",
        "- No mezcles texto libre y la invocacion: si invocas, respondé SOLO con la etiqueta <plantilla>...</plantilla>.",
    ])
    return "\n".join(lines)
