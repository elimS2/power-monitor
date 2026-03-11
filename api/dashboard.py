"""Dashboard API routes."""
import time

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from api.deps import check_admin, check_key
from database import kv_get, recent_deye_log, recent_events, recent_heartbeats
import dtek

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


@router.post("/api/refresh-status")
async def ep_refresh_status(key: str = Query("")):
    """Оновити аватарку та надіслати повідомлення про поточний стан у канал."""
    check_admin(key)
    from power_monitor import _ts_fmt_hm, update_chat_photo
    from database import last_nonzero_grid_voltage, deye_voltage_trend, has_grid_voltage_now

    now = time.time()
    is_down = kv_get("power_down") == "1"
    voltage_anomaly = kv_get("voltage_anomaly") == "1"

    if is_down:
        await update_chat_photo(True)
        return {"ok": True, "message": "power_down — аватарка оновлена, повідомлення не надсилається"}

    plugs_dead = False
    hb = recent_heartbeats(1)
    if hb:
        plugs_dead = hb[0]["plug204"] == 0 and hb[0]["plug175"] == 0

    if voltage_anomaly or (plugs_dead and has_grid_voltage_now()):
        from power_monitor import VOLTAGE_STATUS

        has_voltage = has_grid_voltage_now()
        is_scheduled = None
        if voltage_anomaly and plugs_dead and not has_voltage:
            slot = dtek.current_slot_status()
            is_scheduled = slot in ("maybe", "off") if slot else False
        trend = deye_voltage_trend(1000, is_scheduled=is_scheduled)
        s = VOLTAGE_STATUS.get(trend, VOLTAGE_STATUS[None])
        await update_chat_photo(s["voltage"] is None, voltage=s["voltage"])
        return {"ok": True, "message": "voltage_anomaly — аватарка оновлена, повідомлення не надсилається"}

    await update_chat_photo(False)
    v = last_nonzero_grid_voltage()
    parts = []
    if v:
        for phase, k in (("L1", "grid_v_l1"), ("L2", "grid_v_l2"), ("L3", "grid_v_l3")):
            val = v.get(k)
            parts.append(f"{phase}={val:.0f} В" if val is not None else f"{phase}=—")
    v_str = ", ".join(parts) if parts else ""
    msg = f"\u2705 {_ts_fmt_hm(now)} Світло є, напруга в нормі"
    if v_str:
        msg += f"\n\U0001f4a0 Напруга: {v_str}"

    from power_monitor import tg_send
    await tg_send(msg)
    return {"ok": True, "sent": True}
