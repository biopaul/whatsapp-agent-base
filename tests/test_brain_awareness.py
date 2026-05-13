"""Tests para inyeccion de awareness en brain.generar_respuesta."""

import os
import json
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_brain_awareness.db")
os.environ.setdefault("OPENROUTER_API_KEY", "sk-or-test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")


def _extract_system_text(kwargs) -> str:
    """El system prompt es el primer mensaje de la lista `messages`."""
    mensajes = kwargs.get("messages", [])
    if not mensajes:
        return ""
    sys_msg = mensajes[0]
    content = sys_msg.get("content", "")
    if isinstance(content, str):
        return content
    # Anthropic-style: list of {type, text, ...} blocks
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return str(content)


def _fake_response():
    resp = MagicMock()
    choice = MagicMock()
    choice.message.content = "respuesta"
    choice.message.tool_calls = None
    resp.choices = [choice]
    resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5, prompt_tokens_details=None)
    resp.model = "test-model"
    return resp


@pytest.mark.asyncio
async def test_awareness_se_inyecta_si_recently_manual():
    from agent import brain, takeover

    now = datetime.now(timezone.utc)
    window = (now - timedelta(minutes=30), now - timedelta(minutes=5))

    captured = {}

    async def fake_create(**kwargs):
        captured["kwargs"] = kwargs
        return _fake_response()

    with patch.object(takeover, "was_recently_manual", return_value=window), \
         patch.object(brain.client.chat.completions, "create", new=fake_create), \
         patch.object(brain, "obtener_contacto", return_value=None, create=True):
        await brain.generar_respuesta("hola", [], telefono="54911@c.us")

    system_str = _extract_system_text(captured["kwargs"]).lower()
    assert "atendido manualmente" in system_str or "operador humano" in system_str


@pytest.mark.asyncio
async def test_awareness_no_se_inyecta_si_nunca_manual():
    from agent import brain, takeover

    captured = {}

    async def fake_create(**kwargs):
        captured["kwargs"] = kwargs
        return _fake_response()

    with patch.object(takeover, "was_recently_manual", return_value=None), \
         patch.object(brain.client.chat.completions, "create", new=fake_create), \
         patch.object(brain, "obtener_contacto", return_value=None, create=True):
        await brain.generar_respuesta("hola", [], telefono="54911@c.us")

    system_str = _extract_system_text(captured["kwargs"]).lower()
    assert "atendido manualmente" not in system_str
    assert "operador humano" not in system_str
