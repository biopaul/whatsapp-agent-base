# agent/providers/base.py — Clase base para proveedores de WhatsApp
# Generado por AgentKit

"""
Define la interfaz común que todos los proveedores de WhatsApp deben implementar.
Esto permite cambiar de proveedor sin modificar el resto del código.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from fastapi import Request


@dataclass
class MensajeEntrante:
    """Mensaje normalizado — mismo formato sin importar el proveedor."""
    telefono: str       # Numero del remitente
    texto: str          # Contenido del mensaje (o transcripcion si es audio)
    mensaje_id: str     # ID unico del mensaje
    es_propio: bool     # True si lo envio el agente o un humano externo (fromMe)
    audio_url: str = "" # URL de descarga del audio (si es voice/ptt)
    # Source del envio para mensajes fromMe (solo WAHA por ahora):
    #   "app" -> WhatsApp Web / app nativa (humano externo)
    #   "api" -> WAHA API (eco de envio del agente o Seguimiento)
    #   ""    -> WAHA antiguo sin campo source; usar heuristica outbound tracker
    source: str = ""
    # True si el mensaje fromMe trae media (imagen/video) sin texto; en ese caso
    # tambien activa takeover externo aunque texto este vacio.
    tiene_media: bool = False


class ProveedorWhatsApp(ABC):
    """Interfaz que cada proveedor de WhatsApp debe implementar."""

    @abstractmethod
    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        """Extrae y normaliza mensajes del payload del webhook."""
        ...

    @abstractmethod
    async def enviar_mensaje(self, telefono: str, mensaje: str) -> bool:
        """Envía un mensaje de texto. Retorna True si fue exitoso."""
        ...

    async def enviar_mensaje_returning_id(self, telefono: str, mensaje: str) -> str | None:
        """
        Envia un mensaje y retorna el ID del mensaje creado por el proveedor.
        Usado para dedupear webhooks from_me=true cuando capturamos mensajes
        enviados durante un takeover.

        Default: llama enviar_mensaje y retorna None (sin id). Providers que
        soportan retornar el id deberian sobreescribir este metodo.
        Sentinel "ok_no_id" significa: envio exitoso pero sin id disponible.
        """
        ok = await self.enviar_mensaje(telefono, mensaje)
        return "ok_no_id" if ok else None

    async def validar_webhook(self, request: Request) -> dict | int | None:
        """Verificación GET del webhook (solo Meta la requiere). Retorna respuesta o None."""
        return None

    async def indicar_escribiendo(self, telefono: str, delay: int = 3) -> None:
        """Muestra el indicador de escritura ('...') al cliente. Opcional por proveedor."""
        pass

    async def indicar_grabando(self, telefono: str) -> None:
        """Muestra el indicador de grabacion de audio al cliente. Opcional."""
        pass

    async def marcar_leido(self, telefono: str) -> None:
        """Marca mensajes del chat como leidos (ticks azules). Opcional."""
        pass

    async def reaccionar(self, telefono: str, mensaje_id: str, emoji: str) -> None:
        """Envia una reaccion emoji a un mensaje especifico. Opcional."""
        pass

    async def enviar_archivo(self, telefono: str, url: str, filename: str, caption: str = "") -> bool:
        """Envia un archivo (PDF, DOCX, etc.) al cliente. Retorna True si fue exitoso."""
        return False

    async def enviar_buttons(
        self,
        telefono: str,
        body_text: str,
        buttons: list[dict],
        footer: str | None = None,
    ) -> tuple[bool, int | None, str | None]:
        """
        Envia un mensaje con botones reply. Cap de 3 botones (limite WAHA reply).

        buttons: [{"id": "opt_1", "title": "Confirmar"}, ...]

        Retorna (ok, status_code, mensaje_id):
        - ok=True: envio exitoso, status 200/201, mensaje_id puede ser str o None.
        - ok=False, status_code=501: provider/engine no soporta (caer a list).
        - ok=False, status_code=otro o None: error real (caer a texto).

        Default: NotImplementedError para forzar override en providers que lo soportan.
        """
        raise NotImplementedError("Provider no implementa enviar_buttons")

    async def enviar_list(
        self,
        telefono: str,
        body_text: str,
        button_title: str,
        sections: list[dict],
        footer: str | None = None,
    ) -> tuple[bool, int | None, str | None]:
        """
        Envia un List Message. WAHA soporta hasta 10 rows totales en sections.

        sections: [{"title": "Servicios", "rows": [{"id": "opt_1", "title": "...", "description": "..."}, ...]}]

        Retorna (ok, status_code, mensaje_id).
        """
        raise NotImplementedError("Provider no implementa enviar_list")
