"""Tests para guided_actions: ejecucion de cada action_type."""

import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_action_text_inyecta_como_user_message():
    from agent import guided_actions
    option = {"id": 11, "visible_text": "Confirmar", "action_type": "text",
              "action_payload": {"text": "confirmo el turno"}}
    result = await guided_actions.ejecutar_accion(
        option=option, chat_id="c@c.us", session_id="s",
        provider=AsyncMock(), parent_dispatch_local_id=1,
    )
    assert result["kind"] == "text_injection"
    assert result["injected_text"] == "confirmo el turno"


@pytest.mark.asyncio
async def test_action_handoff_envia_mensaje():
    from agent import guided_actions
    option = {"id": 12, "visible_text": "Hablar con humano", "action_type": "handoff", "action_payload": {}}
    provider = AsyncMock()
    provider.enviar_mensaje_returning_id = AsyncMock(return_value="m1")

    result = await guided_actions.ejecutar_accion(
        option=option, chat_id="c@c.us", session_id="s",
        provider=provider, parent_dispatch_local_id=1,
    )
    assert result["kind"] == "handoff"
    provider.enviar_mensaje_returning_id.assert_awaited()


@pytest.mark.asyncio
async def test_action_template_dispara_subplantilla():
    from agent import guided_actions

    option = {"id": 13, "visible_text": "Submenu", "action_type": "template",
              "action_payload": {"template_name": "submenu_x"}}
    provider = AsyncMock()

    with patch("agent.guided_dispatcher.dispatch_plantilla",
               new=AsyncMock(return_value={"ok": True, "format_used": "numbered_text",
                                            "dispatch_local_id": 99, "dispatch_remote_id": None})) as mock_disp:
        result = await guided_actions.ejecutar_accion(
            option=option, chat_id="c@c.us", session_id="s",
            provider=provider, parent_dispatch_local_id=1,
        )
    assert result["kind"] == "template"
    mock_disp.assert_awaited_once()


@pytest.mark.asyncio
async def test_action_calendar_stub():
    from agent import guided_actions
    option = {"id": 14, "visible_text": "Agendar", "action_type": "calendar", "action_payload": {}}
    provider = AsyncMock()
    provider.enviar_mensaje_returning_id = AsyncMock(return_value="m1")

    result = await guided_actions.ejecutar_accion(
        option=option, chat_id="c@c.us", session_id="s",
        provider=provider, parent_dispatch_local_id=1,
    )
    assert result["kind"] == "calendar_stub"
    provider.enviar_mensaje_returning_id.assert_awaited()


@pytest.mark.asyncio
async def test_action_mercadopago_stub():
    from agent import guided_actions
    option = {"id": 15, "visible_text": "Pagar", "action_type": "mercadopago", "action_payload": {}}
    provider = AsyncMock()
    provider.enviar_mensaje_returning_id = AsyncMock(return_value="m1")

    result = await guided_actions.ejecutar_accion(
        option=option, chat_id="c@c.us", session_id="s",
        provider=provider, parent_dispatch_local_id=1,
    )
    assert result["kind"] == "mercadopago_stub"


@pytest.mark.asyncio
async def test_action_unknown_type_fallback():
    from agent import guided_actions
    option = {"id": 99, "visible_text": "X", "action_type": "no_existe", "action_payload": {}}
    provider = AsyncMock()
    result = await guided_actions.ejecutar_accion(
        option=option, chat_id="c@c.us", session_id="s",
        provider=provider, parent_dispatch_local_id=1,
    )
    assert result["kind"] == "unknown"
