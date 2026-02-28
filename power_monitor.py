"""
Power outage monitor server.

Receives ICMP ping results from MikroTik every ~10s for two smart plugs,
stores in SQLite, detects outages by cross-checking both plugs, and
sends Telegram notifications.

Run:
    uvicorn power_monitor:app --host 0.0.0.0 --port 8080
"""

import asyncio
import logging
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

# ─── Config (override via environment variables) ─────────────

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "YOUR_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "YOUR_CHAT_ID")
API_KEY = os.getenv("API_KEY", "changeme")
DB_PATH = Path(os.getenv("DB_PATH", str(Path(__file__).parent / "power_monitor.db")))

# Both plugs must be dead for this many consecutive heartbeats → outage
OUTAGE_CONFIRM_COUNT = 6  # 6 × 10s = ~60 seconds

# No heartbeat for this long → MikroTik/internet alert
STALE_THRESHOLD_SEC = int(os.getenv("STALE_THRESHOLD_SEC", "300"))

# Keep heartbeat data for this many days
CLEANUP_KEEP_DAYS = 90

# Kyiv timezone offset for display (UTC+2 / UTC+3 summer)
UA_TZ = timezone(timedelta(hours=2))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("power_monitor")


# ─── Database ────────────────────────────────────────────────

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
        """)


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
            "SELECT plug204, plug175, ts FROM heartbeats ORDER BY id DESC LIMIT ?", (n,)
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


def cleanup_old():
    cutoff = time.time() - CLEANUP_KEEP_DAYS * 86400
    with _conn() as db:
        deleted = db.execute("DELETE FROM heartbeats WHERE ts < ?", (cutoff,)).rowcount
    if deleted:
        log.info("Cleaned up %d old heartbeats", deleted)


# ─── Telegram ────────────────────────────────────────────────

async def tg_send(text: str):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json={"chat_id": TG_CHAT_ID, "text": text})
            log.info("TG [%s]: %s", r.status_code, text.replace("\n", " | "))
    except Exception as e:
        log.error("TG send failed: %s", e)


# ─── Detection logic ─────────────────────────────────────────

_lock = asyncio.Lock()


async def analyze():
    async with _lock:
        rows = recent_heartbeats(OUTAGE_CONFIRM_COUNT)

        if len(rows) < OUTAGE_CONFIRM_COUNT:
            return

        all_dead = all(r["plug204"] == 0 and r["plug175"] == 0 for r in rows)
        latest_alive = rows[0]["plug204"] > 0 or rows[0]["plug175"] > 0
        is_down = kv_get("power_down") == "1"

        if all_dead and not is_down:
            kv_set("power_down", "1")
            save_event("down")
            log.warning("POWER OUTAGE detected")
            await tg_send("Світло ЗК 6\nСвітло пропало!")

        elif latest_alive and is_down:
            kv_set("power_down", "0")
            save_event("up")
            log.info("POWER RESTORED")
            await tg_send("Світло ЗК 6\nСвітло з'явилось!")


async def watchdog():
    """Alert if no heartbeats received for too long."""
    rows = recent_heartbeats(1)
    if not rows:
        return

    age = time.time() - rows[0]["ts"]
    alerted = kv_get("stale_alerted") == "1"

    if age > STALE_THRESHOLD_SEC and not alerted:
        kv_set("stale_alerted", "1")
        minutes = int(age // 60)
        log.warning("No heartbeat for %dm", minutes)
        await tg_send(f"Світло ЗК 6\nMikroTik не відповідає вже {minutes} хв")
    elif age <= STALE_THRESHOLD_SEC and alerted:
        kv_set("stale_alerted", "0")


# ─── Background loop ─────────────────────────────────────────

async def bg_loop():
    cleanup_tick = 0
    while True:
        try:
            await watchdog()
            cleanup_tick += 1
            if cleanup_tick >= 2880:  # ~24h at 30s interval
                cleanup_old()
                cleanup_tick = 0
        except Exception as e:
            log.error("bg_loop: %s", e)
        await asyncio.sleep(30)


# ─── FastAPI ─────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    task = asyncio.create_task(bg_loop())
    log.info("Power monitor started, DB=%s", DB_PATH)
    yield
    task.cancel()


app = FastAPI(title="Power Monitor", lifespan=lifespan)


def _check_key(key: str):
    if key != API_KEY:
        raise HTTPException(403, "forbidden")


@app.get("/api/heartbeat")
async def ep_heartbeat(
    plug204: int = Query(0),
    plug175: int = Query(0),
    key: str = Query(""),
):
    _check_key(key)
    save_heartbeat(plug204, plug175)
    kv_set("stale_alerted", "0")
    log.debug("HB plug204=%d plug175=%d", plug204, plug175)
    await analyze()
    return {"ok": True}


@app.get("/api/status")
async def ep_status(key: str = Query("")):
    _check_key(key)
    return {
        "power_down": kv_get("power_down") == "1",
        "heartbeats": recent_heartbeats(20),
        "events": recent_events(30),
    }


def _ts_fmt(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UA_TZ).strftime("%H:%M:%S")


def _ts_fmt_full(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UA_TZ).strftime("%Y-%m-%d %H:%M:%S")


@app.get("/", response_class=HTMLResponse)
async def dashboard(key: str = Query("")):
    _check_key(key)
    is_down = kv_get("power_down") == "1"
    hb = recent_heartbeats(30)
    ev = recent_events(30)

    hb_rows = ""
    for r in hb:
        c204 = "down" if r["plug204"] == 0 else "up"
        c175 = "down" if r["plug175"] == 0 else "up"
        hb_rows += (
            f'<tr><td>{_ts_fmt(r["ts"])}</td>'
            f'<td class="{c204}">{r["plug204"]}/3</td>'
            f'<td class="{c175}">{r["plug175"]}/3</td></tr>\n'
        )

    ev_rows = ""
    for e in ev:
        cls = "down" if e["event"] == "down" else "up"
        label = "Пропало" if e["event"] == "down" else "З'явилось"
        ev_rows += f'<tr><td>{_ts_fmt_full(e["ts"])}</td><td class="{cls}">{label}</td></tr>\n'

    status_cls = "down" if is_down else "up"
    status_text = "Світло ВІДСУТНЄ" if is_down else "Світло є"

    return f"""<!DOCTYPE html>
