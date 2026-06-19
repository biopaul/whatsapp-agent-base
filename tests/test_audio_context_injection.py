"""Verifica que cuando llega audio + TTS habilitado, se inyecta nota al LLM."""

import os
import pytest
from unittest.mock import patch, AsyncMock

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_audio_ctx.db")
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


async def _capture_contexto(fue_audio: bool, tts_cfg: dict) -> str:
    """Ejecuta _procesar_y_responder mockeando todo + captura el contexto pasado al LLM."""
    from agent import main as agent_main

    captured = {"contexto": None}

    async def fake_generar(texto, historial, contexto_extra="", telefono=""):
        captured["contexto"] = contexto_extra
        return "respuesta del LLM"

    with patch.object(agent_main, "generar_respuesta", new=fake_generar), \
         patch.object(agent_main, "send_audio_or_text",
                      new=AsyncMock(return_value=True)), \
         patch.object(agent_main, "send_user_message",
                      new=AsyncMock(return_value=True)), \
         patch.object(agent_main, "guardar_mensaje", new=AsyncMock()), \
         patch.object(agent_main, "obtener_historial",
                      new=AsyncMock(return_value=[])), \
         patch.object(agent_main, "_es_nueva_sesion",
                      new=AsyncMock(return_value=False)), \
         patch.object(agent_main, "get_tts_config", return_value=tts_cfg), \
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
    return captured["contexto"] or ""


@pytest.mark.asyncio
async def test_inyecta_nota_audio_si_fue_audio_y_tts_enabled():
    """fue_audio=True + TTS habilitado → contexto incluye instruccion para el LLM."""
    cfg = {"enabled": True, "voice_id": "AR_F_v1", "max_chars_per_message": 640,
           "seconds_remaining": 100, "model": "eleven_turbo_v2_5", "api_key": "sk"}
    contexto = await _capture_contexto(fue_audio=True, tts_cfg=cfg)
    assert "nota de voz" in contexto.lower()
    assert "no digas que no podes mandar audios" in contexto.lower()


@pytest.mark.asyncio
async def test_no_inyecta_nota_si_fue_audio_false():
    """Mensaje de texto → no se inyecta la nota."""
    cfg = {"enabled": True, "voice_id": "AR_F_v1", "max_chars_per_message": 640,
           "seconds_remaining": 100, "model": "eleven_turbo_v2_5", "api_key": "sk"}
    contexto = await _capture_contexto(fue_audio=False, tts_cfg=cfg)
    assert "nota de voz" not in contexto.lower()
    assert "no podes mandar audios" not in contexto.lower()


@pytest.mark.asyncio
async def test_inyecta_nota_alternativa_si_tts_disabled():
    """fue_audio=True pero TTS deshabilitado → inyecta nota alternativa para evitar disclaimers."""
    cfg = {"enabled": False}
    contexto = await _capture_contexto(fue_audio=True, tts_cfg=cfg)
    # Hay nota (cliente envio audio)
    assert "nota de voz" in contexto.lower()
    # Pero le dice al LLM que solo puede texto + sin disculpas
    assert "solo pod" in contexto.lower() and "texto" in contexto.lower()
    assert "no le expliques" in contexto.lower()
    assert "ni te disculpes" in contexto.lower()


@pytest.mark.asyncio
async def test_inyecta_nota_alternativa_si_voice_id_vacia():
    """fue_audio=True + enabled=True pero sin voice_id → inyecta nota alternativa."""
    cfg = {"enabled": True, "voice_id": None}
    contexto = await _capture_contexto(fue_audio=True, tts_cfg=cfg)
    assert "nota de voz" in contexto.lower()
    assert "solo pod" in contexto.lower() and "texto" in contexto.lower()


@pytest.mark.asyncio
async def test_nota_disabled_no_confunde_con_nota_enabled():
    """Cuando TTS deshabilitado, NO se incluye la nota positiva de 'sera convertida a audio'."""
    cfg = {"enabled": False}
    contexto = await _capture_contexto(fue_audio=True, tts_cfg=cfg)
    # La nota positiva NO debe aparecer
    assert "sera convertida" not in contexto.lower()
    assert "automaticamente a audio" not in contexto.lower()
