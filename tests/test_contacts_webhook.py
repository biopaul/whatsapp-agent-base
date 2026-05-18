"""Tests para contacts_webhook: touch + filtros + fail-silent."""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock


def _make_response(status: int, json_data=None):
    class R:
        def __init__(self):
            self.status_code = status
            self._data = json_data
        def json(self):
            return self._data
        @property
        def text(self):
            return str(self._data)
    return R()


@pytest.fixture
def reset_module(monkeypatch):
    monkeypatch.delenv("CONTACTS_URL_BASE", raising=False)
    import importlib
    from agent import contacts_webhook
    importlib.reload(contacts_webhook)
    yield contacts_webhook


@pytest.fixture
def module_with_url(monkeypatch):
    monkeypatch.setenv("CONTACTS_URL_BASE", "http://wp.test/wp-json/gowap/v1/contacts/tok123")
    import importlib
    from agent import contacts_webhook
    importlib.reload(contacts_webhook)
    yield contacts_webhook


def test_should_touch_chat_id_individual():
    from agent.contacts_webhook import should_touch_chat_id
    assert should_touch_chat_id("5491172320998@c.us") is True


def test_should_touch_chat_id_skipea_grupos():
    from agent.contacts_webhook import should_touch_chat_id
    assert should_touch_chat_id("123456789-987654321@g.us") is False


def test_should_touch_chat_id_skipea_broadcast():
    from agent.contacts_webhook import should_touch_chat_id
    assert should_touch_chat_id("status@broadcast") is False


def test_should_touch_chat_id_skipea_vacio():
    from agent.contacts_webhook import should_touch_chat_id
    assert should_touch_chat_id("") is False
    assert should_touch_chat_id(None) is False


@pytest.mark.asyncio
async def test_touch_noop_si_url_vacia(reset_module):
    # No debe hacer nada (ni levantar) si CONTACTS_URL_BASE esta vacio
    await reset_module.touch_contact(chat_id="123@c.us", direction="in")


@pytest.mark.asyncio
async def test_touch_skipea_chat_no_individual(module_with_url):
    calls = {"n": 0}

    async def fake_post(self, url, *args, **kwargs):
        calls["n"] += 1
        return _make_response(200, {"ok": True})

    with patch("httpx.AsyncClient.post", new=fake_post):
        await module_with_url.touch_contact(chat_id="g-123@g.us", direction="in")
    assert calls["n"] == 0  # nunca llamo a la red


@pytest.mark.asyncio
async def test_touch_envia_payload_correcto(module_with_url):
    captured = {}

    async def fake_post(self, url, *args, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return _make_response(200, {"ok": True, "contact_id": 42})

    with patch("httpx.AsyncClient.post", new=fake_post):
        await module_with_url.touch_contact(
            chat_id="5491172320998@c.us",
            direction="in",
            name="Juan",
            preview="Hola que tal",
        )

    assert captured["url"].endswith("/touch")
    assert captured["json"]["chat_id"] == "5491172320998@c.us"
    assert captured["json"]["direction"] == "in"
    assert captured["json"]["name"] == "Juan"
    assert captured["json"]["last_message_preview"] == "Hola que tal"
    assert "timestamp" in captured["json"]


@pytest.mark.asyncio
async def test_touch_recorta_preview_a_200_chars(module_with_url):
    captured = {}

    async def fake_post(self, url, *args, **kwargs):
        captured["json"] = kwargs.get("json")
        return _make_response(200, {"ok": True})

    long_text = "a" * 500
    with patch("httpx.AsyncClient.post", new=fake_post):
        await module_with_url.touch_contact(
            chat_id="5491@c.us", direction="out", preview=long_text
        )
    assert len(captured["json"]["last_message_preview"]) == 200


@pytest.mark.asyncio
async def test_touch_omite_campos_none(module_with_url):
    captured = {}

    async def fake_post(self, url, *args, **kwargs):
        captured["json"] = kwargs.get("json")
        return _make_response(200, {"ok": True})

    with patch("httpx.AsyncClient.post", new=fake_post):
        await module_with_url.touch_contact(
            chat_id="5491@c.us", direction="in"
        )
    # name y preview no se envian si son None
    assert "name" not in captured["json"]
    assert "last_message_preview" not in captured["json"]
    # chat_id, direction, timestamp siempre presentes
    assert captured["json"]["chat_id"] == "5491@c.us"
    assert captured["json"]["direction"] == "in"
    assert "timestamp" in captured["json"]


@pytest.mark.asyncio
async def test_touch_fail_silent_en_red_error(module_with_url):
    async def fake_post(self, url, *args, **kwargs):
        import httpx as h
        raise h.ConnectError("boom")

    # No debe levantar
    with patch("httpx.AsyncClient.post", new=fake_post):
        await module_with_url.touch_contact(chat_id="5491@c.us", direction="in")


@pytest.mark.asyncio
async def test_touch_fail_silent_en_500(module_with_url):
    async def fake_post(self, url, *args, **kwargs):
        return _make_response(500, {"error": "boom"})

    with patch("httpx.AsyncClient.post", new=fake_post):
        await module_with_url.touch_contact(chat_id="5491@c.us", direction="in")


@pytest.mark.asyncio
async def test_touch_401_marca_token_invalido(module_with_url):
    """Tras 401, el modulo se short-circuitea hasta restart."""
    calls = {"n": 0}

    async def fake_post(self, url, *args, **kwargs):
        calls["n"] += 1
        return _make_response(401, {"code": "contacts_token_invalid"})

    with patch("httpx.AsyncClient.post", new=fake_post):
        await module_with_url.touch_contact(chat_id="5491@c.us", direction="in")
        await module_with_url.touch_contact(chat_id="5491@c.us", direction="out")
        await module_with_url.touch_contact(chat_id="5491@c.us", direction="in")

    assert calls["n"] == 1  # solo el primer call llega
