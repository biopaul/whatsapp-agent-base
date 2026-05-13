# tests/mock_plugin_takeover.py
# Mini FastAPI server que simula el endpoint /takeover del plugin WP.
#
# Uso:
#   uvicorn tests.mock_plugin_takeover:app --port 9000
#
# Setear en el agente:
#   TAKEOVER_URL_BASE=http://localhost:9000/wp-json/gowap/v1/takeover/test-token

from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, HTTPException

app = FastAPI(title="Mock Plugin Takeover")
_state: dict[str, dict] = {}  # chat_id -> {"expires_at": datetime}
_VALID_TOKEN = "test-token"


@app.get("/wp-json/gowap/v1/takeover/{token}/active")
async def get_active(token: str):
    if token != _VALID_TOKEN:
        raise HTTPException(status_code=401, detail={"code": "takeover_token_invalid"})
    now = datetime.now(timezone.utc)
    return [
        {"chat_id": cid, "expires_at": entry["expires_at"].isoformat().replace("+00:00", "Z")}
        for cid, entry in _state.items()
        if entry["expires_at"] > now
    ]


@app.get("/wp-json/gowap/v1/takeover/{token}/{chat_id}")
async def get_chat(token: str, chat_id: str):
    if token != _VALID_TOKEN:
        raise HTTPException(status_code=401, detail={"code": "takeover_token_invalid"})
    entry = _state.get(chat_id)
    if entry is None:
        raise HTTPException(status_code=404)
    now = datetime.now(timezone.utc)
    if entry["expires_at"] <= now:
        return {"mode": "auto"}
    return {
        "mode": "manual",
        "expires_at": entry["expires_at"].isoformat().replace("+00:00", "Z"),
    }


# Control endpoints (no parte del contrato real - solo para testing manual)

@app.post("/_mock/set_manual/{chat_id}")
async def set_manual(chat_id: str, minutes: int = 30):
    _state[chat_id] = {"expires_at": datetime.now(timezone.utc) + timedelta(minutes=minutes)}
    return {"ok": True, "chat_id": chat_id, "expires_in_min": minutes}


@app.post("/_mock/set_auto/{chat_id}")
async def set_auto(chat_id: str):
    _state.pop(chat_id, None)
    return {"ok": True, "chat_id": chat_id}


@app.get("/_mock/state")
async def get_state():
    return _state
