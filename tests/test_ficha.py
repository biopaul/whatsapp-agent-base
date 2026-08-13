"""Tests para el sistema de Ficha (agent/ficha.py + memory.py)."""

import asyncio
import os
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, AsyncMock

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("OPENROUTER_API_KEY", "sk-or-test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")


@pytest.fixture(autouse=True)
async def _fresh_db(monkeypatch):
    """Recarga memory con DB in-memory limpia por test."""
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    import importlib
    from agent import memory
    importlib.reload(memory)
    await memory.inicializar_db()
    yield


# ============================================================ Helpers puros

def test_sanitize_normaliza_tags_a_snake_case():
    from agent.ficha import _sanitize_ficha_dict
    raw = {"nombre": "  Juan  ", "email": "  ", "tags": ["Lead Calificado", "cita_agendada"], "resumen": "  "}
    out = _sanitize_ficha_dict(raw)
    assert out["nombre"] == "Juan"
    assert out["email"] is None
    assert out["tags"] == ["lead_calificado", "cita_agendada"]
    assert out["resumen"] is None


def test_sanitize_cap_5_tags():
    from agent.ficha import _sanitize_ficha_dict
    raw = {"tags": ["t1", "t2", "t3", "t4", "t5", "t6", "t7"]}
    out = _sanitize_ficha_dict(raw)
    assert len(out["tags"]) == 5


def test_sanitize_tolera_tipos_raros():
    from agent.ficha import _sanitize_ficha_dict
    out = _sanitize_ficha_dict({"nombre": 123, "email": None, "tags": None, "resumen": []})
    assert out["nombre"] is None
    assert out["email"] is None
    assert out["tags"] == []
    assert out["resumen"] is None


def test_extract_json_con_fences():
    from agent.ficha import _extract_json
    text = '```json\n{"nombre": "Juan"}\n```'
    assert _extract_json(text) == {"nombre": "Juan"}


def test_extract_json_sin_fences():
    from agent.ficha import _extract_json
    assert _extract_json('{"nombre": "Juan"}') == {"nombre": "Juan"}


def test_extract_json_texto_alrededor():
    from agent.ficha import _extract_json
    text = 'Aca esta:\n{"nombre": "Juan", "tags": []}\nEspero te sirva'
    assert _extract_json(text) == {"nombre": "Juan", "tags": []}


def test_extract_json_invalido_retorna_none():
    from agent.ficha import _extract_json
    assert _extract_json("nada de json aca") is None


def test_extract_json_vacio_none():
    from agent.ficha import _extract_json
    assert _extract_json("") is None
    assert _extract_json(None) is None


# ============================================================ Detector cierre

@pytest.mark.asyncio
async def test_detector_cierre_sin_historial_es_false():
    from agent.ficha import detectar_cierre_bloque
    assert (await detectar_cierre_bloque("54911@c.us")) is False


@pytest.mark.asyncio
async def test_detector_cierre_mensaje_reciente_es_false():
    from agent import memory
    from agent.ficha import detectar_cierre_bloque
    await memory.guardar_mensaje("54911@c.us", "user", "hola")
    assert (await detectar_cierre_bloque("54911@c.us")) is False


@pytest.mark.asyncio
async def test_detector_cierre_mensaje_viejo_es_true():
    """Simula un mensaje de hace 8h → cierre bloque True (default 6h)."""
    from agent import memory
    from agent.ficha import detectar_cierre_bloque
    async with memory.async_session() as s:
        m = memory.Mensaje(
            telefono="54911@c.us", role="user", content="hola",
            timestamp=datetime.utcnow() - timedelta(hours=8),
        )
        s.add(m)
        await s.commit()
    assert (await detectar_cierre_bloque("54911@c.us")) is True


# ============================================================ build_ficha_context

@pytest.mark.asyncio
async def test_build_context_ficha_none_es_vacio():
    from agent.ficha import build_ficha_context
    assert build_ficha_context(None) == ""


