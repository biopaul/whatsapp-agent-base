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


def _extract_msg_id(response) -> str | None:
    """Extrae el id del mensaje del response WAHA (soporta {'id': str} o {'id': {'_serialized': str}})."""
    try:
        body = response.json()
    except Exception:
        return None
    if not isinstance(body, dict):
        return None
    raw = body.get("id")
    if isinstance(raw, str) and raw:
        return raw
    if isinstance(raw, dict):
        s = raw.get("_serialized") or raw.get("id")
        if isinstance(s, str) and s:
            return s
    return None


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

        evento = body.get("event", "")
        if evento not in ("message", "message.any"):
            return []

        payload = body.get("payload", {})
        es_propio = payload.get("fromMe", False)
        mensaje_id = payload.get("id", "")
        source = (payload.get("source") or "").lower()  # "app" | "api" | ""

        # Resolver chat_id: para mensajes salientes (fromMe) el remitente "from" es
        # el numero del agente, no el del cliente. WAHA expone chatId con el destino;
        # si no esta, usar "to". Para entrantes, "from" es el chat correcto.
        # Normalizar @s.whatsapp.net -> @c.us (algunos engines WAHA usan el primero).
        raw_chat = (
            payload.get("chatId")
            or (payload.get("to") if es_propio else None)
            or payload.get("from", "")
        )
        chat_id = (raw_chat or "").replace("@s.whatsapp.net", "@c.us")

        # Audio / nota de voz — detectar por hasMedia + mimetype
        has_media = bool(payload.get("hasMedia", False))
        media = payload.get("media") or {}
        mimetype = media.get("mimetype", "")

        if has_media:
            logger.info(f"WAHA hasMedia=true de {chat_id} | mimetype={mimetype!r} | media_keys={list(media.keys())} | id={mensaje_id} | fromMe={es_propio} | source={source!r}")

        # Eco WAHA via API: el agente o Seguimiento ya enviaron este mensaje. Skip
        # antes de cualquier procesamiento adicional (no genera audio, no marca leido).
        if es_propio and source == "api":
            return []

        if has_media and mimetype.startswith("audio/") and not es_propio:
            media_url = media.get("url", "")
            if not media_url:
                media_url = f"{self.base_url}/api/{self.session}/messages/{mensaje_id}/download"
            else:
                # WAHA reporta URLs con localhost — reescribir a la URL publica.
                import re
                media_url = re.sub(r'^https?://localhost(:\d+)?', self.base_url, media_url)
            logger.info(f"Audio detectado de {chat_id}: {mimetype} -> {media_url[:120]}")
            return [MensajeEntrante(
                telefono=chat_id,
                texto="",
                mensaje_id=mensaje_id,
                es_propio=es_propio,
                audio_url=media_url,
                source=source,
                tiene_media=True,
            )]

        # Mensajes de texto / media no-audio
        texto = payload.get("body", "") or ""

        # Mensajes fromMe: retornarlos si vienen de WhatsApp Web/app (source=app)
        # o si tienen contenido (texto o media). Sirven para activar takeover externo
        # y para capturar el historial del humano cuando esta en manual mode.
        if es_propio:
            if source == "app" or texto or has_media:
                return [MensajeEntrante(
                    telefono=chat_id,
                    texto=texto,
                    mensaje_id=mensaje_id,
                    es_propio=True,
                    source=source,
                    tiene_media=has_media,
                )]
            return []

        # Entrantes sin texto: solo log, no procesar.
        if not texto and has_media:
            logger.info(f"WAHA media no-audio ignorado de {chat_id}: mimetype={mimetype!r}")
        if not texto:
            return []

        return [MensajeEntrante(
            telefono=chat_id,
            texto=texto,
            mensaje_id=mensaje_id,
            es_propio=False,
            source=source,
            tiene_media=has_media,
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

    async def enviar_mensaje_returning_id(self, telefono: str, mensaje: str) -> str | None:
        """Envia mensaje via WAHA y retorna el message id (si WAHA lo provee)."""
        if not self.base_url:
            logger.warning("WAHA_BASE_URL no configurado — mensaje no enviado")
            return None
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
                    return None
                # Parsear id del response. WAHA puede retornar:
                #   {"id": "false_chat@c.us_3EB..."}
                # o anidarlo en {"_data": {...}, "id": {...}}
                try:
                    body = r.json()
                except Exception:
                    return "ok_no_id"
                if isinstance(body, dict):
                    raw_id = body.get("id")
                    if isinstance(raw_id, str) and raw_id:
                        return raw_id
                    if isinstance(raw_id, dict):
                        # Algunos WAHA retornan {"id": {"_serialized": "..."}}
                        serialized = raw_id.get("_serialized") or raw_id.get("id")
                        if isinstance(serialized, str) and serialized:
                            return serialized
                return "ok_no_id"
            except Exception as e:
                logger.error(f"Error WAHA enviar: {e}")
                return None

    async def _set_presence(self, telefono: str, presence: str) -> None:
        """Envia un estado de presencia al chat."""
        chat_id = _asegurar_chat_id(telefono)
        async with httpx.AsyncClient() as client:
            try:
                r = await client.post(
                    f"{self.base_url}/api/{self.session}/presence",
                    json={"chatId": chat_id, "presence": presence},
                    headers=self._headers(),
                )
                if r.status_code not in (200, 201):
                    logger.info(f"presence={presence} WAHA: {r.status_code} — {r.text}")
            except Exception as e:
                logger.info(f"presence={presence} WAHA fallo (no critico): {e}")

    async def indicar_escribiendo(self, telefono: str, delay: int = 3) -> None:
        await self._set_presence(telefono, "typing")

    async def indicar_grabando(self, telefono: str) -> None:
        await self._set_presence(telefono, "recording")

    async def marcar_leido(self, telefono: str) -> None:
        """Marca mensajes del chat como leidos (ticks azules)."""
        chat_id = _asegurar_chat_id(telefono)
        async with httpx.AsyncClient() as client:
            try:
                r = await client.post(
                    f"{self.base_url}/api/{self.session}/chats/{chat_id}/messages/read",
                    json={},
                    headers=self._headers(),
                )
                if r.status_code not in (200, 201):
                    logger.info(f"marcar_leido WAHA: {r.status_code} — {r.text}")
            except Exception as e:
                logger.info(f"marcar_leido WAHA fallo (no critico): {e}")

    async def enviar_archivo(self, telefono: str, url: str, filename: str, caption: str = "") -> bool:
        """Envia un archivo al cliente via WAHA POST /api/sendFile."""
        chat_id = _asegurar_chat_id(telefono)
        payload: dict = {
            "session": self.session,
            "chatId": chat_id,
            "file": {"url": url},
        }
        if caption:
            payload["caption"] = caption
        async with httpx.AsyncClient() as client:
            try:
                r = await client.post(
                    f"{self.base_url}/api/sendFile",
                    json=payload,
                    headers=self._headers(),
                    timeout=30.0,
                )
                if r.status_code not in (200, 201):
                    logger.error(f"enviar_archivo WAHA: {r.status_code} — {r.text}")
                    return False
                logger.info(f"Archivo enviado a {telefono}: {filename}")
                return True
            except Exception as e:
                logger.error(f"enviar_archivo WAHA fallo: {e}")
                return False

    async def reaccionar(self, telefono: str, mensaje_id: str, emoji: str) -> None:
        """Envia una reaccion emoji a un mensaje."""
        chat_id = _asegurar_chat_id(telefono)
        async with httpx.AsyncClient() as client:
            try:
                r = await client.post(
                    f"{self.base_url}/api/reaction",
                    json={
                        "session": self.session,
                        "chatId": chat_id,
                        "messageId": mensaje_id,
                        "reaction": emoji,
                    },
                    headers=self._headers(),
                )
                if r.status_code not in (200, 201):
                    logger.info(f"reaccionar WAHA: {r.status_code} — {r.text}")
            except Exception as e:
                logger.info(f"reaccionar WAHA fallo (no critico): {e}")

    async def enviar_buttons(
        self,
        telefono: str,
        body_text: str,
        buttons: list[dict],
        footer: str | None = None,
    ) -> tuple[bool, int | None, str | None]:
        """WAHA /api/sendButtons. Retorna (ok, status, msg_id)."""
        if not self.base_url:
            return (False, None, None)
        chat_id = _asegurar_chat_id(telefono)
        payload: dict = {
            "session": self.session,
            "chatId": chat_id,
            "body": body_text,
            "buttons": [{"type": "reply", "id": b["id"], "title": b["title"]} for b in buttons[:3]],
        }
        if footer:
            payload["footer"] = footer
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                r = await client.post(
                    f"{self.base_url}/api/sendButtons",
                    json=payload,
                    headers=self._headers(),
                )
            except Exception as e:
                logger.error(f"WAHA sendButtons exception: {e}")
                return (False, None, None)

            if r.status_code in (200, 201):
                msg_id = _extract_msg_id(r)
                return (True, r.status_code, msg_id)
            if r.status_code == 501:
                logger.info(f"WAHA sendButtons: 501 Not Implemented (engine no soporta)")
                return (False, 501, None)
            logger.error(f"WAHA sendButtons HTTP {r.status_code}: {r.text[:200]}")
            return (False, r.status_code, None)

    async def enviar_list(
        self,
        telefono: str,
        body_text: str,
        button_title: str,
        sections: list[dict],
        footer: str | None = None,
    ) -> tuple[bool, int | None, str | None]:
        """WAHA /api/sendList. Retorna (ok, status, msg_id)."""
        if not self.base_url:
            return (False, None, None)
        chat_id = _asegurar_chat_id(telefono)
        payload: dict = {
            "session": self.session,
            "chatId": chat_id,
            "body": body_text,
            "buttonText": button_title,
            "sections": sections,
        }
        if footer:
            payload["footer"] = footer
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                r = await client.post(
                    f"{self.base_url}/api/sendList",
                    json=payload,
                    headers=self._headers(),
                )
            except Exception as e:
                logger.error(f"WAHA sendList exception: {e}")
                return (False, None, None)

            if r.status_code in (200, 201):
                msg_id = _extract_msg_id(r)
                return (True, r.status_code, msg_id)
            logger.error(f"WAHA sendList HTTP {r.status_code}: {r.text[:200]}")
            return (False, r.status_code, None)
