"""Tests para guided_dispatcher: parseo y orquestacion."""

import pytest
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock


@pytest.fixture
async def temp_db(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp.name}")
    monkeypatch.setenv("GUIDED_URL_BASE", "http://wp.test/wp-json/gowap/v1/guided/tok")
    import importlib
    from agent import memory, guided_templates
    importlib.reload(memory)
    importlib.reload(guided_templates)
    await memory.inicializar_db()
    yield memory
    try:
        await memory.engine.dispose()
        os.unlink(tmp.name)
    except Exception:
        pass


def test_parse_plantilla_invocation_simple():
    from agent.guided_dispatcher import parse_plantilla_invocation
    assert parse_plantilla_invocation("<plantilla>menu_principal</plantilla>") == "menu_principal"
    assert parse_plantilla_invocation("texto <plantilla>x</plantilla> mas") == "x"
    assert parse_plantilla_invocation("Antes\n<plantilla>turnos</plantilla>\nDespues") == "turnos"


def test_parse_plantilla_invocation_no_match():
    from agent.guided_dispatcher import parse_plantilla_invocation
    assert parse_plantilla_invocation("texto sin tag") is None
    assert parse_plantilla_invocation("") is None
    assert parse_plantilla_invocation("<plantilla></plantilla>") is None


def test_parse_plantilla_invocation_trim():
    from agent.guided_dispatcher import parse_plantilla_invocation
    assert parse_plantilla_invocation("<plantilla>  menu  </plantilla>") == "menu"


@pytest.mark.asyncio
async def test_dispatch_invoca_cascada_y_registra(temp_db):
    from agent import guided_dispatcher, guided_templates, memory

    template = {
        "id": 1, "name": "t1", "body_text": "elegi:", "footer_text": None,
        "depth_level": 1, "parent_template_id": None,
        "options": [
            {"id": 11, "order": 1, "visible_text": "Si", "action_type": "text", "action_payload": {}},
            {"id": 12, "order": 2, "visible_text": "No", "action_type": "text", "action_payload": {}},
        ]
    }
    # Llenar cache
    guided_templates._cache = [template]
    guided_templates._cache_at = datetime.now(timezone.utc)

    provider = AsyncMock()

    with patch("agent.guided_cascade.enviar_con_cascada",
               new=AsyncMock(return_value={"format_used": "numbered_text", "mensaje_id": "msg1"})), \
         patch("agent.guided_templates.register_dispatch",
               new=AsyncMock(return_value=42)):
        result = await guided_dispatcher.dispatch_plantilla(
            provider=provider, session_id="sess",
            chat_id="54911@c.us", name="t1"
        )

    assert result["ok"] is True
    assert result["format_used"] == "numbered_text"

    # Verificar que se guardo el dispatch local
    d = await memory.obtener_dispatch_activo("54911@c.us")
    assert d is not None
    assert d["template_id"] == 1
    assert d["remote_dispatch_id"] == 42


@pytest.mark.asyncio
async def test_dispatch_si_plantilla_no_existe_retorna_ok_false(temp_db):
    from agent import guided_dispatcher, guided_templates
    guided_templates._cache = []
    guided_templates._cache_at = datetime.now(timezone.utc)

    provider = AsyncMock()
    # Patch get_active para que no haga HTTP
    with patch("agent.guided_templates.get_active", new=AsyncMock(return_value=[])):
        result = await guided_dispatcher.dispatch_plantilla(
            provider=provider, session_id="sess",
            chat_id="54911@c.us", name="inexistente"
        )
    assert result["ok"] is False
    assert "not_found" in result["reason"]


def test_render_plantillas_prompt_block_vacio_si_no_hay():
    from agent.guided_dispatcher import render_plantillas_prompt_block
    assert render_plantillas_prompt_block([]) == ""


def test_render_plantillas_prompt_block_incluye_raices():
    from agent.guided_dispatcher import render_plantillas_prompt_block
    templates = [
        {"id": 1, "name": "raiz", "trigger_description": "Cuando X", "body_text": "Hola",
         "footer_text": None, "depth_level": 1, "parent_template_id": None,
         "options": [{"visible_text": "Si", "action_type": "text"}]},
        {"id": 2, "name": "sub", "trigger_description": "tr", "body_text": "b",
         "footer_text": None, "depth_level": 2, "parent_template_id": 1, "options": []},
    ]
    block = render_plantillas_prompt_block(templates)
    assert "RESPUESTAS GUIADAS" in block
    assert "raiz" in block
    assert "Cuando X" in block
    # Sub-plantilla NO debe aparecer en el listado top-level
    assert "sub" not in block
