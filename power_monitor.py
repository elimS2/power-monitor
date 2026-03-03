"""
Power outage monitor server.

Receives ICMP ping results from router every ~10s for two smart plugs,
stores in SQLite, detects outages by cross-checking both plugs, and
sends Telegram notifications.

Run:
    uvicorn power_monitor:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import subprocess
import logging
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI, Query, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response

# ─── Config (override via environment variables) ─────────────

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "YOUR_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "YOUR_CHAT_ID")
TG_TEST_CHAT_ID = os.getenv("TG_TEST_CHAT_ID", "")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "")
AVATAR_ON_START = os.getenv("AVATAR_ON_START", "1") == "1"
DELETE_PHOTO_MSG = os.getenv("DELETE_PHOTO_MSG", "0") == "1"
TG_WEBHOOK_SECRET = hashlib.sha256(TG_BOT_TOKEN.encode()).hexdigest()[:32]
def _parse_keys(raw: str) -> dict:
    """Parse 'label:key,label2:key2' or plain 'key1,key2' into {key: label}."""
    result = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            label, key = entry.split(":", 1)
            result[key.strip()] = label.strip()
        else:
            result[entry] = ""
    return result

API_KEYS = _parse_keys(os.getenv("API_KEYS", os.getenv("API_KEY", "changeme")))
DB_PATH = Path(os.getenv("DB_PATH", str(Path(__file__).parent / "power_monitor.db")))

# Both plugs must be dead for this many consecutive heartbeats → outage
OUTAGE_CONFIRM_COUNT = 6  # 6 × 10s = ~60 seconds

# No heartbeat for this long → router/internet alert
STALE_THRESHOLD_SEC = int(os.getenv("STALE_THRESHOLD_SEC", "300"))

# Keep heartbeat data for this many days
CLEANUP_KEEP_DAYS = 90

# Kyiv timezone offset for display (UTC+2 / UTC+3 summer)
UA_TZ = timezone(timedelta(hours=2))

# ─── DTEK schedule config ─────────────────────────────────────
DTEK_API_URL = os.getenv("DTEK_API_URL", "https://dtek-api.svitlo-proxy.workers.dev/")
DTEK_REGION = os.getenv("DTEK_REGION", "kiivska-oblast")
DTEK_QUEUE = os.getenv("DTEK_QUEUE", "5.1")

_schedule_cache: dict = {}
_schedule_fetched_at: float = 0

def _git_version() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).parent,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"

GIT_COMMIT = _git_version()

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


# ─── Telegram ────────────────────────────────────────────────

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


def schedule_history_for_date(target_date: str) -> list[dict]:
    with _conn() as db:
        rows = db.execute(
            "SELECT grid_json, fetched_at FROM schedule_history WHERE target_date=? ORDER BY id ASC",
            (target_date,),
        ).fetchall()
    return [{"grid": json.loads(r["grid_json"]), "ts": r["fetched_at"]} for r in rows]


_UA_MONTHS = {
    "січня": 1, "лютого": 2, "березня": 3, "квітня": 4,
    "травня": 5, "червня": 6, "липня": 7, "серпня": 8,
    "вересня": 9, "жовтня": 10, "листопада": 11, "грудня": 12,
}

_BOILER_RE = re.compile(
    r"[🔵⚫🟡●]\s*(\d{1,2})\s+(\w+):\s*([\d:,\s\-–]+)",
)
_TIME_RANGE_RE = re.compile(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})")


def parse_boiler_schedule(text: str) -> list[dict]:
    """Parse Oselya Service boiler/generator schedule from message text.

    Returns [{"date": "2026-03-02", "intervals": [["16:00","20:00"], ...]}]
    """
    lower = text.lower()
    if "котельн" not in lower and "генератор" not in lower:
        return []
    year = datetime.now(UA_TZ).year
    results = []
    for m in _BOILER_RE.finditer(text):
        day = int(m.group(1))
        month_name = m.group(2).lower().rstrip(":")
        month = _UA_MONTHS.get(month_name)
        if not month:
            continue
        ranges_str = m.group(3)
        intervals = _TIME_RANGE_RE.findall(ranges_str)
        if not intervals:
            continue
        date_str = f"{year}-{month:02d}-{day:02d}"
        results.append({"date": date_str, "intervals": [list(iv) for iv in intervals]})
    return results


async def tg_send(text: str, chat_id: str = "") -> int:
    """Send message, return message_id (0 on failure)."""
    target = chat_id or TG_CHAT_ID
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": target, "text": text}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json=payload)
            save_tg_log(target, text, r.status_code)
            log.info("TG [%s] to %s: %s", r.status_code, target, text.replace("\n", " | "))
            if r.status_code == 200:
                return r.json().get("result", {}).get("message_id", 0)
    except Exception as e:
        save_tg_log(target, text, 0)
        log.error("TG send failed: %s", e)
    return 0



# ─── Channel photo ───────────────────────────────────────────

_ICONS_DIR = Path(__file__).parent
_PHOTO_ON = (_ICONS_DIR / "icon_on.png").read_bytes()
_PHOTO_OFF = (_ICONS_DIR / "icon_off.png").read_bytes()


async def _delete_service_msg(client: httpx.AsyncClient, api: str):
    """Send temp message, delete it and the service message before it."""
    r = await client.post(f"{api}/sendMessage", json={"chat_id": TG_CHAT_ID, "text": "."})
    if r.status_code == 200:
        tid = r.json().get("result", {}).get("message_id", 0)
        if tid:
            await client.post(f"{api}/deleteMessage", json={"chat_id": TG_CHAT_ID, "message_id": tid - 1})
            await client.post(f"{api}/deleteMessage", json={"chat_id": TG_CHAT_ID, "message_id": tid})


async def update_chat_photo(is_down: bool):
    photo = _PHOTO_OFF if is_down else _PHOTO_ON
    api = f"https://api.telegram.org/bot{TG_BOT_TOKEN}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{api}/setChatPhoto",
                data={"chat_id": TG_CHAT_ID},
                files={"photo": ("status.png", photo, "image/png")},
            )
            log.info("setChatPhoto [%s]: %s", r.status_code, r.text[:120])
            if DELETE_PHOTO_MSG and r.status_code == 200:
                await asyncio.sleep(2)
                await _delete_service_msg(client, api)
    except Exception as e:
        log.error("setChatPhoto failed: %s", e)


# ─── Telegram bot (webhook for /status command) ──────────────

async def setup_tg_bot():
    """Register webhook and set bot menu commands on startup."""
    if not WEBHOOK_HOST:
        log.warning("WEBHOOK_HOST not set — bot commands disabled")
        return
    url = f"{WEBHOOK_HOST}/api/tg-webhook"
    api = f"https://api.telegram.org/bot{TG_BOT_TOKEN}"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{api}/setWebhook",
            json={
                "url": url,
                "secret_token": TG_WEBHOOK_SECRET,
                "allowed_updates": ["message", "channel_post"],
            },
        )
        log.info("setWebhook: %s", r.json())
        r = await client.post(
            f"{api}/setMyCommands",
            json={"commands": [{"command": "status", "description": "Статус світла"}]},
        )
        log.info("setMyCommands: %s", r.json())


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
            now = time.time()
            prev = recent_events(1)
            if prev:
                since_ts = prev[0]["ts"]
            elif first_heartbeat_ts():
                since_ts = first_heartbeat_ts()
            else:
                since_ts = 0
            kv_set("power_down", "1")
            save_event("down")
            log.warning("POWER OUTAGE detected")
            msg = f"\u274c {_ts_fmt_hm(now)} Світло зникло"
            if since_ts:
                dur = _format_duration(int(now - since_ts))
                msg += f"\n\U0001f553 Воно було {dur} ({_ts_fmt_hm(since_ts)} - {_ts_fmt_hm(now)})"
            await update_chat_photo(True)
            await tg_send(msg)

        elif latest_alive and is_down:
            now = time.time()
            prev = recent_events(1)
            kv_set("power_down", "0")
            save_event("up")
            log.info("POWER RESTORED")
            msg = f"\u2705 {_ts_fmt_hm(now)} Світло з'явилось"
            if prev:
                since_ts = prev[0]["ts"]
                dur = _format_duration(int(now - since_ts))
                msg += f"\n\U0001f553 Його не було {dur} ({_ts_fmt_hm(since_ts)} - {_ts_fmt_hm(now)})"
            await update_chat_photo(False)
            await tg_send(msg)


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
        await tg_send(f"\u26a0\ufe0f Роутер не відповідає вже {minutes} хв")
    elif age <= STALE_THRESHOLD_SEC and alerted:
        kv_set("stale_alerted", "0")


# ─── DTEK schedule ────────────────────────────────────────────

def _day_slots_to_48(day_data: dict) -> list[str]:
    """Convert DTEK API {HH:MM: 1|2|3} dict to 48-element grid.

    1 = ok, 2 = maybe, 3 = off.
    """
    grid = ["ok"] * 48
    for i in range(48):
        key = f"{i // 2:02d}:{'30' if i % 2 else '00'}"
        val = day_data.get(key, 1)
        if val == 3:
            grid[i] = "off"
        elif val == 2:
            grid[i] = "maybe"
    return grid


_UA_WEEKDAYS = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"]


def _grid_text_summary(grid: list[str], date_str: str, day_label: str) -> str:
    """Build human-readable text summary of outage periods from 48-slot grid."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        weekday = _UA_WEEKDAYS[dt.weekday()]
        date_fmt = dt.strftime("%d.%m.%Y")
    except Exception:
        weekday = ""
        date_fmt = date_str

    header = f"\U0001f5d3\ufe0f Графік відключень на {day_label.lower()}, {date_fmt}"
    if weekday:
        header += f" ({weekday})"
    header += f", для групи {DTEK_QUEUE}:"

    blocks: list[tuple[int, int, str]] = []
    i = 0
    while i < 48:
        if grid[i] == "ok":
            i += 1
            continue
        btype = grid[i]
        start = i
        while i < 48 and grid[i] == btype:
            i += 1
        blocks.append((start, i, btype))

    if not blocks:
        return f'<div class="sg-text">{header}<br>\u2705 Відключень не заплановано</div>'

    lines = [header]
    for start, end, btype in blocks:
        sh, sm = divmod(start * 30, 60)
        eh, em = divmod(end * 30, 60)
        start_t = f"{sh:02d}:{sm:02d}"
        end_t = f"{eh:02d}:{em:02d}" if eh < 24 else "24:00"
        dur_min = (end - start) * 30
        if dur_min >= 60:
            dur_str = f"~{dur_min / 60:g} год."
        else:
            dur_str = f"~{dur_min} хв."
        marker = "\u25aa\ufe0f" if btype == "off" else "\u25ab\ufe0f"
        lines.append(f"{marker} {start_t} - {end_t} ({dur_str})")

    return '<div class="sg-text">' + "<br>".join(lines) + "</div>"


