# agent/ficha.py — Ficha persistente del cliente + auto-refresh

"""
Genera y actualiza la Ficha del cliente en background.

Trigger: cuando llega un mensaje nuevo y el ultimo mensaje registrado tiene
mas de FICHA_CIERRE_BLOQUE_HORAS (default 6h) de antiguedad. El calculo
corre en background y no bloquea la respuesta al cliente actual.

Modelo LLM: usa el primer modelo del tier FULL configurado (mejor calidad
para extraccion estructurada). Env override: FICHA_MODEL.

Formato: JSON estricto con {nombre, email, tags, resumen}. Merge incremental
cuando ya existe ficha vigente (D4=b).
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from openai import AsyncOpenAI

from agent.config_loader import get_ai_models
from agent.memory import (
    Ficha,
    obtener_ficha,
    obtener_historial,
    obtener_ultimo_timestamp,
    upsert_ficha_auto,
)

logger = logging.getLogger("agentkit")

FICHA_CIERRE_BLOQUE_HORAS = float(os.getenv("FICHA_CIERRE_BLOQUE_HORAS", "6"))
FICHA_HISTORIAL_MAX_MENSAJES = int(os.getenv("FICHA_HISTORIAL_MAX_MENSAJES", "200"))
FICHA_MODEL_OVERRIDE = os.getenv("FICHA_MODEL", "").strip()
FICHA_MAX_TOKENS = int(os.getenv("FICHA_MAX_TOKENS", "600"))

_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

_TAGS_BASE = [
    "lead_frio", "lead_calificado", "cita_agendada", "cliente_activo",
    "reclamo_abierto", "no_interesado", "requiere_seguimiento",
]


# --------------------------------------------------------------- Trigger ---

async def detectar_cierre_bloque(telefono: str) -> bool:
    """
    True si el ultimo mensaje del chat tiene >FICHA_CIERRE_BLOQUE_HORAS de
    antiguedad. False si no hay historial o si es reciente.
    """
    ultimo = await obtener_ultimo_timestamp(telefono)
    if ultimo is None:
        return False
    ahora = datetime.utcnow()
    delta = ahora - ultimo
    return delta >= timedelta(hours=FICHA_CIERRE_BLOQUE_HORAS)


# ---------------------------------------------------- Formateo / helpers ---

def _format_historial(historial: list[dict]) -> str:
    """Convierte historial a lineas [YYYY-MM-DD HH:MM] role: content."""
    lines = []
    for m in historial:
        role = "cliente" if m.get("role") == "user" else "agente"
        content = (m.get("content") or "").strip()
        if not content or content == "SILENCIO":
            continue
        ts = m.get("timestamp")
        if isinstance(ts, datetime):
            stamp = ts.strftime("%Y-%m-%d %H:%M")
        else:
            stamp = "----"
        lines.append(f"[{stamp}] {role}: {content}")
    return "\n".join(lines)


def _extract_json(text: str) -> Optional[dict]:
    """Parsea JSON del output del LLM. Tolera fences markdown si el modelo los agrega."""
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return None


def _sanitize_ficha_dict(raw: dict) -> dict:
    """Normaliza el dict del LLM a la forma canonica {nombre, email, tags, resumen}."""
    nombre = raw.get("nombre")
    email = raw.get("email")
    tags = raw.get("tags") or []
    resumen = raw.get("resumen")
    if isinstance(nombre, str):
        nombre = nombre.strip() or None
    else:
        nombre = None
    if isinstance(email, str):
        email = email.strip() or None
    else:
        email = None
    if not isinstance(tags, list):
        tags = []
    tags = [str(t).strip().lower().replace(" ", "_") for t in tags if t]
    tags = [t for t in tags if t][:5]
    if isinstance(resumen, str):
        resumen = resumen.strip() or None
    else:
        resumen = None
    return {"nombre": nombre, "email": email, "tags": tags, "resumen": resumen}


def _prompt_primera(historial_fmt: str) -> str:
    return f"""Sos un asistente que extrae la ficha de un cliente a partir del historial
completo de una conversacion de WhatsApp con nuestro agente comercial.

Tu unico output es un objeto JSON valido con esta forma exacta:

{{
  "nombre": string | null,
  "email": string | null,
  "tags": [string, ...],
  "resumen": string | null
}}

Reglas estrictas:

