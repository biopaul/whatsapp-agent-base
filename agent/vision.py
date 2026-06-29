# agent/vision.py — Descarga + armado de bloques multimodales para OpenRouter

"""
Pipeline de visión para verificación de comprobantes de pago.

- Descarga el binario desde WAHA (mismo patrón que transcriber).
- Arma bloque `image_url` con data URI base64 (compatible OpenAI/OpenRouter).
- Para PDFs usa el bloque `file` que OpenRouter soporta para modelos Anthropic.
- Detecta marker [PAGO_VERIFICADO] en la respuesta del LLM.

El LLM decide si el comprobante es válido en base al contexto del system prompt
del owner (que define alias, monto esperado, etc.). Sin estructura rígida — esto es v1.
"""

import base64
import logging
import re
from typing import Optional

import httpx

logger = logging.getLogger("agentkit")

DOWNLOAD_TIMEOUT = 15.0
MAX_IMAGE_BYTES = 5 * 1024 * 1024   # 5 MB
MAX_PDF_BYTES = 30 * 1024 * 1024    # 30 MB

# Marker convencional que el LLM emite cuando confirma pago valido.
# Mismo patrón que SILENCIO / ESCALAR — se elimina del texto antes de mandar al cliente.
PAGO_VERIFICADO_MARKER = "[PAGO_VERIFICADO]"
_PAGO_RE = re.compile(r"\s*\[\s*PAGO_VERIFICADO\s*\]\s*", re.IGNORECASE)

_ALLOWED_IMAGE_MIMES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


async def descargar_media(url: str, waha_api_key: str = "") -> Optional[bytes]:
    """Descarga el binario. Retorna bytes o None si falla."""
    if not url:
        return None
    headers = {}
    if waha_api_key:
        headers["X-Api-Key"] = waha_api_key
    try:
        async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT) as client:
            r = await client.get(url, headers=headers)
        if r.status_code != 200:
            logger.warning(f"descargar_media: HTTP {r.status_code} para {url[:120]}")
            return None
        return r.content
    except Exception as e:
        logger.warning(f"descargar_media: error {type(e).__name__} - {e}")
        return None


def build_image_block(image_bytes: bytes, mimetype: str) -> Optional[dict]:
    """
    Bloque `image_url` con data URI base64. Formato OpenAI/OpenRouter.

    Funciona con modelos GPT-4o, Claude (via OpenRouter), Gemini, etc.
    """
    if not image_bytes:
        return None
    if len(image_bytes) > MAX_IMAGE_BYTES:
        logger.warning(f"build_image_block: imagen {len(image_bytes)}B excede limite, descartando")
        return None
    media_type = mimetype if mimetype in _ALLOWED_IMAGE_MIMES else "image/jpeg"
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{media_type};base64,{b64}"},
    }


def build_pdf_block(pdf_bytes: bytes, filename: str = "document.pdf") -> Optional[dict]:
    """
    Bloque `file` con PDF base64. Soportado por OpenRouter para modelos Anthropic.

    Si el modelo no soporta PDF, el provider devuelve error y el caller cae a fallback.
    """
    if not pdf_bytes:
        return None
    if len(pdf_bytes) > MAX_PDF_BYTES:
        logger.warning(f"build_pdf_block: pdf {len(pdf_bytes)}B excede limite, descartando")
        return None
    b64 = base64.b64encode(pdf_bytes).decode("ascii")
    safe_name = filename or "document.pdf"
    return {
        "type": "file",
        "file": {
            "filename": safe_name,
            "file_data": f"data:application/pdf;base64,{b64}",
        },
    }


def extract_pago_verificado(texto: str) -> tuple[str, bool]:
    """
    Detecta y remueve el marker [PAGO_VERIFICADO] del texto del LLM.

    Retorna (texto_limpio, verified).
    Si el LLM solo emitió el marker sin texto adicional, retorna ("", True) —
    el caller debe usar un fallback amable para no mandar mensaje vacío.
    """
    if not texto:
        return "", False
    if not _PAGO_RE.search(texto):
        return texto, False
    limpio = _PAGO_RE.sub(" ", texto).strip()
    limpio = re.sub(r"\s{2,}", " ", limpio).strip()
    return limpio, True
