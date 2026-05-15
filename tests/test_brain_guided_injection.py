"""Tests para inyeccion de plantillas guiadas en brain.generar_respuesta."""

import os
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock, MagicMock

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_brain_guided.db")
os.environ.setdefault("OPENROUTER_API_KEY", "sk-or-test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    monkeypatch.delenv("TAKEOVER_URL_BASE", raising=False)
    monkeypatch.delenv("GUIDED_URL_BASE", raising=False)
    import importlib
    from agent import takeover, guided_templates
    importlib.reload(takeover)
    importlib.reload(guided_templates)


def _extract_system_text(messages):
    """Extrae todo el texto del system message (handle str y list-of-dict shapes)."""
    if not messages:
        return ""
    sys_msg = messages[0]
    content = sys_msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else "" for b in content)
    return ""


@pytest.mark.asyncio
async def test_inyeccion_bloque_plantillas_si_hay_activas():
    from agent import brain, guided_templates

    template = {
        "id": 1, "name": "menu_turnos", "trigger_description": "Cuando pidan turno",
        "body_text": "Elegi:", "footer_text": None,
        "depth_level": 1, "parent_template_id": None,
        "options": [{"id": 11, "order": 1, "visible_text": "Mañana", "action_type": "text", "action_payload": {}}]
    }

    captured = {}

    async def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages", [])
        resp = MagicMock()
        resp.choices = [MagicMock(message=MagicMock(content="ok", tool_calls=None))]
        resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        return resp

    with patch("agent.guided_templates.get_active", new=AsyncMock(return_value=[template])), \
         patch.object(brain.client.chat.completions, "create", new=fake_create):
        await brain.generar_respuesta("hola", [], telefono="54911@c.us")

    text = _extract_system_text(captured.get("messages", []))
    assert "RESPUESTAS GUIADAS DISPONIBLES" in text
    assert "menu_turnos" in text
    assert "Cuando pidan turno" in text


@pytest.mark.asyncio
async def test_no_inyeccion_si_lista_vacia():
    from agent import brain

    captured = {}

    async def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages", [])
        resp = MagicMock()
        resp.choices = [MagicMock(message=MagicMock(content="ok", tool_calls=None))]
        resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        return resp

    with patch("agent.guided_templates.get_active", new=AsyncMock(return_value=[])), \
         patch.object(brain.client.chat.completions, "create", new=fake_create):
        await brain.generar_respuesta("hola", [], telefono="54911@c.us")

    text = _extract_system_text(captured.get("messages", [])).upper()
    assert "RESPUESTAS GUIADAS" not in text
