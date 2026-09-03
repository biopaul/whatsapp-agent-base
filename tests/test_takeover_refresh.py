# tests/test_takeover_refresh.py — endpoint POST /takeover/refresh + apply_push_update

import os
os.environ.setdefault("OPENAI_API_KEY", "test-dummy")
os.environ.setdefault("OPENROUTER_API_KEY", "test-dummy")
os.environ["TAKEOVER_URL_BASE"] = "http://takeover.test"
os.environ["TAKEOVER_REFRESH_TOKEN"] = "secret-test-token"

import asyncio
import importlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("TAKEOVER_URL_BASE", "http://takeover.test")
    monkeypatch.setenv("TAKEOVER_REFRESH_TOKEN", "secret-test-token")
    from agent import takeover
    importlib.reload(takeover)
    yield


# --- apply_push_update: idempotencia y transiciones ---

def test_push_manual_sobre_sin_cache_crea():
    from agent import takeover
    expires = datetime.now(timezone.utc) + timedelta(minutes=40)
    result = takeover.apply_push_update("chat1", "manual", expires)
    assert result == "updated"
    assert takeover._cache["chat1"].mode == "manual"
    assert takeover._cache["chat1"].expires_at == expires


def test_push_auto_sobre_sin_cache_crea():
    from agent import takeover
    result = takeover.apply_push_update("chat1", "auto")
    assert result == "updated"
    assert takeover._cache["chat1"].mode == "auto"


def test_push_manual_idempotente_dentro_tolerancia_60s():
    from agent import takeover
    expires = datetime.now(timezone.utc) + timedelta(minutes=40)
    takeover.apply_push_update("chat1", "manual", expires)
    # Segundo push con expires_at 30s despues → dentro de tolerancia
    expires2 = expires + timedelta(seconds=30)
    result = takeover.apply_push_update("chat1", "manual", expires2)
    assert result == "unchanged"


def test_push_manual_actualiza_si_fuera_tolerancia():
    from agent import takeover
    expires = datetime.now(timezone.utc) + timedelta(minutes=40)
    takeover.apply_push_update("chat1", "manual", expires)
    # Segundo push con expires_at 5 min despues → fuera de tolerancia
    expires2 = expires + timedelta(minutes=5)
    result = takeover.apply_push_update("chat1", "manual", expires2)
    assert result == "updated"
    assert takeover._cache["chat1"].expires_at == expires2


def test_push_auto_sobre_auto_idempotente():
    from agent import takeover
    takeover.apply_push_update("chat1", "auto")
    result = takeover.apply_push_update("chat1", "auto")
    assert result == "unchanged"


def test_push_auto_sobre_manual_preserva_last_manual_until():
    from agent import takeover
    expires = datetime.now(timezone.utc) + timedelta(minutes=40)
    takeover.apply_push_update("chat1", "manual", expires)
    result = takeover.apply_push_update("chat1", "auto")
    assert result == "updated"
    assert takeover._cache["chat1"].mode == "auto"
    assert takeover._cache["chat1"].last_manual_until == expires


def test_push_manual_sin_expires_at_raise():
    from agent import takeover
    with pytest.raises(ValueError, match="expires_at"):
        takeover.apply_push_update("chat1", "manual", None)


def test_push_mode_invalido_raise():
    from agent import takeover
    with pytest.raises(ValueError, match="mode invalido"):
        takeover.apply_push_update("chat1", "invalid_mode", None)


# --- Endpoint HTTP ---

def _client():
    from agent import main as main_mod
    importlib.reload(main_mod)
    return TestClient(main_mod.app)


def test_endpoint_sin_token_401():
    client = _client()
    r = client.post("/takeover/refresh", json={
        "chat_id": "chat1", "mode": "auto"
    })
    assert r.status_code == 401


def test_endpoint_token_invalido_401():
    client = _client()
    r = client.post("/takeover/refresh",
                    headers={"X-Refresh-Token": "wrong"},
                    json={"chat_id": "chat1", "mode": "auto"})
    assert r.status_code == 401


def test_endpoint_token_valido_auto_ok():
    client = _client()
    r = client.post("/takeover/refresh",
                    headers={"X-Refresh-Token": "secret-test-token"},
                    json={"chat_id": "chat1", "mode": "auto"})
    assert r.status_code == 200
    assert r.json() == {"status": "updated"}


def test_endpoint_manual_con_expires_ok():
    client = _client()
    expires = "2050-01-01T12:00:00Z"
    r = client.post("/takeover/refresh",
                    headers={"X-Refresh-Token": "secret-test-token"},
                    json={"chat_id": "chat1", "mode": "manual",
                          "expires_at": expires})
    assert r.status_code == 200
    assert r.json() == {"status": "updated"}


def test_endpoint_idempotente_204():
    client = _client()
    payload = {"chat_id": "chat1", "mode": "auto"}
    headers = {"X-Refresh-Token": "secret-test-token"}
    r1 = client.post("/takeover/refresh", headers=headers, json=payload)
    assert r1.status_code == 200
    r2 = client.post("/takeover/refresh", headers=headers, json=payload)
    assert r2.status_code == 204


def test_endpoint_manual_sin_expires_400():
    client = _client()
    r = client.post("/takeover/refresh",
                    headers={"X-Refresh-Token": "secret-test-token"},
                    json={"chat_id": "chat1", "mode": "manual"})
    assert r.status_code == 400


def test_endpoint_mode_invalido_400():
    client = _client()
    r = client.post("/takeover/refresh",
                    headers={"X-Refresh-Token": "secret-test-token"},
                    json={"chat_id": "chat1", "mode": "xxx"})
    assert r.status_code == 400


def test_endpoint_sin_chat_id_400():
    client = _client()
    r = client.post("/takeover/refresh",
                    headers={"X-Refresh-Token": "secret-test-token"},
                    json={"mode": "auto"})
    assert r.status_code == 400


def test_endpoint_expires_at_invalido_400():
    client = _client()
    r = client.post("/takeover/refresh",
                    headers={"X-Refresh-Token": "secret-test-token"},
                    json={"chat_id": "chat1", "mode": "manual",
                          "expires_at": "no-es-una-fecha"})
    assert r.status_code == 400


def test_endpoint_deshabilitado_si_no_hay_token_env(monkeypatch):
    monkeypatch.setenv("TAKEOVER_REFRESH_TOKEN", "")
    from agent import takeover
    importlib.reload(takeover)
    client = _client()
    # Aunque mande un token cualquiera, si el env esta vacio, rechaza
    r = client.post("/takeover/refresh",
                    headers={"X-Refresh-Token": "anything"},
                    json={"chat_id": "chat1", "mode": "auto"})
    assert r.status_code == 401
    # Restaurar env
    monkeypatch.setenv("TAKEOVER_REFRESH_TOKEN", "secret-test-token")
    importlib.reload(takeover)
