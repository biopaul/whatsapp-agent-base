# agent/main.py — Servidor FastAPI + Webhook de WhatsApp
# Generado por AgentKit

"""
Servidor principal del agente de WhatsApp de SimpleProp (Sofi).
Funciona con cualquier proveedor (Whapi, Meta, Twilio) gracias a la capa de providers.
"""

import os
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv

from agent.brain import generar_respuesta
from agent.memory import inicializar_db, guardar_mensaje, obtener_historial, obtener_ultimo_timestamp, existe_mensaje_id
from agent import brain
from agent.providers import obtener_proveedor
from agent.config_loader import get_notify_phone, get_notify_name, get_tz_offset, get_capabilities, is_within_business_hours, get_out_of_hours_message, invalidate_cache, is_agent_paused, get_pause_reason, get_config_updated_at, get_tts_config, is_solo_mode
from agent.transcriber import procesar_audio
from agent.reactions import elegir_reaccion
from agent.knowledge_loader import get_public_docs
from agent import usage_reporter, takeover, outbound, debouncer, labels
from agent import tts_client, audio_converter, tts_voices, tts_text_cleaner
from agent import contacts_webhook
from agent import guided_dispatcher, guided_selection, guided_actions, guided_templates
from agent.memory import obtener_dispatch_activo

def _silencios_consecutivos(historial: list[dict]) -> int:
    """
    Cuenta cuántos mensajes consecutivos del asistente son SILENCIO
    al final del historial.
    """
    count = 0
    for msg in reversed(historial):
        if msg["role"] == "assistant":
            if msg["content"].strip() == "SILENCIO":
                count += 1
            else:
                break
    return count


def _debe_prebloquear(historial: list[dict]) -> bool:
    """
    Pre-bloquea sin llamar a Claude si hay silencios consecutivos recientes,
    pero cada 3 silencios deja pasar un mensaje para que Claude evalúe
    si el cliente retomó con una consulta legítima.
    """
    n = _silencios_consecutivos(historial)
    if n == 0:
        return False
    # Cada 3 silencios consecutivos, Claude obtiene una oportunidad
    return n % 3 != 0


def _saludo_por_hora() -> str:
    """Retorna el saludo apropiado segun la hora local configurada."""
    tz_local = timezone(timedelta(hours=get_tz_offset()))
    hora = datetime.now(tz_local).hour
    if 6 <= hora < 12:
        return "Buen día"
    elif 12 <= hora < 20:
        return "Buenas tardes"
    else:
        return "Buenas noches"


def _dividir_partes(texto: str) -> list[str]:
    """
    Divide la respuesta de Claude en partes usando '---' como separador.
    Claude usa esta convencion cuando el prompt le indica enviar mensajes cortos
    y dividir respuestas largas en partes.
    Filtra partes vacias y normaliza espacios.
    """
    # Soporta: '\n---\n', '\n\n---\n\n', '---' solo en una linea
    import re
    partes = re.split(r'\n\s*---\s*\n', texto)
    return [p.strip() for p in partes if p.strip()]


def _parsear_enviar_archivo(respuesta: str) -> tuple[str, str | None]:
    """
    Busca la señal ENVIAR_ARCHIVO:<nombre> al final de la respuesta de Claude.
    Retorna (texto_limpio, nombre_archivo_o_None).
    La señal puede estar en la ultima linea o precedida de un salto.
    """
    lineas = respuesta.rstrip().splitlines()
    for i in range(len(lineas) - 1, max(len(lineas) - 4, -1), -1):
        linea = lineas[i].strip()
        if linea.upper().startswith("ENVIAR_ARCHIVO:"):
            nombre = linea[len("ENVIAR_ARCHIVO:"):].strip()
            texto_limpio = "\n".join(lineas[:i] + lineas[i + 1:]).strip()
            return texto_limpio, nombre
    return respuesta, None


def _detectar_keyword_escalar(texto: str) -> bool:
    """Detecta frases que indican que el cliente quiere atención humana."""
    texto_lower = texto.lower()
    return any(kw in texto_lower for kw in KEYWORDS_ESCALAR)


async def _enviar_alerta_humano(telefono: str, motivo: str) -> None:
    """Envia alerta al numero configurado para escalado humano."""
    notify_phone = get_notify_phone()
    if not notify_phone:
        return
    notify_name = get_notify_name()
    numero_limpio = telefono.split("@")[0]
    link = f"https://wa.me/{numero_limpio}"
    saludo = f"*{notify_name}, atencion requerida*" if notify_name else "*Atencion requerida*"
    alerta = f"{saludo}\n\n{motivo}\n\n{link}"
    try:
        await proveedor.enviar_mensaje(notify_phone, alerta)
    except Exception as e:
        logger.error(f"Error enviando alerta a humano: {e}")


