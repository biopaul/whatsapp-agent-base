"""Tests para tts_client (cliente ElevenLabs)."""

import pytest
from unittest.mock import patch


def _make_response(status: int, content: bytes = b"", text: str = ""):
    class R:
        def __init__(self):
            self.status_code = status
            self.content = content
            self.text = text or str(content)
    return R()


@pytest.fixture
def reset_module(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    import importlib
    from agent import tts_client
    importlib.reload(tts_client)
    yield tts_client


@pytest.fixture
def module_with_key(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-test")
    import importlib
    from agent import tts_client
    importlib.reload(tts_client)
    yield tts_client


@pytest.mark.asyncio
async def test_synthesize_noop_si_key_vacia(reset_module):
    result = await reset_module.synthesize("hola", voice_id="voice_x")
    assert result is None
    assert reset_module.last_error_reason() == "no_api_key"


@pytest.mark.asyncio
async def test_synthesize_ok_devuelve_mp3_bytes(module_with_key):
    fake_mp3 = b"FAKE_MP3_BYTES" * 50

    async def fake_post(self, url, *args, **kwargs):
        return _make_response(200, content=fake_mp3)

    with patch("httpx.AsyncClient.post", new=fake_post):
        result = await module_with_key.synthesize("hola mundo", voice_id="voice_x")
    assert result == fake_mp3
    assert module_with_key.last_error_reason() is None


@pytest.mark.asyncio
async def test_synthesize_401_marca_reason(module_with_key):
    async def fake_post(self, url, *args, **kwargs):
        return _make_response(401, text="unauthorized")

    with patch("httpx.AsyncClient.post", new=fake_post):
        result = await module_with_key.synthesize("hola", voice_id="voice_x")
    assert result is None
    assert module_with_key.last_error_reason() == "elevenlabs_401"


@pytest.mark.asyncio
async def test_synthesize_429_marca_reason(module_with_key):
    async def fake_post(self, url, *args, **kwargs):
        return _make_response(429, text="rate limited")

    with patch("httpx.AsyncClient.post", new=fake_post):
        result = await module_with_key.synthesize("hola", voice_id="voice_x")
    assert result is None
    assert module_with_key.last_error_reason() == "elevenlabs_429"


@pytest.mark.asyncio
async def test_synthesize_5xx_marca_reason(module_with_key):
    async def fake_post(self, url, *args, **kwargs):
        return _make_response(500, text="server error")

    with patch("httpx.AsyncClient.post", new=fake_post):
        result = await module_with_key.synthesize("hola", voice_id="voice_x")
    assert result is None
    assert module_with_key.last_error_reason() == "elevenlabs_5xx"


@pytest.mark.asyncio
async def test_synthesize_timeout_marca_reason(module_with_key):
    async def fake_post(self, url, *args, **kwargs):
        import httpx as h
        raise h.TimeoutException("timeout")

    with patch("httpx.AsyncClient.post", new=fake_post):
        result = await module_with_key.synthesize("hola", voice_id="voice_x")
    assert result is None
    assert module_with_key.last_error_reason() == "elevenlabs_timeout"


@pytest.mark.asyncio
async def test_synthesize_envia_payload_correcto(module_with_key):
    captured = {}

    async def fake_post(self, url, *args, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        captured["headers"] = kwargs.get("headers")
        return _make_response(200, content=b"mp3")

    with patch("httpx.AsyncClient.post", new=fake_post):
        await module_with_key.synthesize(
            "texto a sintetizar",
            voice_id="voice_abc",
            model="eleven_turbo_v2_5",
        )
    assert "voice_abc" in captured["url"]
    assert captured["json"]["text"] == "texto a sintetizar"
    assert captured["json"]["model_id"] == "eleven_turbo_v2_5"
    assert "output_format" in captured["json"]
    assert captured["headers"]["xi-api-key"] == "sk-test"


@pytest.mark.asyncio
async def test_synthesize_api_key_param_tiene_prioridad_sobre_env_var(module_with_key):
    """Si se pasa api_key explicito, gana sobre la env var."""
    captured = {}

    async def fake_post(self, url, *args, **kwargs):
        captured["headers"] = kwargs.get("headers")
        return _make_response(200, content=b"mp3")

    with patch("httpx.AsyncClient.post", new=fake_post):
        await module_with_key.synthesize(
            "hola", voice_id="v", api_key="sk-from-config"
        )
    # El env var era "sk-test" pero el param tiene prioridad
    assert captured["headers"]["xi-api-key"] == "sk-from-config"


@pytest.mark.asyncio
async def test_synthesize_usa_env_var_si_api_key_param_vacio(module_with_key):
    """Fallback a env var cuando no se pasa api_key (caso dev/local)."""
    captured = {}

    async def fake_post(self, url, *args, **kwargs):
        captured["headers"] = kwargs.get("headers")
        return _make_response(200, content=b"mp3")

    with patch("httpx.AsyncClient.post", new=fake_post):
        await module_with_key.synthesize("hola", voice_id="v")  # sin api_key
    assert captured["headers"]["xi-api-key"] == "sk-test"


@pytest.mark.asyncio
async def test_synthesize_api_key_param_funciona_sin_env_var(reset_module):
    """Sin env var, el api_key param solo es suficiente."""
    captured = {}

    async def fake_post(self, url, *args, **kwargs):
        captured["headers"] = kwargs.get("headers")
        return _make_response(200, content=b"mp3")

    with patch("httpx.AsyncClient.post", new=fake_post):
        result = await reset_module.synthesize(
            "hola", voice_id="v", api_key="sk-from-plugin"
        )
    assert result == b"mp3"
    assert captured["headers"]["xi-api-key"] == "sk-from-plugin"
