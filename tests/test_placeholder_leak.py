# tests/test_placeholder_leak.py — defensa contra placeholders [NOMBRE_X] sin llenar

import os
os.environ.setdefault("OPENAI_API_KEY", "test-dummy")
os.environ.setdefault("OPENROUTER_API_KEY", "test-dummy")

import logging


# --- Sanitize del output ---

def test_sanitize_remueve_nombre_negocio():
    from agent.brain import _sanitize_output
    # Caso real reportado en produccion (captura del cliente)
    entrada = "Soy la asistente de [NOMBRE_NEGOCIO], aquí para ayudarte con tus consultas."
    salida = _sanitize_output(entrada)
    assert "[NOMBRE_NEGOCIO]" not in salida
    assert "Soy la asistente de" in salida
    assert "ayudarte" in salida
    # Verificamos que la coma no quedo huerfana (espacios raros)
    assert ",  " not in salida


def test_sanitize_remueve_multiples_placeholders():
    from agent.brain import _sanitize_output
    entrada = "Hola, soy [NOMBRE_AGENTE] de [NOMBRE_NEGOCIO], atendemos [HORARIO]."
    salida = _sanitize_output(entrada)
    for ph in ["[NOMBRE_AGENTE]", "[NOMBRE_NEGOCIO]", "[HORARIO]"]:
        assert ph not in salida


def test_sanitize_no_toca_brackets_normales():
    from agent.brain import _sanitize_output
    # Corchetes con texto no all-caps NO son placeholders — no tocar
    entrada = "El precio es [oferta especial] este mes"
    salida = _sanitize_output(entrada)
    assert "[oferta especial]" in salida


def test_sanitize_no_toca_brackets_cortos():
    from agent.brain import _sanitize_output
    # Placeholders de 1-2 chars podrian ser codigos legitimos (ej: [OK], [X])
    entrada = "Confirmar con [OK] o [X]"
    salida = _sanitize_output(entrada)
    assert "[OK]" in salida
    assert "[X]" in salida


def test_sanitize_placeholder_con_digitos():
    from agent.brain import _sanitize_output
    entrada = "Version [V1_ALPHA] y [PLAN_2024]"
    salida = _sanitize_output(entrada)
    assert "[V1_ALPHA]" not in salida
    assert "[PLAN_2024]" not in salida


# --- Warning en config_loader ---

def test_warn_placeholders_una_vez_dispara_warning(caplog):
    from agent import config_loader
    # Reset del set de avisados para test aislado
    config_loader._placeholders_avisados.clear()
    prompt = "Sos [NOMBRE_AGENTE] de [NOMBRE_NEGOCIO]"
    with caplog.at_level(logging.WARNING, logger="agentkit"):
        config_loader._warn_placeholders_una_vez(prompt)
    assert any("placeholders sin llenar" in r.message for r in caplog.records)
    assert any("NOMBRE_AGENTE" in r.message and "NOMBRE_NEGOCIO" in r.message for r in caplog.records)


def test_warn_placeholders_solo_una_vez_por_hash(caplog):
    from agent import config_loader
    config_loader._placeholders_avisados.clear()
    prompt = "Hola [NOMBRE_NEGOCIO]"
    with caplog.at_level(logging.WARNING, logger="agentkit"):
        config_loader._warn_placeholders_una_vez(prompt)
        config_loader._warn_placeholders_una_vez(prompt)
        config_loader._warn_placeholders_una_vez(prompt)
    warnings = [r for r in caplog.records if "placeholders sin llenar" in r.message]
    assert len(warnings) == 1


def test_warn_no_dispara_si_prompt_limpio(caplog):
    from agent import config_loader
    config_loader._placeholders_avisados.clear()
    prompt = "Sos Sofi de SimpleProp"
    with caplog.at_level(logging.WARNING, logger="agentkit"):
        config_loader._warn_placeholders_una_vez(prompt)
    warnings = [r for r in caplog.records if "placeholders sin llenar" in r.message]
    assert len(warnings) == 0


def test_warn_no_falla_con_prompt_vacio(caplog):
    from agent import config_loader
    config_loader._placeholders_avisados.clear()
    # No debe explotar
    config_loader._warn_placeholders_una_vez("")
    config_loader._warn_placeholders_una_vez(None)
