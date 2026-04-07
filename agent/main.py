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

# Zona horaria configurable — default: Argentina (GMT-3)
TZ_OFFSET = int(os.getenv("TZ_OFFSET", "-3"))
TZ_LOCAL = timezone(timedelta(hours=TZ_OFFSET))

load_dotenv()

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
log_level = logging.DEBUG if ENVIRONMENT == "development" else logging.INFO
logging.basicConfig(level=log_level)
logger = logging.getLogger("agentkit")

proveedor = obtener_proveedor()
PORT = int(os.getenv("PORT", 8000))

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
    """Retorna el saludo apropiado según la hora local configurada."""
    hora = datetime.now(TZ_LOCAL).hour
    if 6 <= hora < 12:
        return "Buen día"
    elif 12 <= hora < 20:
        return "Buenas tardes"
    else:
        return "Buenas noches"


async def _es_nueva_sesion(telefono: str) -> bool:
    """
    Retorna True si el último mensaje fue de un día diferente (en hora local)
    o si no hay historial previo.
    """
    ultimo = await obtener_ultimo_timestamp(telefono)
    if ultimo is None:
        return True
    ahora = datetime.now(TZ_LOCAL)
    ultimo_local = ultimo.replace(tzinfo=timezone.utc).astimezone(TZ_LOCAL)
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
            if msg.es_propio or not msg.texto:
                continue

            logger.info(f"Mensaje de {msg.telefono}: {msg.texto}")

            historial = await obtener_historial(msg.telefono)

            # Pre-bloquear si hay silencios consecutivos recientes (sin llamar a Claude)
            if _debe_prebloquear(historial):
                await guardar_mensaje(msg.telefono, "user", msg.texto)
                await guardar_mensaje(msg.telefono, "assistant", "SILENCIO")
                logger.info(f"Pre-bloqueado {msg.telefono} ({_silencios_consecutivos(historial)} silencios consecutivos)")
                continue

            # Detectar si es nueva sesión (nuevo día) y armar saludo
            contexto = ""
            if await _es_nueva_sesion(msg.telefono):
                saludo = _saludo_por_hora()
                contexto = f"Es el primer mensaje del día de este cliente. Comenzá tu respuesta con '{saludo}' de forma natural, integrado en tu mensaje (no como fórmula aislada)."

            respuesta = await generar_respuesta(msg.texto, historial, contexto)

            # Si Claude indica silencio, guardar en DB y no enviar
            if respuesta.strip() == "SILENCIO":
                await guardar_mensaje(msg.telefono, "user", msg.texto)
                await guardar_mensaje(msg.telefono, "assistant", "SILENCIO")
                logger.info(f"Silencio activado para {msg.telefono}")
                continue

            await guardar_mensaje(msg.telefono, "user", msg.texto)
            await guardar_mensaje(msg.telefono, "assistant", respuesta)

            # Mostrar "está escribiendo..." y simular tiempo de escritura
            await proveedor.indicar_escribiendo(msg.telefono)
            delay = min(len(respuesta) * 0.025, 5.0)  # ~25ms por caracter, máx 5s
            await asyncio.sleep(delay)

            await proveedor.enviar_mensaje(msg.telefono, respuesta)
            logger.info(f"Respuesta a {msg.telefono}: {respuesta}")

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Error en webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))