async def _activar_escalacion(chat_id: str, motivo: str) -> None:
    """
    Cierra el ciclo de escalacion en TRES pasos coordinados:
      1. Notificar al humano dueno del agente via WhatsApp
      2. Activar takeover manual (silencia la IA hasta que el humano libere)
      3. Marcar el chat con etiqueta "Escalado" en el plugin WP

    Cada paso es fail-open: si uno falla, los otros igual se intentan.
    """
    try:
        await _enviar_alerta_humano(chat_id, motivo)
    except Exception as e:
        logger.error(f"_activar_escalacion alerta_humano fallo: {e}")
    try:
        await takeover.register_manual_takeover(chat_id)
    except Exception as e:
        logger.warning(f"_activar_escalacion register_manual_takeover fallo: {e}")
    try:
        await labels.apply_label(chat_id, "Escalado")
    except Exception as e:
        logger.warning(f"_activar_escalacion apply_label fallo: {e}")


def _respuesta_version() -> str:
    """
    Respuesta al comando /version.
    Muestra la fecha de ultima actualizacion de la config en WP, en hora local del agente.
    """
    raw = get_config_updated_at()
    if not raw:
        return "Version: sin informacion de actualizacion disponible."
    try:
        from datetime import datetime, timezone, timedelta
        # WP guarda en UTC con formato MySQL: '2026-04-17 14:30:00'
        dt_utc = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        tz_local = timezone(timedelta(hours=get_tz_offset()))
        dt_local = dt_utc.astimezone(tz_local)
        meses = ["enero","febrero","marzo","abril","mayo","junio",
                 "julio","agosto","septiembre","octubre","noviembre","diciembre"]
        fecha = f"{dt_local.day} de {meses[dt_local.month - 1]} de {dt_local.year}"
        hora  = dt_local.strftime("%H:%M")
        return f"Ultima actualizacion: {fecha} a las {hora}."
    except Exception:
        return f"Ultima actualizacion: {raw}."


async def _es_nueva_sesion(telefono: str) -> bool:
    """
    Retorna True si el último mensaje fue de un día diferente (en hora Argentina)
    o si no hay historial previo.
    """
    ultimo = await obtener_ultimo_timestamp(telefono)
    if ultimo is None:
        return True
    tz_local = timezone(timedelta(hours=get_tz_offset()))
    ahora = datetime.now(tz_local)
    ultimo_local = ultimo.replace(tzinfo=timezone.utc).astimezone(tz_local)
    return ahora.date() != ultimo_local.date()

load_dotenv()

# Configuración de logging según entorno
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
log_level = logging.DEBUG if ENVIRONMENT == "development" else logging.INFO
logging.basicConfig(level=log_level)
logger = logging.getLogger("agentkit")

# Proveedor de WhatsApp (se configura en .env con WHATSAPP_PROVIDER)
proveedor = obtener_proveedor()
PORT = int(os.getenv("PORT", 8000))
WAHA_SESSION = os.getenv("WAHA_SESSION", "default")

async def send_user_message(chat_id: str, text: str) -> bool:
    """
    Envia un mensaje al cliente con checkpoint de takeover (race protection).

    Si entre la generacion del LLM y este envio el chat paso a manual mode,
    descartamos el mensaje. Caso happy: enviamos via provider y persistimos
    en historial con mensaje_id (para que el webhook from_me posterior dedupee).

    Returns: True si se envio, False si se descarto o fallo el envio.
    """
    if await takeover.is_chat_in_manual_mode(chat_id):
        logger.info(f"discard_response reason=manual_mode_during_generation chat_id={chat_id}")
        return False

    msg_id = await proveedor.enviar_mensaje_returning_id(chat_id, text)
    if msg_id is None:
        return False

    # Registrar envio del agente para el outbound tracker. Asi cuando llegue el
    # eco fromMe de WAHA (con source vacio en engines antiguos), no se confunde
    # con un humano escribiendo desde WhatsApp Web.
    outbound.register_agent_outbound(chat_id)

    persisted_id = msg_id if msg_id != "ok_no_id" else None
    await guardar_mensaje(chat_id, "assistant", text, mensaje_id=persisted_id)

    # Fire-and-forget: notificar a WP para mantener contacts sincronizado
    asyncio.create_task(contacts_webhook.touch_contact(
        chat_id=chat_id, direction="out", preview=text
    ))
    return True


_ENGAGEMENT_INSTRUCTIONS = {
    5: "",
    4: (
        "Nivel de respuesta ALTO: responde casi todos los mensajes. "
        "Emiti SILENCIO solo si el mensaje es un acuse vacio sin contenido "
        "(ej: 'ok', 'dale', 'gracias', 'ya esta') que no requiere respuesta."
    ),
    3: (
        "Nivel de respuesta MEDIO: responde solo si el mensaje tiene sustancia "
        "(una pregunta concreta, un pedido, o contenido nuevo relevante). "
        "Si es chitchat sin contenido, comentario social, o acuse: emiti SILENCIO."
    ),
    2: (
        "Nivel de respuesta BAJO: responde solo si el mensaje toca temas "
        "relacionados con tu negocio o tus objetivos configurados. "
        "Para cualquier mensaje off-topic, social, o sin relacion clara con "
        "lo que ofreces: emiti SILENCIO."
    ),
    1: (
        "Nivel de respuesta MINIMO: responde unicamente si el mensaje encaja "
        "ESTRICTAMENTE con los objetivos exactos de tu rol configurado. "
        "Cualquier mensaje fuera de esos objetivos —aunque sea cordial o "
        "relacionado tangencialmente— emiti SILENCIO sin excepcion."
    ),
}


