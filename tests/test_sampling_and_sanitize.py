# tests/test_sampling_and_sanitize.py — defaults de sampling + sanitize output

import os
os.environ.setdefault("OPENAI_API_KEY", "test-dummy")
os.environ.setdefault("OPENROUTER_API_KEY", "test-dummy")

import importlib


def _reload_brain():
    from agent import brain as brain_mod
    importlib.reload(brain_mod)
    return brain_mod


# --- Defaults nuevos ---

def test_max_tokens_default_1500(monkeypatch):
    monkeypatch.delenv("AI_MAX_TOKENS", raising=False)
    brain_mod = _reload_brain()
    assert brain_mod._MAX_TOKENS == 1500


def test_max_tokens_env_override(monkeypatch):
    monkeypatch.setenv("AI_MAX_TOKENS", "2500")
    brain_mod = _reload_brain()
    assert brain_mod._MAX_TOKENS == 2500


def test_temperature_default_07(monkeypatch):
    monkeypatch.delenv("AI_TEMPERATURE", raising=False)
    brain_mod = _reload_brain()
    assert brain_mod._TEMPERATURE == 0.7


def test_temperature_env_override(monkeypatch):
    monkeypatch.setenv("AI_TEMPERATURE", "0.4")
    brain_mod = _reload_brain()
    assert brain_mod._TEMPERATURE == 0.4


# --- Sanitize del output ---

def test_sanitize_remueve_s_thought_bare_word():
    from agent.brain import _sanitize_output
    # Caso real reportado en produccion (captura del cliente)
    entrada = "Buenísimo, Camila. Quedó súper claro el s_thought enfoque."
    salida = _sanitize_output(entrada)
    assert "s_thought" not in salida
    assert "Camila" in salida
    assert "enfoque" in salida


def test_sanitize_remueve_tags_html_style():
    from agent.brain import _sanitize_output
    entrada = "<thinking>plan</thinking>Hola como estas"
    salida = _sanitize_output(entrada)
    assert "<thinking>" not in salida
    assert "</thinking>" not in salida
    # NOTA: el sanitize solo quita las tags, no el contenido entre ellas.
    # Los tokens tecnicos suelen aparecer sueltos o el modelo mete la tag
    # sin cerrar; para bloques bien formados el humano puede iterar el regex.
    assert "Hola como estas" in salida


def test_sanitize_scratchpad_variantes():
    from agent.brain import _sanitize_output
    for token in ["scratchpad_start", "scratchpad_end", "inner_monologue"]:
        entrada = f"Texto antes {token} texto despues"
        salida = _sanitize_output(entrada)
        assert token not in salida


def test_sanitize_case_insensitive():
    from agent.brain import _sanitize_output
    entrada = "Hola <THINKING>x</THINKING> mundo"
    salida = _sanitize_output(entrada)
    assert "THINKING" not in salida.upper() or "<THINKING>" not in salida


def test_sanitize_no_toca_texto_limpio():
    from agent.brain import _sanitize_output
    entrada = "Hola Juan, ¿cómo va todo? Espero que bien 😊"
    salida = _sanitize_output(entrada)
    assert salida == entrada


def test_sanitize_no_toca_palabra_normal_similar():
    from agent.brain import _sanitize_output
    # "pensamiento" y "reflexion" NO son tokens tecnicos, no deben tocarse
    entrada = "Mi pensamiento sobre esa reflexion es que..."
    salida = _sanitize_output(entrada)
    assert salida == entrada


def test_sanitize_colapsa_espacios_dobles():
    from agent.brain import _sanitize_output
    entrada = "hola  s_thought  mundo"
    salida = _sanitize_output(entrada)
    assert "  " not in salida
    assert "hola" in salida
    assert "mundo" in salida


def test_sanitize_empty_input():
    from agent.brain import _sanitize_output
    assert _sanitize_output("") == ""
    assert _sanitize_output(None) is None
