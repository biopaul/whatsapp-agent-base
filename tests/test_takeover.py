"""Tests para el modulo takeover."""

import pytest
import httpx
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock


@pytest.fixture(autouse=True)
def reset_takeover_state(monkeypatch):
    """Cada test arranca con cache limpia y TAKEOVER_URL_BASE no seteado."""
    import importlib
    monkeypatch.delenv("TAKEOVER_URL_BASE", raising=False)
    from agent import takeover
    importlib.reload(takeover)
    yield takeover


@pytest.mark.asyncio
async def test_no_op_mode_when_url_empty(reset_takeover_state):
    """Sin TAKEOVER_URL_BASE el modulo retorna False sin pegarle a la red."""
    takeover = reset_takeover_state
    assert await takeover.is_chat_in_manual_mode("54911@c.us") is False


@pytest.mark.asyncio
async def test_was_recently_manual_returns_none_when_no_history(reset_takeover_state):
    takeover = reset_takeover_state
    assert takeover.was_recently_manual("54911@c.us") is None


@pytest.mark.asyncio
async def test_preload_active_noop_when_url_empty(reset_takeover_state):
    """preload no falla si URL no esta seteada."""
    takeover = reset_takeover_state
    await takeover.preload_active()  # no debe lanzar


def _make_response(status: int, json_data=None):
    """Construye un mock de httpx.Response con .status_code y .json()."""
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
def takeover_with_url(monkeypatch):
    """Modulo recargado con TAKEOVER_URL_BASE seteado."""
    import importlib
    monkeypatch.setenv("TAKEOVER_URL_BASE", "http://wp.test/wp-json/gowap/v1/takeover/tok123")
    from agent import takeover
    importlib.reload(takeover)
    yield takeover


@pytest.mark.asyncio
async def test_is_manual_returns_true_when_plugin_says_manual(takeover_with_url):
    takeover = takeover_with_url
    future = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    fake_response = _make_response(200, {"mode": "manual", "expires_at": future})

    async def fake_get(self, url, *args, **kwargs):
        return fake_response

    with patch("httpx.AsyncClient.get", new=fake_get):
        assert await takeover.is_chat_in_manual_mode("54911@c.us") is True


@pytest.mark.asyncio
async def test_is_manual_returns_false_when_plugin_says_auto(takeover_with_url):
    takeover = takeover_with_url
    fake_response = _make_response(200, {"mode": "auto"})

    async def fake_get(self, url, *args, **kwargs):
        return fake_response

    with patch("httpx.AsyncClient.get", new=fake_get):
        assert await takeover.is_chat_in_manual_mode("54911@c.us") is False


@pytest.mark.asyncio
async def test_is_manual_404_treated_as_auto(takeover_with_url):
    takeover = takeover_with_url
    fake_response = _make_response(404)

    async def fake_get(self, url, *args, **kwargs):
        return fake_response

    with patch("httpx.AsyncClient.get", new=fake_get):
        assert await takeover.is_chat_in_manual_mode("54911@c.us") is False


