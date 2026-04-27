# agent/reactions.py — Logica de reacciones contextuales con emoji
#
# Decide si el mensaje del cliente merece una reaccion y cual.
# El objetivo es que se sienta humano: solo reaccionar cuando
# una persona real lo haria (cierre de conversacion, confirmacion,
# agradecimiento, entusiasmo, etc.)

import re
import random

# Patrones con sus emojis posibles.
# Cada tupla: (regex compilado, lista de emojis candidatos)
# Se evaluan en orden; el primero que matchee gana.
_PATTERNS: list[tuple[re.Pattern, list[str]]] = [
    # Agradecimiento / cierre amable
    (re.compile(
        r"(?:gracias|muchas gracias|te agradezco|muy amable|genial[,.]?\s*gracias)",
        re.IGNORECASE,
    ), ["👍", "😊"]),

    # Confirmacion de compra / contratacion
    (re.compile(
        r"(?:lo voy a (?:contratar|comprar|tomar|adquirir)|voy a (?:contratar|comprar)|quiero contratar|quiero comprar|me interesa contratar|cerramos|trato hecho|dale.*va)",
        re.IGNORECASE,
    ), ["💪", "🙌", "🔥"]),

    # Despedida / cierre conversacional
    (re.compile(
        r"(?:^(?:dale|ok|bueno|listo|perfecto|excelente|va|sale)[.!,]*\s*(?:gracias|te aviso|nos vemos|chau|bye|hasta luego|adios)?[.!]*$)",
        re.IGNORECASE,
    ), ["👍", "🙌"]),

    # "te aviso" / "lo veo y te digo"
    (re.compile(
        r"(?:te aviso|te confirmo|lo (?:veo|reviso|analizo|pienso|consulto)|me lo pienso|despues te (?:digo|escribo|aviso))",
        re.IGNORECASE,
    ), ["👍"]),

    # Entusiasmo explicito
    (re.compile(
        r"(?:que bueno|increible|espectacular|buenisimo|excelente noticia|me encanta|hermoso|fantastico)",
        re.IGNORECASE,
    ), ["🔥", "😊", "🙌"]),

    # Saludo inicial (no reaccionar -- dejar que el agente responda)
    # Se incluye para NO matchear accidentalmente con patrones genericos
]


def elegir_reaccion(texto_cliente: str) -> str | None:
    """
    Evalua el mensaje del cliente y retorna un emoji si amerita reaccion,
    o None si no debe reaccionar.

    Solo reacciona a mensajes cortos (< 120 chars) para evitar
    reaccionar a consultas largas donde se veria raro.
    """
    texto = texto_cliente.strip()

    # No reaccionar a mensajes largos (consultas, no cierres)
    if len(texto) > 120:
        return None

    # No reaccionar a preguntas (el cliente espera una respuesta, no un emoji)
    if "?" in texto:
        return None

    for pattern, emojis in _PATTERNS:
        if pattern.search(texto):
            return random.choice(emojis)

    return None
