# tests/test_retoma.py — Retoma de conversación después de pausa

import os
os.environ.setdefault("OPENAI_API_KEY", "test-dummy")
os.environ.setdefault("OPENROUTER_API_KEY", "test-dummy")

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from agent.main import (
    _formatear_tiempo_pausa,
    _horas_desde_ultimo_mensaje,
    RETOMA_HORAS_THRESHOLD,
    HISTORIAL_RETOMA_LIMIT,
)


# --- _formatear_tiempo_pausa ---

def test_formato_menos_de_una_hora():
    assert _formatear_tiempo_pausa(0.3) == "hace alrededor de una hora"
    assert _formatear_tiempo_pausa(1) == "hace alrededor de una hora"


def test_formato_horas_intermedias():
    assert _formatear_tiempo_pausa(5) == "hace 5 horas"
    assert _formatear_tiempo_pausa(12) == "hace 12 horas"
    assert _formatear_tiempo_pausa(20) == "hace 20 horas"


def test_formato_ayer():
    # 24h = ayer redondeo a 1 día
    assert _formatear_tiempo_pausa(24) == "ayer"
    assert _formatear_tiempo_pausa(30) == "ayer"


def test_formato_dias():
    assert _formatear_tiempo_pausa(48) == "hace 2 días"
    assert _formatear_tiempo_pausa(72) == "hace 3 días"
    assert _formatear_tiempo_pausa(120) == "hace 5 días"


def test_formato_semanas():
    assert _formatear_tiempo_pausa(168) == "hace una semana"
    assert _formatear_tiempo_pausa(336) == "hace 2 semanas"
    assert _formatear_tiempo_pausa(504) == "hace 3 semanas"


def test_formato_meses():
    assert _formatear_tiempo_pausa(720) == "hace alrededor de un mes"
    assert _formatear_tiempo_pausa(1440) == "hace alrededor de 2 meses"


# --- _horas_desde_ultimo_mensaje ---

def test_horas_desde_ultimo_none_cuando_sin_historial():
    async def _run():
        with patch("agent.main.obtener_ultimo_timestamp", return_value=None):
            result = await _horas_desde_ultimo_mensaje("5491155@c.us")
        return result
    assert asyncio.run(_run()) is None


def test_horas_desde_ultimo_calcula_correctamente():
    async def _run():
        # Mock: último mensaje fue hace exactamente 5 horas (en UTC).
        hace_5h = datetime.now(timezone.utc) - timedelta(hours=5)
        with patch("agent.main.obtener_ultimo_timestamp", return_value=hace_5h.replace(tzinfo=None)):
            result = await _horas_desde_ultimo_mensaje("chat1")
        return result
    h = asyncio.run(_run())
    assert h is not None
    assert 4.9 < h < 5.1  # tolerancia por el tiempo que tarda en correr el test


def test_horas_desde_ultimo_pausa_larga():
    async def _run():
        hace_3_dias = datetime.now(timezone.utc) - timedelta(days=3)
        with patch("agent.main.obtener_ultimo_timestamp", return_value=hace_3_dias.replace(tzinfo=None)):
            result = await _horas_desde_ultimo_mensaje("chat1")
        return result
    h = asyncio.run(_run())
    assert h is not None
    assert 71 < h < 73


# --- Constantes configurables ---

def test_threshold_default_12():
    assert RETOMA_HORAS_THRESHOLD == 12.0


def test_historial_retoma_limit_default_40():
    assert HISTORIAL_RETOMA_LIMIT == 40


# --- Clasificación de estado (semántica) ---

def test_clasificacion_primer_contacto():
    """horas_pausa = None -> primer contacto."""
    horas_pausa = None
    es_primer_contacto = horas_pausa is None
    es_retoma = (horas_pausa is not None) and (horas_pausa >= RETOMA_HORAS_THRESHOLD)
    assert es_primer_contacto is True
    assert es_retoma is False


def test_clasificacion_conversacion_continua():
    """0 < horas_pausa < threshold -> continua."""
    horas_pausa = 3.5
    es_primer_contacto = horas_pausa is None
    es_retoma = (horas_pausa is not None) and (horas_pausa >= RETOMA_HORAS_THRESHOLD)
    assert es_primer_contacto is False
    assert es_retoma is False


def test_clasificacion_retoma_exacto_threshold():
    """horas_pausa = threshold -> retoma (borde inclusivo)."""
    horas_pausa = 12.0
    es_primer_contacto = horas_pausa is None
    es_retoma = (horas_pausa is not None) and (horas_pausa >= RETOMA_HORAS_THRESHOLD)
    assert es_retoma is True


def test_clasificacion_retoma_dos_dias():
    horas_pausa = 48.0
    es_primer_contacto = horas_pausa is None
    es_retoma = (horas_pausa is not None) and (horas_pausa >= RETOMA_HORAS_THRESHOLD)
    assert es_retoma is True


def test_clasificacion_borde_justo_debajo_threshold():
    """11.9h -> sigue continua, no retoma."""
    horas_pausa = 11.9
    es_retoma = (horas_pausa is not None) and (horas_pausa >= RETOMA_HORAS_THRESHOLD)
    assert es_retoma is False
