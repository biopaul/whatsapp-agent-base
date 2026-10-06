# tests/test_blocked_chats.py — blocked_chat_ids desde config WP

import os
os.environ.setdefault("OPENAI_API_KEY", "test-dummy")
os.environ.setdefault("OPENROUTER_API_KEY", "test-dummy")

import asyncio
import importlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset():
    from agent import config_loader
    importlib.reload(config_loader)
    yield


# --- get_blocked_chat_ids: parsing y backward compat ---

def test_blocked_field_ausente_devuelve_empty_frozenset():
    from agent import config_loader
    with patch.object(config_loader, "get_config", return_value={}):
        result = config_loader.get_blocked_chat_ids()
    assert result == frozenset()
    assert isinstance(result, frozenset)


def test_blocked_field_none_devuelve_empty():
    from agent import config_loader
    with patch.object(config_loader, "get_config", return_value={"blocked_chat_ids": None}):
        assert config_loader.get_blocked_chat_ids() == frozenset()


def test_blocked_field_lista_vacia():
    from agent import config_loader
    with patch.object(config_loader, "get_config", return_value={"blocked_chat_ids": []}):
        assert config_loader.get_blocked_chat_ids() == frozenset()


def test_blocked_field_tipo_invalido_no_lista():
    from agent import config_loader
    with patch.object(config_loader, "get_config", return_value={"blocked_chat_ids": "not-a-list"}):
        assert config_loader.get_blocked_chat_ids() == frozenset()


def test_blocked_field_lista_normal():
    from agent import config_loader
    cfg = {"blocked_chat_ids": ["5491111@c.us", "5492222@lid"]}
    with patch.object(config_loader, "get_config", return_value=cfg):
        result = config_loader.get_blocked_chat_ids()
    assert result == frozenset({"5491111@c.us", "5492222@lid"})


def test_blocked_field_ignora_entries_malformadas():
    from agent import config_loader
    cfg = {"blocked_chat_ids": ["5491111@c.us", "", None, 42, "  5492222@c.us  "]}
    with patch.object(config_loader, "get_config", return_value=cfg):
        result = config_loader.get_blocked_chat_ids()
    # None, "", 42 son ignorados; el que tiene espacios se trimea
    assert result == frozenset({"5491111@c.us", "5492222@c.us"})


# --- Match con variantes @c.us / @lid ---

def test_match_directo_c_us():
    from agent import config_loader
    from agent.memory import _telefono_variantes
    cfg = {"blocked_chat_ids": ["5491111@c.us"]}
    with patch.object(config_loader, "get_config", return_value=cfg):
        blocked = config_loader.get_blocked_chat_ids()
    assert any(v in blocked for v in _telefono_variantes("5491111@c.us"))


def test_match_cross_suffix_lid_bloqueado_llega_c_us():
    """Config bloquea con @lid, mensaje llega con @c.us — debe matchear via variantes."""
    from agent import config_loader
    from agent.memory import _telefono_variantes
    cfg = {"blocked_chat_ids": ["5491111@lid"]}
    with patch.object(config_loader, "get_config", return_value=cfg):
        blocked = config_loader.get_blocked_chat_ids()
    # El mensaje llega con @c.us
    variantes_incoming = _telefono_variantes("5491111@c.us")
    assert any(v in blocked for v in variantes_incoming)


def test_match_cross_suffix_c_us_bloqueado_llega_lid():
    """Config bloquea con @c.us, mensaje llega con @lid — debe matchear."""
    from agent import config_loader
    from agent.memory import _telefono_variantes
    cfg = {"blocked_chat_ids": ["5491111@c.us"]}
    with patch.object(config_loader, "get_config", return_value=cfg):
        blocked = config_loader.get_blocked_chat_ids()
    variantes_incoming = _telefono_variantes("5491111@lid")
    assert any(v in blocked for v in variantes_incoming)


def test_no_match_numero_distinto():
    from agent import config_loader
    from agent.memory import _telefono_variantes
    cfg = {"blocked_chat_ids": ["5491111@c.us"]}
    with patch.object(config_loader, "get_config", return_value=cfg):
        blocked = config_loader.get_blocked_chat_ids()
    variantes_incoming = _telefono_variantes("5499999@c.us")
    assert not any(v in blocked for v in variantes_incoming)


