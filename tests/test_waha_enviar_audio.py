"""Tests para enviar_audio del provider WAHA (JSON + base64)."""

import base64
import os
import pytest
from unittest.mock import patch


def _make_response(status: int, json_data=None):
    class R:
        def __init__(self):
            self.status_code = status
            self._data = json_data or {}
        def json(self):
            return self._data
        @property
        def text(self):
            return str(self._data)
    return R()


@pytest.fixture
def waha_provider(monkeypatch):
    monkeypatch.setenv("WAHA_BASE_URL", "http://waha.test")
    monkeypatch.setenv("WAHA_SESSION", "default")
    monkeypatch.setenv("WAHA_API_KEY", "test-key")
    import importlib
    from agent.providers import waha
    importlib.reload(waha)
    yield waha.ProveedorWAHA()


@pytest.mark.asyncio
async def test_enviar_audio_envia_json_con_base64(waha_provider):
    """El payload debe ser JSON con session, chatId y file.data en base64."""
    audio = b"FAKE_OGG_BYTES" * 20
    captured = {}

    async def fake_post(self, url, *args, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        captured["data"] = kwargs.get("data")
        captured["files"] = kwargs.get("files")
        return _make_response(200, {"id": "msg_001"})

    with patch("httpx.AsyncClient.post", new=fake_post):
        result = await waha_provider.enviar_audio("54911@c.us", audio)

    assert result == "msg_001"
    assert captured["url"].endswith("/api/sendVoice")
    # Debe ser JSON, NO multipart
    assert captured["json"] is not None
    assert captured["data"] is None
    assert captured["files"] is None
    # Campos requeridos
    assert captured["json"]["session"] == "default"
    assert captured["json"]["chatId"] == "54911@c.us"
    assert "file" in captured["json"]
    assert captured["json"]["file"]["mimetype"] == "audio/ogg; codecs=opus"
    # base64 decode debe recuperar los bytes originales
    decoded = base64.b64decode(captured["json"]["file"]["data"])
    assert decoded == audio


@pytest.mark.asyncio
async def test_enviar_audio_retorna_none_en_400(waha_provider):
    """HTTP 400 retorna None (el caller lo trata como waha_sendvoice_failed)."""
    async def fake_post(self, url, *args, **kwargs):
        return _make_response(400, {"message": "bad request"})

    with patch("httpx.AsyncClient.post", new=fake_post):
        result = await waha_provider.enviar_audio("54911@c.us", b"audio")

    assert result is None


@pytest.mark.asyncio
async def test_enviar_audio_retorna_none_si_base_url_vacia(monkeypatch):
    monkeypatch.delenv("WAHA_BASE_URL", raising=False)
    monkeypatch.setenv("WAHA_SESSION", "default")
    import importlib
    from agent.providers import waha
    importlib.reload(waha)
    p = waha.ProveedorWAHA()
    result = await p.enviar_audio("54911@c.us", b"audio")
    assert result is None


@pytest.mark.asyncio
async def test_enviar_audio_ok_no_id_si_response_sin_id(waha_provider):
    async def fake_post(self, url, *args, **kwargs):
        return _make_response(200, {"status": "sent"})

    with patch("httpx.AsyncClient.post", new=fake_post):
        result = await waha_provider.enviar_audio("54911@c.us", b"audio")

    assert result == "ok_no_id"
