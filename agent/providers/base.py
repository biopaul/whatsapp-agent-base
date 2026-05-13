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
    es_propio: bool     # True si lo envio el agente (se ignora)
    audio_url: str = "" # URL de descarga del audio (si es voice/ptt)


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