@pytest.mark.asyncio
async def test_build_context_completa_incluye_todos_los_campos():
    from agent import memory
    from agent.ficha import build_ficha_context
    row = memory.Ficha(
        telefono="54911@c.us", nombre="Juan Perez", email="juan@x.com",
        tags=["lead_calificado", "cita_agendada"],
        resumen="Interesado en plan premium, agendo demo para el viernes.",
        ultima_actualizacion=datetime.utcnow() - timedelta(days=4),
    )
    ctx = build_ficha_context(row)
    assert "## Ficha del cliente" in ctx
    assert "Juan Perez" in ctx
    assert "juan@x.com" in ctx
    assert "lead_calificado, cita_agendada" in ctx
    assert "plan premium" in ctx
    assert "hace 4 dias" in ctx


@pytest.mark.asyncio
async def test_build_context_omite_lineas_nulas():
    from agent import memory
    from agent.ficha import build_ficha_context
    row = memory.Ficha(
        telefono="x", nombre="Juan", email=None, tags=[], resumen=None,
        ultima_actualizacion=datetime.utcnow(),
    )
    ctx = build_ficha_context(row)
    assert "Juan" in ctx
    assert "Email:" not in ctx
    assert "Tags:" not in ctx
    assert "Contexto previo:" not in ctx


@pytest.mark.asyncio
async def test_build_context_completamente_vacia_es_vacio():
    from agent import memory
    from agent.ficha import build_ficha_context
    row = memory.Ficha(
        telefono="x", nombre=None, email=None, tags=[], resumen=None,
        ultima_actualizacion=None,
    )
    assert build_ficha_context(row) == ""


# ============================================================ CRUD memory

@pytest.mark.asyncio
async def test_upsert_auto_crea_nueva():
    from agent import memory
    row = await memory.upsert_ficha_auto(
        "54911@c.us", "Juan", "j@x.com", ["lead_frio"], "Consulto por precio."
    )
    assert row.nombre == "Juan"
    assert row.tags == ["lead_frio"]
    assert row.editado_manualmente is False


@pytest.mark.asyncio
async def test_upsert_auto_respeta_editado_manualmente():
    """Si la ficha esta marcada como editada manualmente, autoupdate NO pisa."""
    from agent import memory
    await memory.upsert_ficha_manual("54911@c.us", {"nombre": "Nombre Manual"})
    row = await memory.upsert_ficha_auto(
        "54911@c.us", "Nombre Automatico", None, ["auto_tag"], "resumen auto"
    )
    # Debe conservar los datos manuales
    assert row.nombre == "Nombre Manual"
    assert row.tags == []
    assert row.editado_manualmente is True


@pytest.mark.asyncio
async def test_upsert_auto_pisa_si_flag_disabled(monkeypatch):
    from agent import memory
    monkeypatch.setenv("FICHA_AUTOUPDATE_RESPETA_MANUAL", "false")
    await memory.upsert_ficha_manual("54911@c.us", {"nombre": "Manual"})
    row = await memory.upsert_ficha_auto(
        "54911@c.us", "Auto", None, ["auto"], "resumen"
    )
    assert row.nombre == "Auto"


@pytest.mark.asyncio
async def test_upsert_manual_marca_flag():
    from agent import memory
    row = await memory.upsert_ficha_manual("x", {"nombre": "Ana", "tags": ["cliente_activo"]})
    assert row.editado_manualmente is True
    assert row.editado_en is not None
    assert row.tags == ["cliente_activo"]


@pytest.mark.asyncio
async def test_upsert_manual_ignora_campos_no_permitidos():
    from agent import memory
    row = await memory.upsert_ficha_manual("x", {
        "nombre": "Ana", "editado_manualmente": False, "resumen": "r"
    })
    assert row.nombre == "Ana"
    assert row.editado_manualmente is True  # el flag del body se ignora


# ============================================================ Backfill

@pytest.mark.asyncio
async def test_backfill_copia_contactos_a_fichas():
    from agent import memory
    # Simulo un Contacto legacy sin Ficha asociada
    async with memory.async_session() as s:
        s.add(memory.Contacto(
            telefono="54999@c.us", nombre="Legacy", email="l@x.com",
            primer_contacto=datetime(2025, 1, 1),
            actualizado_en=datetime(2025, 6, 1),
        ))
        await s.commit()
    await memory._backfill_contactos_a_fichas()
    row = await memory.obtener_ficha("54999@c.us")
    assert row is not None
    assert row.nombre == "Legacy"
    assert row.email == "l@x.com"


