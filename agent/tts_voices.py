# agent/tts_voices.py — Catalogo curado de voces TTS

"""
Catalogo de voice_ids de ElevenLabs curados por acento y genero.

El plugin WP envia la KEY (ej "AR_F_v1") en el config.tts.voice_id.
El agente la resuelve aca al voice_id concreto de ElevenLabs.

Esto permite cambiar el voice_id concreto sin tocar el contrato con WP
(util si una voz se discontinua o encontramos una mejor).

Pre-lanzamiento: Pablo testea voces en el playground de ElevenLabs y reemplaza
los placeholders abajo por los voice_ids reales antes del primer deploy productivo.
"""

from typing import Optional


VOICES: dict[str, dict] = {
    "AR_M_v1": {"voice_id": "QK4xDwo9ESPHA4JNUpX3", "label": "Argentina - Hombre"},
    "AR_F_v1": {"voice_id": "4wDRKlxcHNOFO5kBvE81", "label": "Argentina - Mujer"},
    "CO_M_v1": {"voice_id": "ECOET12tGKHdXyB0CfqU", "label": "Colombia - Hombre"},
    "CO_F_v1": {"voice_id": "VmejBeYhbrcTPwDniox7", "label": "Colombia - Mujer"},
    "ES_M_v1": {"voice_id": "j41pQugxGaKleSQLIyG2", "label": "Espana - Hombre"},
    "ES_F_v1": {"voice_id": "ERYLdjEaddaiN9sDjaMX", "label": "Espana - Mujer"},
}


def resolve_voice_id(key: Optional[str]) -> Optional[str]:
    """
    Resuelve una key del catalogo (ej "AR_F_v1") al voice_id concreto de ElevenLabs.
    Retorna None si la key es vacia o no existe en el catalogo.
    """
    if not key:
        return None
    entry = VOICES.get(key)
    if entry is None:
        return None
    return entry.get("voice_id")
