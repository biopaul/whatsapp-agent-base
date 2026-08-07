"""Tests para el comando /models (helper _respuesta_models)."""

import os
import pytest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_models_cmd.db")
os.environ.setdefault("OPENROUTER_API_KEY", "sk-or-test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")


def test_muestra_ambos_tiers_configurados():
    from agent import main as agent_main
    cfg = {
        "quick": ["anthropic/claude-3-5-haiku", "openai/gpt-4o-mini"],
        "full": ["anthropic/claude-sonnet-4-6"],
    }
    with patch.object(agent_main, "get_ai_models", return_value=cfg):
        out = agent_main._respuesta_models()
    assert "anthropic/claude-3-5-haiku" in out
    assert "openai/gpt-4o-mini" in out
    assert "anthropic/claude-sonnet-4-6" in out
    assert "Rapido" in out
    assert "Completo" in out


def test_muestra_placeholder_si_quick_vacio():
    from agent import main as agent_main
    cfg = {"quick": [], "full": ["anthropic/claude-sonnet-4-6"]}
    with patch.object(agent_main, "get_ai_models", return_value=cfg):
        out = agent_main._respuesta_models()
    assert "(no configurado)" in out
    assert "anthropic/claude-sonnet-4-6" in out


def test_muestra_placeholder_si_full_vacio():
    from agent import main as agent_main
    cfg = {"quick": ["openai/gpt-4o-mini"], "full": []}
    with patch.object(agent_main, "get_ai_models", return_value=cfg):
        out = agent_main._respuesta_models()
    assert "openai/gpt-4o-mini" in out
    assert "(no configurado)" in out


def test_ambos_tiers_vacios():
    from agent import main as agent_main
    cfg = {"quick": [], "full": []}
    with patch.object(agent_main, "get_ai_models", return_value=cfg):
        out = agent_main._respuesta_models()
    assert out.count("(no configurado)") == 2


def test_config_sin_claves_no_rompe():
    """Robustez: si get_ai_models devuelve dict incompleto, no explota."""
    from agent import main as agent_main
    with patch.object(agent_main, "get_ai_models", return_value={}):
        out = agent_main._respuesta_models()
    assert "(no configurado)" in out


def test_lista_multiples_modelos_por_tier_separados_por_coma():
    from agent import main as agent_main
    cfg = {
        "quick": ["a/model-1", "b/model-2", "c/model-3"],
        "full": ["x/premium"],
    }
    with patch.object(agent_main, "get_ai_models", return_value=cfg):
        out = agent_main._respuesta_models()
    assert "a/model-1, b/model-2, c/model-3" in out
