# agent/audio_converter.py — Conversion mp3 -> OGG/Opus para WhatsApp voice notes

"""
WhatsApp acepta voice notes en formato OGG con codec Opus (mono, ~24-32kbps).
ElevenLabs nos devuelve mp3. Convertimos via ffmpeg subprocess sin archivos
intermedios (stdin/stdout pipes).

Si ffmpeg no esta instalado en el sistema, el modulo retorna None y loguea
fatal. Esto se evita instalando ffmpeg en el Dockerfile (Task 9).
"""

import asyncio
import logging
import shutil
from typing import Optional

logger = logging.getLogger("agentkit")

FFMPEG_TIMEOUT = 8  # segundos
FFMPEG_BIN: Optional[str] = shutil.which("ffmpeg")


async def mp3_to_ogg_opus(mp3_bytes: bytes) -> Optional[bytes]:
    """
    Convierte mp3 bytes a OGG/Opus bytes para WhatsApp voice notes.
    Retorna OGG bytes o None ante cualquier error.
    """
    if not mp3_bytes:
        return None

    if FFMPEG_BIN is None:
        logger.error("audio_converter: ffmpeg no esta instalado en el sistema")
        return None

    cmd = [
        FFMPEG_BIN,
        "-hide_banner", "-loglevel", "error",
        "-i", "pipe:0",
        "-c:a", "libopus",
        "-b:a", "32k",
        "-application", "voip",
        "-ac", "1",  # mono
        "-f", "ogg",
        "pipe:1",
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as e:
        logger.error(f"audio_converter: no se pudo spawn ffmpeg - {e}")
        return None

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(input=mp3_bytes),
            timeout=FFMPEG_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("audio_converter: ffmpeg timeout")
        try:
            process.kill()
        except Exception:
            pass
        return None
    except Exception as e:
        logger.error(f"audio_converter: ffmpeg communicate error - {e}")
        return None

    if process.returncode != 0:
        logger.warning(
            f"audio_converter: ffmpeg returncode {process.returncode} "
            f"stderr={stderr[:200] if stderr else b''!r}"
        )
        return None

    if not stdout:
        logger.warning("audio_converter: ffmpeg returned empty stdout")
        return None

    return stdout
