# agent/guided_selection.py — Matcher de input del usuario contra opciones de un dispatch

"""
Cuando el usuario responde a una plantilla guiada activa, este modulo decide
si su input matchea una opcion concreta.

Niveles de match (en orden):
1. Numero puro: "1", "2", ...  -> match por order (1-indexed)
2. Emoji numerico: 1️⃣, 2️⃣, ..., 🔟  -> match por order
3. ID literal: "opt_11"  -> match exacto por id
4. Texto literal visible: "Confirmar"  -> match case-insensitive por visible_text
5. Match parcial: el visible_text esta dentro del texto user.lower()

Si nada matchea -> None (el caller pasa el mensaje al LLM normal).
"""

import re
from typing import Optional


_EMOJI_NUMS = {
    "1️⃣": 1, "2️⃣": 2, "3️⃣": 3, "4️⃣": 4, "5️⃣": 5,
    "6️⃣": 6, "7️⃣": 7, "8️⃣": 8, "9️⃣": 9, "🔟": 10,
}
_NUM_RE = re.compile(r"^\d{1,2}$")
_OPT_ID_RE = re.compile(r"^opt_(\d+)$")


def match_user_input(text: str, dispatch: dict) -> Optional[dict]:
    """
    Intenta matchear el input del usuario contra las opciones del dispatch.
    Retorna {"option": {...}, "match_kind": "..."} o None.
    """
    options = dispatch.get("options_snapshot") or []
    if not options:
        return None

    raw = (text or "").strip()
    if not raw:
        return None

    # 1) Numero puro
    if _NUM_RE.match(raw):
        n = int(raw)
        if 1 <= n <= len(options):
            return {"option": options[n - 1], "match_kind": "number"}

    # 2) Emoji numerico
    raw_collapsed = raw.replace("️", "")
    for emoji, n in _EMOJI_NUMS.items():
        if raw == emoji or raw_collapsed == emoji.replace("️", ""):
            if 1 <= n <= len(options):
                return {"option": options[n - 1], "match_kind": "emoji"}

    # 3) ID literal (botones reply mandan "opt_{id}")
    m = _OPT_ID_RE.match(raw)
    if m:
        target_id = int(m.group(1))
        for o in options:
            if int(o.get("id", -1)) == target_id:
                return {"option": o, "match_kind": "id"}

    # 4) Texto literal visible (case insensitive, igual exacto)
    low = raw.lower()
    for o in options:
        vt = (o.get("visible_text") or "").strip().lower()
        if vt and vt == low:
            return {"option": o, "match_kind": "text_exact"}

    # 5) Match parcial: visible_text esta dentro del input (al menos 3 chars)
    for o in options:
        vt = (o.get("visible_text") or "").strip().lower()
        if len(vt) >= 3 and vt in low:
            return {"option": o, "match_kind": "text_substring"}

    return None
