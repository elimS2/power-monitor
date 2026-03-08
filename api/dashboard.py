"""Dashboard API routes."""
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from api.deps import check_admin, check_key
from database import kv_get, recent_events, recent_heartbeats

router = APIRouter(tags=["dashboard"])


@router.get("/api/status")
async def ep_status(key: str = Query("")):
    check_key(key)
    return {
        "power_down": kv_get("power_down") == "1",
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
