# tests/test_waha_parser.py — WAHA parsear_webhook: chat_id, source, media

import asyncio
from unittest.mock import AsyncMock, MagicMock

from agent.providers.waha import ProveedorWAHA


def _request(payload: dict, event: str = "message"):
    """Mock de Request FastAPI con body json."""
    req = MagicMock()
    req.json = AsyncMock(return_value={"event": event, "payload": payload})
    return req


def _parse(payload: dict):
    provider = ProveedorWAHA()
    return asyncio.run(provider.parsear_webhook(_request(payload)))


# --- Entrantes (fromMe=False) ---

def test_incoming_text_basic():
    msgs = _parse({
        "fromMe": False,
        "from": "5491155@c.us",
        "id": "abc",
        "body": "hola",
        "hasMedia": False,
    })
    assert len(msgs) == 1
    assert msgs[0].telefono == "5491155@c.us"
    assert msgs[0].texto == "hola"
    assert msgs[0].es_propio is False
    assert msgs[0].tiene_media is False


def test_incoming_normalizes_s_whatsapp_net():
    msgs = _parse({
        "fromMe": False,
        "from": "5491155@s.whatsapp.net",
        "id": "abc",
        "body": "hola",
    })
    assert msgs[0].telefono == "5491155@c.us"


# --- Salientes (fromMe=True) ---

def test_outgoing_source_api_skipped():
    """Eco WAHA del agente: source=api -> lista vacia."""
    msgs = _parse({
        "fromMe": True,
        "from": "agent@c.us",
        "to": "5491155@c.us",
        "id": "abc",
        "body": "respuesta del agente",
        "source": "api",
    })
    assert msgs == []


def test_outgoing_source_app_returns_message_for_takeover():
    """Humano desde WhatsApp Web/app: source=app -> retorna MensajeEntrante."""
    msgs = _parse({
        "fromMe": True,
        "from": "agent@c.us",
        "to": "5491155@c.us",
        "id": "abc",
        "body": "hola desde web",
        "source": "app",
    })
    assert len(msgs) == 1
    assert msgs[0].es_propio is True
    assert msgs[0].source == "app"
    assert msgs[0].telefono == "5491155@c.us"  # usa `to`, no `from`
    assert msgs[0].texto == "hola desde web"


def test_outgoing_chat_id_uses_chatId_when_present():
    msgs = _parse({
        "fromMe": True,
        "chatId": "5499999@c.us",
        "from": "agent@c.us",
        "to": "5491155@c.us",
        "id": "abc",
        "body": "x",
        "source": "app",
    })
    # chatId tiene prioridad sobre to.
    assert msgs[0].telefono == "5499999@c.us"


def test_outgoing_media_without_body_still_returns_for_takeover():
    msgs = _parse({
        "fromMe": True,
        "to": "5491155@c.us",
        "id": "abc",
        "body": "",
        "hasMedia": True,
        "source": "app",
    })
    assert len(msgs) == 1
    assert msgs[0].tiene_media is True
    assert msgs[0].es_propio is True


def test_outgoing_empty_no_source_no_media_returns_empty():
    """fromMe sin source, sin body, sin media -> nada que hacer."""
    msgs = _parse({
        "fromMe": True,
        "to": "5491155@c.us",
        "id": "abc",
        "body": "",
        "hasMedia": False,
    })
    assert msgs == []


def test_incoming_audio_keeps_audio_url():
    msgs = _parse({
        "fromMe": False,
        "from": "5491155@c.us",
        "id": "abc",
        "body": "",
        "hasMedia": True,
        "media": {"mimetype": "audio/ogg", "url": "https://w/audio.ogg"},
    })
    assert len(msgs) == 1
    assert msgs[0].audio_url
    assert msgs[0].tiene_media is True


def test_non_message_event_returns_empty():
    msgs = _parse(
        payload={"fromMe": False, "from": "x", "body": "y"},
    )
    # default event="message" -> tiene que procesar; chequeamos el caso negativo
    # con session.status:
    provider = ProveedorWAHA()
    req = MagicMock()
    req.json = AsyncMock(return_value={"event": "session.status", "payload": {}})
    out = asyncio.run(provider.parsear_webhook(req))
    assert out == []
