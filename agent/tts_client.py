# agent/tts_client.py — Cliente de la TTS REST API de ElevenLabs

"""
Sintetiza texto a mp3 via ElevenLabs.

API key compartida (master de Pablo) en env var ELEVENLABS_API_KEY.
Si la key esta vacia, el modulo opera en no-op y retorna None directo.

Trackea last_error_reason para que el caller pueda reportarlo al plugin
como tts_errors event.
"""

import os
import logging
from typing import Optional

import httpx

logger = logging.getLogger("agentkit")

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
HTTP_TIMEOUT = float(os.getenv("TTS_HTTP_TIMEOUT", "10"))
DEFAULT_MODEL = os.getenv("TTS_DEFAULT_MODEL", "eleven_turbo_v2_5")
DEFAULT_OUTPUT_FORMAT = "mp3_44100_64"

_last_error_reason: Optional[str] = None


def last_error_reason() -> Optional[str]:
    """Reason del ultimo error de synthesize (o None si la ultima call fue OK)."""
    return _last_error_reason


def _set_reason(reason: Optional[str]) -> None:
    global _last_error_reason
    _last_error_reason = reason


async def synthesize(
    text: str,
    voice_id: str,
    model: str = DEFAULT_MODEL,
    output_format: str = DEFAULT_OUTPUT_FORMAT,
) -> Optional[bytes]:
    """
    Convierte texto a mp3 bytes via ElevenLabs Turbo v2.5.
    Retorna bytes o None ante cualquier error. last_error_reason() trae el motivo.
    """
    if not ELEVENLABS_API_KEY:
        _set_reason("no_api_key")
        logger.warning("tts_client: ELEVENLABS_API_KEY vacia, no-op")
        return None

    if not text or not voice_id:
        _set_reason("invalid_input")
        return None

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": text,
        "model_id": model,
        "output_format": output_format,
    }

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException:
        logger.warning(f"tts_client: timeout al sintetizar")
        _set_reason("elevenlabs_timeout")
        return None
    except Exception as e:
        logger.warning(f"tts_client: error red {type(e).__name__} - {e}")
        _set_reason("elevenlabs_timeout")
        return None

    if r.status_code == 401:
        logger.error("tts_client: 401 - API key invalida")
        _set_reason("elevenlabs_401")
        return None
    if r.status_code == 429:
        logger.warning("tts_client: 429 - rate limited / quota global")
        _set_reason("elevenlabs_429")
        return None
    if r.status_code >= 500:
        logger.warning(f"tts_client: {r.status_code} - server error")
        _set_reason("elevenlabs_5xx")
        return None
    if r.status_code != 200:
        logger.warning(f"tts_client: HTTP {r.status_code} - {r.text[:200]}")
        _set_reason(f"elevenlabs_{r.status_code}")
        return None

    _set_reason(None)
    return r.content
