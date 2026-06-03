# agent/labels.py — Aplicacion de etiquetas a contactos via endpoint WP
#
# El plugin gowap-agent-orchestrator expone un endpoint token-auth para que el
# agente le marque etiquetas a contactos (ej: "Escalado" cuando deriva al
# humano). Patron consistente con takeover.py / contacts_webhook.py:
#
#   POST /wp-json/gowap/v1/labels/{token}/apply
#       body: { "chat_id": "5491155@c.us", "label": "Escalado" }
#       resp: 200 OK
#
# La URL base se deriva de CONFIG_URL (mismo token):
#   CONFIG_URL  = https://example.com/wp-json/gowap/v1/config/{token}
#   LABELS_URL  = https://example.com/wp-json/gowap/v1/labels/{token}
#
# Fail-open: si el endpoint no esta deployado en el plugin (404), o si la red
# falla, loguea warning y sigue. La escalacion y el takeover funcionan igual.

import os
import logging
from typing import Optional

import httpx

logger = logging.getLogger("agentkit")

HTTP_TIMEOUT = float(os.getenv("LABELS_HTTP_TIMEOUT", "5"))

# Cache para no re-loguear el mismo 404 cada vez (endpoint plugin todavia no deployed).
_endpoint_unavailable: bool = False


def _resolve_labels_base() -> Optional[str]:
    """Deriva la URL base de /labels/{token} desde CONFIG_URL."""
    config_url = os.getenv("CONFIG_URL", "").strip()
    if "/config/" not in config_url:
        return None
    prefix, token = config_url.rsplit("/config/", 1)
    token = token.rstrip("/")
    if not token:
        return None
    return f"{prefix}/labels/{token}"


async def apply_label(chat_id: str, label: str) -> bool:
    """
    Marca un contacto con una etiqueta. Idempotente del lado WP (si ya estaba,
    no duplica). Fail-open: True si OK, False si fallo (pero sin levantar).
    """
    global _endpoint_unavailable
    if _endpoint_unavailable:
        return False

    base = _resolve_labels_base()
    if not base:
        return False

    url = f"{base}/apply"
    payload = {"chat_id": chat_id, "label": label}
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.post(url, json=payload)
    except Exception as e:
        logger.warning(f"labels.apply_label {chat_id} '{label}': red error {type(e).__name__} - {e}")
        return False

    if r.status_code == 404:
        # Endpoint plugin todavia no existe. Loguear una vez y deshabilitar
        # el modulo hasta el proximo restart del container.
        if not _endpoint_unavailable:
            logger.warning(
                "labels.apply_label: endpoint /labels/{token}/apply no encontrado "
                "(plugin desactualizado?). Etiquetas no se aplicaran hasta upgrade."
            )
        _endpoint_unavailable = True
        return False

    if r.status_code == 401:
        logger.error("labels.apply_label: token invalido (401). Modulo deshabilitado.")
        _endpoint_unavailable = True
        return False

    if r.status_code >= 400:
        logger.warning(f"labels.apply_label {chat_id} '{label}': HTTP {r.status_code} - {r.text[:200]}")
        return False

    logger.info(f"Etiqueta aplicada: chat={chat_id} label='{label}'")
    return True


def reset_endpoint_status() -> None:
    """Util para tests."""
    global _endpoint_unavailable
    _endpoint_unavailable = False
