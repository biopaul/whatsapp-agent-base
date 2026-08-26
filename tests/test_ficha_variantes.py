# tests/test_ficha_variantes.py — obtener_ficha con fallback de variantes de chat_id

import os
os.environ.setdefault("OPENAI_API_KEY", "test-dummy")
os.environ.setdefault("OPENROUTER_API_KEY", "test-dummy")
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import asyncio
import pytest

from agent import memory


@pytest.fixture(autouse=True)
def _reset_engine(monkeypatch, tmp_path):
    """DB nueva por test para aislamiento total."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    engine = create_async_engine(db_url)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(memory, "engine", engine)
    monkeypatch.setattr(memory, "async_session", session_maker)
    asyncio.run(memory.inicializar_db())
    yield


def _crear_ficha(telefono: str, nombre: str) -> None:
    asyncio.run(memory.upsert_ficha_manual(telefono, {"nombre": nombre}))


def test_match_exacto():
    _crear_ficha("5491155@c.us", "Mayra")
    ficha = asyncio.run(memory.obtener_ficha("5491155@c.us"))
    assert ficha is not None
    assert ficha.nombre == "Mayra"


def test_fallback_c_us_a_s_whatsapp_net():
    """Ficha guardada con @s.whatsapp.net, se busca con @c.us — debe encontrarla."""
    _crear_ficha("5491155@s.whatsapp.net", "Mayra")
    ficha = asyncio.run(memory.obtener_ficha("5491155@c.us"))
    assert ficha is not None
    assert ficha.nombre == "Mayra"


def test_fallback_s_whatsapp_net_a_c_us():
    """Ficha guardada con @c.us, se busca con @s.whatsapp.net — debe encontrarla."""
    _crear_ficha("5491155@c.us", "Mayra")
    ficha = asyncio.run(memory.obtener_ficha("5491155@s.whatsapp.net"))
    assert ficha is not None
    assert ficha.nombre == "Mayra"


def test_fallback_sin_sufijo():
    """Ficha guardada sin sufijo, se busca con @c.us."""
    _crear_ficha("5491155", "Mayra")
    ficha = asyncio.run(memory.obtener_ficha("5491155@c.us"))
    assert ficha is not None
    assert ficha.nombre == "Mayra"


def test_no_encontrada_devuelve_none():
    _crear_ficha("5491155@c.us", "Mayra")
    ficha = asyncio.run(memory.obtener_ficha("9999999@c.us"))
    assert ficha is None


def test_prioridad_match_exacto_sobre_variante():
    """Si hay una ficha con match exacto Y otra con variante, prima la exacta."""
    _crear_ficha("5491155@c.us", "Mayra")
    _crear_ficha("5491155@s.whatsapp.net", "OTRO_NOMBRE_NO_DEBERIA_APARECER")
    ficha = asyncio.run(memory.obtener_ficha("5491155@c.us"))
    assert ficha is not None
    assert ficha.nombre == "Mayra"
