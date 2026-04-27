# agent/usage_reporter.py — Reporta uso al plugin WordPress via POST /usage

"""
Envia eventos de mensajes respondidos al endpoint WP:
  POST /wp-json/gowap/v1/usage/{token}

Caracteristicas:
- No-bloqueante: el webhook responde al usuario antes de que el POST termine
- Batch: acumula eventos y los envia en grupos para reducir overhead
- Retry con backoff exponencial: 2s, 4s, 8s, 16s, 32s (5 intentos max)
- Cola con tope: si supera MAX_QUEUE eventos, descarta los mas viejos
- En exito: actualiza el estado de pausa en memoria de forma inmediata
- En 404: deshabilita el reporter (token invalido)
"""

import os
import asyncio
import time
import logging
from typing import Optional

import httpx

logger = logging.getLogger("agentkit")

USAGE_URL: str = os.getenv("USAGE_URL", "")

# Configuracion via env vars
_MAX_BATCH   = int(os.getenv("USAGE_BATCH_SIZE",  "20"))
_MAX_QUEUE   = int(os.getenv("USAGE_QUEUE_MAX",   "200"))
_DRAIN_WAIT  = float(os.getenv("USAGE_DRAIN_WAIT", "10.0"))  # segundos de espera max por evento
_MAX_RETRIES = int(os.getenv("USAGE_MAX_RETRIES", "5"))

_queue: asyncio.Queue = asyncio.Queue()
_task: Optional[asyncio.Task] = None
_bad_token: bool = False
_started: bool = False


async def start(url: str = "") -> None:
    """
    Inicia el reporter. Llamar desde el lifespan de FastAPI.
    url: sobreescribe USAGE_URL si se pasa.
    """
    global _queue, _task, _bad_token, _started, USAGE_URL

    if url:
        USAGE_URL = url

    if not USAGE_URL:
        logger.warning("USAGE_URL no configurado — el uso no sera reportado a WordPress")
        return

    _bad_token = False
    _queue = asyncio.Queue()
    _task = asyncio.create_task(_drain_loop())
    _started = True
    logger.info(f"UsageReporter iniciado: {USAGE_URL}")


async def report(chat_id: str) -> None:
    """
    Encola un evento 'message'. No-bloqueante — retorna inmediatamente.
    Se debe llamar DESPUES de enviar la respuesta al cliente.
    """
    if not USAGE_URL or _bad_token:
        return

    event = {
        "type": "message",
        "chat_id": chat_id,
        "at": int(time.time()),
    }

    # Si la cola esta llena, descartar el evento mas antiguo para hacer lugar
    if _queue.qsize() >= _MAX_QUEUE:
        try:
            _queue.get_nowait()
            logger.warning("UsageReporter: cola llena, se descarto evento antiguo")
        except asyncio.QueueEmpty:
            pass

    try:
        _queue.put_nowait(event)
    except asyncio.QueueFull:
        pass  # race condition, ignorar


async def _drain_loop() -> None:
    """Tarea de fondo: espera eventos y los envia en batch."""
    while True:
        events: list[dict] = []

        # Esperar al menos un evento (con timeout para no bloquear para siempre)
        try:
            event = await asyncio.wait_for(_queue.get(), timeout=_DRAIN_WAIT)
            events.append(event)
        except asyncio.TimeoutError:
            continue  # sin eventos, volver a esperar

        # Drenar eventos adicionales disponibles inmediatamente
        while len(events) < _MAX_BATCH:
            try:
                events.append(_queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        await _send_with_retry(events)


async def _send_with_retry(events: list[dict]) -> None:
    """Envia el batch con reintentos exponenciales."""
    global _bad_token

    backoff = 2.0
    for attempt in range(_MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    USAGE_URL,
                    json={"events": events},
                    headers={"Content-Type": "application/json"},
                )

            if resp.status_code == 200:
                data = resp.json()
                logger.info(
                    f"Usage OK: inserted={data.get('inserted', '?')} "
                    f"msgs={data.get('messages_used', '?')} "
                    f"chats={data.get('chats_used', '?')}"
                )
                # Actualizar estado de pausa inmediatamente sin esperar /config
                if data.get("agent_paused"):
                    from agent.config_loader import set_paused_state
                    set_paused_state(True, data.get("pause_reason"))
                    logger.warning(
                        f"Agente pausado por respuesta /usage: {data.get('pause_reason')}"
                    )
                return

            elif resp.status_code == 404:
                error_body = resp.json() if resp.content else {}
                logger.error(
                    f"USAGE_URL invalida (404) {error_body.get('code', '')} "
                    "— reportes deshabilitados hasta reinicio"
                )
                _bad_token = True
                return

            elif resp.status_code in (429, 500, 502, 503, 504):
                logger.warning(
                    f"Usage HTTP {resp.status_code}, intento {attempt + 1}/{_MAX_RETRIES}"
                )
                # Continuar al retry

            else:
                logger.warning(f"Usage HTTP inesperado {resp.status_code} — no reintentar")
                return

        except (httpx.TimeoutException, httpx.NetworkError) as e:
            logger.warning(f"Usage red: {e}, intento {attempt + 1}/{_MAX_RETRIES}")

        except Exception as e:
            logger.error(f"Usage error inesperado: {e}")
            return

        if attempt < _MAX_RETRIES - 1:
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

    logger.error(f"Usage: {len(events)} eventos perdidos tras {_MAX_RETRIES} reintentos")
