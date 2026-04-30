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
from sqlalchemy import String, Text, DateTime, select, Integer
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


async def inicializar_db():
    """Crea las tablas si no existen."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def guardar_mensaje(telefono: str, role: str, content: str):
    """Guarda un mensaje en el historial de conversación."""
    async with async_session() as session:
        mensaje = Mensaje(
            telefono=telefono,
            role=role,
            content=content,
            timestamp=datetime.utcnow()
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
