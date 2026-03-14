"""Debug API routes."""
import re
import subprocess
import time
from datetime import datetime

from fastapi import APIRouter, Query

from api.deps import check_admin, check_permission
from config import UA_TZ
from database import DOWN_LIKE_EVENTS, _conn, events_in_range, parse_boiler_schedule

router = APIRouter(tags=["debug"])

# Read-only SQL: only SELECT allowed
_SQL_READONLY = re.compile(r"^\s*(SELECT|WITH\s+\w+\s+AS)", re.IGNORECASE | re.DOTALL)
_SQL_FORBIDDEN = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE)\b", re.IGNORECASE)


@router.get("/api/debug-webhooks")
def ep_debug_webhooks(key: str = Query(""), limit: int = Query(20)):
    check_permission(key, "debug")
    with _conn() as db:
        rows = db.execute(
            "SELECT id, chat_id, text, ts FROM webhook_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "chat_id": r["chat_id"],
            "text": r["text"],
            "ts": datetime.fromtimestamp(r["ts"], tz=UA_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        }
        for r in rows
    ]


@router.get("/api/debug-boiler-parse")
def ep_debug_boiler_parse(key: str = Query(""), text: str = Query("")):
    check_permission(key, "debug")
    result = parse_boiler_schedule(text)
    return {"input_len": len(text), "parsed": result}


@router.get("/api/debug-deye-battery")
def ep_debug_deye_battery(key: str = Query(""), days: int = Query(7, ge=1, le=31)):
    """Debug battery episodes: raw deye_log rows (battery_soc, battery_power_w) per discharge/charge episode."""
    check_permission(key, "debug")
    now = datetime.now(UA_TZ)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    ts_start = month_start.timestamp()
    ts_end = time.time()
    charge_window_h = 6

    events = events_in_range(ts_start, ts_end)
    if not events:
        return {"message": "no power_events in range", "ts_start": ts_start, "ts_end": ts_end}

    with _conn() as db:
        deye_rows = db.execute(
            """SELECT battery_soc, battery_power_w, ts FROM deye_log
               WHERE ts >= ? AND ts <= ? ORDER BY ts""",
            (ts_start, ts_end + charge_window_h * 3600),
        ).fetchall()
    deye_rows = [dict(r) for r in deye_rows]

    episodes = []
    i = 0
    while i < len(events):
        if events[i]["event"] not in DOWN_LIKE_EVENTS:
            i += 1
            continue
        down_ts = events[i]["ts"]
        up_ts = None
        j = i + 1
        while j < len(events):
            if events[j]["event"] == "up":
                up_ts = events[j]["ts"]
                break
            if events[j]["event"] in DOWN_LIKE_EVENTS:
                break
            j += 1
        i = j

        if up_ts is None:
            continue

        ep_rows = [r for r in deye_rows if down_ts <= r["ts"] <= up_ts]
        ch_rows = [
            r for r in deye_rows
            if up_ts <= r["ts"] <= min(up_ts + charge_window_h * 3600, ts_end + 3600)
        ]

        def fmt_row(r):
            dt = datetime.fromtimestamp(r["ts"], tz=UA_TZ).strftime("%Y-%m-%d %H:%M:%S")
            return {
                "ts_str": dt,
                "battery_soc": r.get("battery_soc"),
                "battery_power_w": r.get("battery_power_w"),
            }

        episodes.append({
            "down": datetime.fromtimestamp(down_ts, tz=UA_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "up": datetime.fromtimestamp(up_ts, tz=UA_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "discharge_rows": [fmt_row(r) for r in ep_rows],
            "discharge_count": len(ep_rows),
            "charge_rows": [fmt_row(r) for r in ch_rows],
            "charge_count": len(ch_rows),
        })

    return {
        "ts_start": ts_start,
        "ts_end": ts_end,
        "events_count": len(events),
        "deye_total_rows": len(deye_rows),
        "episodes": episodes[-days:] if episodes else [],
    }


@router.get("/api/debug-sql")
def ep_debug_sql(key: str = Query(""), query: str = Query(""), limit: int = Query(500, ge=1, le=1000)):
    """Execute read-only SQL (SELECT only). For agent/CI access to DB."""
    check_permission(key, "debug")
    q = query.strip()
    if not _SQL_READONLY.match(q):
        return {"error": "only SELECT (or WITH ... AS) allowed"}
    if _SQL_FORBIDDEN.search(q):
        return {"error": "forbidden keywords: INSERT, UPDATE, DELETE, DROP, etc."}
    try:
        with _conn() as db:
            db.execute("PRAGMA read_uncommitted = 1")
            rows = db.execute(q, ()).fetchmany(limit)
        return {"rows": [dict(r) for r in rows], "count": len(rows)}
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/debug-log")
def ep_debug_log(key: str = Query(""), lines: int = Query(100, ge=1, le=500)):
    """Read power-monitor service log from journalctl. Admin only."""
    check_admin(key)
    try:
        out = subprocess.run(
            ["journalctl", "-u", "power-monitor", "-n", str(lines), "--no-pager"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd="/",
        )
        if out.returncode != 0:
            return {"error": out.stderr or f"exit {out.returncode}", "lines": 0}
        return {"lines": len(out.stdout.strip().splitlines()), "log": out.stdout}
    except subprocess.TimeoutExpired:
        return {"error": "timeout", "lines": 0}
    except Exception as e:
        return {"error": str(e), "lines": 0}