1. NOMBRE: solo si el cliente lo dijo explicitamente. No inventes. Si dijo
   "Juan", pone "Juan". Si dijo "Juan Perez", pone "Juan Perez". Si nunca
   se identifico, null.

2. EMAIL: solo si aparece un email valido en el historial (con @ y dominio).
   Si no, null.

3. TAGS: lista de etiquetas cortas en snake_case que resuman el estado del
   cliente. Usa las que apliquen de esta lista base:
     - lead_frio             (consultas iniciales sin definirse)
     - lead_calificado       (mostro interes concreto en algo)
     - cita_agendada         (agendo una reunion, turno o llamada)
     - cliente_activo        (ya compro / contrato)
     - reclamo_abierto       (tiene una queja no resuelta)
     - no_interesado         (dijo explicitamente que no)
     - requiere_seguimiento  (quedo algo pendiente de tu parte)
   Podes agregar tags nuevos si aparecen situaciones no cubiertas, siempre
   en snake_case y descriptivos (ej: "pidio_catalogo", "solicito_precio").
   Maximo 5 tags. Si no tenes senales claras, lista vacia [].

4. RESUMEN: 60-80 palabras en tercera persona, tono neutro/profesional.
   Incluye: en que quedaron, que producto/servicio le interesa, cualquier
   dato relevante que el agente deberia recordar en un proximo contacto
   (fechas mencionadas, condiciones especiales, dolores expresados).
   No repitas literalmente el chat. No inventes datos.
   Si el historial no tiene sustancia (ej: solo saludos), null.

5. Devolve SOLO el JSON. Sin explicaciones, sin markdown, sin fences.
   Si algo no se puede extraer, usa null o [] segun corresponda.

=== HISTORIAL ===
{historial_fmt}"""


def _prompt_incremental(ficha_vigente: dict, delta_fmt: str) -> str:
    ficha_json = json.dumps(ficha_vigente, ensure_ascii=False, indent=2)
    return f"""Sos un asistente que actualiza la ficha de un cliente a partir de nuevos
mensajes intercambiados desde la ultima actualizacion.

Recibis:
- La ficha VIGENTE (lo que ya sabemos del cliente).
- El DELTA (mensajes nuevos desde la ultima actualizacion).

Tu unico output es un objeto JSON valido con esta forma exacta:

{{
  "nombre": string | null,
  "email": string | null,
  "tags": [string, ...],
  "resumen": string | null
}}

Reglas de merge:

1. NOMBRE: si la ficha vigente ya tiene nombre, mantenelo (a menos que el
   cliente lo haya corregido explicitamente en el delta). Si estaba null y
   ahora aparece, agregarlo.

2. EMAIL: mismo criterio que nombre.

3. TAGS: partis de los tags vigentes. Agrega los nuevos que apliquen segun
   el delta. Remove los que ya no son ciertos (ej: "reclamo_abierto" si el
   reclamo se resolvio; "cita_agendada" si la cita se cancelo). Vocabulario:
     - lead_frio, lead_calificado, cita_agendada, cliente_activo,
       reclamo_abierto, no_interesado, requiere_seguimiento
   Podes agregar nuevos en snake_case si hay situaciones no cubiertas.
   Maximo 5 tags.

4. RESUMEN: reescribi el resumen combinando lo vigente con lo nuevo. NO
   concatenes ni acumules — hace una version fresca de 60-80 palabras que
   refleje el estado actual del cliente. Priorizá lo mas reciente si hay
   cambios (ej: si antes queria plan A y ahora quiere plan B, el resumen
   dice plan B).
   Mantene: fechas comprometidas, promesas del agente, dolores clave.

5. Devolve SOLO el JSON. Sin explicaciones, sin markdown, sin fences.

=== FICHA VIGENTE ===
{ficha_json}

