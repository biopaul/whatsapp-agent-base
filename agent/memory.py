# agent/memory.py — Memoria de conversaciones con SQLite
# Generado por AgentKit

"""
Sistema de memoria del agente. Guarda el historial de conversaciones
por número de teléfono usando SQLite (local) o PostgreSQL (producción).
"""

import os
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Text, DateTime, select, Integer, Boolean, JSON
from dotenv import load_dotenv

load_dotenv()

# Configuración de base de datos
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./agentkit.db")

# Si es PostgreSQL en producción, ajustar el esquema de URL
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Mensaje(Base):
    """Modelo de mensaje en la base de datos."""
    __tablename__ = "mensajes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), index=True)
    role: Mapped[str] = mapped_column(String(20))  # "user" o "assistant"
    content: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    mensaje_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)


class Contacto(Base):
    """
    Datos del cliente final aprendidos durante la conversación.
    Indexado por número de teléfono. Persiste entre sesiones.
    """
    __tablename__ = "contactos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), index=True, unique=True)
    nombre: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str] = mapped_column(String(190), default="")
    primer_contacto: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WahaSessionCapabilities(Base):
    """Cache de capabilities de WAHA por sesion (buttons/lists)."""
    __tablename__ = "waha_session_capabilities"

    session_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    supports_buttons: Mapped[bool] = mapped_column(Boolean, default=False)
    last_buttons_probe: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    supports_lists: Mapped[bool] = mapped_column(Boolean, default=True)
    last_lists_probe: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class GuidedDispatchLocal(Base):
    """Cache local de dispatches de plantillas guiadas (para resolver seleccion 10min)."""
    __tablename__ = "guided_dispatches_local"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(Integer, index=True)
    chat_id: Mapped[str] = mapped_column(String(100), index=True)
    dispatched_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    format_used: Mapped[str] = mapped_column(String(20))
    options_snapshot: Mapped[dict] = mapped_column(JSON, default=list)
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remote_dispatch_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


