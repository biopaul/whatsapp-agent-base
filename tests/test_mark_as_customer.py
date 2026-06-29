"""Tests para contacts_webhook.mark_as_customer."""

import os
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_mark_customer.db")
os.environ.setdefault("OPENROUTER_API_KEY", "sk-or-test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")


def _resp(status: int, json_body: dict | None = None):
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=json_body or {})
    r.text = str(json_body or "")
    return r


@pytest.fixture
def cw(monkeypatch):
    """Carga contacts_webhook con CONTACTS_URL_BASE seteado y _token_invalid reseteado."""
    monkeypatch.setenv("CONTACTS_URL_BASE", "https://wp.test/wp-json/gowap/v1/contacts/abc123")
    import importlib
    from agent import contacts_webhook
    importlib.reload(contacts_webhook)
    yield contacts_webhook


@pytest.mark.asyncio
async def test_mark_as_customer_ok(cw):
    captured = {}

    async def fake_post(self, url, *args, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return _resp(200, {"ok": True, "customer_since": "2026-06-29 19:33:10"})

    with patch("httpx.AsyncClient.post", new=fake_post):
        ok = await cw.mark_as_customer("54911@c.us", is_customer=True, source="payment_receipt_image")

    assert ok is True
    assert captured["url"].endswith("/customer")
    assert captured["json"]["chat_id"] == "54911@c.us"
    assert captured["json"]["is_customer"] is True
    assert captured["json"]["source"] == "payment_receipt_image"


@pytest.mark.asyncio
async def test_mark_as_customer_revertir(cw):
    captured = {}

    async def fake_post(self, url, *args, **kwargs):
        captured["json"] = kwargs.get("json")
        return _resp(200, {"ok": True})

    with patch("httpx.AsyncClient.post", new=fake_post):
        ok = await cw.mark_as_customer("54911@c.us", is_customer=False)

    assert ok is True
    assert captured["json"]["is_customer"] is False
    assert "source" not in captured["json"]


@pytest.mark.asyncio
async def test_mark_as_customer_no_envia_si_chat_no_es_c_us(cw):
    """Grupos / broadcast no se marcan."""
    called = {"n": 0}

    async def fake_post(self, url, *args, **kwargs):
        called["n"] += 1
        return _resp(200)

    with patch("httpx.AsyncClient.post", new=fake_post):
        ok = await cw.mark_as_customer("12345@g.us")

    assert ok is False
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_mark_as_customer_no_envia_si_url_base_vacia(monkeypatch):
    monkeypatch.delenv("CONTACTS_URL_BASE", raising=False)
    import importlib
    from agent import contacts_webhook
    importlib.reload(contacts_webhook)

    called = {"n": 0}

    async def fake_post(self, url, *args, **kwargs):
        called["n"] += 1
        return _resp(200)

    with patch("httpx.AsyncClient.post", new=fake_post):
        ok = await contacts_webhook.mark_as_customer("54911@c.us")

    assert ok is False
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_mark_as_customer_401_deshabilita_modulo(cw):
    async def fake_post(self, url, *args, **kwargs):
        return _resp(401, {"code": "invalid_token"})

    with patch("httpx.AsyncClient.post", new=fake_post):
        ok1 = await cw.mark_as_customer("54911@c.us")
        # Segundo call: módulo deshabilitado, no debe pegarle al endpoint
        ok2 = await cw.mark_as_customer("54922@c.us")

    assert ok1 is False
    assert ok2 is False


@pytest.mark.asyncio
async def test_mark_as_customer_500_no_rompe(cw):
    async def fake_post(self, url, *args, **kwargs):
        return _resp(500, {"error": "boom"})

    with patch("httpx.AsyncClient.post", new=fake_post):
        ok = await cw.mark_as_customer("54911@c.us")

    assert ok is False


@pytest.mark.asyncio
async def test_mark_as_customer_error_red_no_rompe(cw):
    async def fake_post(self, url, *args, **kwargs):
        raise ConnectionError("network down")

    with patch("httpx.AsyncClient.post", new=fake_post):
        ok = await cw.mark_as_customer("54911@c.us")

    assert ok is False
