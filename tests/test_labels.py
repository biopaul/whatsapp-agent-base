# tests/test_labels.py — apply_label + URL derivation + endpoint disable on 404

import os
# Dummy env vars para que el import de agent.main / agent.brain no crashee
# en CI/local sin OPENROUTER/OPENAI keys.
os.environ.setdefault("OPENAI_API_KEY", "test-dummy")
os.environ.setdefault("OPENROUTER_API_KEY", "test-dummy")

import asyncio
import importlib
from unittest.mock import patch, AsyncMock, MagicMock


def _reload_labels_with_env(env: dict):
    from agent import labels
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    importlib.reload(labels)
    return labels


def _mock_async_client(status_code: int, body: dict | None = None):
    response = MagicMock()
    response.status_code = status_code
    response.json = MagicMock(return_value=body or {})
    response.text = "" if body is None else str(body)
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.post = AsyncMock(return_value=response)
    return client


def test_url_derivation_from_config_url():
    labels = _reload_labels_with_env({
        "CONFIG_URL": "https://example.com/wp-json/gowap/v1/config/" + "a" * 64,
    })
    expected = "https://example.com/wp-json/gowap/v1/labels/" + "a" * 64
    assert labels._resolve_labels_base() == expected


def test_url_none_when_config_unset():
    labels = _reload_labels_with_env({"CONFIG_URL": ""})
    assert labels._resolve_labels_base() is None


def test_apply_label_success():
    labels = _reload_labels_with_env({
        "CONFIG_URL": "https://example.com/wp-json/gowap/v1/config/aaa",
    })
    client = _mock_async_client(200, {"ok": True})
    with patch("agent.labels.httpx.AsyncClient", return_value=client):
        ok = asyncio.run(labels.apply_label("5491155@c.us", "Escalado"))
    assert ok is True
    sent = client.post.call_args
    assert sent[1]["json"] == {"chat_id": "5491155@c.us", "label": "Escalado"}


def test_apply_label_404_disables_endpoint():
    labels = _reload_labels_with_env({
        "CONFIG_URL": "https://example.com/wp-json/gowap/v1/config/aaa",
    })
    client = _mock_async_client(404)
    with patch("agent.labels.httpx.AsyncClient", return_value=client):
        first = asyncio.run(labels.apply_label("c1", "Escalado"))
        second = asyncio.run(labels.apply_label("c2", "Otro"))
    assert first is False
    assert second is False
    # Solo se llamo a POST una vez (segunda corto en el guard).
    assert client.post.call_count == 1


def test_apply_label_false_when_no_url():
    labels = _reload_labels_with_env({"CONFIG_URL": ""})
    ok = asyncio.run(labels.apply_label("c1", "Escalado"))
    assert ok is False


def test_reset_endpoint_status():
    labels = _reload_labels_with_env({
        "CONFIG_URL": "https://example.com/wp-json/gowap/v1/config/aaa",
    })
    client_404 = _mock_async_client(404)
    with patch("agent.labels.httpx.AsyncClient", return_value=client_404):
        asyncio.run(labels.apply_label("c1", "Escalado"))
    assert labels._endpoint_unavailable is True
    labels.reset_endpoint_status()
    assert labels._endpoint_unavailable is False


def test_apply_label_false_on_500_does_not_disable():
    labels = _reload_labels_with_env({
        "CONFIG_URL": "https://example.com/wp-json/gowap/v1/config/aaa",
    })
    client = _mock_async_client(500, {})
    with patch("agent.labels.httpx.AsyncClient", return_value=client):
        ok = asyncio.run(labels.apply_label("c1", "Escalado"))
    assert ok is False
    # 500 es transitorio, no debe deshabilitar el endpoint.
    assert labels._endpoint_unavailable is False


def test_keyword_expansion_catches_real_user_phrases():
    """Casos reales que antes no disparaban escalado."""
    from agent.main import _detectar_keyword_escalar
    assert _detectar_keyword_escalar("a ver el agente no kiero hablar con un Bot si no con una persona real") is True
    assert _detectar_keyword_escalar("necesito un humano por favor") is True
    assert _detectar_keyword_escalar("no me sirve este chat") is True
    assert _detectar_keyword_escalar("quiero hablar con alguien de verdad") is True
    assert _detectar_keyword_escalar("hola que tal") is False
