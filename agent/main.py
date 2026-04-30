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
from agent.memory import inicializar_db, guardar_mensaje, obtener_historial, obtener_ultimo_timestamp
from agent.providers import obtener_proveedor
from agent.config_loader import get_notify_phone, get_notify_name, get_tz_offset, get_capabilities, is_within_business_hours, get_out_of_hours_message, invalidate_cache, is_agent_paused, get_pause_reason, get_config_updated_at
from agent.transcriber import procesar_audio
from agent.reactions import elegir_reaccion
from agent.knowledge_loader import get_public_docs
from agent import usage_reporter

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

KEYWORDS_ESCALAR = [
    "quiero hablar con",
    "hablar con alguien",
    "hablar con una persona",
    "hablar con un humano",
    "hablar con alguien del equipo",
    "con un asesor",
    "con el dueño",
    "con el encargado",
    "me comunicas con",
    "me pasas con",
    "quiero un humano",
    "llamame",
    "llamar a alguien",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa la base de datos al arrancar el servidor."""
    await inicializar_db()
    await usage_reporter.start()
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
                continue

            # Soft pause — ignorar mensajes si el plan esta pausado
            if is_agent_paused():
                logger.info(f"Agente pausado ({get_pause_reason()!r}) — ignorando mensaje de {msg.telefono}")
                continue

            # Marcar como leido inmediatamente (ticks azules)
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
                await proveedor.enviar_mensaje(msg.telefono, _respuesta_version())
                continue

            # Gate de horario — responder fuera de horario sin llamar a la IA
            if not is_within_business_hours():
                out_msg = get_out_of_hours_message()
                await proveedor.enviar_mensaje(msg.telefono, out_msg)
                logger.info(f"Fuera de horario — respuesta enviada a {msg.telefono}")
                continue

            # Obtener historial ANTES de guardar el mensaje actual
            historial = await obtener_historial(msg.telefono)

            # Pre-bloquear si hay silencios consecutivos recientes (sin llamar a Claude)
            if _debe_prebloquear(historial):
                await guardar_mensaje(msg.telefono, "user", msg.texto)
                await guardar_mensaje(msg.telefono, "assistant", "SILENCIO")
                logger.info(f"Pre-bloqueado {msg.telefono} ({_silencios_consecutivos(historial)} silencios consecutivos)")
                continue

            # Escalado por keyword -- el cliente pide explicitamente un humano
            if _detectar_keyword_escalar(msg.texto):
                respuesta = "Claro! Te conecto con alguien del equipo ahora mismo."
                await guardar_mensaje(msg.telefono, "user", msg.texto)
                await guardar_mensaje(msg.telefono, "assistant", respuesta)
                delay = max(1, min(round(len(respuesta) * 0.025), 5))
                await proveedor.indicar_escribiendo(msg.telefono, delay)
                await asyncio.sleep(delay)
                await proveedor.enviar_mensaje(msg.telefono, respuesta)
                await _enviar_alerta_humano(msg.telefono, "El cliente pide hablar con un humano")
                logger.info(f"Escalado por keyword: {msg.telefono}")
                continue

            # Reaccion contextual al mensaje del cliente (antes de responder)
            if caps.get("reactions", True):
                emoji = elegir_reaccion(msg.texto)
                if emoji:
                    await proveedor.reaccionar(msg.telefono, msg.mensaje_id, emoji)
                    logger.info(f"Reaccion {emoji} a {msg.telefono}")

            # Detectar si es nueva sesion (nuevo dia) — solo informar la hora, no prescribir formato
            contexto = ""
            if await _es_nueva_sesion(msg.telefono):
                saludo = _saludo_por_hora()
                contexto = f"Es la primera vez que este cliente escribe hoy. Es hora de {saludo.lower()}."

            # Indicar profundidad de conversacion para calibrar largo de respuesta
            turnos = len([m for m in historial if m["role"] == "user"])
            if turnos >= 3:
                profundidad = f"Ya llevan {turnos} intercambios. Responde solo lo que se pregunta, sin introduccion."
                contexto = f"{contexto}\n{profundidad}".strip() if contexto else profundidad

            # Generar respuesta con Claude
            respuesta = await generar_respuesta(msg.texto, historial, contexto, telefono=msg.telefono)

            # Si Claude indica silencio, guardar en DB y no enviar
            if respuesta.strip() == "SILENCIO":
                await guardar_mensaje(msg.telefono, "user", msg.texto)
                await guardar_mensaje(msg.telefono, "assistant", "SILENCIO")
                logger.info(f"Silencio activado para {msg.telefono}")
                continue

            # Detectar senal de escalado: ESCALAR: <motivo>\n<mensaje al cliente>
            motivo_escalar = None
            if respuesta.startswith("ESCALAR:"):
                primera_linea, _, resto = respuesta.partition("\n")
                motivo_escalar = primera_linea[len("ESCALAR:"):].strip()
                respuesta = resto.strip()

            # Detectar señal de envio de archivo: ENVIAR_ARCHIVO:<nombre>
            archivo_nombre: str | None = None
            respuesta, archivo_nombre = _parsear_enviar_archivo(respuesta)

            # Guardar mensaje del usuario Y respuesta del agente en memoria
            await guardar_mensaje(msg.telefono, "user", msg.texto)
            await guardar_mensaje(msg.telefono, "assistant", respuesta)

            # Dividir en partes si Claude uso separador ---
            partes = _dividir_partes(respuesta)

            for idx, parte in enumerate(partes):
                delay = max(1, min(round(len(parte) * 0.025), 5))
                if idx == 0:
                    # Primera parte: indicador de presencia segun tipo de mensaje
                    if fue_audio:
                        await proveedor.indicar_grabando(msg.telefono)
                    else:
                        await proveedor.indicar_escribiendo(msg.telefono, delay)
                else:
                    # Partes siguientes: siempre "escribiendo" con pausa realista
                    await proveedor.indicar_escribiendo(msg.telefono, delay)
                await asyncio.sleep(delay)
                await proveedor.enviar_mensaje(msg.telefono, parte)

            logger.info(f"Respuesta a {msg.telefono} ({len(partes)} parte/s): {respuesta[:120]}")

            # Reportar uso al plugin WP (no-bloqueante)
            await usage_reporter.report(msg.telefono)

            # Enviar archivo publico si Claude lo solicito
            if archivo_nombre:
                public_docs = get_public_docs()
                doc = next((d for d in public_docs if d["name"] == archivo_nombre), None)
                if doc and doc.get("url"):
                    await proveedor.enviar_archivo(msg.telefono, doc["url"], archivo_nombre)
                else:
                    logger.warning(f"Archivo publico no encontrado: {archivo_nombre!r}")

            if motivo_escalar:
                await _enviar_alerta_humano(msg.telefono, motivo_escalar)
                logger.info(f"Alerta de escalado enviada: {motivo_escalar}")

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

    # Guardar en historial primero (asi el LLM lo ve en proximos turnos)
    try:
        await guardar_mensaje(phone, "assistant", message)
    except Exception as e:
        logger.error(f"agent_notification: error guardando en historial: {e}")
        # No abortar — intentar enviar igual

    # Enviar via provider (WAHA)
    try:
        ok = await proveedor.enviar_mensaje(phone, message)
    except Exception as e:
        logger.error(f"agent_notification: provider exception: {e}")
        raise HTTPException(status_code=502, detail="provider exception")

    if not ok:
        raise HTTPException(status_code=502, detail="provider failed")

    return {"status": "sent"}
