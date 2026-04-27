# agent/brain.py — Cerebro del agente: conexion con OpenRouter API
# WhatsApp Agent Base

"""
Logica de IA del agente. Lee el system prompt desde WP config (o YAML local)
y genera respuestas usando OpenRouter (API compatible con OpenAI).
Soporta routing de dos niveles: modelo rapido para consultas simples,
modelo completo para consultas complejas.
"""

import os
import logging
from openai import AsyncOpenAI
from dotenv import load_dotenv
from agent.config_loader import get_ai_models, get_system_prompt, get_fallback_message, get_error_message
from agent.knowledge_loader import get_knowledge_text, get_public_docs

load_dotenv()
logger = logging.getLogger("agentkit")

# Cliente OpenRouter (API compatible con OpenAI)
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

# Maximo de tokens por respuesta.
_MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", "500"))

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


async def generar_respuesta(mensaje: str, historial: list[dict], contexto_extra: str = "") -> str:
    """
    Genera una respuesta usando OpenRouter.

    Args:
        mensaje: El mensaje nuevo del usuario.
        historial: Lista de mensajes anteriores [{"role": "user/assistant", "content": "..."}].
        contexto_extra: Instrucciones adicionales para esta respuesta.

    Returns:
        La respuesta generada por el modelo.
    """
    if not mensaje or len(mensaje.strip()) < 2:
        return get_fallback_message()

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

    # Construir mensajes: system como primer mensaje, luego historial, luego el actual.
    # Filtrar SILENCIO para no confundir al modelo.
    mensajes = [{"role": "system", "content": system_prompt}]
    for msg in historial:
        if msg["content"].strip() != "SILENCIO":
            mensajes.append({"role": msg["role"], "content": msg["content"]})
    mensajes.append({"role": "user", "content": mensaje})

    # Seleccionar tier de modelos segun complejidad
    models_config = get_ai_models()
    complejo = _es_consulta_compleja(mensaje, historial)
    models = models_config["full"] if complejo else models_config["quick"]

    tier = "full" if complejo else "quick"
    logger.debug(f"Tier seleccionado: {tier} — modelos: {models}")

    try:
        kwargs: dict = {
            "model": models[0],
            "max_tokens": _MAX_TOKENS,
            "messages": mensajes,
        }
        # Multi-model fallback: si hay mas de un modelo en el tier, usar routing de OpenRouter
        if len(models) > 1:
            kwargs["extra_body"] = {"models": models, "route": "fallback"}

        response = await client.chat.completions.create(**kwargs)

        respuesta = response.choices[0].message.content or ""
        usage = response.usage
        modelo_usado = getattr(response, "model", models[0])
        logger.info(
            f"Respuesta generada ({usage.prompt_tokens} in / {usage.completion_tokens} out) "
            f"modelo={modelo_usado} tier={tier}"
        )
        return respuesta

    except Exception as e:
        logger.error(f"Error OpenRouter API: {e}")
        return get_error_message()
