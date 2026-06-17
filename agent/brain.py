# agent/brain.py — Cerebro del agente: conexion con OpenRouter API
# WhatsApp Agent — SimpleProp Sofi

"""
Logica de IA del agente. Lee el system prompt desde WP config (o YAML local)
y genera respuestas usando OpenRouter (API compatible con OpenAI).
Soporta routing de dos niveles: modelo rapido para consultas simples,
modelo completo para consultas complejas.
"""

import os
import re
import json
import logging
from openai import AsyncOpenAI
from dotenv import load_dotenv
from agent.config_loader import get_ai_models, get_system_prompt, get_fallback_message, get_error_message, get_active_connectors
from agent.knowledge_loader import get_knowledge_text, get_public_docs
from agent.connectors.registry import get_tools_for_connector, build_connectors_context
from agent.connectors.executor import execute_tool
from agent.memory import obtener_contacto
from agent import takeover
from agent import guided_templates, guided_dispatcher

load_dotenv()
logger = logging.getLogger("agentkit")

# Cliente OpenRouter (API compatible con OpenAI)
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

# Maximo de tokens por respuesta.
_MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", "500"))

# Rango Unicode amplio de emojis para detectar mensajes formados solo por
# pictografias. Incluye Emoticons, Symbols & Pictographs (con extensiones),
# Transport, Misc Symbols, Dingbats, Flags, modificadores y ZWJ. Tambien
# permite caracteres de variation selector y espacios entre emojis.
_EMOJI_REGEX = re.compile(
    r'['
    r'\U0001F300-\U0001F9FF'    # Symbols & Pictographs (incluye 😎, 🎉, 🔥)
    r'\U0001FA00-\U0001FAFF'    # Symbols & Pictographs Extended-A
    r'\U0001F600-\U0001F64F'    # Emoticons (😀-🙏)
    r'\U0001F680-\U0001F6FF'    # Transport & Map
    r'\U0001F1E6-\U0001F1FF'    # Banderas regionales
    r'\U00002600-\U000027BF'    # Misc Symbols + Dingbats (☀️, ✅, ❤️)
    r'\U0001F900-\U0001F9FF'    # Supplemental Symbols
    r'\U0000FE00-\U0000FE0F'    # Variation selectors (FE0F)
    r'‍'                   # Zero-width joiner (para emojis compuestos)
    r']+',
    flags=re.UNICODE,
)


def _solo_emojis(texto: str) -> bool:
    """True si el mensaje (sin espacios) esta formado unicamente por emojis."""
    if not texto or not texto.strip():
        return False
    sin_emojis = _EMOJI_REGEX.sub('', texto).strip()
    return sin_emojis == ''

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
# Redactada en español neutro (tú) para evitar contaminar la salida del modelo
# con voseo cuando el cliente del agente no es del Cono Sur. Si el agente debe
# hablar en otro dialecto (rioplatense, mexicano, etc.), debe indicarlo
# explícitamente el system prompt del cliente — ese prompt tiene prioridad
# sobre las preferencias implícitas de esta capa.
_WHATSAPP_NATURALNESS = """\
Estás chateando con clientes por WhatsApp. Reglas de comunicación:

FORMATO
- Mensajes cortos. Una idea por mensaje.
- Si tienes mucho para decir, usa --- para separar en mensajes distintos en vez de hacer uno largo.
- Nunca uses listas con guiones o números salvo que el cliente haya pedido una lista explícitamente.
- Nunca uses negrita (**texto**), itálica (*texto*) ni encabezados (## Título).
- Un emoji ocasional está bien; varios seguidos no.

TONO
- Habla como lo haría una persona real en un chat, no como un documento de ayuda.
- Nunca empieces un mensaje con "Claro!", "Por supuesto!", "Excelente!", "Perfecto!" ni similares.
- No repitas lo que el cliente acaba de decir antes de responder.
- Si la respuesta es corta, que sea corta. No la rellenes para que parezca más completa.

LARGO
- 1 a 3 oraciones para preguntas simples.
- 4 a 6 oraciones máximo para temas complejos.
- Si necesitas más espacio, divide con --- en vez de hacer un bloque largo.

IDIOMA Y DIALECTO
- Por defecto, habla en español neutro (tú: tienes, puedes, eres, haces).
- NO uses voseo rioplatense (vos/tenés/podés/sos/hacés) a menos que el system prompt principal del cliente lo solicite explícitamente o que el usuario te esté hablando claramente en voseo.
- Estas reglas mismas están escritas en neutro para evitar que su tono se contagie. Tu salida debe seguir las indicaciones del system prompt del cliente, no el dialecto de estas instrucciones.

ESCALACIÓN A HUMANO
- SÍ tienes capacidad de derivar al cliente a una persona del equipo. NO digas que no puedes derivar, no digas que en este chat solo puedes ayudar tú, no digas que no tienes la capacidad de transferir. Eso es FALSO.
- CÓMO escalar: empieza tu respuesta con el marcador literal "ESCALAR: <motivo breve>" en la PRIMERA línea y después, en líneas siguientes, el mensaje al cliente. El cliente NO ve el "ESCALAR:" — el sistema lo procesa y lo elimina antes de enviar. Ejemplo:
    ESCALAR: cliente frustrado pide humano
    Listo, te conecto con alguien del equipo. En unos minutos te van a escribir por acá.
- CUÁNDO escalar: úsalo solo en estos casos. No escales por consultas que puedes responder.
  1. El cliente pide explícitamente hablar con un humano / persona real / asesor / dueño / encargado, en cualquier formulación (incluyendo "no quiero hablar con un bot", "quiero hablar con alguien", typos).
  2. El cliente muestra frustración persistente (más de un mensaje quejándose) y la situación lo amerita.
  3. Hay una queja seria, un reclamo, un problema que requiere acción humana (cambio de pedido, reembolso, problema técnico que no puedes resolver).
  4. El cliente menciona algo grave (urgencia médica, legal, peligro) que excede el alcance del agente.
- DESPUÉS de escalar, tú NO sigues respondiendo en ese chat hasta que el humano intervenga. Tu mensaje de escalación es el último por un rato — no añadas más preguntas tipo "¿algo más?".

"""


