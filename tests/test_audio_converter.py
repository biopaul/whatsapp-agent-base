"""Tests para audio_converter (mp3 -> OGG/Opus via ffmpeg)."""

import pytest
import shutil


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


@pytest.mark.asyncio
@pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg no instalado en el sistema")
async def test_mp3_to_ogg_opus_conversion_real():
    """Si hay ffmpeg, conversion de mp3 a ogg debe funcionar."""
    from agent.audio_converter import mp3_to_ogg_opus

    # Generar mp3 minimo via ffmpeg (silencio de 1s)
    import subprocess
    result = subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", "anullsrc=duration=1", "-f", "mp3", "-"],
        capture_output=True, timeout=10
    )
    if result.returncode != 0 or not result.stdout:
        pytest.skip(f"No se pudo generar mp3 con ffmpeg: {result.stderr[:200]}")
    mp3_bytes = result.stdout

    ogg = await mp3_to_ogg_opus(mp3_bytes)
    assert ogg is not None
    assert len(ogg) > 0
    # OGG empieza con "OggS" magic bytes
    assert ogg[:4] == b"OggS"


@pytest.mark.asyncio
async def test_mp3_to_ogg_opus_bytes_invalidos_retorna_none():
    """Si los bytes no son mp3 valido, retorna None."""
    from agent.audio_converter import mp3_to_ogg_opus
    result = await mp3_to_ogg_opus(b"esto no es mp3")
    assert result is None


@pytest.mark.asyncio
async def test_mp3_to_ogg_opus_input_vacio_retorna_none():
    from agent.audio_converter import mp3_to_ogg_opus
    assert await mp3_to_ogg_opus(b"") is None
