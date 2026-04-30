# agent/brain.py — Cerebro del agente: conexion con OpenRouter API
# WhatsApp Agent — SimpleProp Sofi

"""
Logica de IA del agente. Lee el system prompt desde WP config (o YAML local)
y genera respuestas usando OpenRouter (API compatible con OpenAI).
Soporta routing de dos niveles: modelo rapido para consultas simples,
modelo completo para consultas complejas.
"""

import os
import json
import logging
from openai import AsyncOpenAI
from dotenv import load_dotenv
from agent.config_loader import get_ai_models, get_system_prompt, get_fallback_message, get_error_message, get_active_connectors
from agent.knowledge_loader import get_knowledge_text, get_public_docs
from agent.connectors.registry import get_tools_for_connector, build_connectors_context
from agent.connectors.executor import execute_tool
from agent.memory import obtener_contacto

load_dotenv()
logger = logging.getLogger("agentkit")

# Cliente OpenRouter (API compatible con OpenAI)
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

# Maximo de tokens por respuesta.
_MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", "500"))

# Prefixes de modelos que soportan function calling en OpenRouter.
TOOL_USE_PREFIXES = (
    "anthropic/",
    "openai/gpt-",
    "google/gemini-",
    "deepseek/deepseek-chat",
    "meta-llama/llama-3.3",
    "mistralai/mistral-large",
)

# Fallback si ningun modelo del plan soporta tool use.
TOOL_USE_FALLBACK_MODEL = "anthropic/claude-3-5-haiku"

# Capa fija de naturalidad — se antepone a TODOS los system prompts.
_WHATSAPP_NATURALNESS = """\
Estas chateando con clientes por WhatsApp. Reglas de comunicacion:

FORMATO
- Mensajes cortos. Una idea por mensaje.
- Si tenes mucho para decir, usa --- para separar en mensajes distintos en vez de hacer uno largo.
- Nunca uses listas con guiones o numeros salvo que el cliente haya pedido una lista explicitamente.
- Nunca uses negrita (**texto**), italica (*texto*) ni encabezados (## Titulo).
- Un emoji ocasional esta bien; varios seguidos no.

TONO
- Habla como lo haria una persona real en un chat, no como un documento de ayuda.
- Nunca empieces un mensaje con "Claro!", "Por supuesto!", "Excelente!", "Perfecto!" ni similares.
- No repitas lo que el cliente acabo de decir antes de responder.
- Si la respuesta es corta, que sea corta. No la rellenes para que parezca mas completa.

LARGO
- 1 a 3 oraciones para preguntas simples.
- 4 a 6 oraciones maximo para temas complejos.
- Si necesitas mas espacio, divide con --- en vez de hacer un bloque largo.

"""


def _filter_tool_use_capable(models: list[str]) -> list[str]:
    """Retorna solo los modelos que soportan function calling."""
    return [m for m in models if any(m.startswith(p) for p in TOOL_USE_PREFIXES)]


def _build_contact_context(contacto) -> str:
    """Inyecta los datos del cliente al system prompt si existen."""
    if contacto is None:
        return ""
    nombre = (contacto.nombre or "").strip()
    email = (contacto.email or "").strip()
    if not nombre and not email:
        return ""
    return (
        "\n\nDATOS DEL CLIENTE\n"
        f"Nombre: {nombre or '(sin dato)'}\n"
        f"Email: {email or '(sin dato)'}"
    )


def _es_consulta_compleja(mensaje: str, historial: list[dict]) -> bool:
    """
    Heuristica para determinar si el mensaje requiere un modelo mas capaz.
    Score >= 2 => complejo.
    """
    score = 0
    if len(mensaje) > 150:
        score += 2
    if mensaje.count("?") > 1:
        score += 1
    turnos = len([m for m in historial if m["role"] == "user"])
    if turnos > 5:
        score += 1
    keywords = [
        "precio", "costo", "cuanto", "cuánto", "comparar", "diferencia",
        "mejor", "recomendar", "problema", "error", "explicar", "detalles",
        "contrato", "condiciones", "garantia",
    ]
    if any(kw in mensaje.lower() for kw in keywords):
        score += 1
    return score >= 2


