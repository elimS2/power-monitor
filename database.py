"""
Power Monitor — database operations (SQLite).
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from datetime import datetime

from config import CLEANUP_KEEP_DAYS, DB_PATH, UA_TZ

log = logging.getLogger("power_monitor")

# Boiler schedule parser constants
_UA_MONTHS = {
    "січня": 1, "лютого": 2, "березня": 3, "квітня": 4,
    "травня": 5, "червня": 6, "липня": 7, "серпня": 8,
    "вересня": 9, "жовтня": 10, "листопада": 11, "грудня": 12,
}
_BOILER_LINE_RE = re.compile(
    r"(\d{1,2})\s+(січня|лютого|березня|квітня|травня|червня|липня|серпня|вересня|жовтня|листопада|грудня)\s*:\s*([\d:,\s\-–]+)",
)
_TIME_RANGE_RE = re.compile(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db():
    with _conn() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS heartbeats (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                plug204 INTEGER NOT NULL,
                plug175 INTEGER NOT NULL,
                ts      REAL    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_hb_ts ON heartbeats(ts);

            CREATE TABLE IF NOT EXISTS power_events (
                id    INTEGER PRIMARY KEY AUTOINCREMENT,
                event TEXT    NOT NULL,
                ts    REAL   NOT NULL
            );

            CREATE TABLE IF NOT EXISTS kv (
                key TEXT PRIMARY KEY,
                val TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tg_log (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT    NOT NULL,
                text    TEXT    NOT NULL,
                status  INTEGER NOT NULL,
                ts      REAL    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS schedule_history (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                target_date TEXT NOT NULL,
                grid_json   TEXT NOT NULL,
                fetched_at  REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sh_date ON schedule_history(target_date);

            CREATE TABLE IF NOT EXISTS boiler_schedule (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                target_date TEXT NOT NULL,
                intervals   TEXT NOT NULL,
                source_text TEXT NOT NULL,
                parsed_at   REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_bs_date ON boiler_schedule(target_date);

            CREATE TABLE IF NOT EXISTS webhook_log (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT    NOT NULL,
                text    TEXT    NOT NULL,
                raw_json TEXT   NOT NULL,
                ts      REAL   NOT NULL
            );

            CREATE TABLE IF NOT EXISTS weather_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                temp        REAL,
                humidity    REAL,
                wind        REAL,
                code        INTEGER,
                t_min       REAL,
                t_max       REAL,
                ts          REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_wl_ts ON weather_log(ts);

            CREATE TABLE IF NOT EXISTS alert_events (
                id    INTEGER PRIMARY KEY AUTOINCREMENT,
                event TEXT    NOT NULL,
                ts    REAL   NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ae_ts ON alert_events(ts);

            CREATE TABLE IF NOT EXISTS deye_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                load_power_w REAL,
                load_l1_w    REAL,
                load_l2_w    REAL,
                load_l3_w    REAL,
                grid_v_l1    REAL,
                grid_v_l2    REAL,
                grid_v_l3    REAL,
                battery_soc  REAL,
                battery_power_w REAL,
                battery_voltage REAL,
                ts           REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_deye_ts ON deye_log(ts);
        """)
        # Migration: add ts_kyiv (readable datetime Kyiv)
        try:
            db.execute("ALTER TABLE deye_log ADD COLUMN ts_kyiv TEXT")
        except sqlite3.OperationalError:
            pass  # column exists
        # Migration: add cumulative energy from Deye internal meter
        for col in ("day_load_kwh", "total_load_kwh", "month_load_kwh", "year_load_kwh"):
            try:
                db.execute(f"ALTER TABLE deye_log ADD COLUMN {col} REAL")
            except sqlite3.OperationalError:
                pass  # column exists
        # Migration: add grid power and grid energy (import/export)
        for col in (
            "grid_power_w",
            "day_grid_import_kwh",
            "day_grid_export_kwh",
            "total_grid_import_kwh",
            "total_grid_export_kwh",
        ):
            try:
                db.execute(f"ALTER TABLE deye_log ADD COLUMN {col} REAL")
            except sqlite3.OperationalError:
                pass  # column exists


