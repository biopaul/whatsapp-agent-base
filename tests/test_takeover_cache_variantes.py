# tests/test_takeover_cache_variantes.py — cache lookup insensible al sufijo
#
# Escenario: el push del plugin cachea con "X@c.us" (canonical) pero el
# webhook posterior de WAHA llega con "X@lid" — o viceversa. La cache local
# debe encontrarse ambas variantes por match del numero.

import os
os.environ.setdefault("OPENAI_API_KEY", "test-dummy")
os.environ.setdefault("OPENROUTER_API_KEY", "test-dummy")
os.environ["TAKEOVER_URL_BASE"] = "http://takeover.test"

import asyncio
import importlib
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture(autouse=True)
def _reset():
    from agent import takeover
    importlib.reload(takeover)
    yield


# --- Helper _cache_variantes ---

def test_variantes_incluye_lid_c_us_wa_net_sin_sufijo():
    from agent.takeover import _cache_variantes
    variantes = _cache_variantes("5492613410679@lid")
    assert "5492613410679@lid" in variantes
    assert "5492613410679@c.us" in variantes
    assert "5492613410679@s.whatsapp.net" in variantes
    assert "5492613410679" in variantes


def test_variantes_prioriza_input_original():
    from agent.takeover import _cache_variantes
    variantes = _cache_variantes("5492613410679@lid")
    assert variantes[0] == "5492613410679@lid"


def test_variantes_input_vacio():
    from agent.takeover import _cache_variantes
    assert _cache_variantes("") == []


# --- is_chat_in_manual_mode con match cross-suffix ---

def test_cache_con_c_us_matchea_lookup_por_lid():
    """Push cachea @c.us, webhook llega con @lid → debe encontrar."""
    from agent import takeover
    future = datetime.now(timezone.utc) + timedelta(minutes=30)
    takeover._cache["5492613410679@c.us"] = takeover.TakeoverEntry(
        mode="manual", expires_at=future
    )
    result = asyncio.run(takeover.is_chat_in_manual_mode("5492613410679@lid"))
    assert result is True


def test_cache_con_lid_matchea_lookup_por_c_us():
    """Poll cachea @lid, luego webhook o request usa @c.us → debe encontrar."""
    from agent import takeover
    future = datetime.now(timezone.utc) + timedelta(minutes=30)
    takeover._cache["5492613410679@lid"] = takeover.TakeoverEntry(
        mode="manual", expires_at=future
    )
    result = asyncio.run(takeover.is_chat_in_manual_mode("5492613410679@c.us"))
    assert result is True


def test_cache_prioriza_match_exacto_sobre_variantes():
    """Si hay entry exacta + entry con otra variante, gana la exacta."""
    from agent import takeover
    now = datetime.now(timezone.utc)
    # Exacta = manual vencida (no debe activar); variante = manual vigente
    takeover._cache["5492613410679@lid"] = takeover.TakeoverEntry(
        mode="manual", expires_at=now - timedelta(minutes=5)
    )
    takeover._cache["5492613410679@c.us"] = takeover.TakeoverEntry(
        mode="manual", expires_at=now + timedelta(minutes=30)
    )
    # Con match exacto vencido, is_chat retorna False sin fallback a variante
    # (el path es: chequeo cache exacta -> no valida -> repollea)
    from unittest.mock import AsyncMock, patch
    with patch("agent.takeover._poll_chat",
               new=AsyncMock(return_value=takeover.TakeoverEntry(
                   mode="auto", last_polled=now))):
        result = asyncio.run(takeover.is_chat_in_manual_mode("5492613410679@lid"))
        # La entry exacta @lid dice manual vencido, se re-pollea → auto
        assert result is False


# --- apply_push_update idempotencia cross-suffix ---

def test_push_con_c_us_es_idempotente_si_ya_hay_lid_mismo_estado():
    """Push llega con @c.us pero ya hay entry @lid en manual → unchanged."""
    from agent import takeover
    future = datetime.now(timezone.utc) + timedelta(minutes=40)
    takeover._cache["5492613410679@lid"] = takeover.TakeoverEntry(
        mode="manual", expires_at=future
    )
    result = takeover.apply_push_update(
        "5492613410679@c.us", "manual", future
    )
    assert result == "unchanged"


def test_push_con_c_us_borra_entry_vieja_en_lid():
    """Cuando el push updatea, si habia una entry con otra variante, se elimina.
    No queremos 2 estados divergentes del mismo chat en cache."""
    from agent import takeover
    # Entry vieja @lid en auto
    takeover._cache["5492613410679@lid"] = takeover.TakeoverEntry(mode="auto")
    # Push con @c.us pasa a manual
    future = datetime.now(timezone.utc) + timedelta(minutes=40)
    result = takeover.apply_push_update("5492613410679@c.us", "manual", future)
    assert result == "updated"
    # Entry @lid debe haber sido eliminada
    assert "5492613410679@lid" not in takeover._cache
    # Entry @c.us guardada
    assert takeover._cache["5492613410679@c.us"].mode == "manual"


def test_push_sin_entry_previa_solo_crea():
    """Sin entry previa, no borra nada."""
    from agent import takeover
    future = datetime.now(timezone.utc) + timedelta(minutes=40)
    result = takeover.apply_push_update("chat_nuevo@c.us", "manual", future)
    assert result == "updated"
    assert takeover._cache["chat_nuevo@c.us"].mode == "manual"


def test_push_variantes_transicion_manual_lid_a_auto_c_us_preserva_last_manual_until():
    """Manual @lid → auto @c.us: preservar last_manual_until en la nueva entry."""
    from agent import takeover
    manual_expires = datetime.now(timezone.utc) + timedelta(minutes=40)
    takeover._cache["5492613410679@lid"] = takeover.TakeoverEntry(
        mode="manual", expires_at=manual_expires
    )
    result = takeover.apply_push_update("5492613410679@c.us", "auto")
    assert result == "updated"
    entry = takeover._cache["5492613410679@c.us"]
    assert entry.mode == "auto"
    assert entry.last_manual_until == manual_expires
    # La entry @lid vieja fue eliminada
    assert "5492613410679@lid" not in takeover._cache