<html lang="uk"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="10">
<title>Power Monitor</title>
<style>
:root {{ --bg: #0f172a; --card: #1e293b; --border: #334155; --text: #e2e8f0; --muted: #94a3b8; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text);
        max-width: 640px; margin: 0 auto; padding: 1rem; }}
h1 {{ text-align: center; font-size: 1.3rem; color: var(--muted); margin-bottom: 1rem; }}
.status {{ text-align: center; font-size: 1.8rem; font-weight: 700; padding: 1.2rem;
           border-radius: 12px; margin-bottom: 1.5rem; }}
.status.up {{ background: #064e3b; color: #6ee7b7; }}
.status.down {{ background: #7f1d1d; color: #fca5a5; animation: pulse 2s infinite; }}
@keyframes pulse {{ 0%,100% {{ opacity:1 }} 50% {{ opacity:.7 }} }}
h2 {{ color: var(--muted); font-size: 0.9rem; text-transform: uppercase; letter-spacing: 0.05em;
     margin: 1.2rem 0 0.5rem; }}
table {{ width: 100%; border-collapse: collapse; background: var(--card); border-radius: 8px; overflow: hidden; }}
th, td {{ padding: 0.5rem 0.75rem; text-align: left; font-size: 0.9rem; }}
th {{ background: var(--border); color: var(--muted); font-weight: 500; }}
tr:not(:last-child) td {{ border-bottom: 1px solid var(--border); }}
td.up {{ color: #6ee7b7; }}
td.down {{ color: #fca5a5; }}
</style>
</head><body>
<h1>Power Monitor — ЗК 6</h1>
<div class="status {status_cls}">{status_text}</div>

<h2>Heartbeats</h2>
<table>
<tr><th>Час</th><th>Plug 204</th><th>Plug 175</th></tr>
{hb_rows}</table>

<h2>Події</h2>
<table>
<tr><th>Час</th><th>Подія</th></tr>
{ev_rows}</table>
</body></html>"""
