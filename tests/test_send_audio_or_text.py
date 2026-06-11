"""Tests para _debe_enviar_audio + send_audio_or_text wrapper."""

import os
import pytest
from unittest.mock import patch, AsyncMock

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_send_audio.db")
os.environ.setdefault("OPENROUTER_API_KEY", "sk-or-test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")


def _tts_cfg(**overrides) -> dict:
    base = {
        "enabled": True,
        "voice_id": "AR_F_v1",
        "model": "eleven_turbo_v2_5",
        "max_chars_per_message": 640,
        "seconds_remaining": 1000,
    }
    base.update(overrides)
    return base


def test_debe_enviar_audio_caso_happy():
    from agent.main import _debe_enviar_audio
    assert _debe_enviar_audio(True, _tts_cfg(), "hola") is True


def test_debe_enviar_audio_false_si_no_fue_audio():
    from agent.main import _debe_enviar_audio
    assert _debe_enviar_audio(False, _tts_cfg(), "hola") is False


def test_debe_enviar_audio_false_si_tts_disabled():
    from agent.main import _debe_enviar_audio
    assert _debe_enviar_audio(True, _tts_cfg(enabled=False), "hola") is False


def test_debe_enviar_audio_false_si_voice_id_none():
    from agent.main import _debe_enviar_audio
    assert _debe_enviar_audio(True, _tts_cfg(voice_id=None), "hola") is False


def test_debe_enviar_audio_false_si_supera_max_chars():
    from agent.main import _debe_enviar_audio
    cfg = _tts_cfg(max_chars_per_message=10)
    assert _debe_enviar_audio(True, cfg, "este texto tiene mas de 10 chars") is False


def test_debe_enviar_audio_false_si_budget_agotado():
    from agent.main import _debe_enviar_audio
    cfg = _tts_cfg(seconds_remaining=0)
    assert _debe_enviar_audio(True, cfg, "hola") is False


def test_debe_enviar_audio_true_si_budget_null_ilimitado():
    from agent.main import _debe_enviar_audio
    cfg = _tts_cfg(seconds_remaining=None)
    assert _debe_enviar_audio(True, cfg, "hola") is True


@pytest.mark.asyncio
async def test_send_audio_or_text_va_a_texto_si_no_audio():
    from agent import main as agent_main

    with patch.object(agent_main, "send_user_message",
                      new=AsyncMock(return_value=True)) as mock_send, \
         patch.object(agent_main, "_send_audio_message",
                      new=AsyncMock()) as mock_audio:
        result = await agent_main.send_audio_or_text(
            "c@c.us", "hola", fue_audio=False, tts_config=_tts_cfg()
        )
    assert result is True
    mock_send.assert_awaited_once_with("c@c.us", "hola")
    mock_audio.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_audio_or_text_pipeline_audio_ok():
    from agent import main as agent_main

    with patch.object(agent_main, "_send_audio_message",
                      new=AsyncMock(return_value={"ok": True})) as mock_audio, \
         patch.object(agent_main, "send_user_message",
                      new=AsyncMock(return_value=True)) as mock_text:
        result = await agent_main.send_audio_or_text(
            "c@c.us", "hola", fue_audio=True, tts_config=_tts_cfg()
        )
    assert result is True
    mock_audio.assert_awaited_once()
    mock_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_audio_or_text_fallback_a_texto_si_tts_falla():
    from agent import main as agent_main

    with patch.object(agent_main, "_send_audio_message",
                      new=AsyncMock(return_value={"ok": False, "reason": "elevenlabs_5xx"})) as mock_audio, \
         patch.object(agent_main, "send_user_message",
                      new=AsyncMock(return_value=True)) as mock_text, \
         patch("agent.usage_reporter.report_tts_error",
               new=lambda chat, reason: None):
        result = await agent_main.send_audio_or_text(
            "c@c.us", "hola", fue_audio=True, tts_config=_tts_cfg()
        )
    assert result is True
    mock_audio.assert_awaited_once()
    mock_text.assert_awaited_once_with("c@c.us", "hola")
