"""Verifica que main.py llama a contacts_webhook.touch_contact en los lugares correctos."""

import os
import pytest
from unittest.mock import patch, AsyncMock

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_contacts_main.db")
os.environ.setdefault("OPENROUTER_API_KEY", "sk-or-test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    monkeypatch.delenv("TAKEOVER_URL_BASE", raising=False)
    monkeypatch.delenv("GUIDED_URL_BASE", raising=False)
    monkeypatch.delenv("CONTACTS_URL_BASE", raising=False)
    import importlib
    from agent import takeover, guided_templates, contacts_webhook
    importlib.reload(takeover)
    importlib.reload(guided_templates)
    importlib.reload(contacts_webhook)


@pytest.mark.asyncio
async def test_send_user_message_dispara_touch_out():
    from agent import main as agent_main
    from agent import takeover, contacts_webhook

    touch_calls = []

    async def fake_touch(**kwargs):
        touch_calls.append(kwargs)

    with patch.object(takeover, "is_chat_in_manual_mode", new=AsyncMock(return_value=False)), \
         patch.object(agent_main.proveedor, "enviar_mensaje_returning_id",
                      new=AsyncMock(return_value="msg_001")), \
         patch.object(agent_main, "guardar_mensaje", new=AsyncMock()), \
         patch.object(contacts_webhook, "touch_contact", new=fake_touch):
        await agent_main.send_user_message("54911@c.us", "hola cliente")
        # Esperar al create_task background
        import asyncio
        await asyncio.sleep(0.1)

    assert len(touch_calls) == 1
    assert touch_calls[0]["chat_id"] == "54911@c.us"
    assert touch_calls[0]["direction"] == "out"
    assert touch_calls[0]["preview"] == "hola cliente"


@pytest.mark.asyncio
async def test_send_user_message_no_dispara_touch_si_envio_falla():
    """Si el provider retorna None (fail), no hay touch (no se persistio)."""
    from agent import main as agent_main
    from agent import takeover, contacts_webhook

    touch_calls = []

    async def fake_touch(**kwargs):
        touch_calls.append(kwargs)

    with patch.object(takeover, "is_chat_in_manual_mode", new=AsyncMock(return_value=False)), \
         patch.object(agent_main.proveedor, "enviar_mensaje_returning_id",
                      new=AsyncMock(return_value=None)), \
         patch.object(agent_main, "guardar_mensaje", new=AsyncMock()), \
         patch.object(contacts_webhook, "touch_contact", new=fake_touch):
        await agent_main.send_user_message("54911@c.us", "hola")
        import asyncio
        await asyncio.sleep(0.1)

    assert len(touch_calls) == 0


@pytest.mark.asyncio
async def test_procesar_mensaje_entrante_dispara_touch_in_en_flujo_normal():
    from agent import takeover, contacts_webhook
    from agent import memory as mem
    from agent import main as agent_main

    touch_calls = []

    async def fake_touch(**kwargs):
        touch_calls.append(kwargs)

    with patch("agent.memory.obtener_contacto", new=AsyncMock(return_value=None)), \
         patch.object(takeover, "is_chat_in_manual_mode", new=AsyncMock(return_value=False)), \
         patch.object(mem, "obtener_dispatch_activo", new=AsyncMock(return_value=None)), \
         patch("agent.memory.guardar_mensaje", new=AsyncMock()), \
         patch("agent.main.guardar_mensaje", new=AsyncMock()), \
         patch("agent.main.obtener_historial", new=AsyncMock(return_value=[])), \
         patch.object(agent_main, "send_user_message", new=AsyncMock()), \
         patch.object(contacts_webhook, "touch_contact", new=fake_touch):
        await agent_main._procesar_mensaje_entrante("54911@c.us", "hola agente", mensaje_id="in_1")
        import asyncio
        await asyncio.sleep(0.1)

    # Debe haber al menos 1 touch in
    in_touches = [c for c in touch_calls if c["direction"] == "in"]
    assert len(in_touches) >= 1
    assert in_touches[0]["chat_id"] == "54911@c.us"
    assert in_touches[0]["preview"] == "hola agente"


@pytest.mark.asyncio
async def test_procesar_mensaje_entrante_dispara_touch_in_durante_manual_mode():
    """Aun en takeover, el touch in se dispara (stop-on-reply aplica)."""
    from agent import main as agent_main
    from agent import takeover, contacts_webhook
    from agent import memory as mem

    touch_calls = []

    async def fake_touch(**kwargs):
        touch_calls.append(kwargs)

    with patch.object(takeover, "is_chat_in_manual_mode", new=AsyncMock(return_value=True)), \
         patch.object(mem, "obtener_contacto", new=AsyncMock(return_value=None)), \
         patch.object(agent_main, "guardar_mensaje", new=AsyncMock()), \
         patch.object(contacts_webhook, "touch_contact", new=fake_touch):
        await agent_main._procesar_mensaje_entrante("54911@c.us", "ping en manual", mensaje_id="in_2")
        import asyncio
        await asyncio.sleep(0.1)

    in_touches = [c for c in touch_calls if c["direction"] == "in"]
    assert len(in_touches) >= 1
    assert in_touches[0]["preview"] == "ping en manual"