def _slot_time(i: int) -> str:
    h, m = divmod(i * 30, 60)
    return f"{h:02d}:{m:02d}"

_GRID_LABEL = {"ok": "світло", "maybe": "можливе", "off": "відключення"}


def _describe_grid_diff(old: list[str], new: list[str]) -> str:
    """Describe what changed between two 48-slot grids."""
    added = []
    removed = []
    for i in range(48):
        if old[i] == new[i]:
            continue
        t = f"{_slot_time(i)}-{_slot_time(i + 1)}"
        if old[i] == "ok" and new[i] != "ok":
            added.append(f"+{t} ({_GRID_LABEL[new[i]]})")
        elif old[i] != "ok" and new[i] == "ok":
            removed.append(f"−{t}")
        else:
            added.append(f"{t}: {_GRID_LABEL[old[i]]}→{_GRID_LABEL[new[i]]}")
    parts = added + removed
    return ", ".join(parts) if parts else "Без змін"


async def fetch_dtek_schedule():
    """Fetch planned outages from DTEK proxy API and cache parsed grids."""
    global _schedule_cache, _schedule_fetched_at

    now = time.time()
    if now - _schedule_fetched_at < 1800:
        return

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(DTEK_API_URL)
            r.raise_for_status()
            raw = r.json()
    except Exception as e:
        log.warning("DTEK API fetch failed: %s", e)
        return

    if "body" in raw and isinstance(raw["body"], str):
        try:
            raw = json.loads(raw["body"])
        except json.JSONDecodeError:
            log.warning("DTEK API: failed to parse body")
            return

    region_data = None
    for reg in raw.get("regions", []):
        if reg.get("cpu") == DTEK_REGION:
            region_data = reg
            break
    if not region_data:
        log.warning("DTEK: region %s not found", DTEK_REGION)
        return

    queue_data = region_data.get("schedule", {}).get(DTEK_QUEUE)
    if not queue_data:
        log.warning("DTEK: queue %s not found in %s", DTEK_QUEUE, DTEK_REGION)
        return

    dates = sorted(queue_data.keys())
    result = {}
    labels = [("today", 0), ("tomorrow", 1)]
    for day_key, idx in labels:
        if idx >= len(dates):
            continue
        date_str = dates[idx]
        day_slots = queue_data[date_str]
        grid = _day_slots_to_48(day_slots)
        result[day_key] = {"date": date_str, "grid": grid}
        _save_schedule_if_changed(date_str, grid)

    _schedule_cache = result
    _schedule_fetched_at = now
    log.info("DTEK schedule updated for %s queue %s", DTEK_REGION, DTEK_QUEUE)


