"""API for Nous/Tuya smart plug control. Requires local plug_controller.py to poll and execute."""
from fastapi import APIRouter, Query

from api.deps import check_permission
from database import kv_get, kv_set

router = APIRouter(tags=["plug"])

PLUG_STATE_KEY = "plug_dashboard_state"
PLUG_CMD_KEY = "plug_dashboard_cmd"


@router.get("/api/plug-status")
def ep_plug_status(key: str = Query("")):
    """Get current plug state (on/off/unknown) for dashboard."""
    check_permission(key, "plug")
    state = kv_get(PLUG_STATE_KEY, "unknown")
    return {"state": state}


@router.post("/api/plug-set")
def ep_plug_set(key: str = Query(""), state: str = Query("")):
    """Set pending command (on/off). Local script will execute."""
    check_permission(key, "plug")
    state = state.lower().strip()
    if state not in ("on", "off"):
        return {"ok": False, "error": "state must be on or off"}
    kv_set(PLUG_CMD_KEY, state)
    return {"ok": True, "pending": state}


@router.get("/api/plug-pending")
def ep_plug_pending(key: str = Query("")):
    """For local script: get and clear pending command."""
    check_permission(key, "plug")
    cmd = kv_get(PLUG_CMD_KEY, "")
    if cmd:
        kv_set(PLUG_CMD_KEY, "")  # clear
    return {"cmd": cmd if cmd else None}


@router.post("/api/plug-done")
def ep_plug_done(key: str = Query(""), state: str = Query("")):
    """For local script: report actual state after executing command."""
    check_permission(key, "plug")
    state = state.lower().strip() if state else "unknown"
    if state in ("on", "off", "unknown"):
        kv_set(PLUG_STATE_KEY, state)
    return {"ok": True}
