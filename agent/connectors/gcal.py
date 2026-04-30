# agent/connectors/gcal.py
"""
Tool schemas para Google Calendar (formato OpenAI function calling).

Las tools son:
- gcal_consultar_disponibilidad: lista horarios libres
- gcal_crear_turno: reserva un turno
- gcal_consultar_proximos_turnos: lista turnos del cliente
- gcal_cancelar_turno: cancela un turno
- gcal_confirmar_turno: marca un turno como confirmado (para flow 24h)
- guardar_contacto: persiste nombre/email aprendido durante la conversacion (local, no Google)

`telefono` no aparece en los parameters — el executor lo agrega automaticamente al ejecutar.
"""

GCAL_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "gcal_consultar_disponibilidad",
            "description": (
                "Consulta horarios libres para reservar un turno. "
                "Usar cuando el cliente pide un turno y aun no se le ofrecio horario."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "servicio": {
                        "type": "string",
                        "description": "Servicio que pide el cliente (ej: 'limpieza', 'control', 'endodoncia')",
                    },
                    "fecha_aproximada": {
                        "type": "string",
                        "description": (
                            "Fecha tentativa formato YYYY-MM-DD, o frase libre como "
                            "'manana', 'lunes proximo', 'esta semana'. Vacio si el cliente no especifico."
                        ),
                    },
                },
                "required": ["servicio"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gcal_crear_turno",
            "description": (
                "Reserva un turno. Llamar SOLO despues de que el cliente confirmo un horario "
                "especifico ofrecido por gcal_consultar_disponibilidad, y se tienen su nombre y "
                "email (o el cliente decidio no dar email)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "servicio": {"type": "string"},
                    "fecha_hora_inicio": {
                        "type": "string",
                        "description": "ISO 8601, ej: '2026-05-05T10:30:00'",
                    },
                    "nombre": {"type": "string"},
                    "email": {
                        "type": "string",
                        "description": "Vacio si el cliente no quiso darlo",
                    },
                },
                "required": ["servicio", "fecha_hora_inicio", "nombre"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gcal_consultar_proximos_turnos",
            "description": (
                "Lista los turnos futuros que tiene reservados ESTE cliente "
                "(identificado por su numero de WhatsApp)."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gcal_cancelar_turno",
            "description": (
                "Cancela un turno futuro del cliente. event_id se obtiene de "
                "gcal_consultar_proximos_turnos."
            ),
            "parameters": {
                "type": "object",
                "properties": {"event_id": {"type": "string"}},
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gcal_confirmar_turno",
            "description": (
                "Marca un turno como confirmado por el cliente "
                "(usar tras el recordatorio 24h cuando el cliente confirma)."
            ),
            "parameters": {
                "type": "object",
                "properties": {"event_id": {"type": "string"}},
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "guardar_contacto",
            "description": (
                "Guarda el nombre y/o email del cliente cuando los aprendes durante la "
                "conversacion. Llamala apenas el cliente provee su nombre o email — "
                "incluso si todavia no pidio turno."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre": {"type": "string"},
                    "email": {"type": "string"},
                },
            },
        },
    },
]
