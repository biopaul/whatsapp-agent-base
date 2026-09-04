# tests/test_takeover_poll_expires_fallback.py — fallback TTL cuando el plugin
# no devuelve expires_at en mode=manual (bug critico prod v1.15.0-).

import os
os.environ.setdefault("OPENAI_API_KEY", "test-dummy")
os.environ.setdefault("OPENROUTER_API_KEY", "test-dummy")
os.environ["TAKEOVER_URL_BASE"] = "http://takeover.test"

import asyncio
import importlib
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset():
    from agent import takeover
    importlib.reload(takeover)
    yield


def _mock_response(status_code=200, json_body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = ""
    resp.json = MagicMock(return_value=json_body or {})
    return resp


def _run_poll(json_body):
    """Corre _poll_chat con un body simulado del plugin."""
    from agent import takeover
    mock_response = _mock_response(200, json_body)
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)
    with patch("agent.takeover.httpx.AsyncClient", return_value=mock_client):
        return asyncio.run(takeover._poll_chat("chat_test@c.us"))


def test_manual_con_expires_at_valido_se_respeta():
    """Path canonico: plugin devuelve expires_at ISO, se usa tal cual."""
    future_iso = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    entry = _run_poll({"mode": "manual", "expires_at": future_iso})
    assert entry is not None
    assert entry.mode == "manual"
    assert entry.expires_at is not None
    # Debe estar cerca del future_iso (no del fallback 40min)
    diff = abs((entry.expires_at - datetime.now(timezone.utc)).total_seconds())
    assert 25 * 60 < diff < 35 * 60  # entre 25 y 35 min


def test_manual_sin_expires_at_fallback_40min():
    """Bug fix: plugin devuelve expires_at=null → fallback a MANUAL_FALLBACK_TTL_MIN."""
    from agent import takeover
    entry = _run_poll({"mode": "manual", "expires_at": None})
    assert entry is not None
    assert entry.mode == "manual"  # NO degradar a auto
    assert entry.expires_at is not None
    diff = (entry.expires_at - datetime.now(timezone.utc)).total_seconds()
    expected = takeover.MANUAL_FALLBACK_TTL_MIN * 60
    # Tolerancia 5s por latencia del test
    assert abs(diff - expected) < 5


def test_manual_sin_campo_expires_at_fallback_40min():
    """Caso similar: expires_at ausente del dict."""
    from agent import takeover
    entry = _run_poll({"mode": "manual"})
    assert entry is not None
    assert entry.mode == "manual"
    assert entry.expires_at is not None
    diff = (entry.expires_at - datetime.now(timezone.utc)).total_seconds()
    assert abs(diff - takeover.MANUAL_FALLBACK_TTL_MIN * 60) < 5


def test_manual_expires_at_string_invalido_fallback():
    """Si expires_at viene malformado, tambien fallback (no degradar a auto)."""
    from agent import takeover
    entry = _run_poll({"mode": "manual", "expires_at": "no-es-una-fecha"})
    assert entry is not None
    assert entry.mode == "manual"
    assert entry.expires_at is not None


def test_auto_no_setea_expires_at():
    """Path auto: expires_at debe seguir siendo None (backward compat)."""
    entry = _run_poll({"mode": "auto"})
    assert entry is not None
    assert entry.mode == "auto"
    assert entry.expires_at is None


def test_is_chat_in_manual_mode_devuelve_true_con_fallback():
    """Integracion: con el fix, un chat en manual sin expires_at retorna True."""
    from agent import takeover
    # Simular la respuesta real del plugin
    entry_from_poll = _run_poll({"mode": "manual", "expires_at": None})
    takeover._cache["chat_test@c.us"] = entry_from_poll
    result = asyncio.run(takeover.is_chat_in_manual_mode("chat_test@c.us"))
    assert result is True
