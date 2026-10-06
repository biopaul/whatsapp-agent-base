# agent/transcriber.py — Transcripcion de audio con OpenAI Whisper API

import os
import io
import asyncio
import logging

import httpx

logger = logging.getLogger("agentkit")

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "whisper-1")
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "es")

# Retry para 429 y 5xx transitorios. Default conservador: 2 reintentos
# (3 intentos totales) con backoff 1s + 2s = max 3s extra. Suficiente para
# superar rate limits momentaneos sin colgar el webhook > 10s. Ambos
# env-overridables para ajustar sin deploy.
WHISPER_MAX_RETRIES = int(os.getenv("WHISPER_MAX_RETRIES", "2"))
WHISPER_RETRY_BASE_DELAY_SEC = float(os.getenv("WHISPER_RETRY_BASE_DELAY_SEC", "1.0"))

# 429 = rate limit; 5xx = server transitorio. 401/403/400 son fatales.
_STATUS_RETRYABLE = {500, 502, 503, 504}


def _get_openai_key() -> str:
    """Lee OPENAI_API_KEY en cada llamada (no al importar el modulo)."""
    return os.getenv("OPENAI_API_KEY", "")


def _is_insufficient_quota(resp: httpx.Response) -> bool:
    """Un 429 por saldo agotado no se recupera con retry — hay que distinguirlo
    del rate-limit transitorio (que si se recupera esperando).

    OpenAI usa estos marcadores en el body JSON:
      {"error": {"type": "insufficient_quota", "code": "insufficient_quota"}}
    """
    try:
        body = resp.json()
    except Exception:
        return False
    err = body.get("error") or {}
    err_type = (err.get("type") or "").lower()
    err_code = (err.get("code") or "").lower()
    return "insufficient_quota" in err_type or "insufficient_quota" in err_code


def _delay_for_attempt(attempt: int, retry_after_header: str | None) -> float:
    """Honra Retry-After si viene (segundos como numero); si no, exponential
    backoff: 1s, 2s, 4s, ...
    attempt es 1-indexed (primer retry = 1)."""
    if retry_after_header:
        try:
            return max(0.0, float(retry_after_header))
        except ValueError:
            pass
    return WHISPER_RETRY_BASE_DELAY_SEC * (2 ** (attempt - 1))


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


async def _llamar_whisper(client: httpx.AsyncClient, api_key: str,
                          filename: str, audio_bytes: bytes) -> httpx.Response:
    return await client.post(
        "https://api.openai.com/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {api_key}"},
        data={
            "model": WHISPER_MODEL,
            "language": WHISPER_LANGUAGE,
            "response_format": "text",
        },
        files={"file": (filename, io.BytesIO(audio_bytes), "audio/ogg")},
    )


async def transcribir_audio(audio_bytes: bytes, filename: str = "audio.ogg") -> str | None:
    """
    Envia audio a OpenAI Whisper API y retorna la transcripcion.
    Retorna None si no hay API key o si falla tras los retries.

    Reintenta en 429 (rate limit transitorio) y 5xx. No reintenta en:
      - 401/403 (auth)
      - 400 (bad request — audio corrupto)
      - 429 insufficient_quota (saldo agotado, no se recupera esperando)
    """
    api_key = _get_openai_key()
    if not api_key:
        logger.warning("OPENAI_API_KEY no configurada - no se puede transcribir audio")
        return None

    max_attempts = WHISPER_MAX_RETRIES + 1
    async with httpx.AsyncClient(timeout=60.0) as client:
        for attempt in range(1, max_attempts + 1):
            try:
                resp = await _llamar_whisper(client, api_key, filename, audio_bytes)
            except Exception as e:
                logger.error(
                    f"Error en transcripcion Whisper (intento {attempt}/{max_attempts}): {e}"
                )
                if attempt >= max_attempts:
                    return None
                await asyncio.sleep(_delay_for_attempt(attempt, None))
                continue

            if resp.status_code == 200:
                text = resp.text.strip()
                suffix = f" intento={attempt}" if attempt > 1 else ""
                logger.info(
                    f"Audio transcripto ({len(audio_bytes)} bytes -> {len(text)} chars){suffix}"
                )
                return text

            if resp.status_code == 429:
                if _is_insufficient_quota(resp):
                    logger.error(
                        "Whisper 429 insufficient_quota — saldo OpenAI agotado, "
                        "no se reintenta (necesita recarga de billing)"
                    )
                    return None
                if attempt >= max_attempts:
                    logger.error(
                        f"Whisper rate-limited tras {WHISPER_MAX_RETRIES} retries — rindo"
                    )
                    return None
                delay = _delay_for_attempt(attempt, resp.headers.get("Retry-After"))
                logger.warning(
                    f"Whisper 429 rate-limit, retry {attempt}/{WHISPER_MAX_RETRIES} "
                    f"tras {delay:.1f}s"
                )
                await asyncio.sleep(delay)
                continue

            if resp.status_code in _STATUS_RETRYABLE and attempt < max_attempts:
                delay = _delay_for_attempt(attempt, resp.headers.get("Retry-After"))
                logger.warning(
                    f"Whisper HTTP {resp.status_code} transitorio, retry "
                    f"{attempt}/{WHISPER_MAX_RETRIES} tras {delay:.1f}s"
                )
                await asyncio.sleep(delay)
                continue

            # Fatal (401/403/400) o retries agotados en 5xx
            logger.error(f"Whisper API error: {resp.status_code} - {resp.text[:200]}")
            return None

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
