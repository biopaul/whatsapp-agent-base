# agent/tts_text_cleaner.py — Sanitizador de texto pre-TTS

"""
Limpia artefactos del texto del LLM que suenan mal cuando se leen por TTS.

Casos cubiertos:
- Emojis (se leen como descripcion textual: "carita feliz", "manos juntas")
- Risas escritas: "jaja", "jeje", "jiji", "jojo", "juju", "lol", "lmao", "xd"
- Markdown: asteriscos, guiones bajos, virgulas, backticks
- Puntuacion repetida: "!!!" -> "!", "???" -> "?", "..." -> "."
- Espacios multiples colapsados a uno

Defense in depth: el LLM tambien recibe una instruccion para evitar estos
artefactos (ver _procesar_y_responder), pero este sanitizer garantiza limpieza
si el LLM se escapa.
"""

import re

# Emojis: rangos Unicode mas comunes (cubre el 99% de uso real en chat hispano)
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001F9FF"   # symbols & pictographs + emoticons + transport
    "\U0001FA00-\U0001FAFF"   # extended pictographs
    "☀-⛿"           # misc symbols (sun, etc)
    "✀-➿"           # dingbats
    "⬀-⯿"           # misc arrows
    "←-⇿"           # arrows basicas
    "‍"                  # zero-width joiner (familias emoji)
    "️"                  # variation selector-16
    "]+",
    flags=re.UNICODE,
)

# Risas escritas: 2+ silabas para evitar falsos positivos (jamon, Jamaica, etc.)
_LAUGH_PATTERN = re.compile(
    r"\b(?:ja|je|ji|jo|ju)(?:ja|je|ji|jo|ju)+\b|\b(?:lol|lmao|rofl|xd+)\b",
    flags=re.IGNORECASE,
)

# Markdown chars que el LLM podria meter aunque le pidamos texto plano
_MARKDOWN_CHARS = re.compile(r"[*_~`]")

# Puntuacion repetida: "!!!" -> "!", "..." -> "."
_REPEATED_PUNCT = re.compile(r"([!?.])\1+")

# Espacios multiples (incluyendo los que quedan tras strip de emojis/risas)
_MULTI_SPACE = re.compile(r"\s+")


def sanitize_for_tts(text: str) -> str:
    """
    Limpia el texto antes de mandarlo al motor TTS.
    Retorna string vacio si el input es None o vacio.
    """
    if not text:
        return ""
    s = text
    s = _EMOJI_PATTERN.sub("", s)
    s = _LAUGH_PATTERN.sub("", s)
    s = _MARKDOWN_CHARS.sub("", s)
    s = _REPEATED_PUNCT.sub(r"\1", s)
    s = _MULTI_SPACE.sub(" ", s)
    return s.strip()
