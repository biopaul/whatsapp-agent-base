"""Tests para el wrapper send_user_message + checkpoint 2."""

import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import pytest
from unittest.mock import patch, AsyncMock


@pytest.fixture(autouse=True)
def reset_takeover(monkeypatch):
    monkeypatch.delenv("TAKEOVER_URL_BASE", raising=False)
    import importlib
    from agent import takeover
    importlib.reload(takeover)


@pytest.mark.asyncio
async def test_send_user_message_envia_si_no_manual():
    """Sin manual mode, envia + persiste assistant con mensaje_id."""
    from agent import main as agent_main
    from agent import takeover

    with patch.object(takeover, "is_chat_in_manual_mode", new=AsyncMock(return_value=False)), \
         patch.object(agent_main.proveedor, "enviar_mensaje_returning_id",
                      new=AsyncMock(return_value="msg_abc")), \
         patch.object(agent_main, "guardar_mensaje", new=AsyncMock()) as mock_save:
        result = await agent_main.send_user_message("54911@c.us", "hola cliente")

    assert result is True
    mock_save.assert_awaited_once_with("54911@c.us", "assistant", "hola cliente", mensaje_id="msg_abc")


@pytest.mark.asyncio
async def test_send_user_message_descarta_si_manual():
    """Con manual mode, NO envia ni persiste."""
    from agent import main as agent_main
    from agent import takeover

    with patch.object(takeover, "is_chat_in_manual_mode", new=AsyncMock(return_value=True)), \
         patch.object(agent_main.proveedor, "enviar_mensaje_returning_id",
                      new=AsyncMock(return_value="msg_xxx")) as mock_send, \
         patch.object(agent_main, "guardar_mensaje", new=AsyncMock()) as mock_save:
        result = await agent_main.send_user_message("54911@c.us", "hola cliente")

    assert result is False
    mock_send.assert_not_awaited()
    mock_save.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_user_message_envio_falla_no_persiste():
    """Si el provider retorna None (fallo), no persistimos en historial."""
    from agent import main as agent_main
    from agent import takeover

    with patch.object(takeover, "is_chat_in_manual_mode", new=AsyncMock(return_value=False)), \
         patch.object(agent_main.proveedor, "enviar_mensaje_returning_id",
                      new=AsyncMock(return_value=None)), \
         patch.object(agent_main, "guardar_mensaje", new=AsyncMock()) as mock_save:
        result = await agent_main.send_user_message("54911@c.us", "hola")

    assert result is False
    mock_save.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_user_message_ok_no_id_persiste_con_none():
    """Si provider devuelve sentinel 'ok_no_id', persistimos con mensaje_id=None."""
    from agent import main as agent_main
    from agent import takeover

    with patch.object(takeover, "is_chat_in_manual_mode", new=AsyncMock(return_value=False)), \
         patch.object(agent_main.proveedor, "enviar_mensaje_returning_id",
                      new=AsyncMock(return_value="ok_no_id")), \
         patch.object(agent_main, "guardar_mensaje", new=AsyncMock()) as mock_save:
        result = await agent_main.send_user_message("54911@c.us", "hola")

    assert result is True
    mock_save.assert_awaited_once_with("54911@c.us", "assistant", "hola", mensaje_id=None)
