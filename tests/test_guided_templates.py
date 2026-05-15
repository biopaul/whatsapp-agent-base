"""Tests para guided_templates: fetch + cache + dispatch tracking."""

import pytest
import os
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
def reset_templates(monkeypatch):
    monkeypatch.delenv("GUIDED_URL_BASE", raising=False)
    import importlib
    from agent import guided_templates
    importlib.reload(guided_templates)
    yield guided_templates


@pytest.fixture
def templates_with_url(monkeypatch):
    monkeypatch.setenv("GUIDED_URL_BASE", "http://wp.test/wp-json/gowap/v1/guided/tok123")
    import importlib
    from agent import guided_templates
    importlib.reload(guided_templates)
    yield guided_templates


@pytest.mark.asyncio
async def test_get_active_noop_si_url_vacia(reset_templates):
    templates = await reset_templates.get_active()
    assert templates == []


@pytest.mark.asyncio
async def test_get_active_devuelve_lista_y_cachea(templates_with_url):
    fake = _make_response(200, [
        {"id": 1, "name": "t1", "trigger_description": "tr1", "body_text": "b1",
         "footer_text": None, "depth_level": 1, "parent_template_id": None, "options": []}
    ])
    calls = {"n": 0}

    async def fake_get(self, url, *args, **kwargs):
        calls["n"] += 1
        return fake

    with patch("httpx.AsyncClient.get", new=fake_get):
        t1 = await templates_with_url.get_active()
        t2 = await templates_with_url.get_active()
    assert len(t1) == 1
    assert t1[0]["name"] == "t1"
    assert calls["n"] == 1  # cache hit segundo call


@pytest.mark.asyncio
async def test_get_active_repolea_tras_ttl(templates_with_url, monkeypatch):
    """Despues del TTL, vuelve a hacer fetch."""
    monkeypatch.setattr(templates_with_url, "CACHE_TTL_SEC", 0)
    fake = _make_response(200, [])
    calls = {"n": 0}

    async def fake_get(self, url, *args, **kwargs):
        calls["n"] += 1
        return fake

    with patch("httpx.AsyncClient.get", new=fake_get):
        await templates_with_url.get_active()
        await templates_with_url.get_active()
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_get_active_invalida_cache_explicita(templates_with_url):
    fake = _make_response(200, [])
    calls = {"n": 0}

    async def fake_get(self, url, *args, **kwargs):
        calls["n"] += 1
        return fake

    with patch("httpx.AsyncClient.get", new=fake_get):
        await templates_with_url.get_active()
        templates_with_url.invalidate_cache()
        await templates_with_url.get_active()
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_get_active_devuelve_cache_stale_si_red_falla(templates_with_url, monkeypatch):
    """Si pega la red OK una vez y despues falla, devuelve cache (stale-while-revalidate)."""
    monkeypatch.setattr(templates_with_url, "CACHE_TTL_SEC", 0)
    fake_ok = _make_response(200, [
        {"id": 1, "name": "t1", "trigger_description": "tr", "body_text": "b",
         "footer_text": None, "depth_level": 1, "parent_template_id": None, "options": []}
    ])
    state = {"first": True}

    async def fake_get(self, url, *args, **kwargs):
        if state["first"]:
            state["first"] = False
            return fake_ok
        import httpx as h
        raise h.ConnectError("boom")

    with patch("httpx.AsyncClient.get", new=fake_get):
        first = await templates_with_url.get_active()
        second = await templates_with_url.get_active()
    assert len(first) == 1
    assert len(second) == 1  # stale cache


@pytest.mark.asyncio
async def test_post_dispatch(templates_with_url):
    fake = _make_response(200, {"dispatch_id": 42})

    async def fake_post(self, url, *args, **kwargs):
        return fake

    with patch("httpx.AsyncClient.post", new=fake_post):
        dispatch_id = await templates_with_url.register_dispatch(
            template_id=1, session_id="s", chat_id="c",
            format_used="numbered_text", dispatched_at=datetime.now(timezone.utc)
        )
    assert dispatch_id == 42


@pytest.mark.asyncio
async def test_post_dispatch_fail_silent(templates_with_url):
    async def fake_post(self, url, *args, **kwargs):
        import httpx as h
        raise h.ConnectError("boom")

    with patch("httpx.AsyncClient.post", new=fake_post):
        dispatch_id = await templates_with_url.register_dispatch(
            template_id=1, session_id="s", chat_id="c",
            format_used="numbered_text", dispatched_at=datetime.now(timezone.utc)
        )
    assert dispatch_id is None


@pytest.mark.asyncio
async def test_post_selection(templates_with_url):
    fake = _make_response(200, {"ok": True})
    captured = {}

    async def fake_post(self, url, *args, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return fake

    with patch("httpx.AsyncClient.post", new=fake_post):
        ok = await templates_with_url.register_selection(
            dispatch_id=42, option_id=3, selected_at=datetime.now(timezone.utc)
        )
    assert ok is True
    assert "42" in captured["url"]
    assert captured["json"]["option_id"] == 3
