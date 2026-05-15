# tests/mock_plugin_guided.py
# Mini FastAPI mock del endpoint /guided del plugin WP.
#
# Uso: uvicorn tests.mock_plugin_guided:app --port 9100
# Setear: GUIDED_URL_BASE=http://localhost:9100/wp-json/gowap/v1/guided/test-token

from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException

app = FastAPI(title="Mock Plugin Guided")

_VALID_TOKEN = "test-token"
_templates: list[dict] = []
_dispatches: list[dict] = []
_selections: list[dict] = []
_next_dispatch_id = 1


@app.get("/wp-json/gowap/v1/guided/{token}/active")
async def get_active(token: str):
    if token != _VALID_TOKEN:
        raise HTTPException(status_code=401, detail={"code": "guided_token_invalid"})
    return _templates


@app.post("/wp-json/gowap/v1/guided/{token}/dispatch")
async def post_dispatch(token: str, body: dict):
    global _next_dispatch_id
    if token != _VALID_TOKEN:
        raise HTTPException(status_code=401)
    dispatch_id = _next_dispatch_id
    _next_dispatch_id += 1
    _dispatches.append({"id": dispatch_id, **body})
    return {"dispatch_id": dispatch_id}


@app.post("/wp-json/gowap/v1/guided/{token}/dispatch/{dispatch_id}/selection")
async def post_selection(token: str, dispatch_id: int, body: dict):
    if token != _VALID_TOKEN:
        raise HTTPException(status_code=401)
    _selections.append({"dispatch_id": dispatch_id, **body})
    return {"ok": True}


# Control endpoints (no parte del contrato real)

@app.post("/_mock/templates")
async def set_templates(templates: list[dict]):
    global _templates
    _templates = templates
    return {"ok": True, "count": len(_templates)}


@app.get("/_mock/state")
async def get_state():
    return {
        "templates": _templates,
        "dispatches": _dispatches,
        "selections": _selections,
    }


@app.post("/_mock/reset")
async def reset():
    global _templates, _dispatches, _selections, _next_dispatch_id
    _templates = []
    _dispatches = []
    _selections = []
    _next_dispatch_id = 1
    return {"ok": True}