async def inicializar_db():
    """Crea las tablas si no existen + migracion no-destructiva."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Migracion: agregar mensaje_id si la tabla ya existia sin esa columna.
        try:
            await conn.exec_driver_sql(
                "ALTER TABLE mensajes ADD COLUMN mensaje_id VARCHAR(100) NULL"
            )
        except Exception:
            # Columna ya existe - ignorar (SQLite no soporta IF NOT EXISTS en ADD COLUMN)
            pass


async def guardar_mensaje(telefono: str, role: str, content: str, mensaje_id: str | None = None):
    """Guarda un mensaje en el historial de conversación."""
    async with async_session() as session:
        mensaje = Mensaje(
            telefono=telefono,
            role=role,
            content=content,
            timestamp=datetime.utcnow(),
            mensaje_id=mensaje_id,
        )
        session.add(mensaje)
        await session.commit()


async def obtener_historial(telefono: str, limite: int = 20) -> list[dict]:
    """
    Recupera los últimos N mensajes de una conversación.

    Args:
        telefono: Número de teléfono del cliente
        limite: Máximo de mensajes a recuperar (default: 20)

    Returns:
        Lista de diccionarios con role y content
    """
    async with async_session() as session:
        query = (
            select(Mensaje)
            .where(Mensaje.telefono == telefono)
            .order_by(Mensaje.timestamp.desc())
            .limit(limite)
        )
        result = await session.execute(query)
        mensajes = result.scalars().all()

        # Invertir para orden cronológico
        mensajes.reverse()

        return [
            {"role": msg.role, "content": msg.content}
            for msg in mensajes
        ]


async def obtener_ultimo_timestamp(telefono: str) -> datetime | None:
    """Retorna el timestamp del último mensaje de una conversación, o None si no hay."""
    async with async_session() as session:
        query = (
            select(Mensaje.timestamp)
            .where(Mensaje.telefono == telefono)
            .order_by(Mensaje.timestamp.desc())
            .limit(1)
        )
        result = await session.execute(query)
        row = result.scalar_one_or_none()
        return row


async def limpiar_historial(telefono: str):
    """Borra todo el historial de una conversación."""
    async with async_session() as session:
        query = select(Mensaje).where(Mensaje.telefono == telefono)
        result = await session.execute(query)
        mensajes = result.scalars().all()
        for msg in mensajes:
            await session.delete(msg)
        await session.commit()


async def obtener_contacto(telefono: str) -> Contacto | None:
    """Retorna el Contacto por teléfono o None si no existe."""
    async with async_session() as session:
        query = select(Contacto).where(Contacto.telefono == telefono)
        result = await session.execute(query)
        return result.scalar_one_or_none()


async def guardar_contacto(telefono: str, nombre: str = "", email: str = "") -> None:
    """
    Crea o actualiza el contacto. Solo actualiza los campos no vacíos
    (no pisa nombre con "" si ya hay nombre guardado, idem email).
    """
    async with async_session() as session:
        query = select(Contacto).where(Contacto.telefono == telefono)
        result = await session.execute(query)
        contacto = result.scalar_one_or_none()

        ahora = datetime.utcnow()
        if contacto is None:
            contacto = Contacto(
                telefono=telefono,
                nombre=nombre,
                email=email,
                primer_contacto=ahora,
                actualizado_en=ahora,
            )
            session.add(contacto)
        else:
            if nombre:
                contacto.nombre = nombre
            if email:
                contacto.email = email
            contacto.actualizado_en = ahora
        await session.commit()


async def existe_mensaje_id(telefono: str, mensaje_id: str | None) -> bool:
    """
    Verifica si ya guardamos este mensaje_id para este telefono.
    Usado para dedupear webhooks from_me=true cuando capturamos mensajes
    enviados por humanos durante un takeover.
    """
    if not mensaje_id:
        return False
    async with async_session() as session:
        query = (
            select(Mensaje.id)
            .where(Mensaje.telefono == telefono, Mensaje.mensaje_id == mensaje_id)
            .limit(1)
        )
        result = await session.execute(query)
        return result.scalar() is not None


async def get_waha_capabilities(session_id: str) -> dict:
    """Retorna capabilities cacheadas o defaults si no existe."""
    async with async_session() as session:
        q = select(WahaSessionCapabilities).where(WahaSessionCapabilities.session_id == session_id)
        row = (await session.execute(q)).scalar_one_or_none()
        if row is None:
            return {
                "session_id": session_id,
                "supports_buttons": False,
                "last_buttons_probe": None,
                "supports_lists": True,
                "last_lists_probe": None,
            }
        return {
            "session_id": row.session_id,
            "supports_buttons": row.supports_buttons,
            "last_buttons_probe": row.last_buttons_probe,
            "supports_lists": row.supports_lists,
            "last_lists_probe": row.last_lists_probe,
        }


async def set_waha_capability(session_id: str, capability: str, value: bool, probe_at: datetime) -> None:
    """Upsert de capability. capability: 'supports_buttons' o 'supports_lists'."""
    probe_field = "last_buttons_probe" if capability == "supports_buttons" else "last_lists_probe"
    async with async_session() as session:
        q = select(WahaSessionCapabilities).where(WahaSessionCapabilities.session_id == session_id)
        row = (await session.execute(q)).scalar_one_or_none()
        if row is None:
            row = WahaSessionCapabilities(session_id=session_id)
            session.add(row)
        setattr(row, capability, value)
        setattr(row, probe_field, probe_at)
        await session.commit()


async def guardar_dispatch_local(
    template_id: int, chat_id: str,
    dispatched_at: datetime, expires_at: datetime,
    format_used: str, options_snapshot: list,
    parent_id: int | None = None,
    remote_dispatch_id: int | None = None,
) -> int:
    """Guarda un dispatch local. Retorna id local."""
    async with async_session() as session:
        d = GuidedDispatchLocal(
            template_id=template_id, chat_id=chat_id,
            dispatched_at=dispatched_at, expires_at=expires_at,
            format_used=format_used, options_snapshot=options_snapshot,
            parent_id=parent_id, remote_dispatch_id=remote_dispatch_id,
        )
        session.add(d)
        await session.commit()
        return d.id


async def obtener_dispatch_activo(chat_id: str) -> dict | None:
    """Retorna el ultimo dispatch no expirado del chat o None."""
    now = datetime.utcnow()
    async with async_session() as session:
        q = (
            select(GuidedDispatchLocal)
            .where(GuidedDispatchLocal.chat_id == chat_id, GuidedDispatchLocal.expires_at > now)
            .order_by(GuidedDispatchLocal.dispatched_at.desc())
            .limit(1)
        )
        row = (await session.execute(q)).scalar_one_or_none()
        if row is None:
            return None
        return {
            "id": row.id,
            "template_id": row.template_id,
            "chat_id": row.chat_id,
            "dispatched_at": row.dispatched_at,
            "expires_at": row.expires_at,
            "format_used": row.format_used,
            "options_snapshot": row.options_snapshot or [],
            "parent_id": row.parent_id,
            "remote_dispatch_id": row.remote_dispatch_id,
        }


async def actualizar_remote_dispatch_id(local_id: int, remote_id: int) -> None:
    """Asocia el id remoto al dispatch local cuando WP responde."""
    async with async_session() as session:
        q = select(GuidedDispatchLocal).where(GuidedDispatchLocal.id == local_id)
        row = (await session.execute(q)).scalar_one_or_none()
        if row is not None:
            row.remote_dispatch_id = remote_id
            await session.commit()