def _is_anthropic_model(model: str) -> bool:
    """True si el modelo se rutea a Anthropic — soporta cache_control: ephemeral explicito."""
    return model.startswith("anthropic/")


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
    # Bloquear solo mensajes verdaderamente vacios. Emojis sueltos (len=1)
    # antes caian aqui y disparaban fallback_message sin llegar al LLM.
    # Ahora pasan: el LLM entiende los emojis nativamente.
    if not mensaje or not mensaje.strip():
        return get_fallback_message()

    # Si el mensaje es solo emojis, agregar un hint al contexto para que el LLM
    # los interprete como reaccion/emocion del cliente en lugar de tratarlos
    # como una pregunta concreta. El emoji per se ya esta en `mensaje` y va
    # como user turn al modelo — esto solo agrega la guia interpretativa.
    if _solo_emojis(mensaje):
        emoji_hint = (
            f"NOTA: el cliente envió un mensaje compuesto solo por emojis: {mensaje.strip()}. "
            "Interprétalo como una reacción emocional o expresiva en relación a tu último "
            "mensaje y al hilo reciente de la conversación, NO como una pregunta. "
            "Responde de forma natural, breve (1 oración suele alcanzar) y conectada al "
            "contexto. Si el contexto no permite interpretarlo, devuelve una respuesta "
            "cordial que invite a continuar el tema actual sin pedir explícitamente que "
            "el cliente reformule."
        )
        contexto_extra = f"{contexto_extra}\n\n{emoji_hint}".strip() if contexto_extra else emoji_hint

    # === STATIC PORTION (cacheable) ===
    # Esta parte es identica entre llamadas para el mismo agente.
    # Cuando un modelo Anthropic la procesa, marcamos cache_control: ephemeral
    # para que su API la cachee y subsiguientes llamadas paguen ~10% del costo.
    # Para OpenAI/DeepSeek/Gemini2.5, el caching es automatico sobre prefijos identicos.
    static_parts: list[str] = [_WHATSAPP_NATURALNESS, get_system_prompt()]

    # Plantillas guiadas activas (RESPUESTAS GUIADAS)
    try:
        _plantillas = await guided_templates.get_active()
        _bloque = guided_dispatcher.render_plantillas_prompt_block(_plantillas)
        if _bloque:
            static_parts.append(_bloque)
    except Exception as e:
        logger.warning(f"No se pudo cargar plantillas guiadas: {e}")

    # Awareness de handoff humano-IA: si el chat estuvo (o esta) en manual mode
    # recientemente, avisar al LLM que los assistant messages en ese rango pueden
    # ser de un humano, no del LLM mismo.
    if telefono:
        _window = takeover.was_recently_manual(telefono)
        if _window:
            _start, _end = _window
            static_parts.append(
                "\n\n## Nota de contexto operativa\n"
                f"Entre {_start.isoformat()} y {_end.isoformat()} este chat fue "
                "atendido manualmente por un operador humano. Los mensajes con "
                "role=assistant en ese rango fueron escritos por un humano, no por "
                "ti. No contradigas lo que dijo y continúa la conversación "
                "coherentemente."
            )

    knowledge = get_knowledge_text()
    if knowledge:
        static_parts.append(f"\n\nDOCUMENTOS DE REFERENCIA\n\n{knowledge}")

    public_docs = get_public_docs()
    if public_docs:
        nombres = "\n".join(f"- {d['name']}" for d in public_docs)
        static_parts.append(
            "\n\nARCHIVOS QUE PODES ENVIAR AL CLIENTE\n"
            "Cuando consideres que el cliente se beneficiaria de recibir uno de estos archivos "
            "(por ejemplo: catalogo, lista de precios, ficha tecnica), podes enviarselo.\n"
            "Para enviarlo, inclui al FINAL de tu respuesta, en una linea propia, la senal:\n"
            "ENVIAR_ARCHIVO:<nombre_exacto_del_archivo>\n"
            "Solo una senal por respuesta. Solo usala si genuinamente agrega valor, no en cada mensaje.\n"
            f"Archivos disponibles:\n{nombres}"
        )

    # Conector context tambien estatico — solo cambia cuando el cliente actualiza su config
    conectores = get_active_connectors()
    tools: list[dict] = []
    for c in conectores:
        tools.extend(get_tools_for_connector(c))
    if conectores:
        static_parts.append(build_connectors_context(conectores))

    static_system = "".join(static_parts)

    # === DYNAMIC PORTION (NOT cacheable) ===
    # Esta parte cambia por mensaje (contexto del dia, saludo) o por conversacion (contacto).
    # La metemos despues del cache breakpoint para que no rompa cache hits.
    dynamic_parts: list[str] = []

    if contexto_extra:
        dynamic_parts.append(f"\n\nCONTEXTO DE ESTA RESPUESTA\n{contexto_extra}")

    if telefono:
        try:
            contacto = await obtener_contacto(telefono)
            contact_ctx = _build_contact_context(contacto)
            if contact_ctx:
                dynamic_parts.append(contact_ctx)
        except Exception as e:
            logger.warning(f"No se pudo obtener contacto: {e}")

        # Awareness de cliente convertido: si el plugin marco al contacto como cliente,
        # cambia la filosofia del agente (soporte vs vendedor). Va en dynamic porque el
        # estado puede cambiar mid-stream (el operador humano lo marca desde la UI).
        is_cust, cust_since = takeover.is_chat_customer(telefono)
        if is_cust:
            since_str = cust_since.date().isoformat() if cust_since else "(fecha no disponible)"
            customer_block = (
                "\n\n## Cliente activo\n"
                f"IMPORTANTE: este contacto ya es CLIENTE de nuestro negocio "
                f"(cliente desde {since_str}). Cambia tu enfoque por completo:\n\n"
                "- NO eres un vendedor: eres un asistente de soporte y customer success.\n"
                "- NO le ofrezcas el producto/servicio principal: ya lo tiene.\n"
                "- Asume que conoce el negocio. Evita explicaciones básicas de qué hacemos.\n"
                "- Trato cordial y familiar, como con alguien que ya nos conoce.\n"
                "- Si pregunta algo nuevo, ayuda a resolverlo. Si parece duda comercial "
                "sobre un servicio adicional, sondea suavemente pero SIN táctica de venta.\n"
                "- Si detectas una queja o reclamo serio, escálalo al humano (no intentes "
                "resolverlo solo).\n"
                "- Mantén un tono profesional pero más distendido: el cliente ya invirtió en "
                "nosotros, no hace falta convencerlo de nada."
            )
            if takeover.was_recently_converted(telefono):
                customer_block += (
                    "\n\nNota: este contacto fue marcado como cliente recientemente. "
                    "Ajusta tu tono y deja de intentar venderle lo que ya compró."
                )
            dynamic_parts.append(customer_block)

    dynamic_system = "".join(dynamic_parts)

    # === Build messages list ===
    # Para Anthropic: structured content blocks con cache_control en la parte estatica
    # Para otros: string concatenado (auto-cache de OpenAI/DeepSeek igual cubre el prefijo)
    # Seleccionar tier y modelos primero para saber si aplica cache_control
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

    use_cache_control = any(_is_anthropic_model(m) for m in models)

    if use_cache_control:
        system_content_blocks: list[dict] = [
            {
                "type": "text",
                "text": static_system,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        if dynamic_system:
            system_content_blocks.append({
                "type": "text",
                "text": dynamic_system,
            })
        system_message: dict = {"role": "system", "content": system_content_blocks}
    else:
        system_message = {"role": "system", "content": static_system + dynamic_system}

    mensajes = [system_message]
    for m in historial:
        if m.get("content", "").strip() != "SILENCIO":
            mensajes.append({"role": m["role"], "content": m["content"]})
    mensajes.append({"role": "user", "content": mensaje})

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
                # Log con cache info
                usage = response.usage
                prompt_tokens = getattr(usage, "prompt_tokens", 0)
                completion_tokens = getattr(usage, "completion_tokens", 0)

                # cached_tokens viene en prompt_tokens_details (extension OpenAI/OpenRouter)
                cached_tokens = 0
                details = getattr(usage, "prompt_tokens_details", None)
                if details is not None:
                    if isinstance(details, dict):
                        cached_tokens = int(details.get("cached_tokens", 0) or 0)
                    else:
                        cached_tokens = int(getattr(details, "cached_tokens", 0) or 0)

                modelo_usado = getattr(response, "model", models[0])
                cache_info = f" cached={cached_tokens}" if cached_tokens > 0 else ""
                logger.info(
                    f"Respuesta generada ({prompt_tokens} in / {completion_tokens} out{cache_info}) "
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