@pytest.mark.asyncio
async def test_backfill_no_pisa_ficha_existente():
    from agent import memory
    await memory.upsert_ficha_manual("54999@c.us", {"nombre": "YaExiste"})
    async with memory.async_session() as s:
        s.add(memory.Contacto(
            telefono="54999@c.us", nombre="Legacy",
            primer_contacto=datetime.utcnow(), actualizado_en=datetime.utcnow(),
        ))
        await s.commit()
    await memory._backfill_contactos_a_fichas()
    row = await memory.obtener_ficha("54999@c.us")
    assert row.nombre == "YaExiste"  # ficha existente ganó


# ============================================================ generar_ficha (LLM mock)

@pytest.mark.asyncio
async def test_generar_ficha_primera_vez_llama_prompt_completo():
    from agent import ficha as ficha_mod
    historial = [
        {"role": "user", "content": "Hola soy Juan", "timestamp": datetime.utcnow()},
        {"role": "assistant", "content": "Hola Juan", "timestamp": datetime.utcnow()},
    ]
    fake_data = {"nombre": "Juan", "email": None, "tags": ["lead_frio"], "resumen": "Consulta inicial."}
    with patch.object(ficha_mod, "_llamar_llm", new=AsyncMock(return_value=fake_data)) as m:
        out = await ficha_mod.generar_ficha("54911@c.us", historial)
    assert out == fake_data
    prompt_arg = m.await_args.args[0]
    assert "HISTORIAL" in prompt_arg
    assert "Juan" in prompt_arg


@pytest.mark.asyncio
async def test_generar_ficha_incremental_pasa_vigente_y_delta():
    from agent import memory, ficha as ficha_mod
    # Ficha vigente creada hace 1h
    await memory.upsert_ficha_auto("54911@c.us", "Juan", None, ["lead_frio"], "resumen viejo")
    # Historial con mensaje viejo (antes de la ficha) y uno nuevo (despues)
    cutoff = (await memory.obtener_ficha("54911@c.us")).ultima_actualizacion
    historial = [
        {"role": "user", "content": "mensaje viejo", "timestamp": cutoff - timedelta(hours=2)},
        {"role": "user", "content": "mensaje nuevo", "timestamp": cutoff + timedelta(minutes=5)},
    ]
    with patch.object(ficha_mod, "_llamar_llm", new=AsyncMock(return_value={
        "nombre": "Juan", "email": None, "tags": ["lead_calificado"], "resumen": "nuevo"
    })) as m:
        out = await ficha_mod.generar_ficha("54911@c.us", historial)
    assert out["tags"] == ["lead_calificado"]
    prompt_arg = m.await_args.args[0]
    assert "FICHA VIGENTE" in prompt_arg
    assert "DELTA" in prompt_arg
    assert "mensaje nuevo" in prompt_arg
    assert "mensaje viejo" not in prompt_arg  # cutoff filtra


@pytest.mark.asyncio
async def test_generar_ficha_incremental_sin_delta_retorna_none():
    from agent import memory, ficha as ficha_mod
    await memory.upsert_ficha_auto("54911@c.us", "Juan", None, [], None)
    cutoff = (await memory.obtener_ficha("54911@c.us")).ultima_actualizacion
    historial = [{"role": "user", "content": "viejo", "timestamp": cutoff - timedelta(hours=1)}]
    out = await ficha_mod.generar_ficha("54911@c.us", historial)
    assert out is None


@pytest.mark.asyncio
async def test_generar_ficha_llm_falla_retorna_none():
    from agent import ficha as ficha_mod
    historial = [{"role": "user", "content": "hola", "timestamp": datetime.utcnow()}]
    with patch.object(ficha_mod, "_llamar_llm", new=AsyncMock(return_value=None)):
        out = await ficha_mod.generar_ficha("x", historial)
    assert out is None


