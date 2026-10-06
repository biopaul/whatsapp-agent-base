# tests/test_transcriber_retry.py — backoff/retry Whisper (429 + 5xx)

import os
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
# Base delay chico para que los tests corran rapido
os.environ["WHISPER_RETRY_BASE_DELAY_SEC"] = "0.01"
os.environ["WHISPER_MAX_RETRIES"] = "2"

import asyncio
import importlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reload():
    from agent import transcriber
    importlib.reload(transcriber)
    yield


def _resp(status: int, text: str = "", json_body: dict | None = None, headers: dict | None = None):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.headers = headers or {}
    if json_body is not None:
        r.json = MagicMock(return_value=json_body)
    else:
        r.json = MagicMock(side_effect=Exception("no json"))
    return r


def _patch_whisper(responses):
    """responses: lista de responses a devolver en orden."""
    from agent import transcriber
    call_mock = AsyncMock(side_effect=responses)
    return patch.object(transcriber, "_llamar_whisper", new=call_mock), call_mock


# --- Success path ---

def test_ok_primer_intento():
    from agent import transcriber
    patcher, call = _patch_whisper([_resp(200, text="hola mundo")])
    with patcher:
        result = asyncio.run(transcriber.transcribir_audio(b"audio"))
    assert result == "hola mundo"
    assert call.await_count == 1


def test_ok_tras_un_429_transitorio():
    from agent import transcriber
    patcher, call = _patch_whisper([
        _resp(429, text="rate limit", json_body={"error": {"type": "tokens"}}),
        _resp(200, text="hola"),
    ])
    with patcher:
        result = asyncio.run(transcriber.transcribir_audio(b"audio"))
    assert result == "hola"
    assert call.await_count == 2


def test_ok_tras_500():
    from agent import transcriber
    patcher, call = _patch_whisper([
        _resp(500, text="server error"),
        _resp(200, text="hola"),
    ])
    with patcher:
        result = asyncio.run(transcriber.transcribir_audio(b"audio"))
    assert result == "hola"
    assert call.await_count == 2


# --- Non-retryable paths ---

def test_insufficient_quota_no_reintenta():
    """429 con body insufficient_quota = saldo agotado, no retry."""
    from agent import transcriber
    patcher, call = _patch_whisper([
        _resp(429, json_body={"error": {"type": "insufficient_quota",
                                         "code": "insufficient_quota"}}),
    ])
    with patcher:
        result = asyncio.run(transcriber.transcribir_audio(b"audio"))
    assert result is None
    assert call.await_count == 1  # un solo intento


def test_401_fatal_no_reintenta():
    from agent import transcriber
    patcher, call = _patch_whisper([_resp(401, text="unauthorized")])
    with patcher:
        result = asyncio.run(transcriber.transcribir_audio(b"audio"))
    assert result is None
    assert call.await_count == 1


def test_400_fatal_no_reintenta():
    from agent import transcriber
    patcher, call = _patch_whisper([_resp(400, text="bad request")])
    with patcher:
        result = asyncio.run(transcriber.transcribir_audio(b"audio"))
    assert result is None
    assert call.await_count == 1


# --- Retries agotados ---

def test_429_retries_agotados():
    """Con WHISPER_MAX_RETRIES=2, hay 3 intentos totales. Si todos 429, falla."""
    from agent import transcriber
    r429 = _resp(429, json_body={"error": {"type": "tokens"}})
    patcher, call = _patch_whisper([r429, r429, r429])
    with patcher:
        result = asyncio.run(transcriber.transcribir_audio(b"audio"))
    assert result is None
    assert call.await_count == 3


def test_500_retries_agotados():
    from agent import transcriber
    r500 = _resp(500)
    patcher, call = _patch_whisper([r500, r500, r500])
    with patcher:
        result = asyncio.run(transcriber.transcribir_audio(b"audio"))
    assert result is None
    assert call.await_count == 3


# --- Retry-After header ---

def test_retry_after_header_se_honra():
    """Si el server devuelve Retry-After, se usa en vez del backoff exponencial."""
    from agent import transcriber
    patcher, call = _patch_whisper([
        _resp(429, json_body={"error": {"type": "tokens"}},
              headers={"Retry-After": "0.02"}),
        _resp(200, text="ok"),
    ])
    with patcher:
        result = asyncio.run(transcriber.transcribir_audio(b"audio"))
    assert result == "ok"
    assert call.await_count == 2


def test_retry_after_invalido_cae_a_backoff():
    """Retry-After con valor no numerico — cae al backoff exponencial."""
    from agent import transcriber
    patcher, call = _patch_whisper([
        _resp(429, json_body={"error": {"type": "tokens"}},
              headers={"Retry-After": "not-a-number"}),
        _resp(200, text="ok"),
    ])
    with patcher:
        result = asyncio.run(transcriber.transcribir_audio(b"audio"))
    assert result == "ok"


# --- Excepciones (red caida) ---

def test_exception_de_red_reintenta():
    from agent import transcriber
    import httpx as _httpx

    async def side_effect(*args, **kwargs):
        if side_effect.calls < 1:
            side_effect.calls += 1
            raise _httpx.NetworkError("conn reset")
        return _resp(200, text="ok")
    side_effect.calls = 0

    with patch.object(transcriber, "_llamar_whisper", new=side_effect):
        result = asyncio.run(transcriber.transcribir_audio(b"audio"))
    assert result == "ok"


# --- Sin API key ---

def test_sin_api_key_devuelve_none(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    from agent import transcriber
    importlib.reload(transcriber)
    result = asyncio.run(transcriber.transcribir_audio(b"audio"))
    assert result is None


# --- Helpers unit ---

def test_is_insufficient_quota_detecta_por_type():
    from agent.transcriber import _is_insufficient_quota
    r = _resp(429, json_body={"error": {"type": "insufficient_quota"}})
    assert _is_insufficient_quota(r) is True


def test_is_insufficient_quota_detecta_por_code():
    from agent.transcriber import _is_insufficient_quota
    r = _resp(429, json_body={"error": {"code": "insufficient_quota"}})
    assert _is_insufficient_quota(r) is True


def test_is_insufficient_quota_false_en_rate_limit_normal():
    from agent.transcriber import _is_insufficient_quota
    r = _resp(429, json_body={"error": {"type": "tokens",
                                          "code": "rate_limit_exceeded"}})
    assert _is_insufficient_quota(r) is False


def test_is_insufficient_quota_false_sin_json():
    from agent.transcriber import _is_insufficient_quota
    r = _resp(429, text="plain text")
    assert _is_insufficient_quota(r) is False


def test_delay_for_attempt_sin_header_backoff_exponencial():
    from agent.transcriber import _delay_for_attempt
    # Con base=0.01, attempt 1 → 0.01, attempt 2 → 0.02, attempt 3 → 0.04
    assert _delay_for_attempt(1, None) == pytest.approx(0.01)
    assert _delay_for_attempt(2, None) == pytest.approx(0.02)
    assert _delay_for_attempt(3, None) == pytest.approx(0.04)


def test_delay_for_attempt_con_retry_after():
    from agent.transcriber import _delay_for_attempt
    assert _delay_for_attempt(1, "2.5") == pytest.approx(2.5)
    assert _delay_for_attempt(5, "0.5") == pytest.approx(0.5)  # ignora attempt