def _engagement_instruction(level) -> str:
    """
    Retorna la instruccion para el LLM segun el nivel de disposicion a responder
    audios (1-5). Default 5 (sin restriccion) si el valor es invalido o ausente.
    """
    try:
        lvl = int(level)
    except (TypeError, ValueError):
        lvl = 5
    if lvl < 1 or lvl > 5:
        lvl = 5
    return _ENGAGEMENT_INSTRUCTIONS.get(lvl, "")


def _debe_enviar_audio(fue_audio: bool, tts_config: dict, text: str) -> bool:
    """Gate combinado: debe esta respuesta salir como voice note?"""
    if not fue_audio:
        return False
    if not tts_config.get("enabled"):
        return False
    if not tts_config.get("voice_id"):
        return False
    max_chars = tts_config.get("max_chars_per_message", 640)
    if len(text) > max_chars:
        return False
    seconds_remaining = tts_config.get("seconds_remaining")
    if seconds_remaining is not None and seconds_remaining <= 0:
        return False
    return True


def _estimate_seconds(text: str) -> int:
    """Estimacion empirica de duracion del audio (~16 chars/seg para espanol Turbo v2.5)."""
    return max(1, round(len(text) / 16))


async def _send_audio_message(chat_id: str, text: str, tts_config: dict) -> dict:
    """
    Pipeline TTS completo: synthesize -> convert -> send.
    Retorna {"ok": True} o {"ok": False, "reason": str}.
    """
    voice_key = tts_config.get("voice_id")
    elevenlabs_voice_id = tts_voices.resolve_voice_id(voice_key)
    if elevenlabs_voice_id is None:
        return {"ok": False, "reason": "voice_key_unknown"}

    # Sanitizar texto antes de TTS: quitar emojis, risas escritas, markdown,
    # puntuacion repetida (defense in depth — el LLM ya recibe la instruccion,
    # esto garantiza limpieza si el modelo se escapa).
    text_clean = tts_text_cleaner.sanitize_for_tts(text)
    if not text_clean:
        return {"ok": False, "reason": "empty_after_sanitize"}

    mp3 = await tts_client.synthesize(
        text=text_clean,
        voice_id=elevenlabs_voice_id,
        api_key=tts_config.get("api_key", ""),
        model=tts_config.get("model", "eleven_turbo_v2_5"),
    )
    if mp3 is None:
        reason = tts_client.last_error_reason() or "elevenlabs_unknown"
        return {"ok": False, "reason": reason}

    ogg = await audio_converter.mp3_to_ogg_opus(mp3)
    if ogg is None:
        return {"ok": False, "reason": "ffmpeg_failed"}

    msg_id = await proveedor.enviar_audio(chat_id, ogg)
    if msg_id is None:
        return {"ok": False, "reason": "waha_sendvoice_failed"}

    # Persistir en historial + contabilizar usage
    persisted_id = msg_id if msg_id != "ok_no_id" else None
    await guardar_mensaje(chat_id, "assistant", text, mensaje_id=persisted_id)
    usage_reporter.report_tts_used(_estimate_seconds(text))

    # Fire-and-forget: notificar a WP del touch out
    asyncio.create_task(contacts_webhook.touch_contact(
        chat_id=chat_id, direction="out", preview=text
    ))
    return {"ok": True}


async def send_audio_or_text(
    chat_id: str,
    text: str,
    fue_audio: bool,
    tts_config: dict,
) -> bool:
    """
    Decide voice note vs texto basado en config + flag.
    Fallback silencioso a texto si TTS falla.
    """
    if _debe_enviar_audio(fue_audio, tts_config, text):
        result = await _send_audio_message(chat_id, text, tts_config)
        if result["ok"]:
            return True
        usage_reporter.report_tts_error(chat_id, result.get("reason", "unknown"))
        logger.warning(f"TTS fail reason={result.get('reason')} chat={chat_id} -> fallback texto")
    return await send_user_message(chat_id, text)


