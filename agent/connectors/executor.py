# agent/connectors/executor.py
"""
Executor de tool calls — routing tool name → operation REST en WP.
"""

import json
import logging
import os
import httpx

from agent.memory import guardar_contacto

logger = logging.getLogger("agentkit")


# Mapeo tool name → (connector_slug, operation_name)
# El operation name es lo que va en /connectors/{token}/{slug}/{op}
TOOL_TO_WP_OPERATION = {
    "gcal_consultar_disponibilidad": ("gcal", "availability"),
    "gcal_crear_turno": ("gcal", "create"),
    "gcal_consultar_proximos_turnos": ("gcal", "list_upcoming"),
    "gcal_cancelar_turno": ("gcal", "cancel"),
    "gcal_confirmar_turno": ("gcal", "confirm"),
}


async def execute_tool(tool_call, telefono: str) -> dict:
    """
    Ejecuta un tool_call generado por el LLM.

    Args:
        tool_call: objeto del SDK de OpenAI con `.function.name` y `.function.arguments` (JSON string)
        telefono: telefono del cliente (inyectado automaticamente, no pasa por el LLM)

    Returns:
        dict con el resultado (lo que se le devuelve al LLM como tool_result).
    """
    name = tool_call.function.name
    try:
        args = json.loads(tool_call.function.arguments)
    except (TypeError, ValueError) as e:
        logger.error(f"execute_tool: args invalidos para {name}: {e}")
        return {"error": "invalid_args", "detail": str(e)}

    if not isinstance(args, dict):
        return {"error": "invalid_args", "detail": "args no es un objeto"}

    # Tool local: persistir contacto en la DB del agente
    if name == "guardar_contacto":
        nombre = str(args.get("nombre", "") or "")
        email = str(args.get("email", "") or "")
        if not nombre and not email:
            return {"ok": False, "message": "ningun campo para guardar"}
        await guardar_contacto(telefono, nombre=nombre, email=email)
        return {"ok": True, "message": "contacto guardado"}

    # Tool remota: REST a WP
    if name in TOOL_TO_WP_OPERATION:
        slug, op = TOOL_TO_WP_OPERATION[name]
        return await _call_wp_connector(slug, op, args, telefono)

    return {"error": "unknown_tool", "tool": name}


async def _call_wp_connector(slug: str, op: str, args: dict, telefono: str) -> dict:
    """
    POST a {wp_base}/connectors/{token}/{slug}/{op}.
    Reconstruye la URL desde CONFIG_URL (que apunta a /config/{token}).
    """
    config_url = os.getenv("CONFIG_URL", "")
    if "/config/" not in config_url:
        logger.error("_call_wp_connector: CONFIG_URL no configurado o malformado")
        return {"error": "server_unavailable", "detail": "CONFIG_URL missing"}

    # CONFIG_URL = https://...wp-json/gowap/v1/config/{token}
    # Construimos URL connector: https://...wp-json/gowap/v1/connectors/{token}/{slug}/{op}
    wp_base, _, token = config_url.rpartition("/config/")
    if not wp_base or not token:
        return {"error": "server_unavailable", "detail": "CONFIG_URL invalid"}

    url = f"{wp_base}/connectors/{token}/{slug}/{op}"

    payload = dict(args)
    payload["telefono"] = telefono

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    return data
                return {"error": "invalid_response", "detail": "no es objeto JSON"}
            logger.error(
                f"_call_wp_connector {slug}/{op} → HTTP {resp.status_code}: {resp.text[:200]}"
            )
            return {"error": "server_error", "status": resp.status_code}
    except httpx.TimeoutException:
        logger.error(f"_call_wp_connector {slug}/{op} → timeout")
        return {"error": "timeout"}
    except Exception as e:
        logger.error(f"_call_wp_connector {slug}/{op} → exception: {e}")
        return {"error": "server_unavailable", "detail": str(e)}
