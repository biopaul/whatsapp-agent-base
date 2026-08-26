# tests/test_generation_invalidation.py — invalidacion de generacion IA en vuelo

import os
os.environ.setdefault("OPENAI_API_KEY", "test-dummy")
os.environ.setdefault("OPENROUTER_API_KEY", "test-dummy")

import asyncio
import importlib
from unittest.mock import AsyncMock

import pytest

from agent import debouncer


@pytest.fixture(autouse=True)
def _clean_debouncer():
    debouncer.clear()
    yield
    debouncer.clear()


# --- Bump del default ---

def test_debounce_default_es_8(monkeypatch):
    monkeypatch.delenv("MESSAGE_DEBOUNCE_SEC", raising=False)
    importlib.reload(debouncer)
    assert debouncer.DEBOUNCE_SEC == 8.0


def test_debounce_env_override(monkeypatch):
    monkeypatch.setenv("MESSAGE_DEBOUNCE_SEC", "3.5")
    importlib.reload(debouncer)
    assert debouncer.DEBOUNCE_SEC == 3.5
    # reset a default para no afectar otros tests
    monkeypatch.setenv("MESSAGE_DEBOUNCE_SEC", "8")
    importlib.reload(debouncer)


# --- GenerationToken lifecycle ---

def test_register_devuelve_token_no_invalidado():
    token = debouncer.register_generation("chat1")
    assert token.invalidated is False


def test_unregister_limpia_registro():
    token = debouncer.register_generation("chat1")
    debouncer.unregister_generation("chat1", token)
    assert "chat1" not in debouncer._active_generations


def test_unregister_no_borra_si_token_diferente():
    """Si otro register arranco entretanto, unregister del viejo NO borra el nuevo."""
    old_token = debouncer.register_generation("chat1")
    new_token = debouncer.register_generation("chat1")  # reemplaza
    debouncer.unregister_generation("chat1", old_token)  # con token viejo
    # El nuevo sigue registrado
    assert debouncer._active_generations.get("chat1") is new_token


# --- Invalidacion via schedule ---

def _mk_handler():
    return AsyncMock()


def test_schedule_invalida_generacion_activa():
    """Cuando llega mensaje nuevo y hay generacion en vuelo, se invalida."""
    async def run():
        handler = _mk_handler()
        token = debouncer.register_generation("chat1")
        assert not token.invalidated
        debouncer.schedule("chat1", "hola", "id1", False, handler)
        assert token.invalidated is True
    asyncio.run(run())


def test_schedule_sin_generacion_activa_no_falla():
    """Schedule cuando no hay generacion activa no debe romper."""
    async def run():
        handler = _mk_handler()
        debouncer.schedule("chat_sin_gen", "hola", "id1", False, handler)
        # sanity: no explota
    asyncio.run(run())


def test_multiples_schedules_no_re_loguean():
    """Si ya se invalido, un segundo schedule no vuelve a poner invalidated=True (idempotente)."""
    async def run():
        handler = _mk_handler()
        token = debouncer.register_generation("chat1")
        debouncer.schedule("chat1", "msg1", "id1", False, handler)
        assert token.invalidated
        # segundo schedule — el token ya esta invalidated, no vuelve a marcar
        debouncer.schedule("chat1", "msg2", "id2", False, handler)
        assert token.invalidated
    asyncio.run(run())


def test_invalidacion_es_por_chat_no_global():
    """Un schedule en chat1 no invalida generaciones en chat2."""
    async def run():
        handler = _mk_handler()
        token1 = debouncer.register_generation("chat1")
        token2 = debouncer.register_generation("chat2")
        debouncer.schedule("chat1", "msg", "id1", False, handler)
        assert token1.invalidated
        assert not token2.invalidated
    asyncio.run(run())


def test_clear_resetea_active_generations():
    debouncer.register_generation("chat1")
    debouncer.register_generation("chat2")
    debouncer.clear()
    assert len(debouncer._active_generations) == 0
