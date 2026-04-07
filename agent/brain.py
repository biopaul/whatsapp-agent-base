# agent/brain.py — Cerebro del agente: conexión con la API de IA
# WhatsApp Agent Base

"""
Genera respuestas usando el proveedor de IA configurado en .env.
Soporta: Claude (Anthropic), OpenAI (GPT), Gemini (Google).

Configurar en .env:
  AI_PROVIDER=claude   → usa ANTHROPIC_API_KEY + modelo configurable
  AI_PROVIDER=openai   → usa OPENAI_API_KEY + modelo configurable
  AI_PROVIDER=gemini   → usa GEMINI_API_KEY + modelo configurable
"""

import os
import yaml
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("agentkit")

AI_PROVIDER = os.getenv("AI_PROVIDER", "claude").lower()

# Modelos por defecto para cada proveedor
_MODELOS_DEFAULT = {
    "claude": "claude-haiku-4-5-20251001",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.0-flash",
}

AI_MODEL = os.getenv("AI_MODEL", _MODELOS_DEFAULT.get(AI_PROVIDER, ""))


def cargar_config_prompts() -> dict:
    """Lee toda la configuración desde config/prompts.yaml."""
    try:
        with open("config/prompts.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.error("config/prompts.yaml no encontrado")
        return {}


def cargar_system_prompt() -> str:
    config = cargar_config_prompts()
    return config.get("system_prompt", "Sos una asistente útil. Respondé en español.")


def obtener_mensaje_error() -> str:
    config = cargar_config_prompts()
    return config.get("error_message", "Lo siento, estoy teniendo un problema técnico. Por favor intentá de nuevo en unos minutos.")


def obtener_mensaje_fallback() -> str:
    config = cargar_config_prompts()
    return config.get("fallback_message", "Disculpá, no entendí tu mensaje. ¿Podés reformularlo?")


async def _responder_claude(system_prompt: str, mensajes: list[dict]) -> str:
    """Genera respuesta usando Anthropic Claude."""
    from anthropic import AsyncAnthropic
    client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = await client.messages.create(
        model=AI_MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=mensajes,
    )
    logger.info(f"[Claude] {response.usage.input_tokens} in / {response.usage.output_tokens} out")
    return response.content[0].text


async def _responder_openai(system_prompt: str, mensajes: list[dict]) -> str:
    """Genera respuesta usando OpenAI."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    # OpenAI recibe el system prompt como primer mensaje del array
    messages_openai = [{"role": "system", "content": system_prompt}] + mensajes
    response = await client.chat.completions.create(
        model=AI_MODEL,
        messages=messages_openai,
        max_tokens=1024,
    )
    logger.info(f"[OpenAI] {response.usage.prompt_tokens} in / {response.usage.completion_tokens} out")
    return response.choices[0].message.content


async def _responder_gemini(system_prompt: str, mensajes: list[dict]) -> str:
    """Genera respuesta usando Google Gemini."""
    import google.generativeai as genai
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel(
        model_name=AI_MODEL,
        system_instruction=system_prompt,
    )
    # Convertir historial al formato de Gemini
    historial_gemini = []
    for msg in mensajes[:-1]:  # todos menos el último (el mensaje actual)
        historial_gemini.append({
            "role": "user" if msg["role"] == "user" else "model",
            "parts": [msg["content"]],
        })
    chat = model.start_chat(history=historial_gemini)
    response = await chat.send_message_async(mensajes[-1]["content"])
    logger.info(f"[Gemini] respuesta generada")
    return response.text


async def generar_respuesta(mensaje: str, historial: list[dict], contexto_extra: str = "") -> str:
    """
    Genera una respuesta usando el proveedor de IA configurado en AI_PROVIDER.

    Args:
        mensaje: El mensaje nuevo del usuario
        historial: Lista de mensajes anteriores [{"role": "user/assistant", "content": "..."}]
        contexto_extra: Instrucciones adicionales para esta respuesta (ej: saludo del día)

    Returns:
        La respuesta generada
    """
    if not mensaje or len(mensaje.strip()) < 2:
        return obtener_mensaje_fallback()

    system_prompt = cargar_system_prompt()
    if contexto_extra:
        system_prompt += f"\n\n## Contexto de esta respuesta\n{contexto_extra}"

    # Filtrar SILENCIO del historial antes de enviarlo a la IA
    mensajes = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in historial
        if msg["content"].strip() != "SILENCIO"
    ]
    mensajes.append({"role": "user", "content": mensaje})

    try:
        if AI_PROVIDER == "claude":
            return await _responder_claude(system_prompt, mensajes)
        elif AI_PROVIDER == "openai":
            return await _responder_openai(system_prompt, mensajes)
        elif AI_PROVIDER == "gemini":
            return await _responder_gemini(system_prompt, mensajes)
        else:
            logger.error(f"AI_PROVIDER no soportado: {AI_PROVIDER}")
            return obtener_mensaje_error()
    except Exception as e:
        logger.error(f"Error {AI_PROVIDER} API: {e}")
        return obtener_mensaje_error()
