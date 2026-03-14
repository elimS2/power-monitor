"""Heartbeat API routes."""
from fastapi import APIRouter, Query

from api.deps import check_admin, check_permission
from database import kv_set, save_heartbeat

router = APIRouter(tags=["heartbeat"])


@router.get("/api/heartbeat")
async def ep_heartbeat(
    plug204: int = Query(0),
    plug175: int = Query(0),
    key: str = Query(""),
):
    check_permission(key, "heartbeat")
    save_heartbeat(plug204, plug175)
    kv_set("stale_alerted", "0")
    from power_monitor import analyze, log

    log.debug("HB plug204=%d plug175=%d", plug204, plug175)
    await analyze()
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
