# agent/connectors/registry.py
"""
Registry de conectores activos.
Phase 1: stub — se completa en Phase 4 con la lógica de building tools desde config.
"""

import logging

logger = logging.getLogger("agentkit")


def get_tools_for_connector(connector: dict) -> list[dict]:
    """
    Phase 1: stub. Retorna lista vacía siempre.
    En Phase 4 esta función va a delegar a gcal.get_tools() según el slug.

    Args:
        connector: dict con "slug", "enabled", etc. proveniente del config WP.

    Returns:
        Lista de tool schemas en formato OpenAI function calling.
    """
    return []


def build_connectors_context(connectors: list[dict]) -> str:
    """
    Phase 1: stub. Retorna string vacío.
    En Phase 4 va a generar el bloque de contexto que se inyecta al system prompt.
    """
    return ""
