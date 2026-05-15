"""Tests para guided_selection: detectar seleccion del usuario."""

import pytest


_DISPATCH = {
    "id": 1, "template_id": 10, "chat_id": "c", "format_used": "numbered_text",
    "options_snapshot": [
        {"id": 11, "order": 1, "visible_text": "Confirmar", "action_type": "text", "action_payload": {"text": "confirmo"}},
        {"id": 12, "order": 2, "visible_text": "Cancelar", "action_type": "text", "action_payload": {"text": "cancelo"}},
        {"id": 13, "order": 3, "visible_text": "Reagendar", "action_type": "text", "action_payload": {"text": "reagendo"}},
    ]
}


def test_match_numero_simple():
    from agent.guided_selection import match_user_input
    assert match_user_input("1", _DISPATCH)["option"]["id"] == 11
    assert match_user_input("2", _DISPATCH)["option"]["id"] == 12
    assert match_user_input("3", _DISPATCH)["option"]["id"] == 13


def test_match_numero_con_espacios():
    from agent.guided_selection import match_user_input
    assert match_user_input("  2  ", _DISPATCH)["option"]["id"] == 12


def test_match_emoji_numerico():
    from agent.guided_selection import match_user_input
    assert match_user_input("1️⃣", _DISPATCH)["option"]["id"] == 11
    assert match_user_input("2️⃣", _DISPATCH)["option"]["id"] == 12


def test_match_texto_literal_visible():
    from agent.guided_selection import match_user_input
    assert match_user_input("Confirmar", _DISPATCH)["option"]["id"] == 11
    assert match_user_input("confirmar", _DISPATCH)["option"]["id"] == 11
    assert match_user_input("cancelar", _DISPATCH)["option"]["id"] == 12


def test_match_texto_libre_sin_match():
    from agent.guided_selection import match_user_input
    result = match_user_input("hola, como va?", _DISPATCH)
    assert result is None


def test_match_devuelve_none_si_dispatch_sin_opciones():
    from agent.guided_selection import match_user_input
    assert match_user_input("1", {"options_snapshot": []}) is None


def test_match_numero_fuera_de_rango():
    from agent.guided_selection import match_user_input
    assert match_user_input("99", _DISPATCH) is None
    assert match_user_input("0", _DISPATCH) is None


def test_match_texto_id_opcional():
    """Por compatibilidad con buttons (que mandan 'opt_11' como id)."""
    from agent.guided_selection import match_user_input
    assert match_user_input("opt_11", _DISPATCH)["option"]["id"] == 11