async def generar_respuesta(mensaje: str, historial: list[dict], contexto_extra: str = "", telefono: str = "") -> str:
    """
    Genera respuesta del LLM. Si hay conectores activos, soporta tool use loop.
    Backward compat: sin conectores, hace una sola llamada al LLM como antes.

    Args:
        mensaje: el mensaje nuevo del cliente.
        historial: lista de [{role, content}] anteriores.
        contexto_extra: contexto adicional para esta respuesta puntual.
        telefono: telefono del cliente (para inyectar en tool calls + lookup contacto).
    """
    if not mensaje or len(mensaje.strip()) < 2:
        return get_fallback_message()

    # Construir system prompt: capa naturalidad + system_prompt + knowledge + public_docs + contexto_extra
    system_prompt = _WHATSAPP_NATURALNESS + get_system_prompt()

    knowledge = get_knowledge_text()
    if knowledge:
        system_prompt += f"\n\nDOCUMENTOS DE REFERENCIA\n\n{knowledge}"

    public_docs = get_public_docs()
    if public_docs:
        nombres = "\n".join(f"- {d['name']}" for d in public_docs)
        system_prompt += (
            "\n\nARCHIVOS QUE PODES ENVIAR AL CLIENTE\n"
            "Cuando consideres que el cliente se beneficiaria de recibir uno de estos archivos "
            "(por ejemplo: catalogo, lista de precios, ficha tecnica), podes enviarselo.\n"
            "Para enviarlo, inclui al FINAL de tu respuesta, en una linea propia, la senal:\n"
            "ENVIAR_ARCHIVO:<nombre_exacto_del_archivo>\n"
            "Solo una senal por respuesta. Solo usala si genuinamente agrega valor, no en cada mensaje.\n"
            f"Archivos disponibles:\n{nombres}"
        )

    if contexto_extra:
        system_prompt += f"\n\nCONTEXTO DE ESTA RESPUESTA\n{contexto_extra}"

    # NUEVO: agregar info del contacto si existe
    if telefono:
        try:
            contacto = await obtener_contacto(telefono)
            system_prompt += _build_contact_context(contacto)
        except Exception as e:
            logger.warning(f"No se pudo obtener contacto: {e}")

    # NUEVO: agregar contexto de conectores y armar tools
    conectores = get_active_connectors()
    tools: list[dict] = []
    for c in conectores:
        tools.extend(get_tools_for_connector(c))
    if conectores:
        system_prompt += build_connectors_context(conectores)

    # Construir mensajes para el LLM (filtrar SILENCIO)
    mensajes = [{"role": "system", "content": system_prompt}]
    for m in historial:
        if m.get("content", "").strip() != "SILENCIO":
            mensajes.append({"role": m["role"], "content": m["content"]})
    mensajes.append({"role": "user", "content": mensaje})

    # Seleccionar tier y modelos
    models_config = get_ai_models()
    complejo = _es_consulta_compleja(mensaje, historial)
    tier = "full" if complejo else "quick"
    models = list(models_config.get(tier, []) or [])

    logger.debug(f"Tier seleccionado: {tier} — modelos: {models}")

    # Si hay tools, filtrar modelos compatibles
    if tools:
        filtered = _filter_tool_use_capable(models)
        if not filtered:
            logger.warning(f"Plan sin modelos compatibles con tool use; fallback a {TOOL_USE_FALLBACK_MODEL}")
            filtered = [TOOL_USE_FALLBACK_MODEL]
        models = filtered

    if not models:
        logger.error("Sin modelos configurados; usando fallback")
        models = [TOOL_USE_FALLBACK_MODEL]

    # Tool use loop (max 5 iteraciones)
    for iteration in range(5):
        try:
            kwargs: dict = {
                "model": models[0],
                "max_tokens": _MAX_TOKENS,
                "messages": mensajes,
            }
            if tools:
                kwargs["tools"] = tools
            if len(models) > 1:
                kwargs["extra_body"] = {"models": models, "route": "fallback"}

            response = await client.chat.completions.create(**kwargs)
        except Exception as e:
            logger.error(f"OpenRouter error iteration {iteration}: {e}")
            return get_error_message()

        msg = response.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None)

        if not tool_calls:
            respuesta = msg.content or ""
            if iteration == 0:
                # Log original info only on direct (no-tool) responses
                usage = response.usage
                modelo_usado = getattr(response, "model", models[0])
                logger.info(
                    f"Respuesta generada ({usage.prompt_tokens} in / {usage.completion_tokens} out) "
                    f"modelo={modelo_usado} tier={tier}"
                )
            return respuesta

        # Append the assistant message (con tool_calls) al historial para que el LLM tenga contexto
        try:
            mensajes.append(msg.model_dump(exclude_unset=True))
        except Exception:
            mensajes.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ],
            })

        # Ejecutar cada tool call y agregar el resultado
        for tc in tool_calls:
            result = await execute_tool(tc, telefono)
            mensajes.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, default=str),
            })

    # Si llegamos aca, excedimos max iterations
    logger.error(f"Tool use loop excedio max iterations para {telefono}")
    return get_error_message()
