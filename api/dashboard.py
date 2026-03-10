"""Dashboard API routes."""
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from api.deps import check_admin, check_key
from database import kv_get, recent_deye_log, recent_events, recent_heartbeats

router = APIRouter(tags=["dashboard"])


@router.get("/api/status")
async def ep_status(key: str = Query("")):
    check_key(key)
    deye_last = None
    rows = recent_deye_log(1)
    if rows:
        r = rows[0]
        deye_last = {
            "grid_v_l1": r.get("grid_v_l1"),
            "grid_v_l2": r.get("grid_v_l2"),
            "grid_v_l3": r.get("grid_v_l3"),
            "ts": r.get("ts"),
        }
    return {
        "power_down": kv_get("power_down") == "1",
        "voltage_anomaly": kv_get("voltage_anomaly") == "1",
        "deye": deye_last,
        "heartbeats": recent_heartbeats(20),
        "events": recent_events(30),
    }


@router.get("/api/dashboard-fragments")
def ep_dashboard_fragments(key: str = Query("")):
    check_key(key)
    from power_monitor import _build_update_fragments

    return JSONResponse(
        _build_update_fragments(),
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@router.get("/api/events")
def ep_events(key: str = Query(""), limit: int = Query(50)):
    check_admin(key)
    return recent_events(limit)
