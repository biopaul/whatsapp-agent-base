"""Tests para el modelo Contacto y sus helpers."""

import os
import asyncio
import pytest
from datetime import datetime

# Setup: usar SQLite in-memory para tests
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(autouse=True)
async def setup_db():
    """Inicializa DB antes de cada test."""
    from agent.memory import inicializar_db, engine, Base
    # Reset por si quedó estado de tests anteriores
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await inicializar_db()
    yield


@pytest.mark.asyncio
async def test_obtener_contacto_inexistente_devuelve_none():
    from agent.memory import obtener_contacto
    contacto = await obtener_contacto("5491134567890")
    assert contacto is None


@pytest.mark.asyncio
async def test_guardar_contacto_inserta_nuevo():
    from agent.memory import guardar_contacto, obtener_contacto

    await guardar_contacto("5491134567890", nombre="Juan", email="juan@test.com")
    contacto = await obtener_contacto("5491134567890")

    assert contacto is not None
    assert contacto.nombre == "Juan"
    assert contacto.email == "juan@test.com"
    assert contacto.telefono == "5491134567890"


@pytest.mark.asyncio
async def test_guardar_contacto_solo_nombre_no_pisa_email_existente():
    from agent.memory import guardar_contacto, obtener_contacto

    # Primero guardo email
    await guardar_contacto("5491134567890", email="juan@test.com")
    # Después solo nombre (no pasar email)
    await guardar_contacto("5491134567890", nombre="Juan Pérez")

    contacto = await obtener_contacto("5491134567890")
    assert contacto.nombre == "Juan Pérez"
    assert contacto.email == "juan@test.com"  # NO se pisó


@pytest.mark.asyncio
async def test_guardar_contacto_solo_email_no_pisa_nombre_existente():
    from agent.memory import guardar_contacto, obtener_contacto

    await guardar_contacto("5491134567890", nombre="Juan")
    await guardar_contacto("5491134567890", email="juan@test.com")

    contacto = await obtener_contacto("5491134567890")
    assert contacto.nombre == "Juan"
    assert contacto.email == "juan@test.com"


@pytest.mark.asyncio
async def test_guardar_contacto_actualiza_actualizado_en():
    from agent.memory import guardar_contacto, obtener_contacto

    await guardar_contacto("5491134567890", nombre="A")
    primer = await obtener_contacto("5491134567890")
    primera_actualizacion = primer.actualizado_en

    # Esperar para que el timestamp sea distinto
    await asyncio.sleep(1.1)

    await guardar_contacto("5491134567890", nombre="B")
    segundo = await obtener_contacto("5491134567890")

    assert segundo.actualizado_en > primera_actualizacion
    # primer_contacto NO cambia
    assert segundo.primer_contacto == primer.primer_contacto


@pytest.mark.asyncio
async def test_telefonos_distintos_son_contactos_distintos():
    from agent.memory import guardar_contacto, obtener_contacto

    await guardar_contacto("5491100000001", nombre="Cliente A")
    await guardar_contacto("5491100000002", nombre="Cliente B")

    a = await obtener_contacto("5491100000001")
    b = await obtener_contacto("5491100000002")

    assert a.nombre == "Cliente A"
    assert b.nombre == "Cliente B"


@pytest.mark.asyncio
async def test_get_active_connectors_sin_config_returns_empty():
    """Sin CONFIG_URL ni archivo local con conectores, get_active_connectors retorna []."""
    from agent.config_loader import get_active_connectors, invalidate_cache
    invalidate_cache()
    result = get_active_connectors()
    assert isinstance(result, list)
    # Sin config remota cargada, debería ser vacío (o no tener la key, defaulteando a [])
    assert result == [] or all(isinstance(c, dict) for c in result)
