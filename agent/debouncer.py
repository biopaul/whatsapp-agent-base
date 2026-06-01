# agent/debouncer.py — Debounce de respuestas IA por chat
#
# Si un cliente envia varios mensajes seguidos (rafaga corta), no queremos
# responder a cada uno individualmente — eso produce 3 respuestas similares
# para 3 preguntas similares y satura el chat.
#
# Patron: por cada chat mantenemos un buffer de mensajes + una asyncio.Task
# que dispara despues de DEBOUNCE_SEC. Cuando llega un mensaje nuevo:
#   1. Append al buffer
#   2. Cancela la Task pendiente (si hay)
#   3. Programa nueva Task con sleep fresco
# Al expirar el sleep sin nuevos mensajes, llama al handler con la lista
# completa de mensajes acumulados.
#
# Sin lock: las operaciones de mutacion son atomicas dentro del event loop
# (no hay await entre el append/cancel/create_task).

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger("agentkit")

# Ventana de espera tras el ultimo mensaje. Configurable por env.
DEBOUNCE_SEC: float = float(os.getenv("MESSAGE_DEBOUNCE_SEC", "4"))

# chat_id -> lista de dicts con info de cada mensaje acumulado.
_pending_messages: dict[str, list[dict[str, Any]]] = {}
# chat_id -> Task del proximo flush.
_pending_tasks: dict[str, asyncio.Task] = {}


def schedule(
    chat_id: str,
    texto: str,
    mensaje_id: str | None,
    fue_audio: bool,
    handler: Callable[..., Awaitable[None]],
) -> None:
    """
    Encola un mensaje para respuesta debouncada. Si ya habia una task pendiente
    para este chat, la cancela y reprograma con sleep fresco.

    handler debe ser una coroutine con firma:
        async def handler(chat_id: str, texto_combinado: str,
                          mensaje_id: str | None, fue_audio: bool,
                          message_count: int) -> None
    """
    _pending_messages.setdefault(chat_id, []).append({
        "texto": texto,
        "mensaje_id": mensaje_id,
        "fue_audio": fue_audio,
    })
    prev = _pending_tasks.get(chat_id)
    if prev and not prev.done():
        prev.cancel()
    _pending_tasks[chat_id] = asyncio.create_task(_flush(chat_id, handler))


async def _flush(chat_id: str, handler: Callable[..., Awaitable[None]]) -> None:
    """
    Espera DEBOUNCE_SEC. Si la task no fue cancelada (no llegaron mas mensajes),
    drena el buffer y llama al handler con los mensajes combinados.
    """
    try:
        await asyncio.sleep(DEBOUNCE_SEC)
    except asyncio.CancelledError:
        return

    msgs = _pending_messages.pop(chat_id, [])
    _pending_tasks.pop(chat_id, None)
    if not msgs:
        return

    # Combinar texto. Para 1 mensaje, texto literal. Para N, juntar con saltos.
    if len(msgs) == 1:
        combined = msgs[0]["texto"]
    else:
        combined = "\n".join(m["texto"] for m in msgs)
        logger.info(f"Debounce: combinando {len(msgs)} mensajes de {chat_id}")

    last = msgs[-1]
    # fue_audio es True si CUALQUIERA de los mensajes lo fue (decide presencia "grabando")
    any_audio = any(m.get("fue_audio", False) for m in msgs)

    try:
        await handler(
            chat_id,
            combined,
            last["mensaje_id"],
            any_audio,
            len(msgs),
        )
    except Exception as e:
        logger.error(f"Debounce flush error para {chat_id}: {e}")


def clear() -> None:
    """Limpia todos los buffers/tasks. Util para tests."""
    for task in _pending_tasks.values():
        if not task.done():
            task.cancel()
    _pending_tasks.clear()
    _pending_messages.clear()


def pending_count(chat_id: str) -> int:
    """Cuantos mensajes hay esperando flush para este chat (util para tests/debug)."""
    return len(_pending_messages.get(chat_id, []))
