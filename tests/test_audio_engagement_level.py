"""Tests para audio_engagement_level (1-5): controla disposicion del LLM a responder audios."""

import os
import pytest
from unittest.mock import patch, AsyncMock

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_engagement.db")
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


def _tts_cfg(level=None) -> dict:
    cfg = {
        "enabled": True,
        "voice_id": "AR_F_v1",
        "model": "eleven_turbo_v2_5",
        "max_chars_per_message": 640,
        "seconds_remaining": 1000,
        "api_key": "sk-test",
    }
    if level is not None:
        cfg["audio_engagement_level"] = level
    return cfg


async def _capture_contexto(tts_cfg: dict, fue_audio: bool = True) -> str:
    from agent import main as agent_main
    captured = {"contexto": None}

    async def fake_generar(texto, historial, contexto_extra="", telefono=""):
        captured["contexto"] = contexto_extra
        return "respuesta"

    with patch.object(agent_main, "generar_respuesta", new=fake_generar), \
         patch.object(agent_main, "send_audio_or_text", new=AsyncMock(return_value=True)), \
         patch.object(agent_main, "send_user_message", new=AsyncMock(return_value=True)), \
         patch.object(agent_main, "guardar_mensaje", new=AsyncMock()), \
         patch.object(agent_main, "obtener_historial", new=AsyncMock(return_value=[])), \
         patch.object(agent_main, "_es_nueva_sesion", new=AsyncMock(return_value=False)), \
         patch.object(agent_main, "get_tts_config", return_value=tts_cfg), \
         patch.object(agent_main, "get_capabilities", return_value={"reactions": False}), \
         patch.object(agent_main, "is_solo_mode", return_value=True), \
         patch.object(agent_main.proveedor, "indicar_grabando", new=AsyncMock()), \
         patch.object(agent_main.proveedor, "indicar_escribiendo", new=AsyncMock()), \
         patch.object(agent_main.usage_reporter, "report", new=AsyncMock()), \
         patch("asyncio.sleep", new=AsyncMock()):
        await agent_main._procesar_y_responder(
            chat_id="54911@c.us", texto="hola", mensaje_id="m1",
            fue_audio=fue_audio, message_count=1,
        )
    return captured["contexto"] or ""


def test_helper_nivel_5_no_instruccion():
    from agent.main import _engagement_instruction
    assert _engagement_instruction(5) == ""


def test_helper_nivel_4_alto():
    from agent.main import _engagement_instruction
    out = _engagement_instruction(4)
    assert "ALTO" in out and "SILENCIO" in out


def test_helper_nivel_3_medio():
    from agent.main import _engagement_instruction
    out = _engagement_instruction(3)
    assert "MEDIO" in out and "sustancia" in out.lower()


def test_helper_nivel_2_bajo():
    from agent.main import _engagement_instruction
    out = _engagement_instruction(2)
    assert "BAJO" in out and "off-topic" in out.lower()


def test_helper_nivel_1_minimo():
    from agent.main import _engagement_instruction
    out = _engagement_instruction(1)
    assert "MINIMO" in out and "estrictamente" in out.lower()


def test_helper_default_si_invalido():
    from agent.main import _engagement_instruction
    assert _engagement_instruction(None) == ""
    assert _engagement_instruction("abc") == ""
    assert _engagement_instruction(99) == ""
    assert _engagement_instruction(0) == ""
    assert _engagement_instruction(-1) == ""


def test_helper_coerce_string_numerico():
    from agent.main import _engagement_instruction
    assert "MINIMO" in _engagement_instruction("1")
    assert _engagement_instruction("5") == ""


@pytest.mark.asyncio
async def test_nivel_5_no_inyecta_instruccion_engagement():
    """Default y nivel 5 → solo nota_audio basica, sin restriccion adicional."""
    contexto = await _capture_contexto(_tts_cfg(level=5))
    assert "nota de voz" in contexto.lower()
    assert "minimo" not in contexto.lower()
    assert "off-topic" not in contexto.lower()


@pytest.mark.asyncio
async def test_sin_campo_default_nivel_5():
    """Si el plugin no manda audio_engagement_level → comportamiento nivel 5."""
    contexto = await _capture_contexto(_tts_cfg(level=None))
    assert "nivel de respuesta" not in contexto.lower()


@pytest.mark.asyncio
async def test_nivel_1_inyecta_instruccion_minimo():
    contexto = await _capture_contexto(_tts_cfg(level=1))
    assert "minimo" in contexto.lower()
    assert "estrictamente" in contexto.lower()


@pytest.mark.asyncio
async def test_nivel_3_inyecta_instruccion_medio():
    contexto = await _capture_contexto(_tts_cfg(level=3))
    assert "medio" in contexto.lower()
    assert "silencio" in contexto.lower()


@pytest.mark.asyncio
async def test_no_inyecta_si_fue_audio_false():
    """Mensaje de texto → no se inyecta engagement aunque level este configurado."""
    contexto = await _capture_contexto(_tts_cfg(level=1), fue_audio=False)
    assert "minimo" not in contexto.lower()
    assert "nivel de respuesta" not in contexto.lower()


@pytest.mark.asyncio
async def test_no_inyecta_si_tts_disabled():
    """TTS deshabilitado → no aplica engagement (la respuesta saldria como texto)."""
    cfg = {"enabled": False, "audio_engagement_level": 1}
    contexto = await _capture_contexto(cfg)
    assert "nivel de respuesta" not in contexto.lower()
    assert "minimo" not in contexto.lower()
