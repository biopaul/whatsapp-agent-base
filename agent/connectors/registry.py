# agent/connectors/registry.py
"""
Registry de conectores activos.
"""

import logging
from agent.connectors.gcal import GCAL_TOOLS

logger = logging.getLogger("agentkit")


def get_tools_for_connector(connector: dict) -> list[dict]:
    """
    Retorna las tool schemas para un conector activo.

    Args:
        connector: dict con "slug", "enabled", "config_summary" del config WP.

    Returns:
        Lista de tool schemas en formato OpenAI function calling.
    """
    if not isinstance(connector, dict):
        return []
    if not connector.get("enabled"):
        return []

    slug = connector.get("slug", "")
    if slug == "gcal":
        return list(GCAL_TOOLS)
    logger.warning(f"Conector desconocido en registry: {slug}")
    return []


def build_connectors_context(connectors: list[dict]) -> str:
    """
    Genera el bloque de contexto que se inyecta al system prompt cuando hay
    conectores activos. Indica al LLM que tools tiene disponibles y como usarlas.
    """
    if not connectors:
        return ""

    lines = ["", "CONECTORES ACTIVOS"]

    for c in connectors:
        if not isinstance(c, dict) or not c.get("enabled"):
            continue
        slug = c.get("slug", "")
        if slug == "gcal":
            lines.append(_build_gcal_context(c))

    if len(lines) <= 2:
        return ""
    return "\n".join(lines)


def _build_gcal_context(connector: dict) -> str:
    cfg = connector.get("config_summary", {}) or {}
    slot_types = cfg.get("slot_types", []) or []

    parts = [
        "",
        "Google Calendar",
        "Tenes acceso a estas herramientas para gestionar turnos:",
        "- gcal_consultar_disponibilidad: ver horarios libres",
        "- gcal_crear_turno: reservar",
        "- gcal_consultar_proximos_turnos: listar turnos del cliente",
        "- gcal_cancelar_turno: cancelar un turno",
        "- gcal_confirmar_turno: marcar confirmacion (para recordatorio 24h)",
        "- guardar_contacto: guardar nombre/email cuando los aprendas",
        "",
    ]

    if slot_types:
        parts.append("Tipos de turno disponibles:")
        for st in slot_types:
            label = st.get("label", "")
            duration = st.get("duration_minutes", 0)
            services = ", ".join(st.get("services", []) or [])
            parts.append(f"- {label} ({duration} min): {services}")
        parts.append("")

    parts.extend(
        [
            "Reglas para usar las tools:",
            "- Antes de reservar, asegurate de tener el nombre del cliente. Email es ideal pero opcional.",
            "- Antes de crear un turno, ofrece al cliente al menos 2-3 horarios libres y que el elija.",
            "- Si el cliente quiere reprogramar, NO uses cancelar+crear: escala con ESCALAR: para que se pase con un humano.",
            "- Si una tool devuelve error, comunicalo al cliente de forma natural ('se me complico acceder al calendario, te paso con alguien').",
        ]
    )
    return "\n".join(parts)
