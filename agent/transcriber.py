# agent/transcriber.py — Transcripcion de audio con OpenAI Whisper API

import os
import io
import logging

import httpx

logger = logging.getLogger("agentkit")

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "whisper-1")
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "es")


def _get_openai_key() -> str:
    """Lee OPENAI_API_KEY en cada llamada (no al importar el modulo)."""
    return os.getenv("OPENAI_API_KEY", "")


async def descargar_audio(url: str, headers: dict | None = None) -> bytes | None:
    """Descarga el archivo de audio desde la URL del proveedor."""
    logger.info(f"Descargando audio desde: {url[:120]}")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers or {})
            if resp.status_code == 200:
                logger.info(f"Audio descargado OK: {len(resp.content)} bytes")
                return resp.content
            logger.error(f"Error descargando audio: HTTP {resp.status_code} - {resp.text[:200]}")
    except Exception as e:
        logger.error(f"Error descargando audio: {e}")
    return None


async def transcribir_audio(audio_bytes: bytes, filename: str = "audio.ogg") -> str | None:
    """
    Envia audio a OpenAI Whisper API y retorna la transcripcion.
    Retorna None si no hay API key o si falla.
    """
    api_key = _get_openai_key()
    if not api_key:
        logger.warning("OPENAI_API_KEY no configurada - no se puede transcribir audio")
        return None

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                data={
                    "model": WHISPER_MODEL,
                    "language": WHISPER_LANGUAGE,
                    "response_format": "text",
                },
                files={"file": (filename, io.BytesIO(audio_bytes), "audio/ogg")},
            )
            if resp.status_code == 200:
                text = resp.text.strip()
                logger.info(f"Audio transcripto ({len(audio_bytes)} bytes -> {len(text)} chars)")
                return text
            logger.error(f"Whisper API error: {resp.status_code} - {resp.text[:200]}")
    except Exception as e:
        logger.error(f"Error en transcripcion Whisper: {e}")
    return None


async def procesar_audio(audio_url: str, waha_api_key: str = "") -> str | None:
    """
    Descarga y transcribe un audio. Retorna el texto o None.
    Pasa headers de autenticacion si es WAHA.
    """
    headers = {}
    if waha_api_key:
        headers["X-Api-Key"] = waha_api_key

    audio_bytes = await descargar_audio(audio_url, headers)
    if not audio_bytes:
        return None

    return await transcribir_audio(audio_bytes)