@pytest.mark.asyncio
async def test_cache_negativo_no_repolea_durante_30s(takeover_with_url):
    """Tras un 'auto' la cache se respeta sin re-pollear por POLL_INTERVAL_AUTO."""
    takeover = takeover_with_url
    fake_response = _make_response(200, {"mode": "auto"})
    call_count = 0

    async def fake_get(self, url, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        return fake_response

    with patch("httpx.AsyncClient.get", new=fake_get):
        await takeover.is_chat_in_manual_mode("54911@c.us")
        await takeover.is_chat_in_manual_mode("54911@c.us")
        await takeover.is_chat_in_manual_mode("54911@c.us")
    assert call_count == 1


@pytest.mark.asyncio
async def test_cache_positivo_no_repolea_hasta_expires(takeover_with_url):
    """Tras un 'manual' con expires_at futuro, no repoleamos."""
    takeover = takeover_with_url
    future = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    fake_response = _make_response(200, {"mode": "manual", "expires_at": future})
    call_count = 0

    async def fake_get(self, url, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        return fake_response

    with patch("httpx.AsyncClient.get", new=fake_get):
        await takeover.is_chat_in_manual_mode("54911@c.us")
        await takeover.is_chat_in_manual_mode("54911@c.us")
    assert call_count == 1


@pytest.mark.asyncio
async def test_network_failure_fail_open_sin_cache(takeover_with_url):
    """Sin cache previa, error de red asume auto."""
    takeover = takeover_with_url

    async def fake_get(self, url, *args, **kwargs):
        raise httpx.ConnectError("boom")

    import httpx
    with patch("httpx.AsyncClient.get", new=fake_get):
        assert await takeover.is_chat_in_manual_mode("54911@c.us") is False


@pytest.mark.asyncio
async def test_401_marca_token_invalid(takeover_with_url):
    """Un 401 marca el modulo como deshabilitado hasta restart."""
    takeover = takeover_with_url
    fake_response = _make_response(401, {"code": "takeover_token_invalid"})
    call_count = 0

    async def fake_get(self, url, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        return fake_response

    with patch("httpx.AsyncClient.get", new=fake_get):
        await takeover.is_chat_in_manual_mode("54911@c.us")
        await takeover.is_chat_in_manual_mode("99999@c.us")
        await takeover.is_chat_in_manual_mode("11111@c.us")
    # Solo el primer call llega al endpoint; los siguientes son short-circuited
    assert call_count == 1


@pytest.mark.asyncio
async def test_preload_carga_chats_activos(takeover_with_url):
    takeover = takeover_with_url
    future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    fake_response = _make_response(200, [
        {"chat_id": "54911@c.us", "expires_at": future},
        {"chat_id": "54922@c.us", "expires_at": future},
    ])

    async def fake_get(self, url, *args, **kwargs):
        return fake_response

    with patch("httpx.AsyncClient.get", new=fake_get):
        await takeover.preload_active()

    assert "54911@c.us" in takeover._cache
    assert takeover._cache["54911@c.us"].mode == "manual"
    assert "54922@c.us" in takeover._cache


@pytest.mark.asyncio
async def test_preload_silent_on_failure(takeover_with_url):
    takeover = takeover_with_url

    async def fake_get(self, url, *args, **kwargs):
        import httpx as h
        raise h.ConnectError("boom")

    # No debe levantar excepcion
    with patch("httpx.AsyncClient.get", new=fake_get):
        await takeover.preload_active()
    assert len(takeover._cache) == 0


def test_was_recently_manual_dentro_del_window(takeover_with_url):
    takeover = takeover_with_url
    now = datetime.now(timezone.utc)
    # Simular un chat que estuvo en manual hace 10 min
    takeover._cache["54911@c.us"] = takeover.TakeoverEntry(
        mode="auto",
        last_polled=now,
        last_manual_until=now - timedelta(minutes=10),
    )
    window = takeover.was_recently_manual("54911@c.us")
    assert window is not None
    start, end = window
    assert end == now - timedelta(minutes=10)


def test_was_recently_manual_fuera_del_window(takeover_with_url):
    takeover = takeover_with_url
    now = datetime.now(timezone.utc)
    # Simular un chat que estuvo en manual hace 2 horas (fuera del window de 60min)
    takeover._cache["54911@c.us"] = takeover.TakeoverEntry(
        mode="auto",
        last_polled=now,
        last_manual_until=now - timedelta(hours=2),
    )
    assert takeover.was_recently_manual("54911@c.us") is None


def test_was_recently_manual_si_esta_en_manual_activo(takeover_with_url):
    """Si el chat esta actualmente en manual, was_recently retorna el window actual."""
    takeover = takeover_with_url
    now = datetime.now(timezone.utc)
    takeover._cache["54911@c.us"] = takeover.TakeoverEntry(
        mode="manual",
        expires_at=now + timedelta(minutes=20),
        last_polled=now,
    )
    window = takeover.was_recently_manual("54911@c.us")
    assert window is not None
    start, end = window
    # End del window es "ahora" (todavia esta activo)
    assert (end - now).total_seconds() < 60
