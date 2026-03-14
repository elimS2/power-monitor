"""
Power Monitor — database operations (SQLite).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import statistics
import sqlite3
import time
from datetime import datetime

from config import CLEANUP_KEEP_DAYS, DB_PATH, UA_TZ

log = logging.getLogger("power_monitor")

# Events that mean "plugs dead" (outage or voltage anomaly)
DOWN_LIKE_EVENTS = ("down", "voltage_high", "voltage_low", "voltage_issue")

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
        # API key permissions (label = API_KEYS value, e.g. admin, vasyl)
        db.execute("""
            CREATE TABLE IF NOT EXISTS api_key_config (
                label     TEXT PRIMARY KEY,
                enabled   INTEGER NOT NULL DEFAULT 1,
                sections  TEXT,
                endpoints TEXT,
                role_id   INTEGER,
                updated_at REAL
            )
        """)
        try:
            db.execute("ALTER TABLE api_key_config ADD COLUMN role_id INTEGER")
        except sqlite3.OperationalError:
            pass
        # API keys stored in DB. Multiple keys per label (history); deactivated_at=NULL = active.
        db.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                label         TEXT NOT NULL,
                key_hash      TEXT NOT NULL UNIQUE,
                key           TEXT NOT NULL,
                key_prefix    TEXT,
                created_at    REAL NOT NULL,
                deactivated_at REAL
            )
        """)
        # Migration: old schema had label as PK. Migrate to new schema.
        cols = [r[1] for r in db.execute("PRAGMA table_info(api_keys)").fetchall()]
        if "deactivated_at" not in cols:
            db.execute("ALTER TABLE api_keys ADD COLUMN deactivated_at REAL")
        if "id" not in cols:
            db.execute("""
                CREATE TABLE api_keys_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label TEXT NOT NULL,
                    key_hash TEXT NOT NULL UNIQUE,
                    key TEXT NOT NULL,
                    key_prefix TEXT,
                    created_at REAL NOT NULL,
                    deactivated_at REAL
                )
            """)
            db.execute("""
                INSERT INTO api_keys_new(label, key_hash, key, key_prefix, created_at, deactivated_at)
                SELECT label, key_hash, key, key_prefix, created_at, NULL FROM api_keys
            """)
            db.execute("DROP TABLE api_keys")
            db.execute("ALTER TABLE api_keys_new RENAME TO api_keys")
        # Roles (user-createable, sections per role). Built-in roles are seeded.
        db.execute("""
            CREATE TABLE IF NOT EXISTS roles (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL UNIQUE,
                sections   TEXT,
                is_builtin INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL
            )
        """)
        # Seed built-in roles if empty
        if db.execute("SELECT COUNT(*) FROM roles").fetchone()[0] == 0:
            for name, sections in [
                ("Усі", None),
                ("Без Deye", json.dumps([s for s in ALL_SECTIONS if s != "deye_details"])),
                ("Базове", json.dumps(["sched_details", "boiler_details", "ev_details", "links_details", "alert_ev_details"])),
            ]:
                db.execute(
                    "INSERT INTO roles(name, sections, is_builtin, created_at) VALUES(?,?,1,?)",
                    (name, sections, time.time()),
                )
        # Migration: add voltage_details to "Без Deye" role if missing
        for row in db.execute("SELECT id, sections FROM roles WHERE name='Без Deye' AND is_builtin=1").fetchall():
            sec = json.loads(row["sections"]) if row["sections"] else []
            if "voltage_details" not in sec:
                updated = [s for s in ALL_SECTIONS if s != "deye_details"]
                db.execute("UPDATE roles SET sections=? WHERE id=?", (json.dumps(updated), row["id"]))


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


# ─── API key config ─────────────────────────────────────────────

# Permission groups for endpoints: dashboard, dashboard_full, heartbeat, deye, plug, debug, admin
# Sections: sched_details, boiler_details, ev_details, links_details, plug_details, alert_ev_details, tg_details, deye_details, hb_details, legend_details, avatars_details
ALL_SECTIONS = [
    "sched_details", "boiler_details", "ev_details", "links_details",
    "plug_details", "alert_ev_details", "tg_details", "voltage_details",
    "deye_details", "hb_details", "legend_details", "avatars_details",
]