def kv_get(key: str, default: str = "") -> str:
    with _conn() as db:
        row = db.execute("SELECT val FROM kv WHERE key=?", (key,)).fetchone()
        return row["val"] if row else default


def kv_set(key: str, val: str):
    with _conn() as db:
        db.execute(
            "INSERT INTO kv(key,val) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET val=excluded.val",
            (key, val),
        )


def save_heartbeat(p204: int, p175: int):
    with _conn() as db:
        db.execute(
            "INSERT INTO heartbeats(plug204, plug175, ts) VALUES(?,?,?)",
            (p204, p175, time.time()),
        )


def recent_heartbeats(n: int) -> list[dict]:
    with _conn() as db:
        rows = db.execute(
            "SELECT plug204, plug175, ts FROM heartbeats ORDER BY ts DESC LIMIT ?", (n,)
        ).fetchall()
    return [dict(r) for r in rows]


def save_event(event: str):
    with _conn() as db:
        db.execute("INSERT INTO power_events(event, ts) VALUES(?,?)", (event, time.time()))


def recent_events(n: int = 50) -> list[dict]:
    with _conn() as db:
        rows = db.execute(
            "SELECT event, ts FROM power_events ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
    return [dict(r) for r in rows]


def events_in_range(ts_start: float, ts_end: float) -> list[dict]:
    """Get power_events in [ts_start, ts_end] ordered by ts ascending."""
    with _conn() as db:
        rows = db.execute(
            "SELECT event, ts FROM power_events WHERE ts >= ? AND ts <= ? ORDER BY ts",
            (ts_start, ts_end),
        ).fetchall()
    return [dict(r) for r in rows]


def save_alert_event(event: str):
    with _conn() as db:
        db.execute("INSERT INTO alert_events(event, ts) VALUES(?,?)", (event, time.time()))


def recent_alert_events(n: int = 30) -> list[dict]:
    with _conn() as db:
        rows = db.execute(
            "SELECT event, ts FROM alert_events ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
    return [dict(r) for r in rows]


def save_deye_log(
    load_power_w: float | None = None,
    load_l1_w: float | None = None,
    load_l2_w: float | None = None,
    load_l3_w: float | None = None,
    grid_power_w: float | None = None,
    grid_v_l1: float | None = None,
    grid_v_l2: float | None = None,
    grid_v_l3: float | None = None,
    battery_soc: float | None = None,
    battery_power_w: float | None = None,
    battery_voltage: float | None = None,
    day_load_kwh: float | None = None,
    total_load_kwh: float | None = None,
    month_load_kwh: float | None = None,
    year_load_kwh: float | None = None,
    day_grid_import_kwh: float | None = None,
    day_grid_export_kwh: float | None = None,
    total_grid_import_kwh: float | None = None,
    total_grid_export_kwh: float | None = None,
):
    ts = time.time()
    ts_kyiv = datetime.fromtimestamp(ts, tz=UA_TZ).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as db:
        db.execute(
            """INSERT INTO deye_log (
                load_power_w, load_l1_w, load_l2_w, load_l3_w,
                grid_power_w,
                grid_v_l1, grid_v_l2, grid_v_l3,
                battery_soc, battery_power_w, battery_voltage,
                day_load_kwh, total_load_kwh, month_load_kwh, year_load_kwh,
                day_grid_import_kwh, day_grid_export_kwh, total_grid_import_kwh, total_grid_export_kwh,
                ts, ts_kyiv
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                load_power_w, load_l1_w, load_l2_w, load_l3_w,
                grid_power_w,
                grid_v_l1, grid_v_l2, grid_v_l3,
                battery_soc, battery_power_w, battery_voltage,
                day_load_kwh, total_load_kwh, month_load_kwh, year_load_kwh,
                day_grid_import_kwh, day_grid_export_kwh, total_grid_import_kwh, total_grid_export_kwh,
                ts, ts_kyiv,
            ),
        )


def recent_deye_log(n: int = 100) -> list[dict]:
    with _conn() as db:
        rows = db.execute(
            """SELECT load_power_w, load_l1_w, load_l2_w, load_l3_w,
                      grid_power_w,
                      grid_v_l1, grid_v_l2, grid_v_l3,
                      battery_soc, battery_power_w, battery_voltage,
                      day_load_kwh, total_load_kwh, month_load_kwh, year_load_kwh,
                      day_grid_import_kwh, day_grid_export_kwh, total_grid_import_kwh, total_grid_export_kwh,
                      ts
               FROM deye_log ORDER BY id DESC LIMIT ?""",
            (n,),
        ).fetchall()
    return [dict(r) for r in rows]


def _integrate_kwh(rows: list) -> float:
    """Trapezoidal integration of load_power_w over time. Returns kWh."""
    total = 0.0
    for i in range(1, len(rows)):
        p_prev = rows[i - 1]["load_power_w"] or 0
        p_curr = rows[i]["load_power_w"] or 0
        dt_h = (rows[i]["ts"] - rows[i - 1]["ts"]) / 3600
        total += (p_prev + p_curr) / 2 * dt_h / 1000  # W -> kWh
    return total


def deye_monthly_load_kwh() -> float | None:
    """Compute load energy (kWh) for current month from deye_log using trapezoidal integration."""
    daily = deye_daily_load_kwh()
    if not daily:
        return None
    return round(sum(d["kwh"] for d in daily), 1)


def _integrate_range(ts_start: float, ts_end: float) -> float | None:
    """Integrate load_power_w in [ts_start, ts_end]. Returns kWh or None if insufficient data."""
    with _conn() as db:
        rows = db.execute(
            """SELECT load_power_w, ts FROM deye_log
               WHERE ts >= ? AND ts <= ? AND load_power_w IS NOT NULL
               ORDER BY ts""",
            (ts_start, ts_end),
        ).fetchall()
    if len(rows) < 2:
        return None
    return round(_integrate_kwh([dict(r) for r in rows]), 2)


def deye_day_load_kwh_integrated() -> float | None:
    """Load energy for today from load_power_w integration (our calculation)."""
    now = datetime.now(UA_TZ)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return _integrate_range(day_start.timestamp(), time.time())


def deye_yearly_load_kwh() -> float | None:
    """Load energy for current year from load_power_w integration."""
    now = datetime.now(UA_TZ)
    year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return _integrate_range(year_start.timestamp(), time.time())


def deye_total_load_kwh_integrated() -> float | None:
    """Total load energy from first deye_log entry (our integration since start)."""
    with _conn() as db:
        row = db.execute(
            "SELECT MIN(ts) as ts_min FROM deye_log WHERE load_power_w IS NOT NULL"
        ).fetchone()
    if not row or row["ts_min"] is None:
        return None
    return _integrate_range(row["ts_min"], time.time())


def deye_cumulative_metrics(last: dict | None) -> list[dict]:
    """
    Cumulative Load Energy and Grid metrics for dashboard table.
    Returns [{"period", "register", "description", "value_inv", "value_integrated"}, ...]
    value_inv = from inverter register; value_integrated = our load_power_w or grid_power_w integration.
    """
    rows = [
        ("День", "526", "Load за сьогодні (скидається о 00:00)", "day_load_kwh", deye_day_load_kwh_integrated),
        ("Місяць", "66", "Load за поточний місяць (×0.001 для 3PH)", "month_load_kwh", deye_monthly_load_kwh),
        ("Всього", "527–528", "Load за весь час (×0.000001 для 3PH)", "total_load_kwh", deye_total_load_kwh_integrated),
        # Grid: тільки лічильник інвертора (інтеграція grid_power_w часто 0 в гібридному режимі)
        ("День імпорт", "520", "Grid імпорт за день (×0.1)", "day_grid_import_kwh", None),
        ("День експорт", "521", "Grid експорт за день (×0.1)", "day_grid_export_kwh", None),
        ("Всього імпорт", "522–523", "Grid імпорт за весь час (×0.000001)", "total_grid_import_kwh", None),
        ("Всього експорт", "524–525", "Grid експорт за весь час (×0.000001)", "total_grid_export_kwh", None),
    ]
    result = []
    for period, reg, desc, key_inv, fn_integrated in rows:
        val_inv = last.get(key_inv) if last else None
        val_int = fn_integrated() if fn_integrated else None
        result.append({
            "period": period,
            "register": reg,
            "description": desc,
            "value_inv": round(val_inv, 2) if val_inv is not None else None,
            "value_integrated": round(val_int, 2) if val_int is not None else None,
        })
    return result


def deye_daily_load_kwh() -> list[dict]:
    """Compute load energy (kWh) per day for current month. Returns [{"date": "YYYY-MM-DD", "kwh": float, "samples": int}, ...]."""
    now = datetime.now(UA_TZ)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    ts_start = month_start.timestamp()
    ts_end = time.time()

    with _conn() as db:
        rows = db.execute(
            """SELECT load_power_w, ts FROM deye_log
               WHERE ts >= ? AND ts <= ? AND load_power_w IS NOT NULL
               ORDER BY ts""",
            (ts_start, ts_end),
        ).fetchall()

    if len(rows) < 2:
        return []

    # Group rows by date (Kyiv timezone)
    by_date: dict[str, list] = {}
    for r in rows:
        dt = datetime.fromtimestamp(r["ts"], tz=UA_TZ)
        key = dt.strftime("%Y-%m-%d")
        if key not in by_date:
            by_date[key] = []
        by_date[key].append(dict(r))

    result = []
    for date_str in sorted(by_date.keys()):
        day_rows = by_date[date_str]
        if len(day_rows) < 2:
            continue
        kwh = round(_integrate_kwh(day_rows), 1)

        # Group by hour for expandable breakdown
        by_hour: dict[int, list] = {}
        for r in day_rows:
            dt = datetime.fromtimestamp(r["ts"], tz=UA_TZ)
            h = dt.hour
            if h not in by_hour:
                by_hour[h] = []
            by_hour[h].append(dict(r))

        hours_data = []
        for hour in range(24):
            hr_rows = by_hour.get(hour, [])
            if len(hr_rows) < 2:
                hours_data.append({"hour": hour, "kwh": 0.0})
            else:
                hours_data.append({"hour": hour, "kwh": round(_integrate_kwh(hr_rows), 2)})

        result.append({"date": date_str, "kwh": kwh, "samples": len(day_rows), "hours": hours_data})
    return result


def _integrate_battery_power(rows: list, positive_only: bool) -> float:
    """Integrate battery_power_w. Deye: negative=charge, positive=discharge. positive_only=True → charge kWh, False → discharge kWh."""
    total = 0.0
    for i in range(1, len(rows)):
        p_prev = rows[i - 1].get("battery_power_w") or 0
        p_curr = rows[i].get("battery_power_w") or 0
        dt_h = (rows[i]["ts"] - rows[i - 1]["ts"]) / 3600
        if positive_only:
            avg = min(0, (p_prev + p_curr) / 2)  # charge = negative (battery consuming)
        else:
            avg = max(0, (p_prev + p_curr) / 2)  # discharge = positive (battery feeding)
        total += abs(avg) * dt_h / 1000  # W -> kWh
    return total


def deye_battery_episodes_for_month() -> tuple[list[dict], dict]:
    """
    Compute discharge (during outage) and charge (after power returns) episodes.
    Each down-up pair = one episode with full detail.
    Returns (daily_list, monthly_summary).
    daily_list: [{"date": str, "discharges": [{"soc_from", "soc_to", "kwh"}], "charges": [...], "cycles": int}]
    monthly_summary: {"cycles": int, "charge_kwh": float, "discharge_kwh": float}
    """
    now = datetime.now(UA_TZ)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    ts_start = month_start.timestamp()
    ts_end = time.time()

    events = events_in_range(ts_start, ts_end)
    if not events:
        return [], {"cycles": 0, "charge_kwh": 0.0, "discharge_kwh": 0.0}

    with _conn() as db:
        deye_rows = db.execute(
            """SELECT battery_soc, battery_power_w, ts FROM deye_log
               WHERE ts >= ? AND ts <= ? ORDER BY ts""",
            (ts_start, ts_end + 3600),
        ).fetchall()
    deye_rows = [dict(r) for r in deye_rows]

    by_date: dict[str, list] = {"discharges": [], "charges": []}

    i = 0
    while i < len(events):
        if events[i]["event"] != "down":
            i += 1
            continue
        down_ts = events[i]["ts"]
        up_ts = None
        j = i + 1
        while j < len(events):
            if events[j]["event"] == "up":
                up_ts = events[j]["ts"]
                j += 1
                break
            if events[j]["event"] == "down":
                break
            j += 1
        i = j

        if up_ts is None:
            continue

        # Discharge: every episode (including tiny ones)
        ep_rows = [r for r in deye_rows if down_ts <= r["ts"] <= up_ts]
        if len(ep_rows) >= 2:
            soc_from = ep_rows[0].get("battery_soc")
            soc_to = ep_rows[-1].get("battery_soc")
            kwh = round(_integrate_battery_power(ep_rows, positive_only=False), 2)
            date_str = datetime.fromtimestamp(down_ts, tz=UA_TZ).strftime("%Y-%m-%d")
            by_date["discharges"].append({
                "date": date_str, "soc_from": soc_from, "soc_to": soc_to, "kwh": kwh,
                "ts_start": down_ts, "ts_end": up_ts,
            })

        # Charge: from up until next down (or end of data). No fixed window.
        charge_end = events[i]["ts"] if i < len(events) and events[i]["event"] == "down" else ts_end
        ch_rows = [r for r in deye_rows if up_ts <= r["ts"] < charge_end]
        if len(ch_rows) >= 2:
            kwh = round(_integrate_battery_power(ch_rows, positive_only=True), 2)
            if kwh > 0:
                charge_only_rows = [r for r in ch_rows if (r.get("battery_power_w") or 0) <= 0]
                if len(charge_only_rows) >= 2:
                    soc_from = charge_only_rows[0].get("battery_soc")
                    soc_to = charge_only_rows[-1].get("battery_soc")
                    charge_duration_h = round(
                        sum(charge_only_rows[k]["ts"] - charge_only_rows[k - 1]["ts"]
                            for k in range(1, len(charge_only_rows))) / 3600, 1)
                else:
                    soc_from = ch_rows[0].get("battery_soc")
                    soc_to = ch_rows[-1].get("battery_soc")
                    charge_duration_h = round((ch_rows[-1]["ts"] - ch_rows[0]["ts"]) / 3600, 1)
                date_str = datetime.fromtimestamp(up_ts, tz=UA_TZ).strftime("%Y-%m-%d")
                by_date["charges"].append({
                    "date": date_str, "soc_from": soc_from, "soc_to": soc_to, "kwh": kwh,
                    "ts_start": up_ts, "ts_end": ch_rows[-1]["ts"],
                    "charge_duration_h": charge_duration_h,
                })

    # Group by date
    all_dates = set(
        [d["date"] for d in by_date["discharges"]] + [d["date"] for d in by_date["charges"]]
    )
    daily = []
    for date_str in sorted(all_dates):
        discharges = [d for d in by_date["discharges"] if d["date"] == date_str]
        charges = [d for d in by_date["charges"] if d["date"] == date_str]
        cycles = max(len(discharges), len(charges))
        daily.append({
            "date": date_str,
            "discharges": discharges,
            "charges": charges,
            "cycles": cycles,
        })

    monthly = {
        "cycles": sum(d["cycles"] for d in daily),
        "charge_kwh": round(sum(c["kwh"] for c in by_date["charges"]), 1),
        "discharge_kwh": round(sum(d["kwh"] for d in by_date["discharges"]), 1),
    }
    return daily, monthly


def last_nonzero_grid_voltage(limit: int = 60) -> dict | None:
    """Get most recent deye_log entry where at least one phase has non-zero voltage."""
    rows = recent_deye_log(limit)
    for r in rows:
        v1 = r.get("grid_v_l1")
        v2 = r.get("grid_v_l2")
        v3 = r.get("grid_v_l3")
        if (v1 and v1 > 0) or (v2 and v2 > 0) or (v3 and v3 > 0):
            return {"grid_v_l1": v1, "grid_v_l2": v2, "grid_v_l3": v3}
    return None


def has_grid_voltage_now(max_age_sec: float = 300) -> bool:
    """True if most recent deye_log (within max_age_sec) has at least one phase with voltage > 0."""
    rows = recent_deye_log(1)
    if not rows:
        return False
    r = rows[0]
    if time.time() - r["ts"] > max_age_sec:
        return False
    v1, v2, v3 = r.get("grid_v_l1"), r.get("grid_v_l2"), r.get("grid_v_l3")
    return (v1 and v1 > 0) or (v2 and v2 > 0) or (v3 and v3 > 0)


def _last_nonzero_for_phase(key: str, limit: int) -> list[tuple[float, float]]:
    """Останні limit ненульових показників для фази key. Повертає [(value, ts), ...] від нових до старих."""
    with _conn() as db:
        rows = db.execute(
            f"""SELECT {key}, ts FROM deye_log WHERE {key} > 0 ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [(r[key], r["ts"]) for r in rows if r[key] is not None and r[key] > 0]


def deye_voltage_trend(n: int = 10, threshold_v: float = 5.0) -> str | None:
    """
    Висока/низька тільки при змішаному стані: є присутні й відсутні фази.
    Тренд дивимось виключно по ВІДСУТНІХ фазах — останні n ненульових показників до зникнення.
    high = тренд по відсутнім РОСТЕ (висока напруга → Зубр вирубив)
    low = тренд по відсутнім ПАДАЄ (низька напруга)
    Якщо тренд невизначений: fallback по рівню присутніх фаз (≥250 → high, ≤190 → low).
    """
    latest_row = recent_deye_log(1)
    if not latest_row:
        return None
    latest = latest_row[0]
    phase_keys = [("grid_v_l1", latest.get("grid_v_l1")), ("grid_v_l2", latest.get("grid_v_l2")), ("grid_v_l3", latest.get("grid_v_l3"))]
    absent_keys = [k for k, v in phase_keys if v is None or v == 0]
    present_keys = [k for k, v in phase_keys if v is not None and v > 0]
    if not absent_keys or not present_keys:
        return None

    present_avg = sum(latest.get(k) for k in present_keys) / len(present_keys)

    all_val_ts: list[tuple[float, float]] = []
    for key in absent_keys:
        all_val_ts.extend(_last_nonzero_for_phase(key, limit=n))
    all_val_ts.sort(key=lambda x: x[1], reverse=True)
    values_from_absent_phases = [v for v, _ in all_val_ts[:n]]
    if len(values_from_absent_phases) < 4:
        if present_avg >= 250:
            return "high"
        if present_avg <= 190:
            return "low"
        return None
    values = values_from_absent_phases[:n]
    half = len(values) // 2
    newer_avg = sum(values[:half]) / half
    older_avg = sum(values[half:]) / (len(values) - half)
    diff = newer_avg - older_avg
    if diff >= threshold_v:
        return "high"
    if diff <= -threshold_v:
        return "low"
    if present_avg >= 250:
        return "high"
    if present_avg <= 190:
        return "low"
    return None


def first_heartbeat_ts() -> float:
    with _conn() as db:
        row = db.execute("SELECT ts FROM heartbeats ORDER BY id ASC LIMIT 1").fetchone()
        return row["ts"] if row else 0.0


def cleanup_old():
    cutoff = time.time() - CLEANUP_KEEP_DAYS * 86400
    with _conn() as db:
        deleted = db.execute("DELETE FROM heartbeats WHERE ts < ?", (cutoff,)).rowcount
    if deleted:
        log.info("Cleaned up %d old heartbeats", deleted)


def save_tg_log(chat_id: str, text: str, status: int):
    with _conn() as db:
        db.execute(
            "INSERT INTO tg_log(chat_id, text, status, ts) VALUES(?,?,?,?)",
            (chat_id, text, status, time.time()),
        )


def recent_tg_log(n: int = 20) -> list[dict]:
    with _conn() as db:
        rows = db.execute(
            "SELECT chat_id, text, status, ts FROM tg_log ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
    return [dict(r) for r in rows]


def save_boiler_schedule(target_date: str, intervals: list, source_text: str):
    intervals_json = json.dumps(intervals, ensure_ascii=False)
    with _conn() as db:
        row = db.execute(
            "SELECT intervals FROM boiler_schedule WHERE target_date=? ORDER BY id DESC LIMIT 1",
            (target_date,),
        ).fetchone()
        if row and row["intervals"] == intervals_json:
            return
        db.execute(
            "INSERT INTO boiler_schedule(target_date, intervals, source_text, parsed_at) VALUES(?,?,?,?)",
            (target_date, intervals_json, source_text, time.time()),
        )
        log.info("Boiler schedule saved for %s: %s", target_date, intervals_json)


def boiler_schedule_for_dates(dates: list[str]) -> dict[str, list]:
    """Return {date: [[start,end], ...]} for the given dates."""
    result: dict[str, list] = {}
    with _conn() as db:
        for d in dates:
            row = db.execute(
                "SELECT intervals FROM boiler_schedule WHERE target_date=? ORDER BY id DESC LIMIT 1",
                (d,),
            ).fetchone()
            if row:
                result[d] = json.loads(row["intervals"])
    return result


def _save_schedule_if_changed(target_date: str, grid: list[str]):
    """Save grid to schedule_history only if it differs from the latest entry for that date."""
    grid_json = json.dumps(grid)
    with _conn() as db:
        row = db.execute(
            "SELECT grid_json FROM schedule_history WHERE target_date=? ORDER BY id DESC LIMIT 1",
            (target_date,),
        ).fetchone()
        if row and row["grid_json"] == grid_json:
            return
        db.execute(
            "INSERT INTO schedule_history(target_date, grid_json, fetched_at) VALUES(?,?,?)",
            (target_date, grid_json, time.time()),
        )
        log.info("Schedule changed for %s — saved to history", target_date)


def save_weather_log(temp, humidity, wind, code, t_min, t_max, ts: float):
    """Log weather snapshot for history."""
    with _conn() as db:
        db.execute(
            "INSERT INTO weather_log(temp, humidity, wind, code, t_min, t_max, ts) VALUES(?,?,?,?,?,?,?)",
            (temp, humidity, wind, code, t_min, t_max, ts),
        )


def schedule_history_for_date(target_date: str) -> list[dict]:
    with _conn() as db:
        rows = db.execute(
            "SELECT grid_json, fetched_at FROM schedule_history WHERE target_date=? ORDER BY id ASC",
            (target_date,),
        ).fetchall()
    return [{"grid": json.loads(r["grid_json"]), "ts": r["fetched_at"]} for r in rows]


def parse_boiler_schedule(text: str) -> list[dict]:
    """Parse Oselya Service boiler/generator schedule from message text.

    Returns [{"date": "2026-03-02", "intervals": [["16:00","20:00"], ...]}]
    """
    lower = text.lower()
    if "котельн" not in lower and "генератор" not in lower:
        log.info("Boiler parse: keywords 'котельн/генератор' not found in: %r", text[:200])
        return []
    year = datetime.now(UA_TZ).year
    results = []
    for m in _BOILER_LINE_RE.finditer(lower):
        day = int(m.group(1))
        month_name = m.group(2)
        month = _UA_MONTHS.get(month_name)
        if not month:
            log.info("Boiler parse: unknown month %r", month_name)
            continue
        ranges_str = m.group(3)
        intervals = _TIME_RANGE_RE.findall(ranges_str)
        if not intervals:
            log.info("Boiler parse: no time ranges in %r", ranges_str)
            continue
        date_str = f"{year}-{month:02d}-{day:02d}"
        results.append({"date": date_str, "intervals": [list(iv) for iv in intervals]})
    log.info("Boiler parse result: %d day(s) from text len=%d", len(results), len(text))
    return results