# ─── Background loop ─────────────────────────────────────────

async def bg_loop():
    cleanup_tick = 0
    schedule_tick = 0
    while True:
        try:
            await watchdog()
            cleanup_tick += 1
            if cleanup_tick >= 2880:  # ~24h at 30s interval
                cleanup_old()
                cleanup_tick = 0
            schedule_tick += 1
            if schedule_tick >= 60:  # ~30min at 30s interval
                await fetch_dtek_schedule()
                schedule_tick = 0
        except Exception as e:
            log.error("bg_loop: %s", e)
        await asyncio.sleep(30)


# ─── FastAPI ─────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    await fetch_dtek_schedule()
    task = asyncio.create_task(bg_loop())
    await setup_tg_bot()
    if AVATAR_ON_START:
        await update_chat_photo(kv_get("power_down") == "1")
    else:
        log.info("Skipping avatar update on start (AVATAR_ON_START=0)")
    log.info("Power monitor started, DB=%s", DB_PATH)
    yield
    task.cancel()


app = FastAPI(title="Power Monitor", lifespan=lifespan)


def _check_key(key: str):
    if key not in API_KEYS:
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


@app.post("/api/test-telegram")
async def ep_test_telegram(key: str = Query("")):
    _check_key(key)
    target = TG_TEST_CHAT_ID or TG_CHAT_ID
    status = _power_status_text()
    await tg_send(status, chat_id=target)
    return {"ok": True, "sent_to": target}



@app.post("/api/tg-webhook")
async def tg_webhook(request: Request):
    secret = request.headers.get("x-telegram-bot-api-secret-token", "")
    if secret != TG_WEBHOOK_SECRET:
        raise HTTPException(403, "forbidden")
    data = await request.json()

    msg = data.get("message") or data.get("channel_post") or {}
    text = (msg.get("text") or "").strip()
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    if not chat_id:
        return {"ok": True}
    cid = str(chat_id)

    fwd = msg.get("forward_origin") or msg.get("forward_from_chat") or {}
    fwd_text = text

    boiler_parsed = parse_boiler_schedule(fwd_text)
    if boiler_parsed:
        for entry in boiler_parsed:
            save_boiler_schedule(entry["date"], entry["intervals"], fwd_text)
        log.info("Boiler schedule parsed: %d day(s) from chat %s", len(boiler_parsed), cid)
        return {"ok": True}

    if text == "/start":
        await tg_send(
            "Привіт! Натисни /status або скористайся меню, щоб дізнатися чи є світло.",
            chat_id=cid,
        )
    elif text == "/status":
        status = _power_status_text()
        await tg_send(status, chat_id=cid)

    return {"ok": True}


