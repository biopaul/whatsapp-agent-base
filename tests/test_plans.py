# tests/test_plans.py — Tests del sistema de planes, limites y uso

"""
Prueba el comportamiento del agente ante:
- Agente pausado (soft pause)
- Reporte de uso con retry en 5xx
- Deteccion de modelo invalido
- Cambio de estado de pausa via /usage response
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# config_loader — is_agent_paused / set_paused_state
# ---------------------------------------------------------------------------

def test_set_paused_state_activa_pausa():
    from agent.config_loader import set_paused_state, is_agent_paused, _agent_paused
    import agent.config_loader as cl
    cl._agent_paused = False
    cl._pause_reason = None
    set_paused_state(True, "limite_mensajes")
    assert cl._agent_paused is True
    assert cl._pause_reason == "limite_mensajes"


def test_set_paused_state_desactiva_pausa():
    import agent.config_loader as cl
    cl._agent_paused = True
    cl._pause_reason = "limite_mensajes"
    from agent.config_loader import set_paused_state
    set_paused_state(False)
    assert cl._agent_paused is False
    assert cl._pause_reason is None


def test_get_ai_model_default():
    import agent.config_loader as cl
    cl._cache = None
    cl._cache_ts = 0.0
    with patch("agent.config_loader._fetch_remote", return_value=None):
        with patch.dict("os.environ", {"AI_MODEL": ""}, clear=False):
            from agent.config_loader import get_ai_model
            # force reload defaults
            cl._local_config = None
            model = get_ai_model()
    assert model.startswith("claude-")


def test_get_ai_model_valida_modelo_desconocido():
    import agent.config_loader as cl
    cl._cache = {"ai_model": "gpt-4-turbo"}
    cl._cache_ts = float("inf")
    from agent.config_loader import get_ai_model, _DEFAULT_MODEL
    model = get_ai_model()
    assert model == _DEFAULT_MODEL


def test_get_ai_model_acepta_modelo_valido():
    import agent.config_loader as cl
    cl._cache = {"ai_model": "claude-haiku-4-6"}
    cl._cache_ts = float("inf")
    from agent.config_loader import get_ai_model
    model = get_ai_model()
    assert model == "claude-haiku-4-6"


# ---------------------------------------------------------------------------
# usage_reporter — encolado y retry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_report_sin_url_no_encola():
    import agent.usage_reporter as ur
    ur.USAGE_URL = ""
    ur._bad_token = False
    ur._queue = asyncio.Queue()
    await ur.report("5491112345678@c.us")
    assert ur._queue.qsize() == 0


@pytest.mark.asyncio
async def test_report_encola_evento():
    import agent.usage_reporter as ur
    ur.USAGE_URL = "http://fake-url/usage/tok"
    ur._bad_token = False
    ur._queue = asyncio.Queue()
    await ur.report("5491112345678@c.us")
    assert ur._queue.qsize() == 1
    event = ur._queue.get_nowait()
    assert event["type"] == "message"
    assert event["chat_id"] == "5491112345678@c.us"


@pytest.mark.asyncio
async def test_report_bad_token_no_encola():
    import agent.usage_reporter as ur
    ur.USAGE_URL = "http://fake-url/usage/tok"
    ur._bad_token = True
    ur._queue = asyncio.Queue()
    await ur.report("5491112345678@c.us")
    assert ur._queue.qsize() == 0
    ur._bad_token = False  # cleanup


@pytest.mark.asyncio
async def test_send_retry_en_503():
    import agent.usage_reporter as ur
    ur.USAGE_URL = "http://fake-url/usage/tok"
    ur._bad_token = False
    ur._MAX_RETRIES = 2

    resp_503 = MagicMock()
    resp_503.status_code = 503
    resp_503.content = b""

    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.json.return_value = {"inserted": 1, "messages_used": 1, "chats_used": 1}

    call_count = {"n": 0}

    async def fake_post(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return resp_503
        return resp_200

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = fake_post

    with patch("agent.usage_reporter.asyncio.sleep", new=AsyncMock()):
        with patch("agent.usage_reporter.httpx.AsyncClient", return_value=mock_client):
            await ur._send_with_retry([{"type": "message", "chat_id": "x", "at": 0}])

    assert call_count["n"] == 2
    ur._MAX_RETRIES = 5  # restore


@pytest.mark.asyncio
async def test_send_404_deshabilita_reporter():
    import agent.usage_reporter as ur
    ur.USAGE_URL = "http://fake-url/usage/bad-token"
    ur._bad_token = False

    resp_404 = MagicMock()
    resp_404.status_code = 404
    resp_404.content = b'{"code":"invalid_token"}'
    resp_404.json.return_value = {"code": "invalid_token"}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=resp_404)

    with patch("agent.usage_reporter.httpx.AsyncClient", return_value=mock_client):
        await ur._send_with_retry([{"type": "message", "chat_id": "x", "at": 0}])

    assert ur._bad_token is True
    ur._bad_token = False  # cleanup


@pytest.mark.asyncio
async def test_send_activa_pausa_desde_respuesta():
    import agent.usage_reporter as ur
    import agent.config_loader as cl
    ur.USAGE_URL = "http://fake-url/usage/tok"
    ur._bad_token = False
    cl._agent_paused = False

    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.json.return_value = {
        "inserted": 1,
        "messages_used": 500,
        "chats_used": 10,
        "agent_paused": True,
        "pause_reason": "limite_mensajes_alcanzado",
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=resp_200)

    with patch("agent.usage_reporter.httpx.AsyncClient", return_value=mock_client):
        await ur._send_with_retry([{"type": "message", "chat_id": "x", "at": 0}])

    assert cl._agent_paused is True
    assert cl._pause_reason == "limite_mensajes_alcanzado"
    cl._agent_paused = False  # cleanup