async def _handle_testaudio_command(chat_id: str) -> None:
    """
    Comando /testaudio — fuerza envio de audio de prueba bypassando el gate de
    fue_audio. Si los demas gates fallan o el pipeline TTS falla, responde
    texto con diagnostico detallado de la causa.
    """
    test_text = "Esta es una prueba de audio."
    tts_config = get_tts_config()

    def _diag_lines() -> list[str]:
        api_key_status = "yes" if tts_config.get("api_key") else "no (verificando env var fallback)"
        sr = tts_config.get("seconds_remaining")
        sr_str = "unlimited" if sr is None else str(sr)
        return [
            f"• tts.enabled = {tts_config.get('enabled', False)}",
            f"• tts.voice_id = {tts_config.get('voice_id', None)}",
            f"• tts.api_key configured = {api_key_status}",
            f"• tts.seconds_remaining = {sr_str}",
            f"• tts.max_chars_per_message = {tts_config.get('max_chars_per_message', 640)}",
        ]

    # Pre-checks
    if not tts_config.get("enabled"):
        msg = "❌ TTS no habilitado para este agente.\n\n" + "\n".join(_diag_lines())
        await send_user_message(chat_id, msg)
        return
    if not tts_config.get("voice_id"):
        msg = "❌ Voice ID no configurada.\n\n" + "\n".join(_diag_lines())
        await send_user_message(chat_id, msg)
        return
    sr = tts_config.get("seconds_remaining")
    if sr is not None and sr <= 0:
        msg = "❌ Budget de TTS agotado para este mes.\n\n" + "\n".join(_diag_lines())
        await send_user_message(chat_id, msg)
        return

    # Intento TTS real
    result = await _send_audio_message(chat_id, test_text, tts_config)
    if result["ok"]:
        # Audio enviado — no hace falta diagnostico
        return

    # Pipeline TTS fallo — reportar la causa
    reason = result.get("reason", "unknown")
    usage_reporter.report_tts_error(chat_id, reason)
    msg = f"❌ TTS pipeline fallo: {reason}\n\n" + "\n".join(_diag_lines())
    await send_user_message(chat_id, msg)


async def _procesar_mensaje_entrante(chat_id: str, texto: str, mensaje_id: str | None = None, fue_audio: bool = False) -> None:
    """
    Procesa un mensaje del cliente (from_me=False).
    Orden:
    1. Checkpoint takeover: si manual mode, persistir user + skip.
    2. Selection check: si hay dispatch activo + input matchea opcion -> ejecutar accion.
    3. Flujo normal: guardar + LLM + dispatcher si respondio con <plantilla>.
    """
    if await takeover.is_chat_in_manual_mode(chat_id):
        logger.info(f"skip_response reason=manual_mode chat_id={chat_id}")
        await guardar_mensaje(chat_id, "user", texto, mensaje_id=mensaje_id)
        # Fire-and-forget: notificar a WP del touch entrante (dispara stop-on-reply si aplica)
        from agent.memory import obtener_contacto as _obt_contacto
        try:
            _contacto = await _obt_contacto(chat_id)
            _name = _contacto.nombre if _contacto and _contacto.nombre else None
        except Exception as _e:
            _name = None
            logger.debug(f"touch_contact: no se pudo obtener contacto - {_e}")
        asyncio.create_task(contacts_webhook.touch_contact(
            chat_id=chat_id, direction="in", name=_name, preview=texto
        ))
        return

    await guardar_mensaje(chat_id, "user", texto, mensaje_id=mensaje_id)
    # Fire-and-forget: notificar a WP del touch entrante (dispara stop-on-reply si aplica)
    from agent.memory import obtener_contacto as _obt_contacto
    try:
        _contacto = await _obt_contacto(chat_id)
        _name = _contacto.nombre if _contacto and _contacto.nombre else None
    except Exception as _e:
        _name = None
        logger.debug(f"touch_contact: no se pudo obtener contacto - {_e}")
    asyncio.create_task(contacts_webhook.touch_contact(
        chat_id=chat_id, direction="in", name=_name, preview=texto
    ))

    # Selection-first: hay dispatch activo? matchea el input?
    from agent import memory as _mem
    dispatch = await _mem.obtener_dispatch_activo(chat_id)
    if dispatch is not None:
        match = guided_selection.match_user_input(texto, dispatch)
        if match is not None:
            from datetime import datetime as _dt, timezone as _tz
            opt = match["option"]
            logger.info(
                f"guided_selection chat={chat_id} dispatch={dispatch['id']} "
                f"option_id={opt.get('id')} match_kind={match['match_kind']}"
            )
            remote_id = dispatch.get("remote_dispatch_id")
            if remote_id is not None:
                await guided_templates.register_selection(remote_id, int(opt["id"]), _dt.now(_tz.utc))

            result = await guided_actions.ejecutar_accion(
                option=opt, chat_id=chat_id, session_id=WAHA_SESSION,
                provider=proveedor, parent_dispatch_local_id=dispatch["id"],
            )

            if result["kind"] == "text_injection":
                injected = result["injected_text"]
                historial = await _mem.obtener_historial(chat_id)
                respuesta = await brain.generar_respuesta(injected, historial, telefono=chat_id)
                await _procesar_respuesta_llm(chat_id, respuesta, fue_audio=fue_audio)
            return

    # Flujo normal
    historial = await obtener_historial(chat_id)
    respuesta = await brain.generar_respuesta(texto, historial, telefono=chat_id)
    await _procesar_respuesta_llm(chat_id, respuesta, fue_audio=fue_audio)


