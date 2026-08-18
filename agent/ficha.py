# agent/ficha.py — Ficha del cliente (edicion 100% humana)

"""
La Ficha es un artefacto CURADO POR HUMANOS: solo se edita desde la UI del
plugin WordPress via PUT /ficha/{telefono}. El agente Python NO la genera,
NO la actualiza automaticamente, NO llama al LLM para sintetizarla.

Semantica:
- Ficha vacia (o no existe) → no se inyecta nada, prima el historial.
- Ficha con datos → se inyecta al system prompt como "datos verificados"
  con instruccion explicita al LLM: si el historial reciente los contradice,
  prima la ficha (fuente de verdad humana).

Historico: en 1.11.x hubo un intento de auto-generacion via LLM (quick model,
cierre de bloque, delta merge, force_full periodico). Se retiro en 1.12.0
tras observar respuestas erraticas causadas por alucinaciones del quick
model que el full model tomaba como verdad. La decision fue mover el feature
al carril curado-humano para eliminar la fuente de ruido. La tabla y los
endpoints GET/PUT sobreviven; POST /recalcular quedo como 410 Gone.
"""

import logging
from typing import Optional

from agent.memory import Ficha

logger = logging.getLogger("agentkit")


# Vocabulario sugerido de tags. NO se valida en el PUT (Q7=C): el plugin
# lo usa como dropdown/autocomplete pero acepta tags custom. Endpoint
# GET /ficha/tags/vocab lo expone al plugin.
TAGS_VOCABULARIO_SUGERIDO = [
    "lead_nuevo",
    "lead_calificado",
    "cita_agendada",
    "cita_confirmada",
    "pago_pendiente",
    "pago_verificado",
    "reclamo_abierto",
    "cliente_activo",
    "cliente_recurrente",
    "vip",
    "no_interesado",
]


def build_ficha_context(ficha: Optional[Ficha]) -> str:
    """
    Formatea el bloque de ficha para inyectar al system prompt del LLM.
    Retorna string vacio si la ficha es None o no tiene ningun dato util.

    Formato:
      ## Datos verificados del cliente
      Nombre: ...
      Email: ...
      Tags: ...
      Contexto previo: ...

      IMPORTANTE: Estos datos fueron verificados por un operador humano.
      Tratalos como fuente de verdad — si el historial reciente los
      contradice, prima esta ficha.
    """
    if ficha is None:
        return ""
    lineas: list[str] = []
    if ficha.nombre:
        lineas.append(f"Nombre: {ficha.nombre}")
    if ficha.email:
        lineas.append(f"Email: {ficha.email}")
    tags = ficha.tags or []
    if tags:
        lineas.append(f"Tags: {', '.join(tags)}")
    if ficha.resumen:
        lineas.append(f"Contexto previo: {ficha.resumen}")
    if not lineas:
        return ""
    cuerpo = "\n".join(lineas)
    advertencia = (
        "\n\nIMPORTANTE: Estos datos fueron verificados por un operador humano. "
        "Tratalos como fuente de verdad — si el historial reciente los contradice, "
        "prima esta ficha."
    )
    return f"\n\n## Datos verificados del cliente\n{cuerpo}{advertencia}"


async def debug_snapshot(telefono: str) -> dict:
    """
    Snapshot del estado interno para GET /ficha/{telefono}/debug.
    Sirve para diagnosticar visualmente que ve el agente para este contacto.
    No modifica nada, no llama al LLM.
    """
    from agent.memory import (
        obtener_ficha,
        obtener_historial_variantes,
    )
    historial, matched = await obtener_historial_variantes(telefono, limite=200)
    ficha_row = await obtener_ficha(telefono)
    ultimo_ts = None
    if historial:
        from datetime import datetime
        last = historial[-1].get("timestamp")
        if isinstance(last, datetime):
            ultimo_ts = last.isoformat()
    return {
        "telefono": telefono,
        "matched_variant": matched,
        "historial_count": len(historial),
        "ultimo_msg_ts": ultimo_ts,
        "ficha_existe": ficha_row is not None,
        "ficha_editada_en": ficha_row.editado_en.isoformat() if ficha_row and ficha_row.editado_en else None,
        "bloque_que_se_inyectaria": build_ficha_context(ficha_row),
    }
