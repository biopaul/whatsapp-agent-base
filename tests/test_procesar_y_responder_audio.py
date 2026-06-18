"""Verifica que _procesar_y_responder rutea via send_audio_or_text (no send_user_message)."""

import os
import pytest
from unittest.mock import patch, AsyncMock

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_pyr_audio.db")
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


async def _run_procesar_with_mocks(fue_audio: bool, llm_response: str = "respuesta del LLM"):
    """Helper: ejecuta _procesar_y_responder con todos los mocks necesarios."""
    from agent import main as agent_main

    captured = []

    async def fake_send_audio_or_text(chat_id, text, fue_audio, tts_config):
        captured.append({
            "text": text,
            "fue_audio": fue_audio,
            "tts_enabled": tts_config.get("enabled"),
        })
        return True

    fake_tts = {
        "enabled": True, "voice_id": "AR_F_v1", "model": "eleven_turbo_v2_5",
        "max_chars_per_message": 640, "seconds_remaining": 100, "api_key": "sk-test",
    }

    with patch.object(agent_main, "send_audio_or_text", new=fake_send_audio_or_text), \
         patch.object(agent_main, "send_user_message",
                      new=AsyncMock(return_value=True)) as mock_text, \
         patch.object(agent_main, "generar_respuesta",
                      new=AsyncMock(return_value=llm_response)), \
         patch.object(agent_main, "guardar_mensaje", new=AsyncMock()), \
         patch.object(agent_main, "obtener_historial",
                      new=AsyncMock(return_value=[])), \
         patch.object(agent_main, "_es_nueva_sesion",
                      new=AsyncMock(return_value=False)), \
         patch.object(agent_main, "get_tts_config", return_value=fake_tts), \
         patch.object(agent_main, "get_capabilities",
                      return_value={"reactions": False}), \
         patch.object(agent_main, "is_solo_mode", return_value=True), \
         patch.object(agent_main.proveedor, "indicar_grabando", new=AsyncMock()), \
         patch.object(agent_main.proveedor, "indicar_escribiendo", new=AsyncMock()), \
         patch.object(agent_main.usage_reporter, "report", new=AsyncMock()), \
         patch("asyncio.sleep", new=AsyncMock()):
        await agent_main._procesar_y_responder(
            chat_id="54911@c.us",
            texto="hola",
            mensaje_id="in_1",
            fue_audio=fue_audio,
            message_count=1,
        )
    return captured, mock_text


@pytest.mark.asyncio
async def test_procesar_y_responder_propaga_fue_audio_true():
    """En el flujo productivo, fue_audio=True llega a send_audio_or_text."""
    captured, mock_text = await _run_procesar_with_mocks(fue_audio=True)

    assert len(captured) == 1
    assert captured[0]["fue_audio"] is True
    assert captured[0]["text"] == "respuesta del LLM"
    assert captured[0]["tts_enabled"] is True
    # send_user_message NO debe haberse llamado desde el loop principal
    mock_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_procesar_y_responder_propaga_fue_audio_false():
    """Con fue_audio=False, send_audio_or_text recibe False (manda texto internamente)."""
    captured, mock_text = await _run_procesar_with_mocks(fue_audio=False)

    assert len(captured) == 1
    assert captured[0]["fue_audio"] is False
