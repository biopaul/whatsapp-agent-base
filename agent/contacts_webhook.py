# agent/contacts_webhook.py — Webhook outbound al plugin WP para sync de contacts

"""
Fire-and-forget: cada mensaje entrante/saliente notifica a WordPress para
mantener wp_gowap_contacts actualizado en tiempo real. Tambien dispara
stop-on-reply del lado WP cuando direction='in'.

Patron consistente con usage_reporter/takeover/guided_templates:
- env var CONTACTS_URL_BASE con token embebido en path
- si vacio, modulo en no-op
- timeout 5s, fail-silent (loguea warning, no rompe flujo)
- NO retry: el sync diario del plugin corrige eventualmente
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger("agentkit")

CONTACTS_URL_BASE = os.getenv("CONTACTS_URL_BASE", "")
HTTP_TIMEOUT = float(os.getenv("CONTACTS_HTTP_TIMEOUT", "5"))
PREVIEW_MAX_CHARS = 200

_token_invalid: bool = False  # set True tras 401; se limpia en restart


def _is_enabled() -> bool:
    return bool(CONTACTS_URL_BASE) and not _token_invalid


def should_touch_chat_id(chat_id: Optional[str]) -> bool:
    """True si el chat_id es un contacto individual (@c.us). Grupos/broadcast = False."""
    if not chat_id:
        return False
    return chat_id.endswith("@c.us")


async def touch_contact(
    chat_id: str,
    direction: str,
    name: Optional[str] = None,
    preview: Optional[str] = None,
    timestamp: Optional[datetime] = None,
) -> None:
    """
    Notifica a WP que hubo un touch en este contacto.
    Fire-and-forget — no retorna ni levanta excepciones.

    direction: "in" | "out"
    """
    global _token_invalid
    if not _is_enabled():
        return
    if not should_touch_chat_id(chat_id):
        return
    if direction not in ("in", "out"):
        logger.warning(f"touch_contact: direction invalida '{direction}'")
        return

    ts = timestamp or datetime.now(timezone.utc)
    payload: dict = {
        "chat_id": chat_id,
        "direction": direction,
        "timestamp": ts.isoformat().replace("+00:00", "Z"),
    }
    if name:
        payload["name"] = name
    if preview:
        payload["last_message_preview"] = preview[:PREVIEW_MAX_CHARS]

    url = f"{CONTACTS_URL_BASE}/touch"
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.post(url, json=payload)
    except Exception as e:
        logger.warning(f"touch_contact: red error {type(e).__name__} - {e}")
        return

    if r.status_code == 401:
        logger.error("touch_contact: token invalido (401). Modulo deshabilitado hasta restart.")
        _token_invalid = True
        return

    if r.status_code >= 400:
        logger.warning(f"touch_contact: HTTP {r.status_code} - {r.text[:200]}")
        return

    # Log info si WP devolvio cancelled_dispatches > 0
    try:
        data = r.json()
        if isinstance(data, dict) and data.get("cancelled_dispatches", 0) > 0:
            logger.info(
                f"touch_contact: WP cancelo {data['cancelled_dispatches']} dispatches "
                f"pendientes para chat={chat_id} (stop-on-reply)"
            )
    except Exception:
        pass


async def mark_as_customer(
    chat_id: str,
    is_customer: bool = True,
    source: Optional[str] = None,
) -> bool:
    """
    Marca a un contacto como cliente (o desmarca con is_customer=False).
    Fire-and-forget — loguea pero no rompe el flujo.

    Endpoint plugin: POST /wp-json/gowap/v1/contacts/{TOKEN}/customer
    Body: {"chat_id", "is_customer", "source"}

    Retorna True si HTTP 200, False en cualquier otro caso (incluye disabled).
    """
    global _token_invalid
    if not _is_enabled():
        return False
    if not should_touch_chat_id(chat_id):
        return False

    payload: dict = {"chat_id": chat_id, "is_customer": bool(is_customer)}
    if source:
        payload["source"] = source

    url = f"{CONTACTS_URL_BASE}/customer"
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.post(url, json=payload)
    except Exception as e:
        logger.warning(f"mark_as_customer: red error {type(e).__name__} - {e}")
        return False

    if r.status_code == 401:
        logger.error("mark_as_customer: token invalido (401). Modulo deshabilitado hasta restart.")
        _token_invalid = True
        return False

    if r.status_code >= 400:
        logger.warning(f"mark_as_customer: HTTP {r.status_code} - {r.text[:200]}")
        return False

    logger.info(
        f"mark_as_customer: chat={chat_id} is_customer={is_customer} "
        f"source={source!r} → OK"
    )
    return True