@pytest.mark.asyncio
async def test_recalcular_background_persiste_resultado():
    from agent import memory, ficha as ficha_mod
    await memory.guardar_mensaje("54911@c.us", "user", "Hola soy Juan")
    with patch.object(ficha_mod, "_llamar_llm", new=AsyncMock(return_value={
        "nombre": "Juan", "email": None, "tags": ["lead_frio"], "resumen": "OK"
    })):
        await ficha_mod.recalcular_ficha_background("54911@c.us")
    row = await memory.obtener_ficha("54911@c.us")
    assert row is not None
    assert row.nombre == "Juan"
    assert row.tags == ["lead_frio"]


@pytest.mark.asyncio
async def test_recalcular_background_no_rompe_si_llm_falla():
    from agent import memory, ficha as ficha_mod
    await memory.guardar_mensaje("54911@c.us", "user", "hola")
    with patch.object(ficha_mod, "_llamar_llm", new=AsyncMock(side_effect=RuntimeError("boom"))):
        await ficha_mod.recalcular_ficha_background("54911@c.us")  # no debe raise
    row = await memory.obtener_ficha("54911@c.us")
    assert row is None  # no se creo nada


# ============================================================ Variantes chat_id

@pytest.mark.asyncio
async def test_variantes_matcheo_c_us_directo():
    from agent import memory
    await memory.guardar_mensaje("54911@c.us", "user", "hola")
    msgs, matched = await memory.obtener_historial_variantes("54911@c.us")
    assert len(msgs) == 1
    assert matched == "54911@c.us"


@pytest.mark.asyncio
async def test_variantes_matcheo_s_whatsapp_net_fallback():
    """Historial guardado con @s.whatsapp.net pero endpoint recibe @c.us."""
    from agent import memory
    await memory.guardar_mensaje("54911@s.whatsapp.net", "user", "hola")
    msgs, matched = await memory.obtener_historial_variantes("54911@c.us")
    assert len(msgs) == 1
    assert matched == "54911@s.whatsapp.net"


@pytest.mark.asyncio
async def test_variantes_matcheo_sin_sufijo():
    from agent import memory
    await memory.guardar_mensaje("54911", "user", "hola")
    msgs, matched = await memory.obtener_historial_variantes("54911@c.us")
    assert len(msgs) == 1
    assert matched == "54911"


@pytest.mark.asyncio
async def test_variantes_sin_matches_devuelve_vacio():
    from agent import memory
    msgs, matched = await memory.obtener_historial_variantes("54999@c.us")
    assert msgs == []
    assert matched is None


@pytest.mark.asyncio
async def test_variantes_incluye_timestamp():
    """Los dicts devueltos deben incluir timestamp (crítico para delta merge)."""
    from agent import memory
    await memory.guardar_mensaje("54911@c.us", "user", "hola")
    msgs, _ = await memory.obtener_historial_variantes("54911@c.us")
    assert "timestamp" in msgs[0]
    assert isinstance(msgs[0]["timestamp"], datetime)


# ============================================================ force_full

@pytest.mark.asyncio
async def test_generar_ficha_force_full_ignora_ficha_previa():
    """Con force_full=True, se usa prompt primera aunque haya ficha vigente."""
    from agent import memory, ficha as ficha_mod
    await memory.upsert_ficha_auto("54911@c.us", "Juan", None, ["lead_frio"], "resumen viejo")
    historial = [{"role": "user", "content": "hola", "timestamp": datetime.utcnow()}]
    with patch.object(ficha_mod, "_llamar_llm", new=AsyncMock(return_value={
        "nombre": "Juan", "email": None, "tags": [], "resumen": "OK"
    })) as m:
        await ficha_mod.generar_ficha("54911@c.us", historial, force_full=True)
    prompt_arg = m.await_args.args[0]
    assert "HISTORIAL" in prompt_arg
    assert "FICHA VIGENTE" not in prompt_arg  # no modo incremental


# ============================================================ recalcular_ficha_sync

