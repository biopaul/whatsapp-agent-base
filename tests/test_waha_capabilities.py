"""Tests para waha_capabilities module."""

import pytest
import os
import tempfile
from datetime import datetime, timedelta, timezone


@pytest.fixture
async def temp_db(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp.name}")
    import importlib
    from agent import memory
    importlib.reload(memory)
    await memory.inicializar_db()
    yield memory
    try:
        await memory.engine.dispose()
        os.unlink(tmp.name)
    except Exception:
        pass


@pytest.mark.asyncio
async def test_should_probe_buttons_si_nunca_se_probo(temp_db):
    from agent import waha_capabilities
    result = await waha_capabilities.should_probe_buttons("sess-x")
    assert result is True


@pytest.mark.asyncio
async def test_should_probe_buttons_false_si_se_probo_hace_1h(temp_db):
    from agent import memory, waha_capabilities
    now = datetime.now(timezone.utc)
    await memory.set_waha_capability("sess-x", "supports_buttons", False, probe_at=now - timedelta(hours=1))
    assert await waha_capabilities.should_probe_buttons("sess-x") is False


@pytest.mark.asyncio
async def test_should_probe_buttons_true_si_paso_24h(temp_db):
    from agent import memory, waha_capabilities
    now = datetime.now(timezone.utc)
    await memory.set_waha_capability("sess-x", "supports_buttons", False, probe_at=now - timedelta(hours=25))
    assert await waha_capabilities.should_probe_buttons("sess-x") is True


@pytest.mark.asyncio
async def test_should_probe_buttons_false_si_ya_son_supported(temp_db):
    """Si ya marcamos True, no se reprueba (sabemos que funcionan)."""
    from agent import memory, waha_capabilities
    now = datetime.now(timezone.utc)
    await memory.set_waha_capability("sess-x", "supports_buttons", True, probe_at=now - timedelta(hours=25))
    assert await waha_capabilities.should_probe_buttons("sess-x") is False


@pytest.mark.asyncio
async def test_mark_capability(temp_db):
    from agent import waha_capabilities, memory
    await waha_capabilities.mark_capability("sess-x", "supports_lists", False)
    caps = await memory.get_waha_capabilities("sess-x")
    assert caps["supports_lists"] is False
    assert caps["last_lists_probe"] is not None
