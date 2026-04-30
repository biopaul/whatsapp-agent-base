"""Tests para el tool use loop en brain.py."""

import os
import json
import pytest
from unittest.mock import AsyncMock
from types import SimpleNamespace

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
# brain.py creates AsyncOpenAI at module level; it reads OPENROUTER_API_KEY
# but falls back to OPENAI_API_KEY when using the openai SDK. Set a dummy value
# so the client initializes without raising during import.
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")


@pytest.fixture(autouse=True)
async def setup_db():
    from agent.memory import inicializar_db, engine, Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await inicializar_db()
    yield


def test_es_consulta_compleja_simple():
    from agent.brain import _es_consulta_compleja
    assert _es_consulta_compleja("hola", []) is False


def test_es_consulta_compleja_largo_y_keyword():
    from agent.brain import _es_consulta_compleja
    msg = "Cual es el precio de la consulta para mi gato? Y como se compara con la opcion premium?"
    assert _es_consulta_compleja(msg, []) is True


def test_es_consulta_compleja_muchos_turnos():
    from agent.brain import _es_consulta_compleja
    historial = [{"role": "user", "content": str(i)} for i in range(10)]
    long_msg = "Como funcionan los precios y que diferencia hay con la otra opcion?"
    assert _es_consulta_compleja(long_msg, historial) is True


def test_filter_tool_use_capable():
    from agent.brain import _filter_tool_use_capable
    models = [
        "anthropic/claude-3-5-haiku",
        "openai/gpt-4o-mini",
        "meta-llama/llama-3.1-8b-instruct",  # 3.1 — no soporta tools
        "deepseek/deepseek-chat",
        "google/gemini-flash-1.5",
    ]
    out = _filter_tool_use_capable(models)
    assert "anthropic/claude-3-5-haiku" in out
    assert "openai/gpt-4o-mini" in out
    assert "deepseek/deepseek-chat" in out
    assert "google/gemini-flash-1.5" in out
    assert "meta-llama/llama-3.1-8b-instruct" not in out


def test_filter_empty_returns_empty():
    from agent.brain import _filter_tool_use_capable
    assert _filter_tool_use_capable([]) == []


def test_filter_no_compatible_returns_empty():
    from agent.brain import _filter_tool_use_capable
    assert _filter_tool_use_capable(["meta-llama/llama-3.1-8b-instruct"]) == []


@pytest.mark.asyncio
async def test_generar_respuesta_sin_conectores_no_pasa_tools(monkeypatch):
    """Sin conectores activos, no se pasan tools al LLM."""
    monkeypatch.setattr("agent.brain.get_active_connectors", lambda: [])

    mock_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content="Hola, como puedo ayudarte?",
            tool_calls=None,
        ))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        model="anthropic/claude-3-5-haiku",
    )

    create_mock = AsyncMock(return_value=mock_response)
    monkeypatch.setattr("agent.brain.client.chat.completions.create", create_mock)

    from agent.brain import generar_respuesta
    result = await generar_respuesta("hola", [], "", telefono="5491100000001")

    assert result == "Hola, como puedo ayudarte?"
    call_kwargs = create_mock.call_args.kwargs
    assert "tools" not in call_kwargs


@pytest.mark.asyncio
async def test_generar_respuesta_con_conectores_pasa_tools(monkeypatch):
    """Con conector activo, se pasan tools al LLM."""
    fake_connector = {
        "slug": "gcal",
        "enabled": True,
        "configured": True,
        "config_summary": {
            "slot_types": [{"label": "Corto", "duration_minutes": 15, "services": ["control"]}]
        },
    }
    monkeypatch.setattr("agent.brain.get_active_connectors", lambda: [fake_connector])

    mock_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content="Listo, no necesito mas info por ahora",
            tool_calls=None,
        ))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        model="anthropic/claude-3-5-haiku",
    )

    create_mock = AsyncMock(return_value=mock_response)
    monkeypatch.setattr("agent.brain.client.chat.completions.create", create_mock)

    from agent.brain import generar_respuesta
    await generar_respuesta("hola", [], "", telefono="5491100000001")

    call_kwargs = create_mock.call_args.kwargs
    tools_passed = call_kwargs.get("tools", [])
    assert len(tools_passed) == 6
    tool_names = [t["function"]["name"] for t in tools_passed]
    assert "gcal_consultar_disponibilidad" in tool_names
    assert "guardar_contacto" in tool_names
