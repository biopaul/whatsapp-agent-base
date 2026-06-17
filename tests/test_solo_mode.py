# tests/test_solo_mode.py — Modo individual / Sin equipo

import os
os.environ.setdefault("OPENAI_API_KEY", "test-dummy")
os.environ.setdefault("OPENROUTER_API_KEY", "test-dummy")

import importlib
from unittest.mock import patch

from agent import config_loader


def _mock_cfg(solo=False, extra=None):
    cfg = {"prompts": {"system_prompt": "Sos asistente de Lupe."},
           "business": {}, "timezone": {"tz_offset": -3},
           "solo_mode": solo}
    if extra:
        cfg.update(extra)
    return cfg


def test_is_solo_mode_default_false():
    with patch.object(config_loader, "get_config", return_value=_mock_cfg(solo=False)):
        assert config_loader.is_solo_mode() is False


def test_is_solo_mode_true_when_flag_set():
    with patch.object(config_loader, "get_config", return_value=_mock_cfg(solo=True)):
        assert config_loader.is_solo_mode() is True


def test_is_solo_mode_false_when_key_missing():
    with patch.object(config_loader, "get_config", return_value={"business": {}}):
        assert config_loader.is_solo_mode() is False


def test_is_solo_mode_truthy_coercion():
    """Valores 1/0 del config remoto deberian coercionar a bool."""
    with patch.object(config_loader, "get_config", return_value=_mock_cfg(solo=1)):
        assert config_loader.is_solo_mode() is True
    with patch.object(config_loader, "get_config", return_value=_mock_cfg(solo=0)):
        assert config_loader.is_solo_mode() is False


# --- brain: bloque dinamico segun modo ---

def test_brain_uses_team_block_by_default():
    from agent import brain
    importlib.reload(brain)
    with patch.object(brain, "is_solo_mode", return_value=False):
        prompt = brain._whatsapp_naturalness()
    assert "ESCALACIÓN A HUMANO" in prompt
    assert "SÍ tienes capacidad de derivar" in prompt
    assert "MODO INDIVIDUAL" not in prompt


def test_brain_uses_solo_block_when_active():
    from agent import brain
    importlib.reload(brain)
    with patch.object(brain, "is_solo_mode", return_value=True):
        prompt = brain._whatsapp_naturalness()
    assert "MODO INDIVIDUAL" in prompt
    assert "NO HAY EQUIPO" in prompt
    assert "ESCALACIÓN A HUMANO" not in prompt
    # Debe instruir al modelo de NO emitir el marcador.
    assert "NUNCA emitas" in prompt
