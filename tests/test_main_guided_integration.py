"""Tests del wiring en main.py: pre-LLM selection + post-LLM dispatch."""

import os
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_main_guided.db")
os.environ.setdefault("OPENROUTER_API_KEY", "sk-or-test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")


@pytest.fixture(autouse=True)
async def reset(monkeypatch):
    monkeypatch.delenv("TAKEOVER_URL_BASE", raising=False)
    monkeypatch.delenv("GUIDED_URL_BASE", raising=False)
    import importlib
    from agent import takeover, guided_templates, memory
    importlib.reload(takeover)
    importlib.reload(guided_templates)
    await memory.inicializar_db()


@pytest.mark.asyncio
async def test_pre_llm_selection_dispara_accion_y_skipea_llm():
    """Si hay dispatch activo + input matchea opcion, ejecuta accion sin llamar al LLM."""
    from agent import main as agent_main
    from agent import takeover, memory, brain

    dispatch_activo = {
        "id": 1, "template_id": 10, "chat_id": "c@c.us",
        "format_used": "numbered_text", "remote_dispatch_id": 42,
        "options_snapshot": [
            {"id": 11, "order": 1, "visible_text": "Si", "action_type": "text",
             "action_payload": {"text": "el usuario confirma"}},
        ],
    }

    with patch.object(takeover, "is_chat_in_manual_mode", new=AsyncMock(return_value=False)), \
         patch.object(memory, "obtener_dispatch_activo", new=AsyncMock(return_value=dispatch_activo)), \
         patch("agent.guided_templates.register_selection", new=AsyncMock(return_value=True)), \
         patch.object(agent_main, "guardar_mensaje", new=AsyncMock()) as mock_save, \
         patch.object(brain, "generar_respuesta", new=AsyncMock(return_value="reinyectada")) as mock_brain, \
         patch.object(agent_main, "_procesar_respuesta_llm", new=AsyncMock()) as mock_proc_resp:
        await agent_main._procesar_mensaje_entrante("c@c.us", "1", mensaje_id="in_1")

    # generar_respuesta SI se llama (porque action text reinyecta), pero NO con el "1" original
    mock_brain.assert_awaited_once()
    call_args = mock_brain.await_args
    # El primer arg es el texto reinyectado, no el "1"
    assert call_args.args[0] == "el usuario confirma" or call_args.kwargs.get("mensaje") == "el usuario confirma"


@pytest.mark.asyncio
async def test_post_llm_si_respuesta_es_plantilla_dispatcha():
    """Si el LLM responde con <plantilla>X</plantilla>, llamamos dispatcher y NO send_user_message."""
    from agent import main as agent_main
    from agent import takeover, memory, brain

    with patch.object(takeover, "is_chat_in_manual_mode", new=AsyncMock(return_value=False)), \
         patch.object(memory, "obtener_dispatch_activo", new=AsyncMock(return_value=None)), \
         patch.object(agent_main, "guardar_mensaje", new=AsyncMock()), \
         patch.object(memory, "obtener_historial", new=AsyncMock(return_value=[])), \
         patch.object(brain, "generar_respuesta", new=AsyncMock(return_value="<plantilla>menu</plantilla>")), \
         patch("agent.guided_dispatcher.dispatch_plantilla",
               new=AsyncMock(return_value={"ok": True, "format_used": "numbered_text"})) as mock_disp, \
         patch.object(agent_main, "send_user_message", new=AsyncMock()) as mock_send:
        await agent_main._procesar_mensaje_entrante("c@c.us", "agendame turno", mensaje_id="in_2")

    mock_disp.assert_awaited_once()
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_post_llm_si_no_es_plantilla_envia_normal():
    """Si el LLM responde texto normal, send_user_message lo envia (con splits)."""
    from agent import main as agent_main
    from agent import takeover, memory, brain

    with patch.object(takeover, "is_chat_in_manual_mode", new=AsyncMock(return_value=False)), \
         patch.object(memory, "obtener_dispatch_activo", new=AsyncMock(return_value=None)), \
         patch.object(agent_main, "guardar_mensaje", new=AsyncMock()), \
         patch.object(memory, "obtener_historial", new=AsyncMock(return_value=[])), \
         patch.object(brain, "generar_respuesta", new=AsyncMock(return_value="hola, en que te ayudo?")), \
         patch.object(agent_main, "send_user_message", new=AsyncMock()) as mock_send:
        await agent_main._procesar_mensaje_entrante("c@c.us", "hola", mensaje_id="in_3")

    mock_send.assert_awaited()
