# tests/test_broadcast_guard.py — defensa contra fuga a status@broadcast

import os
os.environ.setdefault("OPENAI_API_KEY", "test-dummy")
os.environ.setdefault("OPENROUTER_API_KEY", "test-dummy")
os.environ.setdefault("WAHA_BASE_URL", "http://waha.test")

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.providers.waha import ProveedorWAHA, _es_chat_broadcast


def _request(payload: dict, event: str = "message"):
    req = MagicMock()
    req.json = AsyncMock(return_value={"event": event, "payload": payload})
    return req


def _parse(payload: dict):
    provider = ProveedorWAHA()
    return asyncio.run(provider.parsear_webhook(_request(payload)))


# --- Helper ---

def test_es_chat_broadcast_status():
    assert _es_chat_broadcast("status@broadcast") is True


def test_es_chat_broadcast_lista():
    assert _es_chat_broadcast("123456@broadcast") is True


def test_es_chat_broadcast_individual():
    assert _es_chat_broadcast("5491155@c.us") is False


def test_es_chat_broadcast_grupo():
    assert _es_chat_broadcast("120363000000000000@g.us") is False


def test_es_chat_broadcast_vacio():
    assert _es_chat_broadcast("") is False


# --- Parser: descartar eventos broadcast ---

def test_parser_descarta_status_broadcast_en_chatId():
    msgs = _parse({
        "fromMe": False,
        "chatId": "status@broadcast",
        "from": "5491155@c.us",
        "id": "abc",
        "body": "hola",
    })
    assert msgs == []


def test_parser_descarta_status_broadcast_en_from():
    msgs = _parse({
        "fromMe": False,
        "from": "status@broadcast",
        "id": "abc",
        "body": "hola",
    })
    assert msgs == []


def test_parser_descarta_broadcast_list():
    msgs = _parse({
        "fromMe": False,
        "chatId": "999@broadcast",
        "id": "abc",
        "body": "hola",
    })
    assert msgs == []


def test_parser_acepta_chat_normal():
    msgs = _parse({
        "fromMe": False,
        "chatId": "5491155@c.us",
        "from": "5491155@c.us",
        "id": "abc",
        "body": "hola",
    })
    assert len(msgs) == 1
    assert msgs[0].telefono == "5491155@c.us"


# --- Guards en métodos de envío ---

def _post_mock(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = ""
    resp.json = MagicMock(return_value=json_data or {})
    return resp


def test_enviar_mensaje_bloqueado_a_broadcast():
    provider = ProveedorWAHA()
    with patch("agent.providers.waha.httpx.AsyncClient") as mock_client:
        result = asyncio.run(provider.enviar_mensaje("status@broadcast", "hola"))
        assert result is False
        mock_client.assert_not_called()


def test_enviar_mensaje_returning_id_bloqueado_a_broadcast():
    provider = ProveedorWAHA()
    with patch("agent.providers.waha.httpx.AsyncClient") as mock_client:
        result = asyncio.run(
            provider.enviar_mensaje_returning_id("status@broadcast", "hola")
        )
        assert result is None
        mock_client.assert_not_called()


def test_enviar_archivo_bloqueado_a_broadcast():
    provider = ProveedorWAHA()
    with patch("agent.providers.waha.httpx.AsyncClient") as mock_client:
        result = asyncio.run(
            provider.enviar_archivo("status@broadcast", "http://x/y.pdf", "y.pdf")
        )
        assert result is False
        mock_client.assert_not_called()


def test_enviar_buttons_bloqueado_a_broadcast():
    provider = ProveedorWAHA()
    with patch("agent.providers.waha.httpx.AsyncClient") as mock_client:
        ok, status, mid = asyncio.run(
            provider.enviar_buttons(
                "status@broadcast", "hola", [{"id": "1", "title": "A"}]
            )
        )
        assert ok is False
        assert mid is None
        mock_client.assert_not_called()


def test_enviar_list_bloqueado_a_broadcast():
    provider = ProveedorWAHA()
    with patch("agent.providers.waha.httpx.AsyncClient") as mock_client:
        ok, status, mid = asyncio.run(
            provider.enviar_list("status@broadcast", "hola", "Ver", [])
        )
        assert ok is False
        assert mid is None
        mock_client.assert_not_called()


def test_enviar_audio_bloqueado_a_broadcast():
    provider = ProveedorWAHA()
    with patch("agent.providers.waha.httpx.AsyncClient") as mock_client:
        result = asyncio.run(provider.enviar_audio("status@broadcast", b"\x00\x01"))
        assert result is None
        mock_client.assert_not_called()


def test_marcar_leido_no_llama_broadcast():
    provider = ProveedorWAHA()
    with patch("agent.providers.waha.httpx.AsyncClient") as mock_client:
        asyncio.run(provider.marcar_leido("status@broadcast"))
        mock_client.assert_not_called()


def test_reaccionar_no_llama_broadcast():
    provider = ProveedorWAHA()
    with patch("agent.providers.waha.httpx.AsyncClient") as mock_client:
        asyncio.run(provider.reaccionar("status@broadcast", "mid", "❤️"))
        mock_client.assert_not_called()


def test_set_presence_no_llama_broadcast():
    provider = ProveedorWAHA()
    with patch("agent.providers.waha.httpx.AsyncClient") as mock_client:
        asyncio.run(provider._set_presence("status@broadcast", "typing"))
        mock_client.assert_not_called()
