"""Tests para tablas WahaSessionCapabilities y GuidedDispatchLocal."""

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
    except (PermissionError, FileNotFoundError):
        pass


@pytest.mark.asyncio
async def test_get_waha_capabilities_devuelve_defaults_si_no_existe(temp_db):
    memory = temp_db
    caps = await memory.get_waha_capabilities("session-x")
    assert caps["supports_buttons"] is False
    assert caps["supports_lists"] is True
    assert caps["last_buttons_probe"] is None


@pytest.mark.asyncio
async def test_set_waha_capabilities_upsert(temp_db):
    memory = temp_db
    now = datetime.now(timezone.utc)
    await memory.set_waha_capability("session-x", "supports_buttons", True, probe_at=now)
    caps = await memory.get_waha_capabilities("session-x")
    assert caps["supports_buttons"] is True
    assert caps["last_buttons_probe"] is not None


@pytest.mark.asyncio
async def test_guarda_dispatch_local(temp_db):
    memory = temp_db
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=10)
    options = [{"id": 1, "order": 1, "visible_text": "Si", "action_type": "text", "action_payload": {"text": "ok"}}]
    dispatch_id = await memory.guardar_dispatch_local(
        template_id=10, chat_id="54911@c.us",
        dispatched_at=now, expires_at=expires,
        format_used="numbered_text", options_snapshot=options,
        parent_id=None
    )
    assert dispatch_id > 0


@pytest.mark.asyncio
async def test_obtener_dispatch_activo_en_chat(temp_db):
    memory = temp_db
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=10)
    await memory.guardar_dispatch_local(
        template_id=10, chat_id="54911@c.us",
        dispatched_at=now, expires_at=expires,
        format_used="numbered_text", options_snapshot=[],
        parent_id=None
    )
    d = await memory.obtener_dispatch_activo("54911@c.us")
    assert d is not None
    assert d["template_id"] == 10


@pytest.mark.asyncio
async def test_obtener_dispatch_activo_ignora_expirados(temp_db):
    memory = temp_db
    now = datetime.now(timezone.utc)
    expires = now - timedelta(minutes=1)
    await memory.guardar_dispatch_local(
        template_id=10, chat_id="54911@c.us",
        dispatched_at=now - timedelta(minutes=20), expires_at=expires,
        format_used="numbered_text", options_snapshot=[],
        parent_id=None
    )
    d = await memory.obtener_dispatch_activo("54911@c.us")
    assert d is None
