"""Tests para get_tts_config en config_loader."""

import pytest
from unittest.mock import patch


def test_get_tts_config_devuelve_disabled_si_no_hay_tts_field():
    from agent import config_loader

    with patch.object(config_loader, "get_config",
                      return_value={"agente": {"nombre": "X"}}):
        result = config_loader.get_tts_config()
    assert result == {"enabled": False}


def test_get_tts_config_extrae_tts_field():
    from agent import config_loader

    fake_config = {
        "agente": {"nombre": "X"},
        "tts": {
            "enabled": True,
            "voice_id": "AR_F_v1",
            "model": "eleven_turbo_v2_5",
            "max_chars_per_message": 640,
            "seconds_remaining": 7480,
        },
    }
    with patch.object(config_loader, "get_config", return_value=fake_config):
        result = config_loader.get_tts_config()
    assert result["enabled"] is True
    assert result["voice_id"] == "AR_F_v1"
    assert result["max_chars_per_message"] == 640
    assert result["seconds_remaining"] == 7480


def test_get_tts_config_normaliza_seconds_negativos():
    """Si seconds_remaining viene negativo, clampea a 0."""
    from agent import config_loader

    fake_config = {"tts": {"enabled": True, "seconds_remaining": -5, "voice_id": "X"}}
    with patch.object(config_loader, "get_config", return_value=fake_config):
        result = config_loader.get_tts_config()
    assert result["seconds_remaining"] == 0


def test_get_tts_config_devuelve_disabled_si_config_no_es_dict():
    """Edge: si el cached config retorna algo que no es dict, default disabled."""
    from agent import config_loader

    with patch.object(config_loader, "get_config", return_value=None):
        result = config_loader.get_tts_config()
    assert result == {"enabled": False}
