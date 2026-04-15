# agent/providers/waha.py — Adaptador para WAHA (WhatsApp HTTP API)
# Self-hosted — https://waha.devlike.pro

import os
import logging
import httpx
from fastapi import Request
from agent.providers.base import ProveedorWhatsApp, MensajeEntrante

logger = logging.getLogger("agentkit")


def _asegurar_chat_id(telefono: str) -> str:
    """Asegura que el teléfono tenga formato chatId de WAHA (number@c.us)."""
    if "@" in telefono:
        return telefono
    return f"{telefono}@c.us"


class ProveedorWAHA(ProveedorWhatsApp):
    """Proveedor de WhatsApp usando WAHA (self-hosted)."""

    def __init__(self):
        self.base_url = os.getenv("WAHA_BASE_URL", "http://localhost:3000").rstrip("/")
        self.api_key = os.getenv("WAHA_API_KEY", "")
        self.session = os.getenv("WAHA_SESSION", "default")

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["X-Api-Key"] = self.api_key
        return h

    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        """Parsea el payload de WAHA (un evento por request)."""
        body = await request.json()

        # WAHA envía un evento por request, no un array
        evento = body.get("event", "")
        if evento not in ("message", "message.any"):
            return []

        payload = body.get("payload", {})

        # Ignorar mensajes sin body (imágenes, stickers, etc.)
        texto = payload.get("body", "")
        if not texto:
            return []

        return [MensajeEntrante(
            telefono=payload.get("from", ""),
            texto=texto,
            mensaje_id=payload.get("id", ""),
            es_propio=payload.get("fromMe", False),
        )]

    async def enviar_mensaje(self, telefono: str, mensaje: str) -> bool:
        """Envía mensaje via WAHA API."""
        if not self.base_url:
            logger.warning("WAHA_BASE_URL no configurado — mensaje no enviado")
            return False
        chat_id = _asegurar_chat_id(telefono)
        async with httpx.AsyncClient() as client:
            try:
                r = await client.post(
                    f"{self.base_url}/api/sendText",
                    json={
                        "session": self.session,
                        "chatId": chat_id,
                        "text": mensaje,
                    },
                    headers=self._headers(),
                )
                if r.status_code not in (200, 201):
                    logger.error(f"Error WAHA enviar: {r.status_code} — {r.text}")
                    return False
                return True
            except Exception as e:
                logger.error(f"Error WAHA enviar: {e}")
                return False

    async def indicar_escribiendo(self, telefono: str, delay: int = 3) -> None:
        """Muestra el indicador 'escribiendo...' via WAHA."""
        chat_id = _asegurar_chat_id(telefono)
        async with httpx.AsyncClient() as client:
            try:
                r = await client.post(
                    f"{self.base_url}/api/{self.session}/presence",
                    json={"chatId": chat_id, "presence": "typing"},
                    headers=self._headers(),
                )
                if r.status_code not in (200, 201):
                    logger.info(f"indicar_escribiendo WAHA: {r.status_code} — {r.text}")
            except Exception as e:
                logger.info(f"indicar_escribiendo WAHA falló (no crítico): {e}")