=== DELTA (mensajes nuevos) ===
{delta_fmt}"""


# ------------------------------------------------------------- Generacion ---

def _model_para_ficha() -> str:
    """Retorna el modelo a usar: override env > primer modelo del tier full."""
    if FICHA_MODEL_OVERRIDE:
        return FICHA_MODEL_OVERRIDE
    models = get_ai_models().get("full") or []
    if models:
        return models[0]
    return "openai/gpt-4o-mini"


async def _llamar_llm(prompt: str) -> Optional[dict]:
    """Llama OpenRouter y parsea JSON. Retorna dict sanitizado o None."""
    model = _model_para_ficha()
    try:
        resp = await _client.chat.completions.create(
            model=model,
            max_tokens=FICHA_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
    except Exception as e:
        logger.warning(f"ficha: llamada LLM fallo ({type(e).__name__}: {e})")
        return None
    try:
        raw = resp.choices[0].message.content or ""
    except (AttributeError, IndexError):
        return None
    parsed = _extract_json(raw)
    if parsed is None:
        logger.warning(f"ficha: LLM devolvio JSON invalido: {raw[:200]}")
        return None
    return _sanitize_ficha_dict(parsed)


async def generar_ficha(telefono: str, historial: list[dict]) -> Optional[dict]:
    """
    Genera (o actualiza incrementalmente) la ficha para este telefono.
    Retorna dict {nombre, email, tags, resumen} o None si el LLM falla.

    Si ya existe ficha vigente: modo incremental, pasa ficha + delta desde
    ultima_actualizacion. Si es primera vez: modo full con todo el historial.
    """
    ficha_previa = await obtener_ficha(telefono)
    if ficha_previa is None:
        historial_recortado = historial[-FICHA_HISTORIAL_MAX_MENSAJES:]
        historial_fmt = _format_historial(historial_recortado)
        if not historial_fmt.strip():
            return None
        prompt = _prompt_primera(historial_fmt)
    else:
        cutoff = ficha_previa.ultima_actualizacion
        delta = [m for m in historial if _msg_ts_after(m, cutoff)]
        if not delta:
            return None
        delta_fmt = _format_historial(delta[-FICHA_HISTORIAL_MAX_MENSAJES:])
        if not delta_fmt.strip():
            return None
        vigente = {
            "nombre": ficha_previa.nombre,
            "email": ficha_previa.email,
            "tags": ficha_previa.tags or [],
            "resumen": ficha_previa.resumen,
        }
        prompt = _prompt_incremental(vigente, delta_fmt)
    return await _llamar_llm(prompt)


def _msg_ts_after(msg: dict, cutoff: datetime) -> bool:
    ts = msg.get("timestamp")
    if not isinstance(ts, datetime):
        return True
    return ts > cutoff


async def recalcular_ficha_background(telefono: str) -> None:
    """
    Fire-and-forget: dispara generacion + persistencia. Nunca levanta.
    Respeta editado_manualmente via upsert_ficha_auto.
    """
    try:
        historial = await obtener_historial(telefono, limite=FICHA_HISTORIAL_MAX_MENSAJES)
        if not historial:
            return
        data = await generar_ficha(telefono, historial)
        if data is None:
            return
        await upsert_ficha_auto(
            telefono=telefono,
            nombre=data["nombre"],
            email=data["email"],
            tags=data["tags"],
            resumen=data["resumen"],
        )
        logger.info(f"ficha: recalculada para {telefono} (tags={data['tags']})")
    except Exception as e:
        logger.warning(f"ficha: recalculo background fallo para {telefono}: {e}")


# ------------------------------------------------------ Injection al prompt ---

def _describir_recencia(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    ahora = datetime.utcnow()
    delta = ahora - ts
    dias = delta.days
    horas = delta.seconds // 3600
    if dias >= 2:
        return f"hace {dias} dias"
    if dias == 1:
        return "hace 1 dia"
    if horas >= 2:
        return f"hace {horas} horas"
    if horas == 1:
        return "hace 1 hora"
    return "hace menos de 1 hora"


def build_ficha_context(ficha: Ficha | None) -> str:
    """
    Formatea el bloque de ficha para inyectar al system prompt.
    Retorna string vacio si no hay ficha o esta vacia.
    """
    if ficha is None:
        return ""
    lines: list[str] = []
    if ficha.nombre:
        lines.append(f"Nombre: {ficha.nombre}")
    if ficha.email:
        lines.append(f"Email: {ficha.email}")
    tags = ficha.tags or []
    if tags:
        lines.append(f"Tags: {', '.join(tags)}")
    if ficha.resumen:
        lines.append(f"Contexto previo: {ficha.resumen}")
    recencia = _describir_recencia(ficha.ultima_actualizacion)
    if recencia:
        lines.append(f"Ultima interaccion: {recencia}")
    if not lines:
        return ""
    return "\n\n## Ficha del cliente\n" + "\n".join(lines)
