"""Verifica que _procesar_respuesta_llm propaga fue_audio + tts_config a send_audio_or_text."""

import os
import pytest
from unittest.mock import patch, AsyncMock

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_main_audio.db")
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


@pytest.mark.asyncio
async def test_procesar_respuesta_llm_propaga_fue_audio_true():
    """Si fue_audio=True, debe llamar a send_audio_or_text con fue_audio=True."""
    from agent import main as agent_main
    from agent import config_loader

    captured = []

    async def fake_send(chat_id, text, fue_audio, tts_config):
        captured.append({"chat_id": chat_id, "text": text, "fue_audio": fue_audio})
        return True

    fake_tts = {"enabled": True, "voice_id": "AR_F_v1", "max_chars_per_message": 640,
                "seconds_remaining": 100, "model": "eleven_turbo_v2_5"}

    with patch.object(agent_main, "send_audio_or_text", new=fake_send), \
         patch.object(config_loader, "get_tts_config", return_value=fake_tts):
        await agent_main._procesar_respuesta_llm("c@c.us", "respuesta texto", fue_audio=True)

    assert len(captured) == 1
    assert captured[0]["fue_audio"] is True


@pytest.mark.asyncio
async def test_procesar_respuesta_llm_propaga_fue_audio_false():
    from agent import main as agent_main
    from agent import config_loader

    captured = []

    async def fake_send(chat_id, text, fue_audio, tts_config):
        captured.append({"fue_audio": fue_audio})
        return True

    with patch.object(agent_main, "send_audio_or_text", new=fake_send), \
         patch.object(config_loader, "get_tts_config",
                      return_value={"enabled": False}):
        await agent_main._procesar_respuesta_llm("c@c.us", "respuesta", fue_audio=False)

    assert len(captured) == 1
    assert captured[0]["fue_audio"] is False
