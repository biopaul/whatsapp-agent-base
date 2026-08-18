# tests/test_ficha_kill_switch.py — verifica FICHA_INYECCION_ACTIVA

import os
os.environ.setdefault("OPENAI_API_KEY", "test-dummy")
os.environ.setdefault("OPENROUTER_API_KEY", "test-dummy")

import importlib


def _reload_brain():
    from agent import brain as brain_mod
    importlib.reload(brain_mod)
    return brain_mod


def test_default_es_false(monkeypatch):
    monkeypatch.delenv("FICHA_INYECCION_ACTIVA", raising=False)
    brain_mod = _reload_brain()
    assert brain_mod.FICHA_INYECCION_ACTIVA is False


def test_true_activa(monkeypatch):
    monkeypatch.setenv("FICHA_INYECCION_ACTIVA", "true")
    brain_mod = _reload_brain()
    assert brain_mod.FICHA_INYECCION_ACTIVA is True


def test_TRUE_mayuscula_activa(monkeypatch):
    monkeypatch.setenv("FICHA_INYECCION_ACTIVA", "TRUE")
    brain_mod = _reload_brain()
    assert brain_mod.FICHA_INYECCION_ACTIVA is True


def test_valor_arbitrario_es_false(monkeypatch):
    monkeypatch.setenv("FICHA_INYECCION_ACTIVA", "yes")
    brain_mod = _reload_brain()
    assert brain_mod.FICHA_INYECCION_ACTIVA is False
