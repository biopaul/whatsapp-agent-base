"""Tests para columna mensaje_id + dedupe."""

import pytest
import os
import tempfile


@pytest.fixture
async def temp_db(monkeypatch):
    """Setup DB temporal aislada por test."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp.name}")

    import importlib
    from agent import memory
    importlib.reload(memory)

    await memory.inicializar_db()
    yield memory
    await memory.engine.dispose()
    try:
        os.unlink(tmp.name)
    except PermissionError:
        pass


@pytest.mark.asyncio
async def test_guardar_mensaje_acepta_mensaje_id(temp_db):
    memory = temp_db
    await memory.guardar_mensaje("54911@c.us", "user", "hola", mensaje_id="abc123")
    historial = await memory.obtener_historial("54911@c.us")
    assert len(historial) == 1
    assert historial[0]["content"] == "hola"


@pytest.mark.asyncio
async def test_guardar_mensaje_sin_mensaje_id_es_compatible(temp_db):
    memory = temp_db
    await memory.guardar_mensaje("54911@c.us", "user", "hola")
    historial = await memory.obtener_historial("54911@c.us")
    assert len(historial) == 1


@pytest.mark.asyncio
async def test_existe_mensaje_id_match(temp_db):
    memory = temp_db
    await memory.guardar_mensaje("54911@c.us", "assistant", "respuesta", mensaje_id="msg_xyz")
    assert await memory.existe_mensaje_id("54911@c.us", "msg_xyz") is True
    assert await memory.existe_mensaje_id("54911@c.us", "msg_otro") is False
    assert await memory.existe_mensaje_id("99999@c.us", "msg_xyz") is False


@pytest.mark.asyncio
async def test_existe_mensaje_id_vacio_retorna_false(temp_db):
    memory = temp_db
    assert await memory.existe_mensaje_id("54911@c.us", "") is False
    assert await memory.existe_mensaje_id("54911@c.us", None) is False