@pytest.mark.asyncio
async def test_recalcular_sync_ok():
    from agent import memory, ficha as ficha_mod
    await memory.guardar_mensaje("54911@c.us", "user", "Hola soy Juan")
    with patch.object(ficha_mod, "_llamar_llm", new=AsyncMock(return_value={
        "nombre": "Juan", "email": None, "tags": ["lead_frio"], "resumen": "OK"
    })):
        result = await ficha_mod.recalcular_ficha_sync("54911@c.us")
    assert result["status"] == "ok"
    assert result["ficha"].nombre == "Juan"
    assert result["matched_variant"] == "54911@c.us"
    assert "elapsed_ms" in result


@pytest.mark.asyncio
async def test_recalcular_sync_no_history():
    from agent import ficha as ficha_mod
    result = await ficha_mod.recalcular_ficha_sync("54999@c.us")
    assert result["status"] == "no_history"
    assert result["ficha"] is None
    assert result["matched_variant"] is None


@pytest.mark.asyncio
async def test_recalcular_sync_llm_failed():
    from agent import memory, ficha as ficha_mod
    await memory.guardar_mensaje("54911@c.us", "user", "hola")
    with patch.object(ficha_mod, "_llamar_llm", new=AsyncMock(return_value=None)):
        result = await ficha_mod.recalcular_ficha_sync("54911@c.us")
    assert result["status"] == "llm_failed"
    assert result["ficha"] is None
    assert result["matched_variant"] == "54911@c.us"
    assert "reason" in result


@pytest.mark.asyncio
async def test_recalcular_sync_match_por_variante():
    """Historial en @s.whatsapp.net pero endpoint recibe @c.us: debe matchear."""
    from agent import memory, ficha as ficha_mod
    await memory.guardar_mensaje("54911@s.whatsapp.net", "user", "hola")
    with patch.object(ficha_mod, "_llamar_llm", new=AsyncMock(return_value={
        "nombre": "Juan", "email": None, "tags": [], "resumen": "OK"
    })):
        result = await ficha_mod.recalcular_ficha_sync("54911@c.us")
    assert result["status"] == "ok"
    assert result["matched_variant"] == "54911@s.whatsapp.net"


@pytest.mark.asyncio
async def test_recalcular_sync_persist_failed():
    from agent import memory, ficha as ficha_mod
    await memory.guardar_mensaje("54911@c.us", "user", "hola")
    with patch.object(ficha_mod, "_llamar_llm", new=AsyncMock(return_value={
        "nombre": "Juan", "email": None, "tags": [], "resumen": "OK"
    })), patch.object(ficha_mod, "upsert_ficha_auto", new=AsyncMock(side_effect=RuntimeError("db down"))):
        result = await ficha_mod.recalcular_ficha_sync("54911@c.us")
    assert result["status"] == "persist_failed"
    assert "db down" in result["reason"]


# ============================================================ debug_snapshot

@pytest.mark.asyncio
async def test_debug_snapshot_chat_vacio():
    from agent import ficha as ficha_mod
    snap = await ficha_mod.debug_snapshot("54999@c.us")
    assert snap["historial_count"] == 0
    assert snap["matched_variant"] is None
    assert snap["ficha_previa_exists"] is False
    assert snap["ficha_editado_manualmente"] is False


@pytest.mark.asyncio
async def test_debug_snapshot_con_historial_y_ficha():
    from agent import memory, ficha as ficha_mod
    await memory.guardar_mensaje("54911@c.us", "user", "hola")
    await memory.upsert_ficha_manual("54911@c.us", {"nombre": "Juan"})
    snap = await ficha_mod.debug_snapshot("54911@c.us")
    assert snap["historial_count"] == 1
    assert snap["matched_variant"] == "54911@c.us"
    assert snap["ficha_previa_exists"] is True
    assert snap["ficha_editado_manualmente"] is True
    assert snap["ultimo_msg_ts"] is not None


@pytest.mark.asyncio
async def test_debug_snapshot_match_por_variante():
    from agent import memory, ficha as ficha_mod
    await memory.guardar_mensaje("54911@s.whatsapp.net", "user", "hola")
    snap = await ficha_mod.debug_snapshot("54911@c.us")
    assert snap["historial_count"] == 1
    assert snap["matched_variant"] == "54911@s.whatsapp.net"