# --- Integracion en el webhook: chat bloqueado no llega al LLM ---

@pytest.mark.asyncio
async def test_webhook_bloqueado_no_llama_llm_ni_persiste():
    """Chat en blocked_chat_ids → no debounce, no LLM, no guardar_mensaje, no marcar_leido."""
    from agent import main as agent_main
    from agent.providers.base import MensajeEntrante

    msg = MensajeEntrante(
        telefono="5491111@c.us",
        texto="hola",
        mensaje_id="mid1",
        es_propio=False,
        source="",
        tiene_media=False,
    )

    request = MagicMock()
    request.json = AsyncMock(return_value={})

    with patch.object(agent_main.proveedor, "parsear_webhook",
                       new=AsyncMock(return_value=[msg])), \
         patch.object(agent_main.proveedor, "marcar_leido", new=AsyncMock()) as mock_read, \
         patch.object(agent_main, "existe_mensaje_id", new=AsyncMock(return_value=False)), \
         patch.object(agent_main, "get_blocked_chat_ids",
                       return_value=frozenset({"5491111@c.us"})), \
         patch.object(agent_main, "guardar_mensaje", new=AsyncMock()) as mock_save, \
         patch.object(agent_main.debouncer, "schedule") as mock_schedule, \
         patch.object(agent_main.takeover, "is_chat_in_manual_mode",
                       new=AsyncMock(return_value=False)):
        r = await agent_main.webhook_handler(request)

    assert r == {"status": "ok"}
    mock_schedule.assert_not_called()
    mock_save.assert_not_awaited()
    mock_read.assert_not_awaited()


@pytest.mark.asyncio
async def test_webhook_no_bloqueado_flujo_normal():
    """Chat NO en blocked_chat_ids → sigue el flujo (schedule al debouncer)."""
    from agent import main as agent_main
    from agent.providers.base import MensajeEntrante

    msg = MensajeEntrante(
        telefono="5499999@c.us",
        texto="hola",
        mensaje_id="mid1",
        es_propio=False,
        source="",
        tiene_media=False,
    )

    request = MagicMock()
    request.json = AsyncMock(return_value={})

    with patch.object(agent_main.proveedor, "parsear_webhook",
                       new=AsyncMock(return_value=[msg])), \
         patch.object(agent_main.proveedor, "marcar_leido", new=AsyncMock()), \
         patch.object(agent_main, "existe_mensaje_id", new=AsyncMock(return_value=False)), \
         patch.object(agent_main, "get_blocked_chat_ids",
                       return_value=frozenset({"5491111@c.us"})), \
         patch.object(agent_main.takeover, "is_chat_in_manual_mode",
                       new=AsyncMock(return_value=False)), \
         patch.object(agent_main, "is_agent_paused", return_value=False), \
         patch.object(agent_main, "is_within_business_hours", return_value=True), \
         patch.object(agent_main.debouncer, "schedule") as mock_schedule:
        r = await agent_main.webhook_handler(request)

    assert r == {"status": "ok"}
    mock_schedule.assert_called_once()


@pytest.mark.asyncio
async def test_webhook_bloqueado_via_lid_variant():
    """Config bloquea @c.us; mensaje llega con @lid — debe bloquear igual."""
    from agent import main as agent_main
    from agent.providers.base import MensajeEntrante

    msg = MensajeEntrante(
        telefono="5491111@lid",
        texto="hola",
        mensaje_id="mid1",
        es_propio=False,
        source="",
        tiene_media=False,
    )
    request = MagicMock()
    request.json = AsyncMock(return_value={})

    with patch.object(agent_main.proveedor, "parsear_webhook",
                       new=AsyncMock(return_value=[msg])), \
         patch.object(agent_main, "existe_mensaje_id", new=AsyncMock(return_value=False)), \
         patch.object(agent_main, "get_blocked_chat_ids",
                       return_value=frozenset({"5491111@c.us"})), \
         patch.object(agent_main.debouncer, "schedule") as mock_schedule, \
         patch.object(agent_main, "guardar_mensaje", new=AsyncMock()) as mock_save:
        await agent_main.webhook_handler(request)

    mock_schedule.assert_not_called()
    mock_save.assert_not_awaited()
