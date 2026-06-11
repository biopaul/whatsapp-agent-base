"""Tests para el catalogo de voces TTS."""

import pytest


def test_resolve_voice_id_ok():
    from agent.tts_voices import resolve_voice_id, VOICES
    # Las 6 keys curadas existen
    for key in ["AR_M_v1", "AR_F_v1", "CO_M_v1", "CO_F_v1", "ES_M_v1", "ES_F_v1"]:
        result = resolve_voice_id(key)
        assert result is not None
        assert isinstance(result, str)
        assert len(result) > 0


def test_resolve_voice_id_unknown_returns_none():
    from agent.tts_voices import resolve_voice_id
    assert resolve_voice_id("XX_X_v99") is None
    assert resolve_voice_id("") is None
    assert resolve_voice_id(None) is None


def test_voices_dict_estructura():
    from agent.tts_voices import VOICES
    assert len(VOICES) == 6
    for key, info in VOICES.items():
        assert "voice_id" in info
        assert "label" in info
        assert isinstance(info["voice_id"], str)
        assert isinstance(info["label"], str)
