"""Tests para la cascada de envio de plantillas guiadas."""

import pytest
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock


os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_cascade.db")
os.environ.setdefault("WAHA_SESSION", "test-session")


@pytest.fixture
async def temp_db(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp.name}")
    import importlib
    from agent import memory
    importlib.reload(memory)
    await memory.inicializar_db()
    yield memory
    try:
        await memory.engine.dispose()
        os.unlink(tmp.name)
    except Exception:
        pass


def _template(name="t1", n_options=2, body="Elegi una:"):
    return {
        "id": 1,
        "name": name,
        "body_text": body,
        "footer_text": None,
        "options": [
            {"id": i + 1, "order": i + 1, "visible_text": f"Op{i+1}", "action_type": "text",
             "action_payload": {"text": f"texto opcion {i+1}"}}
            for i in range(n_options)
        ],
    }


@pytest.mark.asyncio
async def test_cascade_intenta_buttons_si_soportados(temp_db):
    """Si supports_buttons=True, primer intento es buttons."""
    from agent import guided_cascade, memory
    now = datetime.now(timezone.utc)
    await memory.set_waha_capability("test-session", "supports_buttons", True, probe_at=now)

    provider = MagicMock()
    provider.enviar_buttons = AsyncMock(return_value=(True, 200, "msg_001"))
    provider.enviar_list = AsyncMock()
    provider.enviar_mensaje_returning_id = AsyncMock()

    result = await guided_cascade.enviar_con_cascada(
        provider=provider, session_id="test-session",
        chat_id="54911@c.us", template=_template(n_options=3),
    )
    assert result["format_used"] == "buttons"
    assert result["mensaje_id"] == "msg_001"
    provider.enviar_buttons.assert_awaited_once()
    provider.enviar_list.assert_not_awaited()


@pytest.mark.asyncio
async def test_cascade_buttons_501_cae_a_list(temp_db):
    """Buttons devuelve 501 -> marca capability False, intenta list."""
    from agent import guided_cascade, memory

    provider = MagicMock()
    provider.enviar_buttons = AsyncMock(return_value=(False, 501, None))
    provider.enviar_list = AsyncMock(return_value=(True, 200, "msg_lst"))
    provider.enviar_mensaje_returning_id = AsyncMock()

    result = await guided_cascade.enviar_con_cascada(
        provider=provider, session_id="test-session",
        chat_id="54911@c.us", template=_template(n_options=3),
    )
    assert result["format_used"] == "list"
    caps = await memory.get_waha_capabilities("test-session")
    assert caps["supports_buttons"] is False  # marcado


@pytest.mark.asyncio
async def test_cascade_buttons_y_list_fallan_cae_a_texto(temp_db):
    from agent import guided_cascade

    provider = MagicMock()
    provider.enviar_buttons = AsyncMock(return_value=(False, 501, None))
    provider.enviar_list = AsyncMock(return_value=(False, 500, None))
    provider.enviar_mensaje_returning_id = AsyncMock(return_value="msg_txt")

    result = await guided_cascade.enviar_con_cascada(
        provider=provider, session_id="test-session",
        chat_id="54911@c.us", template=_template(n_options=3),
    )
    assert result["format_used"] == "numbered_text"


@pytest.mark.asyncio
async def test_cascade_mas_de_10_opciones_salta_list(temp_db):
    """Con >10 opciones, list no aplica, salta directo a texto."""
    from agent import guided_cascade

    provider = MagicMock()
    provider.enviar_buttons = AsyncMock(return_value=(False, 501, None))
    provider.enviar_list = AsyncMock()
    provider.enviar_mensaje_returning_id = AsyncMock(return_value="msg_txt")

    result = await guided_cascade.enviar_con_cascada(
        provider=provider, session_id="test-session",
        chat_id="54911@c.us", template=_template(n_options=11),
    )
    assert result["format_used"] == "numbered_text"
    provider.enviar_list.assert_not_awaited()


@pytest.mark.asyncio
async def test_cascade_buttons_solo_si_3_opciones_o_menos(temp_db):
    """Con >3 opciones, buttons no aplica, salta directo a list."""
    from agent import guided_cascade, memory
    now = datetime.now(timezone.utc)
    await memory.set_waha_capability("test-session", "supports_buttons", True, probe_at=now)

    provider = MagicMock()
    provider.enviar_buttons = AsyncMock()
    provider.enviar_list = AsyncMock(return_value=(True, 200, "msg_lst"))

    result = await guided_cascade.enviar_con_cascada(
        provider=provider, session_id="test-session",
        chat_id="54911@c.us", template=_template(n_options=5),
    )
    assert result["format_used"] == "list"
    provider.enviar_buttons.assert_not_awaited()
