# agent/main.py — Servidor FastAPI + Webhook de WhatsApp
# WhatsApp Agent Base

"""
Servidor principal del agente de WhatsApp.
Funciona con cualquier proveedor (Whapi, Meta, Twilio) gracias a la capa de providers.
"""

import os
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv

from agent.brain import generar_respuesta
from agent.memory import inicializar_db, guardar_mensaje, obtener_historial, obtener_ultimo_timestamp
from agent.providers import obtener_proveedor
from agent.config_loader import get_notify_phone, get_notify_name, get_tz_offset, invalidate_cache
from agent.transcriber import procesar_audio

load_dotenv()

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
log_level = logging.DEBUG if ENVIRONMENT == "development" else logging.INFO
logging.basicConfig(level=log_level)
logger = logging.getLogger("agentkit")

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

def _silencios_consecutivos(historial: list[dict]) -> int:
    """Cuenta cuántos mensajes consecutivos del asistente son SILENCIO al final del historial."""
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


async def _es_nueva_sesion(telefono: str) -> bool:
    """
    Retorna True si el último mensaje fue de un día diferente (en hora local)
    o si no hay historial previo.
    """
    ultimo = await obtener_ultimo_timestamp(telefono)
    if ultimo is None:
        return True
    tz_local = timezone(timedelta(hours=get_tz_offset()))
    ahora = datetime.now(tz_local)
    ultimo_local = ultimo.replace(tzinfo=timezone.utc).astimezone(tz_local)
    return ahora.date() != ultimo_local.date()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa la base de datos al arrancar el servidor."""
    await inicializar_db()
    logger.info("Base de datos inicializada")
    logger.info(f"Servidor corriendo en puerto {PORT}")
    logger.info(f"Proveedor de WhatsApp: {proveedor.__class__.__name__}")
    yield


app = FastAPI(
    title="WhatsApp AI Agent",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/")
async def health_check():
    """Endpoint de salud para Railway/monitoreo."""
    return {"status": "ok", "service": "whatsapp-agent"}


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
    """Verificación GET del webhook (requerido por Meta Cloud API)."""
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
        mensajes = await proveedor.parsear_webhook(request)

        for msg in mensajes:
            if msg.es_propio:
                continue

            # Transcribir audio si es nota de voz
            if msg.audio_url and not msg.texto:
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

            historial = await obtener_historial(msg.telefono)

            # Pre-bloquear si hay silencios consecutivos recientes (sin llamar a Claude)
            if _debe_prebloquear(historial):
                await guardar_mensaje(msg.telefono, "user", msg.texto)
                await guardar_mensaje(msg.telefono, "assistant", "SILENCIO")
                logger.info(f"Pre-bloqueado {msg.telefono} ({_silencios_consecutivos(historial)} silencios consecutivos)")
                continue

            # Escalado por keyword — el cliente pide explícitamente un humano
            if _detectar_keyword_escalar(msg.texto):
                respuesta = "¡Claro! Te conecto con alguien del equipo ahora mismo."
                await guardar_mensaje(msg.telefono, "user", msg.texto)
                await guardar_mensaje(msg.telefono, "assistant", respuesta)
                delay = max(1, min(round(len(respuesta) * 0.025), 5))
                await proveedor.indicar_escribiendo(msg.telefono, delay)
                await asyncio.sleep(delay)
                await proveedor.enviar_mensaje(msg.telefono, respuesta)
                await _enviar_alerta_humano(msg.telefono, "El cliente pide hablar con un humano")
                logger.info(f"Escalado por keyword: {msg.telefono}")
                continue

            # Detectar si es nueva sesión (nuevo día) y armar saludo
            contexto = ""
            if await _es_nueva_sesion(msg.telefono):
                saludo = _saludo_por_hora()
                contexto = f"Es el primer mensaje del día de este cliente. Comenzá tu respuesta con '{saludo}' de forma natural, integrado en tu mensaje (no como fórmula aislada)."

            # Indicar profundidad de conversación para calibrar largo de respuesta
            turnos = len([m for m in historial if m["role"] == "user"])
            if turnos >= 3:
                profundidad = f"Ya llevan {turnos} intercambios. Sé conciso y directo — respondé solo lo que se pregunta."
                contexto = f"{contexto}\n{profundidad}".strip() if contexto else profundidad

            respuesta = await generar_respuesta(msg.texto, historial, contexto)

            # Si Claude indica silencio, guardar en DB y no enviar
            if respuesta.strip() == "SILENCIO":
                await guardar_mensaje(msg.telefono, "user", msg.texto)
                await guardar_mensaje(msg.telefono, "assistant", "SILENCIO")
                logger.info(f"Silencio activado para {msg.telefono}")
                continue

            # Detectar señal de escalado: ESCALAR: <motivo>\n<mensaje al cliente>
            motivo_escalar = None
            if respuesta.startswith("ESCALAR:"):
                primera_linea, _, resto = respuesta.partition("\n")
                motivo_escalar = primera_linea[len("ESCALAR:"):].strip()
                respuesta = resto.strip()

            await guardar_mensaje(msg.telefono, "user", msg.texto)
            await guardar_mensaje(msg.telefono, "assistant", respuesta)

            # Mostrar "está escribiendo..." y simular tiempo de escritura
            delay = max(1, min(round(len(respuesta) * 0.025), 5))  # 1–5s según longitud
            await proveedor.indicar_escribiendo(msg.telefono, delay)
            await asyncio.sleep(delay)

            await proveedor.enviar_mensaje(msg.telefono, respuesta)
            logger.info(f"Respuesta a {msg.telefono}: {respuesta}")

            if motivo_escalar:
                await _enviar_alerta_humano(msg.telefono, motivo_escalar)
                logger.info(f"Alerta de escalado enviada: {motivo_escalar}")

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Error en webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))
