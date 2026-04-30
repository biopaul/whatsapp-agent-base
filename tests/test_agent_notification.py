"""Tests del endpoint POST /agent/notification."""

import os
import pytest
from unittest.mock import AsyncMock

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
# brain.py creates AsyncOpenAI at module level; needs a dummy key to initialize
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")


@pytest.fixture(autouse=True)
async def setup_db():
    from agent.memory import inicializar_db, engine, Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await inicializar_db()
    yield


def get_test_client(monkeypatch, token="abc123"):
    """Helper: arma TestClient con CONFIG_URL conocido."""
    monkeypatch.setenv("CONFIG_URL", f"https://example.com/wp-json/gowap/v1/config/{token}")
    import importlib
    import agent.main
    importlib.reload(agent.main)
    from fastapi.testclient import TestClient
    return TestClient(agent.main.app)


def test_notification_sin_token_retorna_401(monkeypatch):
    client = get_test_client(monkeypatch)
    r = client.post("/agent/notification", json={"phone": "5491100000001", "message": "hola"})
    assert r.status_code == 401


def test_notification_token_invalido_retorna_401(monkeypatch):
    client = get_test_client(monkeypatch, token="abc123")
    r = client.post(
        "/agent/notification",
        json={"phone": "5491100000001", "message": "hola"},
        headers={"X-Gowap-Token": "wrong"},
    )
    assert r.status_code == 401


def test_notification_sin_phone_retorna_400(monkeypatch):
    client = get_test_client(monkeypatch, token="abc123")
    r = client.post(
        "/agent/notification",
        json={"message": "hola"},
        headers={"X-Gowap-Token": "abc123"},
    )
    assert r.status_code == 400


def test_notification_provider_falla_retorna_502(monkeypatch):
    monkeypatch.setenv("CONFIG_URL", "https://example.com/wp-json/gowap/v1/config/abc123")
    import importlib, agent.main
    importlib.reload(agent.main)

    agent.main.proveedor.enviar_mensaje = AsyncMock(return_value=False)

    from fastapi.testclient import TestClient
    client = TestClient(agent.main.app)

    r = client.post(
        "/agent/notification",
        json={"phone": "5491100000001", "message": "hola"},
        headers={"X-Gowap-Token": "abc123"},
    )
    assert r.status_code == 502


def test_notification_ok_guarda_historial_y_envia(monkeypatch):
    monkeypatch.setenv("CONFIG_URL", "https://example.com/wp-json/gowap/v1/config/abc123")
    import importlib, agent.main
    importlib.reload(agent.main)

    agent.main.proveedor.enviar_mensaje = AsyncMock(return_value=True)

    from fastapi.testclient import TestClient
    client = TestClient(agent.main.app)

    r = client.post(
        "/agent/notification",
        json={"phone": "5491100000001", "message": "Recordatorio: tu turno es manana"},
        headers={"X-Gowap-Token": "abc123"},
    )
    assert r.status_code == 200
    assert r.json() == {"status": "sent"}

    agent.main.proveedor.enviar_mensaje.assert_called_once()

    # Verificar que se guardo en historial
    import asyncio
    from agent.memory import obtener_historial
    historial = asyncio.run(obtener_historial("5491100000001"))
    assert len(historial) >= 1
    assert historial[-1]["role"] == "assistant"
    assert "Recordatorio" in historial[-1]["content"]
