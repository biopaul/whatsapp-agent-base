"""Tests para sanitize_for_tts."""

import pytest
from agent.tts_text_cleaner import sanitize_for_tts


def test_empty_input():
    assert sanitize_for_tts("") == ""
    assert sanitize_for_tts(None) == ""


def test_strips_emoji_carita_feliz():
    assert sanitize_for_tts("Hola 😊") == "Hola"
    assert sanitize_for_tts("😀😁😂") == ""


def test_strips_emoji_manos_juntas():
    assert sanitize_for_tts("Gracias 🙏") == "Gracias"


def test_strips_emoji_intercalados():
    assert sanitize_for_tts("Hola 👋 como va? 😊") == "Hola como va?"


def test_strips_risas_basicas():
    assert sanitize_for_tts("jaja que bueno") == "que bueno"
    assert sanitize_for_tts("Bien jeje") == "Bien"


def test_strips_risas_largas():
    assert sanitize_for_tts("jajajaja muy bueno") == "muy bueno"
    assert sanitize_for_tts("jejeje siii") == "siii"


def test_strips_risas_case_insensitive():
    assert sanitize_for_tts("JAJA grande") == "grande"
    assert sanitize_for_tts("JaJaJa") == ""


def test_strips_lol_lmao():
    assert sanitize_for_tts("eso es genial lol") == "eso es genial"
    assert sanitize_for_tts("XD que bueno") == "que bueno"


def test_no_falsos_positivos_palabras_con_ja():
    """Palabras como 'jamon', 'Jamaica' NO deben ser tocadas."""
    assert sanitize_for_tts("Tenemos jamon de bellota") == "Tenemos jamon de bellota"
    assert sanitize_for_tts("Soy de Jamaica") == "Soy de Jamaica"
    assert sanitize_for_tts("La jirafa es alta") == "La jirafa es alta"


def test_strips_markdown_asteriscos():
    assert sanitize_for_tts("Esto es *importante*") == "Esto es importante"
    assert sanitize_for_tts("**negrita**") == "negrita"


def test_strips_markdown_guion_bajo_y_tilde():
    assert sanitize_for_tts("Esto es _enfatico_") == "Esto es enfatico"
    assert sanitize_for_tts("Esto es ~tachado~") == "Esto es tachado"


def test_strips_backticks():
    assert sanitize_for_tts("usa `comando` para esto") == "usa comando para esto"


def test_colapsa_puntuacion_repetida():
    assert sanitize_for_tts("Hola!!!") == "Hola!"
    assert sanitize_for_tts("Que???") == "Que?"
    assert sanitize_for_tts("Esperando...") == "Esperando."


def test_colapsa_espacios_multiples():
    assert sanitize_for_tts("Hola    mundo") == "Hola mundo"


def test_combinacion_emojis_risas_markdown():
    """Caso real: el LLM mete todo mezclado."""
    inp = "Hola! 😊 jaja que **bueno** te ayudo... 🙏"
    out = sanitize_for_tts(inp)
    # No emojis, no risas, no markdown, puntuacion normalizada
    assert "😊" not in out
    assert "jaja" not in out.lower()
    assert "**" not in out
    assert "🙏" not in out
    assert "..." not in out
    # Pero el contenido principal queda
    assert "Hola" in out and "bueno" in out and "te ayudo" in out


def test_texto_limpio_queda_intacto():
    """Si no hay nada para limpiar, el texto vuelve igual (modulo trim)."""
    text = "Hola, como estas? Te ayudo con eso."
    assert sanitize_for_tts(text) == text


def test_solo_emojis_devuelve_vacio():
    assert sanitize_for_tts("😀😁😂🙏👋") == ""
