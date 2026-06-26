# tests/test_replay_dedup.py — defensas A + B contra replay de WAHA

import os
os.environ.setdefault("OPENAI_API_KEY", "test-dummy")
os.environ.setdefault("OPENROUTER_API_KEY", "test-dummy")

import asyncio
import importlib
import time
from unittest.mock import AsyncMock, MagicMock

from agent.providers.waha import ProveedorWAHA


def _request(payload: dict, event: str = "message"):
    """Mock de Request FastAPI con body json."""
    req = MagicMock()
    req.json = AsyncMock(return_value={"event": event, "payload": payload})
    return req


def _parse(payload: dict):
    provider = ProveedorWAHA()
    return asyncio.run(provider.parsear_webhook(_request(payload)))


# --- Defensa B: gate por timestamp en el parser ---

def test_skip_mensaje_muy_viejo():
    """Mensaje con timestamp de hace 1 hora se descarta como replay."""
    msgs = _parse({
        "fromMe": False,
        "from": "5491155@c.us",
        "id": "viejo123",
        "body": "hola",
        "timestamp": time.time() - 3600,
    })
    assert msgs == []


def test_acepta_mensaje_reciente():
    """Mensaje dentro de la ventana se procesa normal."""
    msgs = _parse({
        "fromMe": False,
        "from": "5491155@c.us",
        "id": "fresco1",
        "body": "hola",
        "timestamp": time.time() - 30,
    })
    assert len(msgs) == 1
    assert msgs[0].texto == "hola"
    assert msgs[0].mensaje_id == "fresco1"


def test_payload_sin_timestamp_procesa_normal():
    """Backward compat: si no viene timestamp, no se aplica gate."""
    msgs = _parse({
        "fromMe": False,
        "from": "5491155@c.us",
        "id": "sin_ts",
        "body": "hola",
    })
    assert len(msgs) == 1
    assert msgs[0].texto == "hola"


def test_timestamp_invalido_procesa_normal():
    """Si timestamp no se puede parsear, no rompe — procesa normal."""
    msgs = _parse({
        "fromMe": False,
        "from": "5491155@c.us",
        "id": "ts_basura",
        "body": "hola",
        "timestamp": "no-es-un-numero",
    })
    assert len(msgs) == 1


def test_timestamp_dentro_de_la_ventana():
    """4 min de antigüedad (default 300s) -> se procesa."""
    msgs = _parse({
        "fromMe": False,
        "from": "5491155@c.us",
        "id": "borde",
        "body": "hola",
        "timestamp": time.time() - 240,
    })
    assert len(msgs) == 1


def test_timestamp_fuera_de_la_ventana():
    """310s (5 min y 10s) -> skip."""
    msgs = _parse({
        "fromMe": False,
        "from": "5491155@c.us",
        "id": "borde_fuera",
        "body": "hola",
        "timestamp": time.time() - 310,
    })
    assert msgs == []


def test_gate_disabled_con_env_zero(monkeypatch):
    """Si WAHA_MAX_MESSAGE_AGE_SEC=0, el gate queda deshabilitado."""
    monkeypatch.setenv("WAHA_MAX_MESSAGE_AGE_SEC", "0")
    from agent.providers import waha as waha_mod
    importlib.reload(waha_mod)
    provider = waha_mod.ProveedorWAHA()
    msgs = asyncio.run(provider.parsear_webhook(_request({
        "fromMe": False,
        "from": "5491155@c.us",
        "id": "muy_viejo_pero_gate_off",
        "body": "hola",
        "timestamp": time.time() - 86400,  # 1 día atrás
    })))
    assert len(msgs) == 1
    monkeypatch.setenv("WAHA_MAX_MESSAGE_AGE_SEC", "300")
    importlib.reload(waha_mod)
