"""Tests para el executor de tool calls."""

import os
import json
import pytest
from types import SimpleNamespace

# Setup: SQLite in-memory para los tests que usan guardar_contacto
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"


def make_tool_call(name: str, arguments):
    """Helper: crea un fake tool_call con el shape del SDK de OpenAI."""
    if isinstance(arguments, dict):
        arguments = json.dumps(arguments)
    return SimpleNamespace(
        function=SimpleNamespace(name=name, arguments=arguments)
    )


@pytest.fixture(autouse=True)
async def setup_db():
    from agent.memory import inicializar_db, engine, Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await inicializar_db()
    yield


@pytest.mark.asyncio
async def test_guardar_contacto_persiste():
    from agent.connectors.executor import execute_tool
    from agent.memory import obtener_contacto

    tc = make_tool_call("guardar_contacto", {"nombre": "Juan", "email": "j@x.com"})
    result = await execute_tool(tc, "5491134567890")
    assert result.get("ok") is True

    contacto = await obtener_contacto("5491134567890")
    assert contacto is not None
    assert contacto.nombre == "Juan"
    assert contacto.email == "j@x.com"


@pytest.mark.asyncio
async def test_guardar_contacto_sin_datos_returns_false():
    from agent.connectors.executor import execute_tool
    tc = make_tool_call("guardar_contacto", {})
    result = await execute_tool(tc, "5491134567890")
    assert result.get("ok") is False


@pytest.mark.asyncio
async def test_unknown_tool_returns_error():
    from agent.connectors.executor import execute_tool
    tc = make_tool_call("herramienta_inexistente", {})
    result = await execute_tool(tc, "5491134567890")
    assert result.get("error") == "unknown_tool"


@pytest.mark.asyncio
async def test_invalid_args_returns_error():
    from agent.connectors.executor import execute_tool
    tc = make_tool_call("gcal_crear_turno", "not-json")
    result = await execute_tool(tc, "5491134567890")
    assert result.get("error") == "invalid_args"


@pytest.mark.asyncio
async def test_wp_call_no_config_url_returns_error(monkeypatch):
    """Sin CONFIG_URL configurado, retorna error sin hacer HTTP."""
    monkeypatch.setenv("CONFIG_URL", "")
    # Re-import to pick up env change
    from agent.connectors.executor import execute_tool
    tc = make_tool_call("gcal_consultar_disponibilidad", {"servicio": "limpieza"})
    result = await execute_tool(tc, "5491134567890")
    assert result.get("error") == "server_unavailable"


@pytest.mark.asyncio
async def test_wp_call_timeout_returns_error(monkeypatch):
    """Si httpx lanza TimeoutException, retorna error timeout."""
    import httpx
    monkeypatch.setenv("CONFIG_URL", "https://example.com/wp-json/gowap/v1/config/abc123")

    from agent.connectors import executor

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, *a, **kw):
            raise httpx.TimeoutException("simulated timeout")

    monkeypatch.setattr(executor.httpx, "AsyncClient", FakeClient)

    tc = make_tool_call("gcal_consultar_disponibilidad", {"servicio": "limpieza"})
    result = await executor.execute_tool(tc, "5491134567890")
    assert result.get("error") == "timeout"


@pytest.mark.asyncio
async def test_wp_call_200_returns_data(monkeypatch):
    """Un 200 con JSON valido se devuelve tal cual, y telefono se inyecta."""
    monkeypatch.setenv("CONFIG_URL", "https://example.com/wp-json/gowap/v1/config/abc123")

    from agent.connectors import executor

    expected_data = {"slots": ["2026-05-05T10:00:00", "2026-05-05T11:00:00"]}
    captured = {}

    class FakeResp:
        status_code = 200
        text = json.dumps(expected_data)
        def json(self):
            return expected_data

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, url, json=None):
            captured['url'] = url
            captured['payload'] = json
            return FakeResp()

    monkeypatch.setattr(executor.httpx, "AsyncClient", FakeClient)

    tc = make_tool_call("gcal_consultar_disponibilidad", {"servicio": "limpieza"})
    result = await executor.execute_tool(tc, "5491134567890")

    assert result == expected_data
    assert "/connectors/abc123/gcal/availability" in captured['url']
    assert captured['payload']['telefono'] == "5491134567890"
    assert captured['payload']['servicio'] == "limpieza"
