"""Tests para el comando /testaudio."""

import os
import pytest
from unittest.mock import patch, AsyncMock

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_testaudio.db")
os.environ.setdefault("OPENROUTER_API_KEY", "sk-or-test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    monkeypatch.delenv("TAKEOVER_URL_BASE", raising=False)
    monkeypatch.delenv("GUIDED_URL_BASE", raising=False)
    monkeypatch.delenv("CONTACTS_URL_BASE", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    import importlib
    from agent import takeover, guided_templates, contacts_webhook, tts_client
    importlib.reload(takeover)
    importlib.reload(guided_templates)
    importlib.reload(contacts_webhook)
    importlib.reload(tts_client)


def _tts_cfg(**overrides) -> dict:
    base = {
        "enabled": True,
        "voice_id": "AR_F_v1",
        "model": "eleven_turbo_v2_5",
        "max_chars_per_message": 640,
        "seconds_remaining": 1000,
        "api_key": "sk-test-key",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_testaudio_envia_audio_cuando_todo_ok():
    """Caso happy: gates pasan + pipeline TTS OK → llega audio, no se manda texto."""
    from agent import main as agent_main
    from agent import config_loader

    with patch.object(agent_main, "get_tts_config", return_value=_tts_cfg()), \
         patch.object(agent_main, "_send_audio_message",
                      new=AsyncMock(return_value={"ok": True})) as mock_audio, \
         patch.object(agent_main, "send_user_message", new=AsyncMock()) as mock_text:
        await agent_main._handle_testaudio_command("c@c.us")

    mock_audio.assert_awaited_once()
    args = mock_audio.await_args
    assert args.args[0] == "c@c.us"
    assert "prueba de audio" in args.args[1].lower()
    mock_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_testaudio_diagnostic_si_tts_disabled():
    from agent import main as agent_main
    from agent import config_loader

    with patch.object(agent_main, "get_tts_config",
                      return_value=_tts_cfg(enabled=False)), \
         patch.object(agent_main, "_send_audio_message",
                      new=AsyncMock()) as mock_audio, \
         patch.object(agent_main, "send_user_message", new=AsyncMock()) as mock_text:
        await agent_main._handle_testaudio_command("c@c.us")

    mock_audio.assert_not_awaited()
    mock_text.assert_awaited_once()
    diag_msg = mock_text.await_args.args[1]
    assert "no habilitado" in diag_msg.lower()
    assert "tts.enabled = False" in diag_msg


@pytest.mark.asyncio
async def test_testaudio_diagnostic_si_voice_id_vacia():
    from agent import main as agent_main
    from agent import config_loader

    with patch.object(agent_main, "get_tts_config",
                      return_value=_tts_cfg(voice_id=None)), \
         patch.object(agent_main, "_send_audio_message",
                      new=AsyncMock()) as mock_audio, \
         patch.object(agent_main, "send_user_message", new=AsyncMock()) as mock_text:
        await agent_main._handle_testaudio_command("c@c.us")

    mock_audio.assert_not_awaited()
    diag_msg = mock_text.await_args.args[1]
    assert "voice id" in diag_msg.lower()
    assert "tts.voice_id = None" in diag_msg


@pytest.mark.asyncio
async def test_testaudio_diagnostic_si_budget_agotado():
    from agent import main as agent_main
    from agent import config_loader

    with patch.object(agent_main, "get_tts_config",
                      return_value=_tts_cfg(seconds_remaining=0)), \
         patch.object(agent_main, "_send_audio_message",
                      new=AsyncMock()) as mock_audio, \
         patch.object(agent_main, "send_user_message", new=AsyncMock()) as mock_text:
        await agent_main._handle_testaudio_command("c@c.us")

    mock_audio.assert_not_awaited()
    diag_msg = mock_text.await_args.args[1]
    assert "budget" in diag_msg.lower() and "agotado" in diag_msg.lower()


@pytest.mark.asyncio
async def test_testaudio_diagnostic_si_pipeline_tts_falla():
    """Gates OK pero el pipeline TTS retorna fail → texto con reason."""
    from agent import main as agent_main
    from agent import config_loader, usage_reporter

    with patch.object(agent_main, "get_tts_config", return_value=_tts_cfg()), \
         patch.object(agent_main, "_send_audio_message",
                      new=AsyncMock(return_value={"ok": False, "reason": "elevenlabs_401"})), \
         patch.object(usage_reporter, "report_tts_error", new=lambda c, r: None), \
         patch.object(agent_main, "send_user_message", new=AsyncMock()) as mock_text:
        await agent_main._handle_testaudio_command("c@c.us")

    mock_text.assert_awaited_once()
    diag_msg = mock_text.await_args.args[1]
    assert "pipeline fallo" in diag_msg.lower()
    assert "elevenlabs_401" in diag_msg


@pytest.mark.asyncio
async def test_testaudio_seconds_remaining_null_es_ilimitado():
    """seconds_remaining=null debe permitir el envio (no caer en agotado)."""
    from agent import main as agent_main
    from agent import config_loader

    with patch.object(agent_main, "get_tts_config",
                      return_value=_tts_cfg(seconds_remaining=None)), \
         patch.object(agent_main, "_send_audio_message",
                      new=AsyncMock(return_value={"ok": True})) as mock_audio:
        await agent_main._handle_testaudio_command("c@c.us")

    mock_audio.assert_awaited_once()
