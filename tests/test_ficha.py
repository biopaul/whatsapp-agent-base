"""Tests para la Ficha del cliente (edicion 100% humana desde 1.12.0)."""

import os
import pytest
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("OPENROUTER_API_KEY", "sk-or-test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")


@pytest.fixture(autouse=True)
async def _fresh_db(monkeypatch):
    """DB in-memory limpia por test."""
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    import importlib
    from agent import memory
    importlib.reload(memory)
    await memory.inicializar_db()
    yield


# ============================================================ build_ficha_context

def test_build_context_none_devuelve_vacio():
    from agent.ficha import build_ficha_context
    assert build_ficha_context(None) == ""


@pytest.mark.asyncio
async def test_build_context_ficha_completa():
    from agent import memory
    from agent.ficha import build_ficha_context
    row = memory.Ficha(
        telefono="54911@c.us", nombre="Ana Paula", email="ana@x.com",
        tags=["cliente_activo", "vip"],
        resumen="Compro plan anual, prefiere pagos con MP.",
        ultima_actualizacion=datetime.utcnow(),
    )
    ctx = build_ficha_context(row)
    assert "## Datos verificados del cliente" in ctx
    assert "Ana Paula" in ctx
    assert "ana@x.com" in ctx
    assert "cliente_activo, vip" in ctx
    assert "plan anual" in ctx
    assert "verificados por un operador humano" in ctx
    assert "prima esta ficha" in ctx


@pytest.mark.asyncio
async def test_build_context_omite_nulos():
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
async def test_build_context_ficha_vacia_devuelve_vacio():
    from agent import memory
    from agent.ficha import build_ficha_context
    row = memory.Ficha(
        telefono="x", nombre=None, email=None, tags=[], resumen=None,
        ultima_actualizacion=None,
    )
    assert build_ficha_context(row) == ""


def test_build_context_no_incluye_label_ultima_interaccion():
    """El label engañoso 'Ultima interaccion' se elimino en 1.12.0."""
    from agent import memory
    from agent.ficha import build_ficha_context
    row = memory.Ficha(
        telefono="x", nombre="Juan", email=None, tags=[], resumen=None,
        ultima_actualizacion=datetime.utcnow(),
    )
    ctx = build_ficha_context(row)
    assert "Ultima interaccion" not in ctx
    assert "Ficha actualizada" not in ctx  # tampoco el rename intermedio


# ============================================================ Vocabulario tags

def test_vocabulario_incluye_categorias_esperadas():
    from agent.ficha import TAGS_VOCABULARIO_SUGERIDO
    esperados = {"lead_nuevo", "lead_calificado", "cita_agendada",
                 "pago_verificado", "cliente_activo", "vip"}
    assert esperados.issubset(set(TAGS_VOCABULARIO_SUGERIDO))


def test_vocabulario_todo_snake_case_lowercase():
    from agent.ficha import TAGS_VOCABULARIO_SUGERIDO
    for tag in TAGS_VOCABULARIO_SUGERIDO:
        assert tag == tag.lower()
        assert " " not in tag


# ============================================================ CRUD manual

@pytest.mark.asyncio
async def test_upsert_manual_crea_nueva_con_flag():
    from agent import memory
    row = await memory.upsert_ficha_manual("54911@c.us", {
        "nombre": "Ana", "tags": ["vip"], "resumen": "cliente premium"
    })
    assert row.nombre == "Ana"
    assert row.tags == ["vip"]
    assert row.editado_manualmente is True
    assert row.editado_en is not None


@pytest.mark.asyncio
async def test_upsert_manual_actualiza_solo_campos_presentes():
    from agent import memory
    await memory.upsert_ficha_manual("x", {
        "nombre": "Ana", "email": "a@x.com", "tags": ["vip"], "resumen": "r"
    })
    row = await memory.upsert_ficha_manual("x", {"nombre": "Ana Paula"})
    # nombre actualizado, el resto sin tocar
    assert row.nombre == "Ana Paula"
    assert row.email == "a@x.com"
    assert row.tags == ["vip"]
    assert row.resumen == "r"


@pytest.mark.asyncio
async def test_upsert_manual_ignora_campos_no_permitidos():
    from agent import memory
    row = await memory.upsert_ficha_manual("x", {
        "nombre": "Ana",
        "editado_manualmente": False,  # ignorado (siempre True desde PUT)
        "primer_contacto": "hackeado",
    })
    assert row.nombre == "Ana"
    assert row.editado_manualmente is True