async def _procesar_respuesta_llm(chat_id: str, respuesta: str, fue_audio: bool = False) -> None:
    """
    Toma la salida del LLM y decide:
    - Si contiene <plantilla>X</plantilla> -> guided_dispatcher.dispatch_plantilla
    - Si no -> send_audio_or_text con splits normales (audio si fue_audio + TTS habilitado)
    """
    plantilla_name = guided_dispatcher.parse_plantilla_invocation(respuesta)
    if plantilla_name:
        result = await guided_dispatcher.dispatch_plantilla(
            provider=proveedor, session_id=WAHA_SESSION,
            chat_id=chat_id, name=plantilla_name,
        )
        if result.get("ok"):
            return
        logger.warning(f"dispatch_plantilla fail: {result.get('reason')} - sending raw LLM text")

    tts_config = get_tts_config()
    for parte in _dividir_partes(respuesta):
        await send_audio_or_text(chat_id, parte, fue_audio=fue_audio, tts_config=tts_config)


async def _procesar_mensaje_propio(chat_id: str, texto: str, mensaje_id: str | None = None) -> None:
    """
    Procesa un mensaje from_me=True. En modo normal lo ignoramos (es nuestro propio
    mensaje, ya guardado por send_user_message). Pero si el chat esta o estuvo
    recientemente en manual, el mensaje puede ser de un humano - lo guardamos como
    assistant para que el LLM lo vea cuando vuelva a tomar control.
    """
    en_manual = await takeover.is_chat_in_manual_mode(chat_id)
    recently = takeover.was_recently_manual(chat_id) if not en_manual else None

    if not en_manual and recently is None:
        return  # mensaje normal del agente, ya guardado por send_user_message

    if mensaje_id and await existe_mensaje_id(chat_id, mensaje_id):
        return  # ya guardado por send_user_message - dedupe

    await guardar_mensaje(chat_id, "assistant", texto, mensaje_id=mensaje_id)
    logger.info(f"captured_human_message chat_id={chat_id} mensaje_id={mensaje_id}")


