"""Tests del flujo webhook con handoff manual."""

import os
import pytest
from unittest.mock import patch, AsyncMock

# Env requirements
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_webhook_handoff.db")
os.environ.setdefault("OPENROUTER_API_KEY", "sk-or-test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")


@pytest.fixture(autouse=True)
def reset_takeover(monkeypatch):
    monkeypatch.delenv("TAKEOVER_URL_BASE", raising=False)
    import importlib
    from agent import takeover
    importlib.reload(takeover)


@pytest.mark.asyncio
async def test_checkpoint1_skipea_llm_si_manual():
    """Mensaje entrante con chat en manual -> guarda user + skip LLM/send."""
    from agent import main as agent_main
    from agent import takeover, memory, brain

    msg_user = "hola, esto deberia ir manual"

    with patch.object(takeover, "is_chat_in_manual_mode", new=AsyncMock(return_value=True)), \
         patch.object(agent_main, "guardar_mensaje", new=AsyncMock()) as mock_save, \
         patch.object(brain, "generar_respuesta", new=AsyncMock(return_value="no debe llamarse")) as mock_brain, \
         patch.object(agent_main, "send_user_message", new=AsyncMock(return_value=True)) as mock_send:

        await agent_main._procesar_mensaje_entrante("54911@c.us", msg_user, mensaje_id="in_001")

    mock_save.assert_awaited_with("54911@c.us", "user", msg_user, mensaje_id="in_001")
    mock_brain.assert_not_awaited()
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_from_me_capturado_durante_manual():
    """from_me=True durante manual mode -> guardar como assistant con dedupe."""
    from agent import main as agent_main
    from agent import takeover, memory

    with patch.object(takeover, "is_chat_in_manual_mode", new=AsyncMock(return_value=True)), \
         patch.object(agent_main, "existe_mensaje_id", new=AsyncMock(return_value=False)), \
         patch.object(agent_main, "guardar_mensaje", new=AsyncMock()) as mock_save:

        await agent_main._procesar_mensaje_propio("54911@c.us", "respuesta humana", mensaje_id="out_001")

    mock_save.assert_awaited_with("54911@c.us", "assistant", "respuesta humana", mensaje_id="out_001")


@pytest.mark.asyncio
async def test_from_me_deduplicado():
    """from_me con mensaje_id ya en DB -> no se guarda dos veces."""
    from agent import main as agent_main
    from agent import takeover

    with patch.object(takeover, "is_chat_in_manual_mode", new=AsyncMock(return_value=True)), \
         patch.object(agent_main, "existe_mensaje_id", new=AsyncMock(return_value=True)), \
         patch.object(agent_main, "guardar_mensaje", new=AsyncMock()) as mock_save:

        await agent_main._procesar_mensaje_propio("54911@c.us", "respuesta humana", mensaje_id="out_001")

    mock_save.assert_not_awaited()


@pytest.mark.asyncio
async def test_from_me_ignorado_si_no_manual_ni_recently():
    """from_me en auto mode (sin recently_manual) -> ignorar."""
    from agent import main as agent_main
    from agent import takeover

    with patch.object(takeover, "is_chat_in_manual_mode", new=AsyncMock(return_value=False)), \
         patch.object(takeover, "was_recently_manual", return_value=None), \
         patch.object(agent_main, "guardar_mensaje", new=AsyncMock()) as mock_save:

        await agent_main._procesar_mensaje_propio("54911@c.us", "respuesta agente", mensaje_id="out_002")

    mock_save.assert_not_awaited()
