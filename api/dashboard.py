"""Dashboard API routes."""
import time
from urllib.parse import quote

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from api.deps import check_admin, check_permission
from config import API_KEYS, GIT_COMMIT
from database import kv_get, recent_deye_log, recent_events, recent_heartbeats
import dtek

router = APIRouter(tags=["dashboard"])


@router.get("/api/status")
async def ep_status(key: str = Query("")):
    check_permission(key, "dashboard")
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
    check_permission(key, "dashboard")
    from power_monitor import _build_update_fragments, record_online

    record_online(key)

    frags = _build_update_fragments()
    key_label = API_KEYS.get(key, "")
    is_admin = API_KEYS.get(key) == "admin"
    qk = quote(key, safe="")
    ver_parts = [frags["pm_ver"]]
    if key_label:
        ver_parts.append(f'<span data-pm-footer="key"> · {key_label}</span>')
    if is_admin:
        ver_parts.append(f'<span data-pm-footer="admin"> · <a href="/admin?key={qk}" style="color:var(--muted)">Адмін</a></span>')
    frags["pm_ver"] = "".join(ver_parts)

    return JSONResponse(
        frags,
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
    from power_monitor import _ts_fmt_hm, get_display_status, update_chat_photo
    from database import last_nonzero_grid_voltage

    now = time.time()
    status = get_display_status()
    v = last_nonzero_grid_voltage()
    parts = []
    if v:
        for phase, k in (("L1", "grid_v_l1"), ("L2", "grid_v_l2"), ("L3", "grid_v_l3")):
            val = v.get(k)
            parts.append(f"{phase}={val:.0f} В" if val is not None else f"{phase}=—")
    v_str = ", ".join(parts) if parts else ""

    if status["status_text"] == "Світло є":
        msg = f"\u2705 {_ts_fmt_hm(now)} Світло є, напруга в нормі"
    elif status["status_text"] == "Світло ВІДСУТНЄ":
        slot = dtek.current_slot_status()
        sched = " (\U0001f4c5 За графіком)" if slot in ("maybe", "off") else " (\u26a1Позапланове)" if slot == "ok" else ""
        msg = f"\u274c {_ts_fmt_hm(now)} Світло ВІДСУТНЄ{sched}"
    else:
        msg = f"\u26a1 {_ts_fmt_hm(now)} {status['status_text']}"
    if v_str:
        msg += f"\n\U0001f4a0 Напруга: {v_str}"

    await update_chat_photo(
        is_down=(status["voltage"] is None and status["status_cls"] == "down"),
        voltage=status.get("voltage"),
        message_to_send=msg,
    )
    return {"ok": True, "sent": True, "status": status["status_text"]}
