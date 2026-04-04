# agent/tools.py — Herramientas del agente
# WhatsApp Agent Base

"""
Herramientas específicas del negocio.
Estas funciones extienden las capacidades del agente más allá de responder texto.
Personalizar según los casos de uso del cliente.
"""

import os
import yaml
import logging

logger = logging.getLogger("agentkit")


def cargar_info_negocio() -> dict:
    """Carga la información del negocio desde business.yaml."""
    try:
        with open("config/business.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.error("config/business.yaml no encontrado")
        return {}


def buscar_en_knowledge(consulta: str) -> str:
    """
    Busca información relevante en los archivos de /knowledge.
    Retorna el contenido más relevante encontrado.
    """
    resultados = []
    knowledge_dir = "knowledge"

    if not os.path.exists(knowledge_dir):
        return "No hay archivos de conocimiento disponibles."

    for archivo in os.listdir(knowledge_dir):
        ruta = os.path.join(knowledge_dir, archivo)
        if archivo.startswith(".") or not os.path.isfile(ruta):
            continue
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                contenido = f.read()
                if consulta.lower() in contenido.lower():
                    resultados.append(f"[{archivo}]: {contenido[:500]}")
        except (UnicodeDecodeError, IOError):
            continue

    if resultados:
        return "\n---\n".join(resultados)
    return "No encontré información específica sobre eso en mis archivos."


def escalar_a_humano(telefono: str, contexto: str) -> str:
    """
    Escala la conversación a un miembro del equipo.
    TODO: conectar con CRM, Slack, email u otro sistema de notificación.
    """
    logger.info(f"Escalada a humano — Tel: {telefono} | Contexto: {contexto}")
    return "Entendido, te conecto con alguien del equipo. ¿Me dejás tu nombre y un buen horario para que te contacten?"


def registrar_lead(telefono: str, nombre: str, interes: str) -> str:
    """
    Registra un lead interesado.
    TODO: integrar con CRM cuando esté disponible.
    """
    logger.info(f"Nuevo lead — Tel: {telefono} | Nombre: {nombre} | Interés: {interes}")
    return f"Lead registrado: {nombre} ({telefono}) — {interes}"


# ════════════════════════════════════════════════════════════
# Agregar aquí funciones específicas según el caso de uso:
#
# Si AGENDAR CITAS:
# def obtener_slots_disponibles(fecha): ...
# def reservar_cita(telefono, fecha, hora, servicio): ...
#
# Si TOMAR PEDIDOS:
# def agregar_al_carrito(telefono, producto, cantidad): ...
# def confirmar_pedido(telefono): ...
#
# Si SOPORTE:
# def crear_ticket(telefono, problema): ...
# def consultar_ticket(ticket_id): ...
# ════════════════════════════════════════════════════════════