def _format_duration(seconds: int) -> str:
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}д")
    if hours:
        parts.append(f"{hours}год")
    parts.append(f"{minutes}хв")
    return " ".join(parts)


def _power_status_text() -> str:
    is_down = kv_get("power_down") == "1"
    ev = recent_events(1)
    hb = recent_heartbeats(1)
    now = time.time()

    if ev:
        since_ts = ev[0]["ts"]
    elif hb:
        since_ts = first_heartbeat_ts() or hb[0]["ts"]
    else:
        return "Світло є (немає даних)"

    dur = _format_duration(int(now - since_ts))
    if is_down:
        return f"\u274c Світло ВІДСУТНЄ вже {dur} (з {_ts_fmt_hm(since_ts)})"
    return f"\u2705 Світло є вже {dur} (з {_ts_fmt_hm(since_ts)})"


def _ts_fmt_hm(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UA_TZ).strftime("%H:%M")


def _ts_fmt(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UA_TZ).strftime("%H:%M:%S")


def _ts_fmt_full(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UA_TZ).strftime("%Y-%m-%d %H:%M:%S")


_ALLOWED_ICONS = {p.name for p in _ICONS_DIR.glob("icon_*.png")}

@app.get("/icons/{name}")
async def serve_icon(name: str):
    if name not in _ALLOWED_ICONS:
        raise HTTPException(404)
    data = (_ICONS_DIR / name).read_bytes()
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/manifest.json")
async def pwa_manifest(key: str = Query("")):
    _check_key(key)
    return JSONResponse(
        {
            "name": "Power Monitor — ЗК 6",
            "short_name": "Світло ЗК6",
            "start_url": f"/?key={key}",
            "scope": "/",
            "display": "standalone",
            "background_color": "#0f172a",
            "theme_color": "#0f172a",
            "icons": [
                {"src": "/icons/icon_on.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
            ],
        },
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/sw.js")
async def service_worker():
    sw_code = """\
const CACHE = 'pm-v1';
const PRECACHE = ['/icons/icon_on.png', '/icons/icon_off.png'];
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(PRECACHE)));
  self.skipWaiting();
});
self.addEventListener('activate', e => {
  e.waitUntil(self.clients.claim());
});
self.addEventListener('fetch', e => {
  if (e.request.mode === 'navigate') return;
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
"""
    return Response(
        content=sw_code,
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


@app.get("/", response_class=HTMLResponse)
async def dashboard(key: str = Query("")):
    _check_key(key)
    is_down = kv_get("power_down") == "1"
    hb = recent_heartbeats(30)
    ev = recent_events(30)

    if hb:
        last_hb_age = int(time.time() - hb[0]["ts"])
        mk_online = last_hb_age < STALE_THRESHOLD_SEC
        mk_cls = "up" if mk_online else "down"
        mk_text = f"Роутер: online ({last_hb_age}с тому)" if mk_online else f"Роутер: OFFLINE ({last_hb_age // 60} хв тому)"
    else:
        mk_cls = "down"
        mk_text = "Роутер: немає даних"

    duration_text = _power_status_text() if (hb or ev) else ""

    schedule_note = ""
    if _schedule_cache and _schedule_cache.get("today"):
        now_kyiv = datetime.now(UA_TZ)
        slot_idx = now_kyiv.hour * 2 + (1 if now_kyiv.minute >= 30 else 0)
        slot_val = _schedule_cache["today"]["grid"][min(slot_idx, 47)]
        if is_down:
            if slot_val == "off":
                schedule_note = "\U0001f4c5 Заплановане відключення"
            elif slot_val == "maybe":
                schedule_note = "\U0001f4c5 Можливе відключення (за графіком)"
            else:
                schedule_note = "\u26a1 Позапланове відключення"
        else:
            if slot_val == "off":
                schedule_note = "\U0001f389 Світло є (всупереч графіку)"
            elif slot_val == "maybe":
                schedule_note = "\U0001f4c5 За графіком (можливе відкл. не сталось)"
            else:
                schedule_note = "\U0001f4c5 За графіком"

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
    for i, e in enumerate(ev):
        cls = "down" if e["event"] == "down" else "up"
        label = "Пропало" if e["event"] == "down" else "З'явилось"
        if i == 0:
            dur_sec = int(time.time() - e["ts"])
            dur_fmt = _format_duration(dur_sec)
            if e["event"] == "down" and is_down:
                dur_str = f"нема вже {dur_fmt} ▸"
            elif e["event"] == "up" and not is_down:
                dur_str = f"є вже {dur_fmt} ▸"
            else:
                dur_str = dur_fmt
        elif i < len(ev):
            dur_sec = int(ev[i - 1]["ts"] - e["ts"])
            dur_str = _format_duration(dur_sec) if dur_sec > 0 else ""
        sched_tag = ""
        if _schedule_cache and _schedule_cache.get("today"):
            ev_kyiv = datetime.fromtimestamp(e["ts"], tz=UA_TZ)
            today_date = _schedule_cache["today"]["date"]
            if ev_kyiv.strftime("%Y-%m-%d") == today_date:
                ev_slot = ev_kyiv.hour * 2 + (1 if ev_kyiv.minute >= 30 else 0)
                sv = _schedule_cache["today"]["grid"][min(ev_slot, 47)]
                if e["event"] == "down" and sv == "ok":
                    sched_tag = ' <span style="color:#fbbf24">⚡позапл.</span>'
                elif e["event"] == "down" and sv != "ok":
                    sched_tag = ' <span style="color:var(--muted)">📅</span>'
        ev_rows += (
            f'<tr><td>{_ts_fmt_full(e["ts"])}</td><td class="{cls}">{label}{sched_tag}</td>'
            f'<td style="color:var(--muted)">{dur_str}</td></tr>\n'
        )

    tg_rows = ""
    for t in recent_tg_log(15):
        ok = "up" if t["status"] == 200 else "down"
        short_chat = "test" if t["chat_id"] == TG_TEST_CHAT_ID else "prod"
        safe_text = t["text"].replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br>")
        tg_rows += (
            f'<tr><td>{_ts_fmt_full(t["ts"])}</td>'
            f'<td class="{ok}">{t["status"]}</td>'
            f'<td>{short_chat}</td>'
            f'<td>{safe_text}</td></tr>\n'
        )

    # ─── DTEK schedule grid ───
    schedule_html = ""
    if _schedule_cache:
        now_kyiv = datetime.now(UA_TZ)
        current_slot = now_kyiv.hour * 2 + (1 if now_kyiv.minute >= 30 else 0)
        sched_rows = ""
        text_blocks = ""
        today_date = ""
        for day_key, day_label in (("today", "Сьогодні"), ("tomorrow", "Завтра")):
            day = _schedule_cache.get(day_key)
            if not day:
                continue
            date_str = day["date"][:10] if day["date"] else ""
            cells = ""
            grid = day["grid"]
            for i in range(48):
                cls = "sg-" + grid[i]
                if i % 2 == 0:
                    cls += " sg-hr"
                if day_key == "today" and i == current_slot:
                    cls += " sg-now"
                cells += f'<td class="{cls}"></td>'
            sched_rows += f'<tr><td class="sg-label">{day_label}<br><span style="font-size:0.7rem;color:var(--muted)">{date_str}</span></td>{cells}</tr>\n'
            text_blocks += _grid_text_summary(grid, date_str, day_label)
            if day_key == "today":
                today_date = date_str

        hour_headers = ""
        for h in range(24):
            hour_headers += f'<th colspan="2" class="sg-hdr">{h:02d}</th>'

        history_html = ""
        if today_date:
            history = schedule_history_for_date(today_date)
            if len(history) > 1:
                hist_rows = ""
                prev_grid = None
                for h in history:
                    ts_str = _ts_fmt_full(h["ts"])
                    if prev_grid is None:
                        diff_text = "Перший графік"
                    else:
                        diff_text = _describe_grid_diff(prev_grid, h["grid"])
                    prev_grid = h["grid"]
                    hist_rows += f"<tr><td>{ts_str}</td><td>{diff_text}</td></tr>\n"
                history_html = f"""
<details id="sched_hist_details" style="margin-top:0.8rem">
<summary style="font-size:0.8rem;color:var(--muted)">Зміни графіку на сьогодні ({len(history)})</summary>
<table>
<tr><th>Час</th><th>Що змінилось</th></tr>
{hist_rows}</table>
</details>
<script>
(function(){{
  var d=document.getElementById('sched_hist_details');
  if(localStorage.getItem('sched_hist_open')==='1') d.open=true;
  d.addEventListener('toggle',function(){{ localStorage.setItem('sched_hist_open',d.open?'1':'0'); }});
}})();
</script>"""

        schedule_html = f"""
<details id="sched_details" open>
<summary><h2 style="display:inline">Графік відключень (черга {DTEK_QUEUE})</h2></summary>
<div class="sg-wrap">
<table class="sg-table">
<colgroup><col class="sg-col-label"><col span="48"></colgroup>
<tr><th class="sg-label"></th>{hour_headers}</tr>
{sched_rows}</table>
</div>
<div class="sg-legend">
<span class="sg-leg-item"><span class="sg-swatch sg-ok"></span> Світло є</span>
<span class="sg-leg-item"><span class="sg-swatch sg-off"></span> Відключення</span>
<span class="sg-leg-item"><span class="sg-swatch sg-maybe"></span> Можливе</span>
<span class="sg-leg-item"><span class="sg-swatch sg-now-demo"></span> Зараз</span>
</div>
{text_blocks}
{history_html}
</details>
<script>
(function(){{
  var d=document.getElementById('sched_details');
  if(localStorage.getItem('sched_open')==='0') d.open=false;
  d.addEventListener('toggle',function(){{ localStorage.setItem('sched_open',d.open?'1':'0'); }});
}})();
</script>
"""

    # ─── Boiler schedule ───
    now_kyiv = datetime.now(UA_TZ)
    today_str = now_kyiv.strftime("%Y-%m-%d")
    tomorrow_str = (now_kyiv + timedelta(days=1)).strftime("%Y-%m-%d")
    boiler_data = boiler_schedule_for_dates([today_str, tomorrow_str])
    boiler_html = ""
    if boiler_data:
        boiler_lines = ""
        for d, label in [(today_str, "Сьогодні"), (tomorrow_str, "Завтра")]:
            intervals = boiler_data.get(d)
            if not intervals:
                continue
            try:
                dt = datetime.strptime(d, "%Y-%m-%d")
                date_fmt = dt.strftime("%d.%m.%Y")
                weekday = _UA_WEEKDAYS[dt.weekday()]
            except Exception:
                date_fmt = d
                weekday = ""
            ranges = ", ".join(f"{s}-{e}" for s, e in intervals)
            boiler_lines += f'<div style="margin-bottom:0.3rem">\U0001f535 {label}, {date_fmt} ({weekday}): <b>{ranges}</b></div>\n'
        if boiler_lines:
            boiler_html = f"""
<details id="boiler_details" open>
<summary><h2 style="display:inline">Графік котельні (генератор)</h2></summary>
{boiler_lines}
</details>
<script>
(function(){{
  var d=document.getElementById('boiler_details');
  if(localStorage.getItem('boiler_open')==='0') d.open=false;
  d.addEventListener('toggle',function(){{ localStorage.setItem('boiler_open',d.open?'1':'0'); }});
}})();
</script>
"""
    elif not boiler_data:
        boiler_html = """
<details id="boiler_details">
<summary><h2 style="display:inline">Графік котельні (генератор)</h2></summary>
<div style="color:var(--muted);font-size:0.85rem">Немає даних</div>
</details>
<script>
(function(){
  var d=document.getElementById('boiler_details');
  if(localStorage.getItem('boiler_open')==='1') d.open=true;
  d.addEventListener('toggle',function(){ localStorage.setItem('boiler_open',d.open?'1':'0'); });
})();
</script>
"""

    status_cls = "down" if is_down else "up"
    status_text = "Світло ВІДСУТНЄ" if is_down else "Світло є"

    return f"""<!DOCTYPE html>
<html lang="uk"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="10">
<meta name="theme-color" content="#0f172a">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Світло ЗК6">
<link rel="apple-touch-icon" href="/icons/icon_on.png">
<link rel="manifest" href="/manifest.json?key={key}">
<script>
if('serviceWorker' in navigator){{navigator.serviceWorker.register('/sw.js');}}
</script>
<script>
(function(){{
  var old=document.querySelector('link[rel="icon"]');
  if(old) old.remove();
  var link=document.createElement('link');
  link.rel='icon';link.type='image/png';
  link.href='/icons/{"icon_off.png" if is_down else "icon_on.png"}?t='+Date.now();
  document.head.appendChild(link);
}})();
</script>
<title>{"❌ Світло нема" if is_down else "✅ Світло є"} — Power Monitor</title>
<style>
:root {{ --bg: #0f172a; --card: #1e293b; --border: #334155; --text: #e2e8f0; --muted: #94a3b8; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text);
        max-width: 800px; margin: 0 auto; padding: 1rem; }}
h1 {{ text-align: center; font-size: 1.3rem; color: var(--muted); margin-bottom: 1rem; }}
.status {{ text-align: center; font-size: 1.8rem; font-weight: 700; padding: 1.2rem;
           border-radius: 12px; margin-bottom: 1.5rem; }}
.status.up {{ background: #064e3b; color: #6ee7b7; }}
.status.down {{ background: #7f1d1d; color: #fca5a5; animation: pulse 2s infinite; }}
@keyframes pulse {{ 0%,100% {{ opacity:1 }} 50% {{ opacity:.7 }} }}
.duration {{ text-align: center; font-size: 1rem; color: var(--muted); margin-bottom: 0.3rem; }}
.schedule-note {{ text-align: center; font-size: 0.85rem; color: var(--muted); margin-bottom: 0.5rem; }}
.mk {{ text-align: center; font-size: 0.9rem; padding: 0.6rem; border-radius: 8px; margin-bottom: 1.5rem; }}
.mk.up {{ background: #1e293b; color: #6ee7b7; }}
.mk.down {{ background: #7f1d1d; color: #fca5a5; }}
.ver {{ text-align: center; color: #475569; font-size: 0.75rem; margin-top: 2rem; }}
h2 {{ color: var(--muted); font-size: 0.9rem; text-transform: uppercase; letter-spacing: 0.05em;
     margin: 1.2rem 0 0.5rem; }}
summary h2 {{ margin: 0; }}
table {{ width: 100%; border-collapse: collapse; background: var(--card); border-radius: 8px; overflow: hidden; }}
th, td {{ padding: 0.5rem 0.75rem; text-align: left; font-size: 0.9rem; }}
th {{ background: var(--border); color: var(--muted); font-weight: 500; }}
tr:not(:last-child) td {{ border-bottom: 1px solid var(--border); }}
td.up {{ color: #6ee7b7; }}
td.down {{ color: #fca5a5; }}
.btn {{ display: inline-block; padding: 0.5rem 1.2rem; border: none; border-radius: 8px; cursor: pointer;
        font-size: 0.9rem; font-weight: 500; background: #334155; color: #e2e8f0; margin: 0.5rem 0; }}
.btn:hover {{ background: #475569; }}
.btn:active {{ background: #1e293b; }}
.btn-row {{ text-align: center; margin-bottom: 1rem; }}
.clocks {{ display: flex; justify-content: center; gap: 1.5rem; font-size: 0.85rem; color: var(--muted); margin-bottom: 1rem; }}
.clocks span {{ white-space: nowrap; }}
details {{ margin: 1.2rem 0 0.5rem; }}
summary {{ cursor: pointer; list-style: none; padding: 0.3rem 0; }}
summary::-webkit-details-marker {{ display: none; }}
summary::before {{ content: '▶ '; font-size: 0.7rem; color: var(--muted); }}
details[open] summary::before {{ content: '▼ '; }}
.sg-wrap {{ overflow-x: auto; }}
.sg-table {{ width: 100%; border-collapse: collapse; table-layout: fixed; background: var(--card); border-radius: 8px; overflow: hidden; }}
.sg-col-label {{ width: 90px; }}
.sg-table th, .sg-table td {{ padding: 0; text-align: center; border: 1px solid var(--border); }}
.sg-hdr {{ font-size: 0.6rem; color: var(--muted); font-weight: 400; padding: 2px 0; }}
.sg-label {{ white-space: nowrap; font-size: 0.75rem; padding: 4px 6px !important; text-align: left; overflow: hidden; }}
.sg-table td:not(.sg-label) {{ height: 22px; }}
.sg-hr {{ border-left: 2px solid #64748b !important; }}
.sg-ok {{ background: #1a3a2a; }}
.sg-off {{ background: #b91c1c; }}
.sg-maybe {{ background: #a16207; }}
.sg-now {{ outline: 2px solid #38bdf8; outline-offset: -2px; z-index: 1; position: relative; }}
.sg-legend {{ display: flex; gap: 1rem; justify-content: center; margin-top: 0.5rem; font-size: 0.75rem; color: var(--muted); flex-wrap: wrap; }}
.sg-leg-item {{ display: flex; align-items: center; gap: 4px; }}
.sg-swatch {{ display: inline-block; width: 14px; height: 14px; border-radius: 3px; }}
.sg-now-demo {{ width: 14px; height: 14px; border-radius: 3px; background: var(--card); outline: 2px solid #38bdf8; }}
.sg-text {{ font-size: 0.85rem; color: var(--text); margin-top: 0.8rem; line-height: 1.6; }}
</style>
</head><body>
<h1>Power Monitor — ЗК 6</h1>
<div class="status {status_cls}"><img src="/icons/{"icon_off.png" if is_down else "icon_on.png"}" style="width:48px;height:48px;border-radius:50%;vertical-align:middle;margin-right:0.5rem">{status_text}</div>
<div class="duration">{duration_text}</div>
<div class="schedule-note">{schedule_note}</div>
<div class="clocks" id="clocks"></div>
<script>
function updClocks(){{
  var now=new Date();
  var fmt=function(tz){{return now.toLocaleTimeString('uk-UA',{{timeZone:tz,hour:'2-digit',minute:'2-digit',second:'2-digit'}})}};
  document.getElementById('clocks').innerHTML=
    '<span>Київ '+fmt('Europe/Kyiv')+'</span>'+
    '<span>UTC '+fmt('UTC')+'</span>'+
    '<span>New York '+fmt('America/New_York')+'</span>';
}}
updClocks(); setInterval(updClocks,1000);
</script>

{schedule_html}

{boiler_html}

<details id="hb_details">
<summary><h2 style="display:inline">Роутер / Heartbeats</h2></summary>
<div class="mk {mk_cls}" id="mkStatus">{mk_text}</div>
<script>
(function(){{
  var age0={last_hb_age if hb else -1};
  if(age0<0) return;
  var stale={STALE_THRESHOLD_SEC};
  var t0=Date.now();
  setInterval(function(){{
    var age=age0+Math.floor((Date.now()-t0)/1000);
    var el=document.getElementById('mkStatus');
    if(age<stale){{
      el.className='mk up';
      el.textContent='Роутер: online ('+age+'с тому)';
    }}else{{
      el.className='mk down';
      el.textContent='Роутер: OFFLINE ('+Math.floor(age/60)+' хв тому)';
    }}
  }},1000);
}})();
</script>
<table>
<tr><th>Час</th><th>Plug 204</th><th>Plug 175</th></tr>
{hb_rows}</table>
</details>
<script>
(function(){{
  var d=document.getElementById('hb_details');
  if(localStorage.getItem('hb_open')==='1') d.open=true;
  d.addEventListener('toggle',function(){{ localStorage.setItem('hb_open',d.open?'1':'0'); }});
}})();
</script>

<h2>Події</h2>
<table>
<tr><th>Час</th><th>Подія</th><th>Тривалість</th></tr>
{ev_rows}</table>

<details id="tg_details">
<summary><h2 style="display:inline">Історія повідомлень Telegram</h2></summary>
<table>
<tr><th>Час</th><th>HTTP</th><th>Канал</th><th>Текст</th></tr>
{tg_rows}</table>
</details>
<script>
(function(){{
  var d=document.getElementById('tg_details');
  if(localStorage.getItem('tg_open')==='1') d.open=true;
  d.addEventListener('toggle',function(){{ localStorage.setItem('tg_open',d.open?'1':'0'); }});
}})();
</script>

<h2>Посилання</h2>
<table>
<tr><th>Опис</th><th>Посилання</th></tr>
<tr><td>Банка на паливо 6 і 6А</td><td><a href="https://send.monobank.ua/jar/7g6rEEejGE" target="_blank" style="color:#6ee7b7">send.monobank.ua/jar/7g6rEEejGE</a></td></tr>
<tr><td>Збір буд6 (вода, тепло, ДБЖ)</td><td><a href="https://send.monobank.ua/jar/faoUpWcMx" target="_blank" style="color:#6ee7b7">send.monobank.ua/jar/faoUpWcMx</a></td></tr>
<tr><td>Перевірити оплату зборів</td><td><a href="https://docs.google.com/spreadsheets/d/1q4fEVocWvtaG2-A8x4eFiZkdFAzFRaRTm7NECLcoYTs/edit?gid=2001051359#gid=2001051359" target="_blank" style="color:#6ee7b7">Таблиця зборів по квартирах</a></td></tr>
<tr><td>Форма на перепуски СКД ліфти</td><td><a href="https://docs.google.com/forms/d/e/1FAIpQLSfE2HdL7oAB88FbcQmCbDW2Du-sF3mhc2RrQE6wTjB_MDEzkg/viewform" target="_blank" style="color:#6ee7b7">Перепуски СКД ліфти Чорновола 6</a></td></tr>
<tr><td>Оселя Сервіс (ЖУС)</td><td><a href="https://www.oselya.com.ua/brovary/contact" target="_blank" style="color:#6ee7b7">oselya.com.ua/brovary/contact</a></td></tr>
</table>

<details id="legend_details">
<summary><h2 style="display:inline">Легенда повідомлень</h2></summary>
<table>
<tr><th>Подія</th><th>Повідомлення</th><th>Канал</th></tr>
<tr><td>Світло зникло</td><td>\u274c 23:31 Світло зникло / \U0001f553 Воно було 3год 30хв (20:01 - 23:31)</td><td>prod</td></tr>
<tr><td>Світло з'явилось</td><td>\u2705 01:15 Світло з'явилось / \U0001f553 Його не було 1год 44хв (23:31 - 01:15)</td><td>prod</td></tr>
<tr><td>Роутер offline</td><td>\u26a0\ufe0f Роутер не відповідає вже N хв</td><td>prod</td></tr>
<tr><td>/status (є)</td><td>\u2705 Світло є вже 3год 30хв (з 01:15)</td><td>приват</td></tr>
<tr><td>/status (нема)</td><td>\u274c Світло ВІДСУТНЄ вже 15хв (з 23:31)</td><td>приват</td></tr>
</table>
</details>

<details id="avatars_details">
<summary><h2 style="display:inline">Аватарки каналу</h2></summary>
<table>
<tr><th>Стан</th><th>Іконка</th><th>Файл</th></tr>
<tr><td>Світло є (активна)</td><td><img src="/icons/icon_on.png" style="width:64px;height:64px;border-radius:50%"></td><td>icon_on.png</td></tr>
<tr><td>Світло нема (активна)</td><td><img src="/icons/icon_off.png" style="width:64px;height:64px;border-radius:50%"></td><td>icon_off.png</td></tr>
<tr><td>Світло нема (v3)</td><td><img src="/icons/icon_off_v3.png" style="width:64px;height:64px;border-radius:50%"></td><td>icon_off_v3.png</td></tr>
<tr><td>Світло нема (v2)</td><td><img src="/icons/icon_off_v2.png" style="width:64px;height:64px;border-radius:50%"></td><td>icon_off_v2.png</td></tr>
<tr><td>Висока напруга (v1)</td><td><img src="/icons/icon_high_voltage_v1.png" style="width:64px;height:64px;border-radius:50%"></td><td>icon_high_voltage_v1.png</td></tr>
<tr><td>Висока напруга (v2)</td><td><img src="/icons/icon_high_voltage_v2.png" style="width:64px;height:64px;border-radius:50%"></td><td>icon_high_voltage_v2.png</td></tr>
<tr><td>Низька напруга (v1)</td><td><img src="/icons/icon_low_voltage_v1.png" style="width:64px;height:64px;border-radius:50%"></td><td>icon_low_voltage_v1.png</td></tr>
<tr><td>Низька напруга (v2)</td><td><img src="/icons/icon_low_voltage_v2.png" style="width:64px;height:64px;border-radius:50%"></td><td>icon_low_voltage_v2.png</td></tr>
</table>
</details>
<script>
(function(){{
  ['legend','avatars'].forEach(function(k){{
    var d=document.getElementById(k+'_details');
    if(localStorage.getItem(k+'_open')==='1') d.open=true;
    d.addEventListener('toggle',function(){{ localStorage.setItem(k+'_open',d.open?'1':'0'); }});
  }});
}})();
</script>

<div class="ver">v {GIT_COMMIT}</div>
</body></html>"""
