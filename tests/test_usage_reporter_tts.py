"""Tests para report_tts_used y report_tts_error en usage_reporter."""

import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def reset_reporter(monkeypatch):
    import importlib
    monkeypatch.setenv("USAGE_URL", "http://wp.test/usage/tok")
    from agent import usage_reporter
    importlib.reload(usage_reporter)
    yield usage_reporter


@pytest.mark.asyncio
async def test_report_tts_used_acumula_y_se_envia(reset_reporter):
    """report_tts_used acumula seconds y se incluye en el proximo batch enviado."""
    reset_reporter.report_tts_used(5)
    reset_reporter.report_tts_used(3)

    captured = {}

    async def fake_post(self, url, json=None, **kwargs):
        captured["payload"] = json
        return type('R', (), {
            'status_code': 200, 'text': 'ok', 'content': b'ok',
            'json': lambda self=None: {'inserted': 0},
        })()

    with patch("httpx.AsyncClient.post", new=fake_post):
        await reset_reporter._send_with_retry([
            {"type": "message", "chat_id": "1@c.us", "at": 0}
        ])

    payload = captured["payload"]
    assert payload.get("tts_seconds_used") == 8


@pytest.mark.asyncio
async def test_report_tts_used_no_se_envia_si_es_cero(reset_reporter):
    """Si no hubo TTS, el campo no aparece en el payload."""
    captured = {}

    async def fake_post(self, url, json=None, **kwargs):
        captured["payload"] = json
        return type('R', (), {
            'status_code': 200, 'text': 'ok', 'content': b'ok',
            'json': lambda self=None: {'inserted': 0},
        })()

    with patch("httpx.AsyncClient.post", new=fake_post):
        await reset_reporter._send_with_retry([
            {"type": "message", "chat_id": "1@c.us", "at": 0}
        ])

    payload = captured["payload"]
    assert "tts_seconds_used" not in payload


@pytest.mark.asyncio
async def test_report_tts_used_se_resetea_tras_envio(reset_reporter):
    """Tras enviar exitosamente, el acumulador vuelve a 0."""
    reset_reporter.report_tts_used(10)

    async def fake_post(self, url, json=None, **kwargs):
        return type('R', (), {
            'status_code': 200, 'text': 'ok', 'content': b'ok',
            'json': lambda self=None: {'inserted': 0},
        })()

    with patch("httpx.AsyncClient.post", new=fake_post):
        await reset_reporter._send_with_retry([])

    captured = {}

    async def fake_post2(self, url, json=None, **kwargs):
        captured["payload"] = json
        return type('R', (), {
            'status_code': 200, 'text': 'ok', 'content': b'ok',
            'json': lambda self=None: {'inserted': 0},
        })()

    with patch("httpx.AsyncClient.post", new=fake_post2):
        await reset_reporter._send_with_retry([])

    assert "tts_seconds_used" not in captured.get("payload", {})


@pytest.mark.asyncio
async def test_report_tts_error_se_incluye_en_payload(reset_reporter):
    reset_reporter.report_tts_error("chat_x@c.us", "elevenlabs_5xx")

    captured = {}

    async def fake_post(self, url, json=None, **kwargs):
        captured["payload"] = json
        return type('R', (), {
            'status_code': 200, 'text': 'ok', 'content': b'ok',
            'json': lambda self=None: {'inserted': 0},
        })()

    with patch("httpx.AsyncClient.post", new=fake_post):
        await reset_reporter._send_with_retry([])

    errors = captured["payload"].get("tts_errors")
    assert isinstance(errors, list)
    assert len(errors) == 1
    assert errors[0]["chat_id"] == "chat_x@c.us"
    assert errors[0]["reason"] == "elevenlabs_5xx"
    assert "at" in errors[0]