SECTION_LABELS = {
    "sched_details": "Графік відключень",
    "boiler_details": "Графік котельні",
    "ev_details": "Події",
    "links_details": "Посилання",
    "plug_details": "Розумна розетка",
    "alert_ev_details": "Тривоги",
    "tg_details": "Історія Telegram",
    "voltage_details": "Напруга мережі",
    "deye_details": "Deye інвертор",
    "hb_details": "Роутер / Heartbeats",
    "legend_details": "Легенда повідомлень",
    "avatars_details": "Аватарки каналу",
}


# ─── Roles ─────────────────────────────────────────────────────

def role_list() -> list[dict]:
    """List all roles (built-in + custom)."""
    with _conn() as db:
        rows = db.execute(
            "SELECT id, name, sections, is_builtin, created_at FROM roles ORDER BY is_builtin DESC, name"
        ).fetchall()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "sections": json.loads(r["sections"]) if r["sections"] else None,
            "is_builtin": bool(r["is_builtin"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def role_get(role_id: int) -> dict | None:
    """Get role by id."""
    with _conn() as db:
        row = db.execute(
            "SELECT id, name, sections, is_builtin, created_at FROM roles WHERE id=?",
            (role_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "sections": json.loads(row["sections"]) if row["sections"] else None,
        "is_builtin": bool(row["is_builtin"]),
        "created_at": row["created_at"],
    }


def role_create(name: str, sections: list[str] | None) -> dict:
    """Create a new role. Returns the created role."""
    with _conn() as db:
        db.execute(
            "INSERT INTO roles(name, sections, is_builtin, created_at) VALUES(?,?,0,?)",
            (name, json.dumps(sections) if sections else None, time.time()),
        )
        rid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    return role_get(rid)


def role_update(role_id: int, name: str | None, sections: list[str] | None) -> bool:
    """Update role. Returns True if found and updated."""
    r = role_get(role_id)
    if not r or r["is_builtin"]:
        return False
    with _conn() as db:
        if name is not None and sections is not None:
            db.execute(
                "UPDATE roles SET name=?, sections=?, created_at=? WHERE id=?",
                (name, json.dumps(sections) if sections else None, time.time(), role_id),
            )
        elif name is not None:
            db.execute("UPDATE roles SET name=?, created_at=? WHERE id=?", (name, time.time(), role_id))
        elif sections is not None:
            db.execute(
                "UPDATE roles SET sections=?, created_at=? WHERE id=?",
                (json.dumps(sections) if sections else None, time.time(), role_id),
            )
        else:
            return False
    return True


def role_delete(role_id: int) -> bool:
    """Delete role. Only custom roles. Returns True if deleted."""
    r = role_get(role_id)
    if not r or r["is_builtin"]:
        return False
    with _conn() as db:
        db.execute("DELETE FROM roles WHERE id=?", (role_id,))
        db.execute("UPDATE api_key_config SET role_id=NULL WHERE role_id=?", (role_id,))
    return True


def role_sections_for_key(role_id: int) -> list[str] | None:
    """Get sections list for a role. None = all sections."""
    r = role_get(role_id)
    if not r:
        return None
    return r["sections"]


# ─── API key config ─────────────────────────────────────────────

def api_key_config_get(label: str) -> dict | None:
    """Get config for key label. Returns None if no row (full access by default)."""
    with _conn() as db:
        row = db.execute(
            "SELECT label, enabled, sections, endpoints, role_id, updated_at FROM api_key_config WHERE label=?",
            (label,),
        ).fetchone()
    if not row:
        return None
    sections = json.loads(row["sections"]) if row["sections"] else None
    role_id = row["role_id"]
    if role_id is not None:
        sections = role_sections_for_key(role_id)
    return {
        "label": row["label"],
        "enabled": bool(row["enabled"]),
        "sections": sections,
        "role_id": role_id,
        "endpoints": json.loads(row["endpoints"]) if row["endpoints"] else None,
        "updated_at": row["updated_at"],
    }


def api_key_config_set_enabled(label: str, enabled: bool):
    with _conn() as db:
        db.execute(
            """INSERT INTO api_key_config(label, enabled, updated_at)
               VALUES(?, ?, ?) ON CONFLICT(label) DO UPDATE SET
               enabled=excluded.enabled, updated_at=excluded.updated_at""",
            (label, 1 if enabled else 0, time.time()),
        )


def api_key_config_set_permissions(
    label: str, sections: list | None = None, endpoints: list | None = None, role_id: int | None = None
):
    """Set permissions. If role_id is set, sections are taken from the role (sections arg ignored for storage)."""
    with _conn() as db:
        sec_json = None if role_id is not None else (json.dumps(sections) if sections else None)
        ep_json = json.dumps(endpoints) if endpoints else None
        ts = time.time()
        db.execute(
            """INSERT INTO api_key_config(label, enabled, sections, endpoints, role_id, updated_at)
               VALUES(?, 1, ?, ?, ?, ?) ON CONFLICT(label) DO UPDATE SET
               sections=excluded.sections, endpoints=excluded.endpoints, role_id=excluded.role_id, updated_at=excluded.updated_at""",
            (label, sec_json, ep_json, role_id, ts),
        )


def _key_hash(plain_key: str) -> str:
    return hashlib.sha256(plain_key.encode()).hexdigest()


def api_key_lookup(plain_key: str) -> str | None:
    """Look up key in DB. Returns label if valid and active, else None."""
    h = _key_hash(plain_key)
    with _conn() as db:
        row = db.execute(
            "SELECT label FROM api_keys WHERE key_hash=? AND (deactivated_at IS NULL OR deactivated_at = 0)",
            (h,),
        ).fetchone()
    return row["label"] if row else None


def api_key_create(label: str, plain_key: str) -> dict:
    """Store new key in DB. Creates api_key_config. Returns {label, key_preview}."""
    key_hash = _key_hash(plain_key)
    key_prefix = plain_key[:8] + "…" if len(plain_key) > 8 else plain_key
    ts = time.time()
    with _conn() as db:
        db.execute(
            "INSERT INTO api_keys(label, key_hash, key, key_prefix, created_at, deactivated_at) VALUES(?,?,?,?,?,?)",
            (label, key_hash, plain_key, key_prefix, ts, None),
        )
    api_key_config_set_enabled(label, True)
    return {"label": label, "key_preview": key_prefix, "created_at": ts}


def api_key_regenerate(label: str) -> dict | None:
    """Deactivate current key, create new one. Returns {label, key, key_preview, created_at} or None."""
    import secrets

    ts = time.time()
    new_key = secrets.token_urlsafe(24)
    key_hash = _key_hash(new_key)
    key_prefix = new_key[:8] + "…" if len(new_key) > 8 else new_key
    with _conn() as db:
        db.execute(
            "UPDATE api_keys SET deactivated_at=? WHERE label=? AND (deactivated_at IS NULL OR deactivated_at = 0)",
            (ts, label),
        )
        db.execute(
            "INSERT INTO api_keys(label, key_hash, key, key_prefix, created_at, deactivated_at) VALUES(?,?,?,?,?,?)",
            (label, key_hash, new_key, key_prefix, ts, None),
        )
    return {"label": label, "key": new_key, "key_preview": key_prefix, "created_at": ts}


def api_key_get_plain(label: str) -> str | None:
    """Get plain key for active DB key (for open-dashboard redirect)."""
    with _conn() as db:
        row = db.execute(
            "SELECT key FROM api_keys WHERE label=? AND (deactivated_at IS NULL OR deactivated_at = 0) AND key IS NOT NULL AND key != ''",
            (label,),
        ).fetchone()
    return row["key"] if row else None


def api_key_list() -> list[dict]:
    """List active keys stored in DB (one per label)."""
    with _conn() as db:
        rows = db.execute(
            """SELECT label, key_prefix, created_at FROM api_keys
               WHERE deactivated_at IS NULL OR deactivated_at = 0
               ORDER BY label"""
        ).fetchall()
    return [
        {"label": r["label"], "key_preview": r["key_prefix"], "source": "db", "created_at": r["created_at"]}
        for r in rows
    ]


def api_key_history(label: str) -> list[dict]:
    """List all keys for label (active + deactivated) with created_at, deactivated_at."""
    with _conn() as db:
        rows = db.execute(
            """SELECT key_prefix, created_at, deactivated_at FROM api_keys
               WHERE label=? ORDER BY created_at DESC""",
            (label,),
        ).fetchall()
    return [
        {
            "key_preview": r["key_prefix"],
            "created_at": r["created_at"],
            "deactivated_at": r["deactivated_at"],
        }
        for r in rows
    ]


def api_key_delete(label: str) -> bool:
    """Delete all keys for label from DB (active + history). Also removes api_key_config."""
    with _conn() as db:
        cur = db.execute("DELETE FROM api_keys WHERE label=?", (label,))
        if cur.rowcount > 0:
            db.execute("DELETE FROM api_key_config WHERE label=?", (label,))
            return True
        return False


def api_key_config_list() -> list[dict]:
    """List all configured keys (only those with a row in api_key_config)."""
    with _conn() as db:
        rows = db.execute(
            "SELECT label, enabled, sections, endpoints, role_id, updated_at FROM api_key_config ORDER BY label"
        ).fetchall()
    result = []
    for r in rows:
        sections = json.loads(r["sections"]) if r["sections"] else None
        role_id = r["role_id"]
        if role_id is not None:
            sections = role_sections_for_key(role_id)
        result.append({
            "label": r["label"],
            "enabled": bool(r["enabled"]),
            "sections": sections,
            "role_id": role_id,
            "endpoints": json.loads(r["endpoints"]) if r["endpoints"] else None,
            "updated_at": r["updated_at"],
        })
    return result


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
    return round(sum(d["integrated_kwh"] for d in daily), 1)


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
        ("Місяць", "66", "Load за поточний місяць (×0.1 за Sunsynk)", "month_load_kwh", deye_monthly_load_kwh),
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
    """Compute load energy (kWh) per day for current month.
    Returns [{"date", "load_kwh", "grid_kwh", "integrated_kwh", "samples", "hours"}, ...].
    load_kwh, grid_kwh = last reading in interval (cumulative counters). integrated = trapezoidal load_power_w.
    Deye resets at ~00:00 Kyiv; may take a few min. We exclude first 10 min after midnight to avoid
    stale pre-reset values (e.g. 38.1 from previous day). Integration uses full Kyiv-day."""
    now = datetime.now(UA_TZ)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    ts_start = month_start.timestamp()
    ts_end = time.time()

    with _conn() as db:
        rows = db.execute(
            """SELECT load_power_w, ts, day_load_kwh, day_grid_import_kwh FROM deye_log
               WHERE ts >= ? AND ts <= ? AND load_power_w IS NOT NULL
               ORDER BY ts""",
            (ts_start, ts_end),
        ).fetchall()

    if len(rows) < 2:
        return []

    # Group rows by date (Kyiv timezone) — full day window 00:00–24:00 Kyiv
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
        integrated_kwh = round(_integrate_kwh(day_rows), 1)

        # Load/Grid from inverter: reset at ~00:00 Kyiv, exclude first 10 min to skip stale values
        y, m, d = (int(x) for x in date_str.split("-"))
        kyiv_midnight = datetime(y, m, d, 0, 0, 0, tzinfo=UA_TZ).timestamp()
        RESET_GRACE_SEC = 600  # 10 min
        inv_rows = [r for r in day_rows if r["ts"] >= kyiv_midnight + RESET_GRACE_SEC]
        last_row = max(inv_rows, key=lambda r: r["ts"]) if inv_rows else None
        load_kwh = last_row.get("day_load_kwh") if last_row else None
        if load_kwh is not None:
            load_kwh = round(load_kwh, 1)
        grid_kwh = last_row.get("day_grid_import_kwh") if last_row else None
        if grid_kwh is not None:
            grid_kwh = round(grid_kwh, 1)

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

        result.append({
            "date": date_str,
            "load_kwh": load_kwh,
            "grid_kwh": grid_kwh,
            "integrated_kwh": integrated_kwh,
            "samples": len(day_rows),
            "hours": hours_data,
        })
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
        if events[i]["event"] not in DOWN_LIKE_EVENTS:
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
            if events[j]["event"] in DOWN_LIKE_EVENTS:
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
        charge_end = events[i]["ts"] if i < len(events) and events[i]["event"] in DOWN_LIKE_EVENTS else ts_end
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


def has_all_three_phases_voltage(max_age_sec: float = 300) -> bool:
    """True if most recent deye_log has all three phases with voltage > 0."""
    rows = recent_deye_log(1)
    if not rows:
        return False
    r = rows[0]
    if time.time() - r["ts"] > max_age_sec:
        return False
    v1, v2, v3 = r.get("grid_v_l1"), r.get("grid_v_l2"), r.get("grid_v_l3")
    return (v1 and v1 > 0) and (v2 and v2 > 0) and (v3 and v3 > 0)


def _last_nonzero_for_phase(key: str, limit: int) -> list[tuple[float, float]]:
    """Останні limit ненульових показників для фази key. Повертає [(value, ts), ...] від нових до старих."""
    with _conn() as db:
        rows = db.execute(
            f"""SELECT {key}, ts FROM deye_log WHERE {key} > 0 ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [(r[key], r["ts"]) for r in rows if r[key] is not None and r[key] > 0]


def deye_voltage_trend(
    n: int = 1000,
    threshold_v: float = 5.0,
    high_v_threshold: float = 240.0,
    is_scheduled: bool | None = None,
    all_absent_n: int = 23,
    all_absent_drop: int = 3,
) -> str | None:
    """
    Висока/низька при змішаному або повністю відсутньому стані.
    high: 1) змішаний стан і хоча б одна присутня > 240; 2) змішаний стан і 2 відсутні фази — обидві мали
      (23, -3, середнє 20) > 240; 3) всі відсутні, не за графіком, хоча б 2 з 3 фаз так само > 240.
    low: тренд по відсутніх падає або present_avg ≤ 190.
    """
    latest_row = recent_deye_log(1)
    if not latest_row:
        return None
    latest = latest_row[0]
    phase_keys = [("grid_v_l1", latest.get("grid_v_l1")), ("grid_v_l2", latest.get("grid_v_l2")), ("grid_v_l3", latest.get("grid_v_l3"))]
    absent_keys = [k for k, v in phase_keys if v is None or v == 0]
    present_keys = [k for k, v in phase_keys if v is not None and v > 0]

    if not absent_keys:
        return None

    if not present_keys:
        # Усі фази зникли — перевіряємо чи була висока напруга перед зникненням
        # high якщо: всі 3 фази мають avg>240; або хоча б 2 з 3 фаз (будь-яка комбінація)
        if is_scheduled is not False:
            return None
        need = all_absent_n
        use_count = need - all_absent_drop
        all_phase_keys = ["grid_v_l1", "grid_v_l2", "grid_v_l3"]
        high_count = 0
        for key in all_phase_keys:
            vals_ts = _last_nonzero_for_phase(key, limit=need)
            if len(vals_ts) < need:
                continue
            values = [v for v, _ in vals_ts[:need]]
            kept = values[all_absent_drop:need]
            avg = sum(kept) / use_count
            if avg > high_v_threshold:
                high_count += 1
        if high_count >= 2:
            return "high"
        return None

    present_values = [latest.get(k) for k in present_keys]
    present_max = max(present_values)
    if present_max > high_v_threshold:
        return "high"

    # Змішаний стан: 2 фази відсутні — якщо обидві мали avg>240 перед зникненням → high (незалежно від присутньої)
    if len(absent_keys) == 2:
        need = all_absent_n
        use_count = need - all_absent_drop
        both_high = True
        for key in absent_keys:
            vals_ts = _last_nonzero_for_phase(key, limit=need)
            if len(vals_ts) < need:
                both_high = False
                break
            values = [v for v, _ in vals_ts[:need]]
            kept = values[all_absent_drop:need]
            avg = sum(kept) / use_count
            if avg <= high_v_threshold:
                both_high = False
                break
        if both_high:
            return "high"

    present_avg = sum(present_values) / len(present_values)

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
    newer_med = statistics.median(values[:half])
    older_med = statistics.median(values[half:])
    diff = newer_med - older_med
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
