# tests/test_config_loader_notify_priority.py — prioridad del panel WP
# sobre NOTIFY_PHONE/NOTIFY_NAME env (y TZ_OFFSET backward-compat).

import os
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("OPENROUTER_API_KEY", "sk-test")

import importlib
from unittest.mock import patch

import pytest


def _reload():
    from agent import config_loader
    importlib.reload(config_loader)
    return config_loader


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("NOTIFY_PHONE", "NOTIFY_NAME", "TZ_OFFSET"):
        monkeypatch.delenv(k, raising=False)
    yield


def _cfg_remote(cfg):
    """Patch _fetch_remote para devolver el config dado (bypass cache)."""
    from agent import config_loader
    config_loader._cache = None
    config_loader._cache_ts = 0.0
    return patch.object(config_loader, "_fetch_remote", return_value=cfg)


# --- NOTIFY_PHONE ---

def test_panel_gana_sobre_env_notify_phone(monkeypatch):
    """config.json con notify_phone + env tambien seteada -> gana el panel."""
    monkeypatch.setenv("NOTIFY_PHONE", "OLD_FROM_RAILWAY")
    cl = _reload()
    cfg_wp = {"notifications": {"notify_phone": "NEW_FROM_PANEL"}}
    with _cfg_remote(cfg_wp):
        assert cl.get_notify_phone() == "NEW_FROM_PANEL"


def test_env_fallback_notify_phone_cuando_panel_vacio(monkeypatch):
    """config.json sin notify_phone (o vacio) + env -> usa env."""
    monkeypatch.setenv("NOTIFY_PHONE", "FROM_RAILWAY")
    cl = _reload()
    cfg_wp = {"notifications": {}}  # sin notify_phone
    with _cfg_remote(cfg_wp):
        assert cl.get_notify_phone() == "FROM_RAILWAY"


def test_env_fallback_notify_phone_cuando_panel_whitespace(monkeypatch):
    """config.json con '   ' (whitespace) + env -> env gana (el .strip() lo trata como vacio)."""
    monkeypatch.setenv("NOTIFY_PHONE", "FROM_RAILWAY")
    cl = _reload()
    cfg_wp = {"notifications": {"notify_phone": "   "}}
    with _cfg_remote(cfg_wp):
        assert cl.get_notify_phone() == "FROM_RAILWAY"


def test_sin_env_sin_panel_notify_phone_devuelve_vacio():
    """Sin env ni panel -> empty string (comportamiento legacy)."""
    cl = _reload()
    cfg_wp = {"notifications": {}}
    with _cfg_remote(cfg_wp):
        assert cl.get_notify_phone() == ""


def test_sin_env_pero_con_panel_notify_phone():
    """Sin env, panel con valor -> panel gana."""
    cl = _reload()
    cfg_wp = {"notifications": {"notify_phone": "PANEL_ONLY"}}
    with _cfg_remote(cfg_wp):
        assert cl.get_notify_phone() == "PANEL_ONLY"


# --- NOTIFY_NAME (mismo set) ---

def test_panel_gana_sobre_env_notify_name(monkeypatch):
    monkeypatch.setenv("NOTIFY_NAME", "OLD_NAME")
    cl = _reload()
    cfg_wp = {"notifications": {"notify_name": "NEW_NAME"}}
    with _cfg_remote(cfg_wp):
        assert cl.get_notify_name() == "NEW_NAME"


def test_env_fallback_notify_name_cuando_panel_vacio(monkeypatch):
    monkeypatch.setenv("NOTIFY_NAME", "FROM_RAILWAY")
    cl = _reload()
    cfg_wp = {"notifications": {}}
    with _cfg_remote(cfg_wp):
        assert cl.get_notify_name() == "FROM_RAILWAY"


def test_env_fallback_notify_name_cuando_panel_whitespace(monkeypatch):
    monkeypatch.setenv("NOTIFY_NAME", "FROM_RAILWAY")
    cl = _reload()
    cfg_wp = {"notifications": {"notify_name": "   "}}
    with _cfg_remote(cfg_wp):
        assert cl.get_notify_name() == "FROM_RAILWAY"


# --- Ortogonalidad: cada campo se evalua por separado ---

def test_notify_phone_del_panel_notify_name_del_env(monkeypatch):
    """Mezclado: panel manda phone, env manda name."""
    monkeypatch.setenv("NOTIFY_NAME", "NAME_FROM_RAILWAY")
    cl = _reload()
    cfg_wp = {"notifications": {"notify_phone": "PHONE_FROM_PANEL"}}
    with _cfg_remote(cfg_wp):
        assert cl.get_notify_phone() == "PHONE_FROM_PANEL"
        assert cl.get_notify_name() == "NAME_FROM_RAILWAY"


# --- TZ_OFFSET sigue siendo backward compat (env override funciona) ---

def test_tz_offset_env_override_sigue_funcionando(monkeypatch):
    """TZ_OFFSET env mantiene prioridad historica (no se cambio por este fix)."""
    monkeypatch.setenv("TZ_OFFSET", "-5")
    cl = _reload()
    cfg_wp = {"notifications": {}, "timezone": {"tz_offset": -3}}
    with _cfg_remote(cfg_wp):
        assert cl.get_tz_offset() == -5