KEYWORDS_ESCALAR = [
    # Solicitud directa de humano
    "quiero hablar con",
    "hablar con alguien",
    "hablar con una persona",
    "hablar con un humano",
    "hablar con alguien del equipo",
    "hablar con alguien de verdad",
    "con un asesor",
    "con el dueño",
    "con el encargado",
    "me comunicas con",
    "me pasas con",
    "quiero un humano",
    "necesito un humano",
    "llamame",
    "llamar a alguien",
    # Rechazo al bot / pedido de persona real
    "persona real",
    "alguien real",
    "ser humano",
    "operador humano",
    "atencion humana",
    "atención humana",
    "no quiero un bot",
    "no quiero hablar con un bot",
    "no kiero hablar con un bot",
    "no kiero un bot",
    "no quiero hablar con una maquina",
    "no quiero hablar con una máquina",
    "no me sirve este chat",
    "esto no me ayuda",
    "esto no sirve",
    "no me estas ayudando",
    "no me estás ayudando",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa la base de datos al arrancar el servidor."""
    await inicializar_db()
    await usage_reporter.start()
    # Single-shot heartbeat para reportar version apenas arranca el container
    try:
        await usage_reporter.report_version_only()
        logger.info("Version reportada al plugin via /usage")
    except Exception as e:
        logger.warning(f"No se pudo reportar version al startup: {e}")
    # Cargar chats actualmente en manual mode (handoff humano-IA)
    try:
        await takeover.preload_active()
    except Exception as e:
        logger.warning(f"No se pudo preload takeover state: {e}")
    logger.info("Base de datos inicializada")
    logger.info(f"Servidor AgentKit corriendo en puerto {PORT}")
    logger.info(f"Proveedor de WhatsApp: {proveedor.__class__.__name__}")
    yield


app = FastAPI(
    title="SimpleProp — Sofi (WhatsApp AI Agent)",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/")
async def health_check():
    """Endpoint de salud para Railway/monitoreo."""
    return {"status": "ok", "service": "simpleprop-sofi"}


@app.get("/config")
async def get_current_config():
    """Devuelve la config activa del agente (para pre-popular el form de WP)."""
    from agent.config_loader import get_config
    return get_config()


@app.post("/config/reload")
async def reload_config():
    """Invalida cache de config remota para forzar re-fetch."""
    invalidate_cache()
    return {"status": "ok", "message": "Config cache invalidated"}


@app.post("/webhook/statuses")
async def webhook_statuses(request: Request):
    """Recibe eventos de estado de Whapi (ticks, receipts). Se ignoran por ahora."""
    return {"status": "ok"}


@app.get("/webhook")
async def webhook_verificacion(request: Request):
    """Verificación GET del webhook (requerido por Meta Cloud API, no-op para otros)."""
    resultado = await proveedor.validar_webhook(request)
    if resultado is not None:
        return PlainTextResponse(str(resultado))
    return {"status": "ok"}


async def _procesar_y_responder(
    chat_id: str,
    texto: str,
    mensaje_id: str | None,
    fue_audio: bool,
    message_count: int = 1,
) -> None:
    """
    Bloque IA: prebloqueo, escalado, generacion Claude, envio multi-parte,
    usage reporting, archivos. Lo llama el debouncer cuando la ventana de
    espera expira, con el texto combinado de uno o varios mensajes seguidos.

    Pre-condiciones (validadas por el caller en el webhook):
      - chat_id NO esta en manual mode
      - El agente NO esta pausado
      - Estamos DENTRO del horario de atencion
      - El texto no es vacio
      - No es el comando /version
    """
    caps = get_capabilities()
    historial = await obtener_historial(chat_id)

    # Pre-bloquear si hay silencios consecutivos recientes (sin llamar a Claude)
    if _debe_prebloquear(historial):
        await guardar_mensaje(chat_id, "user", texto)
        await guardar_mensaje(chat_id, "assistant", "SILENCIO")
        logger.info(f"Pre-bloqueado {chat_id} ({_silencios_consecutivos(historial)} silencios consecutivos)")
        return

    # Escalado por keyword -- el cliente pide explicitamente un humano.
    # En modo individual saltamos esta rama: no hay equipo a quien escalar,
    # asi que dejamos que el LLM responda con el bloque "MODO INDIVIDUAL"
    # del system prompt (que le explica que tiene que asegurarle al cliente
    # que la persona que atiende es la unica disponible).
    if not is_solo_mode() and _detectar_keyword_escalar(texto):
        respuesta_kw = "Te conecto con alguien del equipo, en unos minutos te escriben por aca."
        await guardar_mensaje(chat_id, "user", texto)
        delay = max(1, min(round(len(respuesta_kw) * 0.025), 5))
        await proveedor.indicar_escribiendo(chat_id, delay)
        await asyncio.sleep(delay)
        await send_user_message(chat_id, respuesta_kw)
        await _activar_escalacion(chat_id, "El cliente pide hablar con un humano")
        logger.info(f"Escalado por keyword: {chat_id}")
        return

    # Detectar si es nueva sesion (nuevo dia) — solo informar la hora, no prescribir formato
    contexto = ""
    if await _es_nueva_sesion(chat_id):
        saludo = _saludo_por_hora()
        contexto = f"Es la primera vez que este cliente escribe hoy. Es hora de {saludo.lower()}."

    # Indicar profundidad de conversacion para calibrar largo de respuesta
    turnos = len([m for m in historial if m["role"] == "user"])
    if turnos >= 3:
        profundidad = f"Ya llevan {turnos} intercambios. Responde solo lo que se pregunta, sin introduccion."
        contexto = f"{contexto}\n{profundidad}".strip() if contexto else profundidad

    # Si vinieron varios mensajes seguidos, decirle a la IA para que responda una sola vez.
    if message_count > 1:
        nota_multi = (
            f"El cliente envio {message_count} mensajes seguidos sin esperar respuesta. "
            "Responde UNA sola vez cubriendo lo que pregunto o dijo en todos ellos. "
            "No repitas lo que escribio; no respondas mensaje por mensaje."
        )
        contexto = f"{contexto}\n{nota_multi}".strip() if contexto else nota_multi

    # Si el cliente mando audio, informarle al LLM como va a salir la respuesta.
    # - Si TTS esta disponible: respuesta = audio. Evita que diga "no puedo audios".
    # - Si TTS NO esta disponible (plan/owner/voice/budget/key): respuesta = texto.
    #   Evita igual que diga "no puedo audios" y que se disculpe — solo respondé al
    #   contenido como si nada.
    if fue_audio:
        _tts_cfg_for_prompt = get_tts_config()
        if _tts_cfg_for_prompt.get("enabled") and _tts_cfg_for_prompt.get("voice_id"):
            nota_audio = (
                "El cliente envio una nota de voz. Tu respuesta sera convertida "
                "automaticamente a audio y enviada como nota de voz. Por eso, "
                "escribi como si estuvieras hablando, no chateando:\n"
                "- NO uses emojis (se leerian como 'carita feliz', 'manos juntas', etc).\n"
                "- NO escribas risas tipo 'jaja', 'jeje', 'lol', 'xd' (se leen literal "
                "y suenan robotico).\n"
                "- NO uses markdown (asteriscos, guiones bajos, comillas invertidas).\n"
                "- NO uses puntuacion exagerada (!!!, ???, ...).\n"
                "- Mantene la respuesta concisa porque el cliente la va a escuchar.\n"
                "- NO digas que no podes mandar audios, porque si podes "
                "(el sistema lo hace por vos)."
            )
            # Disposicion a responder audios (1-5). Solo aplica cuando la
            # respuesta saldria como audio; ahorra budget TTS frenando bucles.
            engagement = _engagement_instruction(
                _tts_cfg_for_prompt.get("audio_engagement_level")
            )
            if engagement:
                nota_audio = f"{nota_audio}\n{engagement}"
        else:
            nota_audio = (
                "El cliente envio una nota de voz. En este momento solo podes "
                "responder con texto (no audio). Respondé naturalmente al "
                "contenido del mensaje. NO le expliques al cliente por que solo "
                "podes texto, ni te disculpes — simplemente respondé al contenido "
                "como si nada."
            )
        contexto = f"{contexto}\n{nota_audio}".strip() if contexto else nota_audio

    # Generar respuesta con Claude
    respuesta = await generar_respuesta(texto, historial, contexto, telefono=chat_id)

    # Si Claude indica silencio, guardar en DB y no enviar
    if respuesta.strip() == "SILENCIO":
        await guardar_mensaje(chat_id, "user", texto)
        await guardar_mensaje(chat_id, "assistant", "SILENCIO")
        logger.info(f"Silencio activado para {chat_id}")
        return

    # Detectar senal de escalado: ESCALAR: <motivo>\n<mensaje al cliente>
    # En modo individual el bloque del system prompt le dice al LLM que NO emita
    # el marcador. Defensa profunda: si igual aparece (modelo desobedece o cache
    # antiguo de prompt), lo limpiamos del texto pero NO disparamos escalacion
    # (no hay equipo a quien escalar). Loggeamos para auditoria.
    motivo_escalar = None
    if respuesta.startswith("ESCALAR:"):
        primera_linea, _, resto = respuesta.partition("\n")
        if is_solo_mode():
            logger.warning(
                f"ESCALAR: emitido en modo solo (LLM ignoro instruccion); "
                f"limpiando marker sin disparar escalacion. chat={chat_id} "
                f"motivo='{primera_linea[len('ESCALAR:'):].strip()[:80]}'"
            )
            resto_limpio = resto.strip()
            # Si el LLM solo emitio el marker sin texto para el cliente, usamos
            # un fallback amable para no enviar mensaje vacio.
            respuesta = resto_limpio if resto_limpio else "Decime, ¿en qué puedo ayudarte?"
        else:
            motivo_escalar = primera_linea[len("ESCALAR:"):].strip()
            respuesta = resto.strip()

    # Detectar señal de envio de archivo: ENVIAR_ARCHIVO:<nombre>
    archivo_nombre: str | None = None
    respuesta, archivo_nombre = _parsear_enviar_archivo(respuesta)

    # Guardar mensaje del usuario; el assistant se persiste por parte via send_user_message
    await guardar_mensaje(chat_id, "user", texto)

    # Dividir en partes si Claude uso separador ---
    partes = _dividir_partes(respuesta)

    # TTS config: si fue_audio + gates OK, send_audio_or_text envia voice note
    tts_config = get_tts_config()

    for idx, parte in enumerate(partes):
        delay = max(1, min(round(len(parte) * 0.025), 5))
        if idx == 0:
            # Primera parte: indicador de presencia segun tipo de mensaje
            if fue_audio:
                await proveedor.indicar_grabando(chat_id)
            else:
                await proveedor.indicar_escribiendo(chat_id, delay)
        else:
            # Partes siguientes: siempre "escribiendo" con pausa realista
            await proveedor.indicar_escribiendo(chat_id, delay)
        await asyncio.sleep(delay)
        await send_audio_or_text(chat_id, parte, fue_audio=fue_audio, tts_config=tts_config)

    logger.info(
        f"Respuesta a {chat_id} ({len(partes)} parte/s, {message_count} msg combinados): "
        f"{respuesta[:120]}"
    )

    # Reportar uso al plugin WP (no-bloqueante)
    await usage_reporter.report(chat_id)

    # Enviar archivo publico si Claude lo solicito
    if archivo_nombre:
        public_docs = get_public_docs()
        doc = next((d for d in public_docs if d["name"] == archivo_nombre), None)
        if doc and doc.get("url"):
            ok_file = await proveedor.enviar_archivo(chat_id, doc["url"], archivo_nombre)
            if ok_file:
                outbound.register_agent_outbound(chat_id)
        else:
            logger.warning(f"Archivo publico no encontrado: {archivo_nombre!r}")

    if motivo_escalar:
        await _activar_escalacion(chat_id, motivo_escalar)
        logger.info(f"Escalacion completada (alerta + takeover + label): {motivo_escalar}")


@app.post("/webhook/messages")
@app.post("/webhook")
async def webhook_handler(request: Request):
    """
    Recibe mensajes de WhatsApp via el proveedor configurado.
    Procesa el mensaje, genera respuesta con Claude y la envía de vuelta.
    """
    try:
        # Parsear webhook — el proveedor normaliza el formato
        mensajes = await proveedor.parsear_webhook(request)

        caps = get_capabilities()
        fue_audio = False

        for msg in mensajes:
            if msg.es_propio:
                # Detectar humano escribiendo desde WhatsApp Web/app -> activar takeover
                # manual en WP. Mensajes con source=api (eco del propio agente o
                # Seguimiento) NO disparan registro: should_register filtra.
                if takeover.should_register_external_takeover(msg):
                    try:
                        await takeover.register_manual_takeover(msg.telefono)
                    except Exception as e:
                        logger.warning(f"register_manual_takeover fallo para {msg.telefono}: {e}")
                # Capturar el mensaje en historial cuando el chat esta/estuvo en manual
                # (handoff humano-IA), para que el LLM tenga contexto al volver.
                if msg.texto:
                    await _procesar_mensaje_propio(
                        msg.telefono,
                        msg.texto,
                        mensaje_id=getattr(msg, "mensaje_id", None),
                    )
                continue

            # Checkpoint manual mode: persistir entrante + skip LLM/respuesta
            # IMPORTANTE: NO marcar leido (tick azul) cuando el agente esta en silencio.
            if await takeover.is_chat_in_manual_mode(msg.telefono):
                logger.info(f"skip_response reason=manual_mode chat_id={msg.telefono}")
                if msg.texto:
                    await guardar_mensaje(
                        msg.telefono,
                        "user",
                        msg.texto,
                        mensaje_id=getattr(msg, "mensaje_id", None),
                    )
                continue

            # Soft pause — ignorar mensajes si el plan esta pausado
            if is_agent_paused():
                logger.info(f"Agente pausado ({get_pause_reason()!r}) — ignorando mensaje de {msg.telefono}")
                continue

            # Gate de horario — silencio total fuera de horario.
            # NO enviar mensaje automatico, NO marcar leido, NO llamar a la IA.
            # El cliente vera ticks grises hasta que volvamos a estar en horario y
            # alguien (IA o humano) atienda.
            if not is_within_business_hours():
                logger.info(f"Fuera de horario — silencio total para {msg.telefono}")
                continue

            # Marcar como leido (ticks azules) — solo si va a procesar el mensaje.
            if caps.get("read_receipts", True):
                await proveedor.marcar_leido(msg.telefono)

            # Gate de imagen — descartar si el plan no lo habilita
            if getattr(msg, "image_url", None) and not caps.get("image_receive", False):
                logger.info(f"Imagen recibida de {msg.telefono} pero image_receive deshabilitado")
                continue

            # Transcribir audio si es nota de voz
            fue_audio = bool(msg.audio_url)
            if msg.audio_url and not msg.texto:
                if not caps.get("audio_receive", True):
                    logger.info(f"Audio recibido de {msg.telefono} pero audio_receive deshabilitado")
                    continue
                waha_key = os.getenv("WAHA_API_KEY", "")
                transcripcion = await procesar_audio(msg.audio_url, waha_key)
                if transcripcion:
                    msg.texto = transcripcion
                    logger.info(f"Audio transcripto de {msg.telefono}: {msg.texto[:80]}")
                else:
                    logger.warning(f"No se pudo transcribir audio de {msg.telefono}")
                    continue

            if not msg.texto:
                continue

            logger.info(f"Mensaje de {msg.telefono}: {msg.texto}")

            # Comando /version — responde sin llamar a Claude ni contar como mensaje
            if msg.texto.strip().lower() == "/version":
                await send_user_message(msg.telefono, _respuesta_version())
                continue

            # Comando /testaudio — fuerza audio de prueba (bypassa gate fue_audio)
            if msg.texto.strip().lower() == "/testaudio":
                await _handle_testaudio_command(msg.telefono)
                continue

            # Reaccion contextual al mensaje (feedback inmediato antes del debounce)
            if caps.get("reactions", True):
                emoji = elegir_reaccion(msg.texto)
                if emoji:
                    await proveedor.reaccionar(msg.telefono, msg.mensaje_id, emoji)
                    logger.info(f"Reaccion {emoji} a {msg.telefono}")

            # Schedule respuesta con debounce. Si llegan mas mensajes en
            # MESSAGE_DEBOUNCE_SEC, el handler recibe el texto combinado y
            # responde UNA sola vez en lugar de N veces.
            debouncer.schedule(
                msg.telefono,
                msg.texto,
                getattr(msg, "mensaje_id", None),
                fue_audio,
                _procesar_y_responder,
            )

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Error en webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/agent/notification")
async def agent_notification(
    request: Request,
    x_gowap_token: str = Header(default=""),
):
    """
    Recibe pushes desde WP para enviar mensajes proactivos al cliente final
    (recordatorios 24h, alertas de cancelacion, etc.). El mensaje se guarda
    en el historial como assistant para que el LLM tenga contexto en futuros
    turnos cuando el cliente responda.

    Auth: header X-Gowap-Token debe matchear el token del CONFIG_URL del agente.

    Body JSON: {phone, message, event_id?, kind?}
    """
    config_url = os.getenv("CONFIG_URL", "")
    expected_token = (config_url or "").rsplit("/config/", 1)[-1] if "/config/" in config_url else ""
    if not expected_token or x_gowap_token != expected_token:
        raise HTTPException(status_code=401, detail="invalid token")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")

    phone = str(body.get("phone", "") or "").strip()
    message = str(body.get("message", "") or "").strip()
    if not phone or not message:
        raise HTTPException(status_code=400, detail="missing fields")

    # send_user_message envia via provider y persiste en historial (con checkpoint takeover)
    try:
        ok = await send_user_message(phone, message)
    except Exception as e:
        logger.error(f"agent_notification: provider exception: {e}")
        raise HTTPException(status_code=502, detail="provider exception")

    if not ok:
        raise HTTPException(status_code=502, detail="provider failed")

    return {"status": "sent"}
