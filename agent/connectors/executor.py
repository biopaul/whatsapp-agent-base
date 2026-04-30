# agent/connectors/executor.py
"""
Executor de tool calls — routing tool name → operation REST en WP.
Phase 1: stub — se completa en Phase 4.
"""

import logging

logger = logging.getLogger("agentkit")


async def execute_tool(tool_call, telefono: str) -> dict:
    """
    Phase 1: stub. Retorna error.
    En Phase 4 va a routear a guardar_contacto local o a una llamada REST a WP.
    """
    return {"error": "connectors not yet implemented (phase 1 stub)"}
