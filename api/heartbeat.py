"""Heartbeat API routes.

The apartment router still posts plug pings here. The rows are history.
They do not decide whether the building has light.
"""
import logging

from fastapi import APIRouter, Query

from api.deps import check_admin, check_permission
from database import save_heartbeat

log = logging.getLogger("power_monitor")

router = APIRouter(tags=["heartbeat"])


@router.get("/api/heartbeat")
async def ep_heartbeat(
    plug204: int = Query(0),
    plug175: int = Query(0),
    key: str = Query(""),
):
    check_permission(key, "heartbeat")
    save_heartbeat(plug204, plug175)
    log.debug("HB plug204=%d plug175=%d", plug204, plug175)
    return {"ok": True}


@router.get("/api/heartbeats")
def ep_heartbeats(
    key: str = Query(""),
    from_ts: float = Query(0),
    to_ts: float = Query(0),
    limit: int = Query(500),
):
    check_admin(key)
    from database import _conn

    with _conn() as db:
        if from_ts and to_ts:
            rows = db.execute(
                "SELECT plug204, plug175, ts FROM heartbeats WHERE ts BETWEEN ? AND ? ORDER BY ts",
                (from_ts, to_ts),
            ).fetchall()
        elif from_ts:
            rows = db.execute(
                "SELECT plug204, plug175, ts FROM heartbeats WHERE ts >= ? ORDER BY ts LIMIT ?",
                (from_ts, limit),
            ).fetchall()
        elif to_ts:
            rows = db.execute(
                "SELECT plug204, plug175, ts FROM heartbeats WHERE ts <= ? ORDER BY ts DESC LIMIT ?",
                (to_ts, limit),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT plug204, plug175, ts FROM heartbeats ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]
