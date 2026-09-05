# tests/test_takeover_poll_expires_fallback.py — contrato del plugin post-v2.57.0
#
# v1.15.1 tenia fallback local (NOW + MANUAL_FALLBACK_TTL_MIN) para manual sin
# expires_at porque el plugin devolvia null. En v2.57.0 el plugin garantiza
# ISO valido en cada respuesta manual (calculado por request). El fallback
# se removio en v1.15.2 para no ocultar violaciones futuras del contrato.

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
    from agent import takeover
    mock_response = _mock_response(200, json_body)
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)
    with patch("agent.takeover.httpx.AsyncClient", return_value=mock_client):
        return asyncio.run(takeover._poll_chat("chat_test@c.us"))


# --- Path canonico (plugin v2.57.0+ compliant) ---

def test_manual_con_expires_at_iso_se_respeta():
    """Path esperado: plugin devuelve mode=manual con expires_at ISO."""
    future = datetime.now(timezone.utc) + timedelta(minutes=30)
    entry = _run_poll({"mode": "manual", "expires_at": future.isoformat()})
    assert entry is not None
    assert entry.mode == "manual"
    assert entry.expires_at is not None
    diff = abs((entry.expires_at - datetime.now(timezone.utc)).total_seconds())
    assert 25 * 60 < diff < 35 * 60


def test_manual_con_expires_at_z_suffix_se_respeta():
    """Compat: ISO con sufijo Z (UTC)."""
    future_iso = "2050-01-01T12:00:00Z"
    entry = _run_poll({"mode": "manual", "expires_at": future_iso})
    assert entry is not None
    assert entry.mode == "manual"
    assert entry.expires_at is not None
    assert entry.expires_at.year == 2050


def test_auto_no_setea_expires_at():
    """Path auto: expires_at debe seguir siendo None."""
    entry = _run_poll({"mode": "auto"})
    assert entry is not None
    assert entry.mode == "auto"
    assert entry.expires_at is None


def test_auto_con_expires_at_ignorado():
    """Si el plugin manda expires_at con mode=auto, lo ignoramos (auto es auto)."""
    entry = _run_poll({"mode": "auto", "expires_at": "2050-01-01T12:00:00Z"})
    assert entry is not None
    assert entry.mode == "auto"
    assert entry.expires_at is None


# --- Contract violation del plugin: manual sin ISO valido ---

def test_manual_sin_expires_at_downgrade_a_auto_con_warning(caplog):
    """Contract violation: mode=manual pero expires_at=null.

    v1.15.1 hacia fallback +40min local. Desde v1.15.2 lo tratamos como
    auto y logueamos WARNING para detectar el bug del plugin.
    """
    import logging
    with caplog.at_level(logging.WARNING, logger="agentkit"):
        entry = _run_poll({"mode": "manual", "expires_at": None})
    assert entry is not None
    assert entry.mode == "auto"  # downgrade
    assert entry.expires_at is None
    assert any(
        "manual con expires_at invalido" in r.message and "tratando como auto" in r.message
        for r in caplog.records
    )


def test_manual_sin_campo_expires_at_downgrade_a_auto(caplog):
    """Similar: expires_at ausente del dict → downgrade + WARNING."""
    import logging
    with caplog.at_level(logging.WARNING, logger="agentkit"):
        entry = _run_poll({"mode": "manual"})
    assert entry is not None
    assert entry.mode == "auto"


def test_manual_expires_at_malformado_downgrade(caplog):
    """Similar: expires_at con string no ISO → downgrade."""
    import logging
    with caplog.at_level(logging.WARNING, logger="agentkit"):
        entry = _run_poll({"mode": "manual", "expires_at": "no-es-una-fecha"})
    assert entry is not None
    assert entry.mode == "auto"


# --- Integracion: is_chat_in_manual_mode con path canonico ---

def test_is_chat_in_manual_mode_true_con_expires_at_valido():
    """Con ISO valido en la respuesta, is_chat_in_manual_mode retorna True."""
    from agent import takeover
    future = datetime.now(timezone.utc) + timedelta(minutes=30)
    takeover._cache["chat_test@c.us"] = takeover.TakeoverEntry(
        mode="manual", expires_at=future
    )
    result = asyncio.run(takeover.is_chat_in_manual_mode("chat_test@c.us"))
    assert result is True


def test_is_chat_in_manual_mode_false_sin_expires_at_valido():
    """Cache con manual + expires_at=None (raro pero posible) → False (defensivo)."""
    from agent import takeover
    takeover._cache["chat_test@c.us"] = takeover.TakeoverEntry(
        mode="manual", expires_at=None
    )
    result = asyncio.run(takeover.is_chat_in_manual_mode("chat_test@c.us"))
    assert result is False
