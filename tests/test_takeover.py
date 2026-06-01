# tests/test_takeover.py — URL derivation + is_manual_takeover GET behavior

import asyncio
import importlib
import os
from unittest.mock import patch, AsyncMock, MagicMock


def _reload_takeover_with_env(env: dict):
    from agent import takeover
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    importlib.reload(takeover)
    return takeover


def _mock_async_client(status_code: int, body: dict | None = None):
    response = MagicMock()
    response.status_code = status_code
    response.json = MagicMock(return_value=body or {})
    response.text = "" if body is None else str(body)

    async_client = MagicMock()
    async_client.__aenter__ = AsyncMock(return_value=async_client)
    async_client.__aexit__ = AsyncMock(return_value=None)
    async_client.get = AsyncMock(return_value=response)
    async_client.post = AsyncMock(return_value=response)
    return async_client, response


def test_url_from_takeover_url_base():
    takeover = _reload_takeover_with_env({
        "TAKEOVER_URL_BASE": "https://example.com/wp-json/gowap/v1/takeover/aaa",
        "CONFIG_URL": None,
    })
    assert takeover._resolve_takeover_base() == "https://example.com/wp-json/gowap/v1/takeover/aaa"


def test_url_from_config_url_fallback():
    takeover = _reload_takeover_with_env({
        "TAKEOVER_URL_BASE": "",
        "CONFIG_URL": "https://example.com/wp-json/gowap/v1/config/" + "a" * 64,
    })
    expected = "https://example.com/wp-json/gowap/v1/takeover/" + "a" * 64
    assert takeover._resolve_takeover_base() == expected


def test_url_empty_when_no_env():
    takeover = _reload_takeover_with_env({"TAKEOVER_URL_BASE": "", "CONFIG_URL": ""})
    assert takeover._resolve_takeover_base() == ""


def test_is_manual_false_when_no_url():
    takeover = _reload_takeover_with_env({"TAKEOVER_URL_BASE": "", "CONFIG_URL": ""})
    result = asyncio.run(takeover.is_manual_takeover("5491155@c.us"))
    assert result is False


def test_is_manual_true_on_response_manual():
    takeover = _reload_takeover_with_env({
        "TAKEOVER_URL_BASE": "https://example.com/wp-json/gowap/v1/takeover/aaa",
        "CONFIG_URL": None,
    })
    client, _ = _mock_async_client(
        200,
        {"mode": "manual", "expires_at": "2099-01-01T00:00:00Z"},
    )
    with patch("agent.takeover.httpx.AsyncClient", return_value=client):
        result = asyncio.run(takeover.is_manual_takeover("5491155@c.us"))
    assert result is True


def test_is_manual_false_on_response_auto():
    takeover = _reload_takeover_with_env({
        "TAKEOVER_URL_BASE": "https://example.com/wp-json/gowap/v1/takeover/aaa",
        "CONFIG_URL": None,
    })
    client, _ = _mock_async_client(200, {"mode": "auto"})
    with patch("agent.takeover.httpx.AsyncClient", return_value=client):
        result = asyncio.run(takeover.is_manual_takeover("5491155@c.us"))
    assert result is False


def test_is_manual_false_on_404():
    takeover = _reload_takeover_with_env({
        "TAKEOVER_URL_BASE": "https://example.com/wp-json/gowap/v1/takeover/aaa",
        "CONFIG_URL": None,
    })
    client, _ = _mock_async_client(404, {})
    with patch("agent.takeover.httpx.AsyncClient", return_value=client):
        result = asyncio.run(takeover.is_manual_takeover("5491155@c.us"))
    assert result is False
