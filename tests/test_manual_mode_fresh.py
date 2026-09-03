# tests/test_manual_mode_fresh.py — bypass de cache en checkpoints criticos

import os
os.environ.setdefault("OPENAI_API_KEY", "test-dummy")
os.environ.setdefault("OPENROUTER_API_KEY", "test-dummy")
os.environ["TAKEOVER_URL_BASE"] = "http://takeover.test"

import asyncio
import importlib
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clean_takeover():
    from agent import takeover
    importlib.reload(takeover)
    yield


def _entry(mode: str, polled_seconds_ago: int = 0, expires_in_min: int = 40):
    from agent.takeover import TakeoverEntry
    now = datetime.now(timezone.utc)
    return TakeoverEntry(
        mode=mode,
        expires_at=now + timedelta(minutes=expires_in_min) if mode == "manual" else None,
        last_polled=now - timedelta(seconds=polled_seconds_ago),
    )


def test_manual_cacheado_no_repolea_ni_con_fresh():
    """Si esta manual con expires_at futuro, es fresca por definicion — no repolea."""
    from agent import takeover

    takeover._cache["chat1"] = _entry("manual", polled_seconds_ago=0, expires_in_min=30)
    with patch.object(takeover, "_poll_chat", new=AsyncMock()) as mock_poll:
        result = asyncio.run(takeover.is_chat_in_manual_mode("chat1", fresh=True))
        assert result is True
        mock_poll.assert_not_awaited()


def test_auto_cacheado_reciente_sin_fresh_no_repolea():
    """Comportamiento clasico: cache auto < TTL, retorna False sin repollear."""
    from agent import takeover

    takeover._cache["chat1"] = _entry("auto", polled_seconds_ago=5)
    with patch.object(takeover, "_poll_chat", new=AsyncMock()) as mock_poll:
        result = asyncio.run(takeover.is_chat_in_manual_mode("chat1", fresh=False))
        assert result is False
        mock_poll.assert_not_awaited()


def test_auto_cacheado_reciente_con_fresh_repolea():
    """El bug fix: fresh=True bypasea el TTL de auto y fuerza re-poll."""
    from agent import takeover

    takeover._cache["chat1"] = _entry("auto", polled_seconds_ago=5)
    # El plugin ahora reporta manual (humano toco el toggle)
    nueva_entry = _entry("manual", polled_seconds_ago=0, expires_in_min=40)
    with patch.object(takeover, "_poll_chat",
                       new=AsyncMock(return_value=nueva_entry)) as mock_poll:
        result = asyncio.run(takeover.is_chat_in_manual_mode("chat1", fresh=True))
        assert result is True
        mock_poll.assert_awaited_once_with("chat1")


def test_auto_cacheado_reciente_con_fresh_confirma_auto():
    """fresh=True re-pollea; si el plugin sigue diciendo auto, retorna False."""
    from agent import takeover

    takeover._cache["chat1"] = _entry("auto", polled_seconds_ago=5)
    nueva_entry = _entry("auto", polled_seconds_ago=0)
    with patch.object(takeover, "_poll_chat",
                       new=AsyncMock(return_value=nueva_entry)) as mock_poll:
        result = asyncio.run(takeover.is_chat_in_manual_mode("chat1", fresh=True))
        assert result is False
        mock_poll.assert_awaited_once()


def test_auto_vencido_repolea_sin_fresh():
    """Cache auto expirada retorna al comportamiento normal (re-poll)."""
    from agent import takeover

    takeover._cache["chat1"] = _entry("auto", polled_seconds_ago=60)  # > TTL 30s
    nueva_entry = _entry("manual", polled_seconds_ago=0, expires_in_min=40)
    with patch.object(takeover, "_poll_chat",
                       new=AsyncMock(return_value=nueva_entry)) as mock_poll:
        result = asyncio.run(takeover.is_chat_in_manual_mode("chat1", fresh=False))
        assert result is True
        mock_poll.assert_awaited_once()


def test_sin_cache_repolea_normal():
    """Sin cache previa, se pollea (con o sin fresh)."""
    from agent import takeover

    nueva_entry = _entry("manual", polled_seconds_ago=0, expires_in_min=40)
    with patch.object(takeover, "_poll_chat",
                       new=AsyncMock(return_value=nueva_entry)) as mock_poll:
        result = asyncio.run(takeover.is_chat_in_manual_mode("chat_nuevo", fresh=True))
        assert result is True
        mock_poll.assert_awaited_once()


def test_default_fresh_es_false():
    """Backward compat: sin pasar el kwarg, comportamiento antiguo."""
    from agent import takeover
    import inspect

    sig = inspect.signature(takeover.is_chat_in_manual_mode)
    assert sig.parameters["fresh"].default is False


def test_fail_open_con_fresh_y_red_caida():
    """Si el poll falla (retorna None) y hay cache auto, retorna False (fail-open)."""
    from agent import takeover

    takeover._cache["chat1"] = _entry("auto", polled_seconds_ago=5)
    with patch.object(takeover, "_poll_chat",
                       new=AsyncMock(return_value=None)) as mock_poll:
        result = asyncio.run(takeover.is_chat_in_manual_mode("chat1", fresh=True))
        assert result is False  # fail-open: si no podemos confirmar, dejamos pasar
        mock_poll.assert_awaited_once()
