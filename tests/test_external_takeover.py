# tests/test_external_takeover.py — should_register + register_manual_takeover + outbound tracker

import asyncio
import importlib
import os
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock, MagicMock


def _reload_takeover_with_env(env: dict):
    from agent import takeover, outbound
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    importlib.reload(takeover)
    importlib.reload(outbound)
    return takeover, outbound


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


def _msg(es_propio=True, source="", telefono="5491155@c.us", texto="", tiene_media=False):
    return SimpleNamespace(
        es_propio=es_propio,
        source=source,
        telefono=telefono,
        texto=texto,
        tiene_media=tiene_media,
    )


# --- should_register_external_takeover ---

def test_should_register_true_when_source_app():
    takeover, outbound = _reload_takeover_with_env({
        "TAKEOVER_URL_BASE": "https://example.com/wp-json/gowap/v1/takeover/aaa",
    })
    outbound.clear_outbound()
    assert takeover.should_register_external_takeover(_msg(source="app", texto="hola")) is True


def test_should_register_false_when_source_api():
    takeover, outbound = _reload_takeover_with_env({
        "TAKEOVER_URL_BASE": "https://example.com/wp-json/gowap/v1/takeover/aaa",
    })
    outbound.clear_outbound()
    assert takeover.should_register_external_takeover(_msg(source="api", texto="eco")) is False


def test_should_register_false_when_outbound_recent_and_source_empty():
    takeover, outbound = _reload_takeover_with_env({
        "TAKEOVER_URL_BASE": "https://example.com/wp-json/gowap/v1/takeover/aaa",
    })
    outbound.clear_outbound()
    outbound.register_agent_outbound("5491155@c.us")
    assert takeover.should_register_external_takeover(_msg(source="", texto="eco")) is False


def test_should_register_true_when_no_outbound_and_text():
    takeover, outbound = _reload_takeover_with_env({
        "TAKEOVER_URL_BASE": "https://example.com/wp-json/gowap/v1/takeover/aaa",
    })
    outbound.clear_outbound()
    assert takeover.should_register_external_takeover(_msg(source="", texto="hola")) is True


def test_should_register_true_when_media_without_text():
    takeover, outbound = _reload_takeover_with_env({
        "TAKEOVER_URL_BASE": "https://example.com/wp-json/gowap/v1/takeover/aaa",
    })
    outbound.clear_outbound()
    assert takeover.should_register_external_takeover(
        _msg(source="", texto="", tiene_media=True)
    ) is True


def test_should_register_false_when_not_es_propio():
    takeover, outbound = _reload_takeover_with_env({
        "TAKEOVER_URL_BASE": "https://example.com/wp-json/gowap/v1/takeover/aaa",
    })
    outbound.clear_outbound()
    assert takeover.should_register_external_takeover(
        _msg(es_propio=False, source="app", texto="hola")
    ) is False


# --- register_manual_takeover ---

def test_register_manual_posts_and_updates_cache():
    takeover, outbound = _reload_takeover_with_env({
        "TAKEOVER_URL_BASE": "https://example.com/wp-json/gowap/v1/takeover/aaa",
        "CONFIG_URL": None,
    })
    client, _ = _mock_async_client(
        200,
        {"mode": "manual", "expires_at": "2099-01-01T00:00:00Z"},
    )
    with patch("agent.takeover.httpx.AsyncClient", return_value=client):
        ok = asyncio.run(takeover.register_manual_takeover("5491155@c.us"))
    assert ok is True
    # POST hit el endpoint /manual.
    client.post.assert_called_once()
    call_url = client.post.call_args[0][0]
    assert call_url.endswith("/manual")
    # Cache local refleja manual.
    assert "5491155@c.us" in takeover._cache
    assert takeover._cache["5491155@c.us"].mode == "manual"


def test_register_manual_false_when_no_url():
    takeover, _ = _reload_takeover_with_env({
        "TAKEOVER_URL_BASE": "",
        "CONFIG_URL": "",
    })
    ok = asyncio.run(takeover.register_manual_takeover("5491155@c.us"))
    assert ok is False


def test_register_manual_false_on_http_error():
    takeover, _ = _reload_takeover_with_env({
        "TAKEOVER_URL_BASE": "https://example.com/wp-json/gowap/v1/takeover/aaa",
        "CONFIG_URL": None,
    })
    client, _ = _mock_async_client(500, {})
    with patch("agent.takeover.httpx.AsyncClient", return_value=client):
        ok = asyncio.run(takeover.register_manual_takeover("5491155@c.us"))
    assert ok is False


# --- outbound tracker ---

def test_outbound_register_and_recent():
    from agent import outbound
    outbound.clear_outbound()
    outbound.register_agent_outbound("chat1")
    assert outbound.is_recent_agent_outbound("chat1") is True
    assert outbound.is_recent_agent_outbound("chat_other") is False


def test_outbound_window_expires():
    from agent import outbound
    import time
    outbound.clear_outbound()
    outbound.register_agent_outbound("chat1")
    # Forzar timestamp viejo.
    outbound._recent["chat1"] = time.time() - (outbound.WINDOW_SEC + 5)
    assert outbound.is_recent_agent_outbound("chat1") is False