@pytest.mark.asyncio
async def test_upsert_manual_acepta_tags_custom():
    """PUT no valida contra vocab. Tag custom se guarda tal cual (Q7=C)."""
    from agent import memory
    row = await memory.upsert_ficha_manual("x", {
        "tags": ["tag_custom_del_negocio", "otro_random"]
    })
    assert "tag_custom_del_negocio" in row.tags
    assert "otro_random" in row.tags


# ============================================================ Backfill Contacto→Ficha

@pytest.mark.asyncio
async def test_backfill_copia_contactos(monkeypatch):
    """Backfill sigue vigente (Q3=B) — seed inicial de nombre/email."""
    from agent import memory
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
    assert row.editado_manualmente is False  # seed no cuenta como edicion


@pytest.mark.asyncio
async def test_backfill_no_pisa_ficha_existente():
    """Idempotente: si ya hay ficha (edicion humana), no la toca."""
    from agent import memory
    await memory.upsert_ficha_manual("54999@c.us", {"nombre": "EditadoManual"})
    async with memory.async_session() as s:
        s.add(memory.Contacto(
            telefono="54999@c.us", nombre="LegacyNoDeberiaGanar",
            primer_contacto=datetime.utcnow(), actualizado_en=datetime.utcnow(),
        ))
        await s.commit()
    await memory._backfill_contactos_a_fichas()
    row = await memory.obtener_ficha("54999@c.us")
    assert row.nombre == "EditadoManual"


# ============================================================ Variantes chat_id

@pytest.mark.asyncio
async def test_variantes_matcheo_c_us_directo():
    from agent import memory
    await memory.guardar_mensaje("54911@c.us", "user", "hola")
    msgs, matched = await memory.obtener_historial_variantes("54911@c.us")
    assert len(msgs) == 1
    assert matched == "54911@c.us"


@pytest.mark.asyncio
async def test_variantes_fallback_s_whatsapp_net():
    from agent import memory
    await memory.guardar_mensaje("54911@s.whatsapp.net", "user", "hola")
    msgs, matched = await memory.obtener_historial_variantes("54911@c.us")
    assert len(msgs) == 1
    assert matched == "54911@s.whatsapp.net"


@pytest.mark.asyncio
async def test_variantes_sin_matches_devuelve_vacio():
    from agent import memory
    msgs, matched = await memory.obtener_historial_variantes("54999@c.us")
    assert msgs == []
    assert matched is None


# ============================================================ debug_snapshot

@pytest.mark.asyncio
async def test_debug_snapshot_chat_vacio():
    from agent.ficha import debug_snapshot
    snap = await debug_snapshot("54999@c.us")
    assert snap["historial_count"] == 0
    assert snap["matched_variant"] is None
    assert snap["ficha_existe"] is False
    assert snap["bloque_que_se_inyectaria"] == ""


@pytest.mark.asyncio
async def test_debug_snapshot_con_historial_y_ficha():
    from agent import memory
    from agent.ficha import debug_snapshot
    await memory.guardar_mensaje("54911@c.us", "user", "hola")
    await memory.upsert_ficha_manual("54911@c.us", {
        "nombre": "Ana", "tags": ["vip"]
    })
    snap = await debug_snapshot("54911@c.us")
    assert snap["historial_count"] == 1
    assert snap["matched_variant"] == "54911@c.us"
    assert snap["ficha_existe"] is True
    assert snap["ficha_editada_en"] is not None
    assert "## Datos verificados del cliente" in snap["bloque_que_se_inyectaria"]
    assert "Ana" in snap["bloque_que_se_inyectaria"]


@pytest.mark.asyncio
async def test_debug_snapshot_ficha_vacia_no_bloque():
    from agent import memory
    from agent.ficha import debug_snapshot
    await memory.guardar_mensaje("54911@c.us", "user", "hola")
    snap = await debug_snapshot("54911@c.us")
    assert snap["ficha_existe"] is False
    assert snap["bloque_que_se_inyectaria"] == ""


# ============================================================ Filosofia (semantic)

def test_no_hay_generar_ficha_ni_llamar_llm():
    """En 1.12.0 eliminamos toda la generacion LLM. Import debe fallar."""
    from agent import ficha as ficha_mod
    assert not hasattr(ficha_mod, "generar_ficha")
    assert not hasattr(ficha_mod, "_llamar_llm")
    assert not hasattr(ficha_mod, "recalcular_ficha_sync")
    assert not hasattr(ficha_mod, "recalcular_ficha_background")
    assert not hasattr(ficha_mod, "detectar_cierre_bloque")


def test_no_hay_upsert_ficha_auto():
    """upsert_ficha_auto se elimino: la ficha se escribe solo desde PUT humano."""
    from agent import memory
    assert not hasattr(memory, "upsert_ficha_auto")
    assert not hasattr(memory, "guardar_ficha_desde_tool")
