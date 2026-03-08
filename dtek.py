"""
DTEK schedule, weather, and alert fetch logic.

Centralizes:
- DTEK schedule API (planned outages)
- Open-Meteo weather
- alerts.com.ua (air raid alerts)
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta

import httpx

from config import (
    ALERT_API_URL,
    ALERT_REGION_IDS,
    DTEK_API_URL,
    DTEK_QUEUE,
    DTEK_REGION,
    UA_TZ,
    WEATHER_URL,
)
from database import (
    _save_schedule_if_changed,
    save_alert_event,
    save_weather_log,
)

log = logging.getLogger("power_monitor")

# ─── Caches ───────────────────────────────────────────────────

schedule_cache: dict = {}
_schedule_fetched_at: float = 0

weather_cache: dict = {}
_weather_fetched_at: float = 0

alert_cache: dict = {}
_alert_fetched_at: float = 0


# ─── Helpers ───────────────────────────────────────────────────

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


def schedule_deviation(is_down_event: bool) -> int | None:
    """Find signed deviation (minutes) from the nearest matching DTEK transition.

    Positive = event happened after the scheduled time.
    Returns None when no schedule data or no matching transitions exist.
    """
    if not schedule_cache or not schedule_cache.get("today"):
        return None

    grid = schedule_cache["today"]["grid"]
    now_kyiv = datetime.now(UA_TZ)
    event_min = now_kyiv.hour * 60 + now_kyiv.minute
    best: int | None = None

    for i in range(1, 48):
        prev_ok = grid[i - 1] == "ok"
        curr_ok = grid[i] == "ok"
        transition_min = i * 30
        if is_down_event and prev_ok and not curr_ok:
            dev = event_min - transition_min
            if best is None or abs(dev) < abs(best):
                best = dev
        elif not is_down_event and not prev_ok and curr_ok:
            dev = event_min - transition_min
            if best is None or abs(dev) < abs(best):
                best = dev

    return best


def fmt_deviation(minutes: int, signed: bool = True) -> str:
    """Format deviation as readable string: '+3хв', '-10хв', '1год 30хв'."""
    a = abs(minutes)
    if a < 60:
        if signed and minutes != 0:
            return f"{'+' if minutes > 0 else '-'}{a}хв"
        return f"{a}хв"
    h, m = divmod(a, 60)
    parts = f"{h}год" + (f" {m}хв" if m else "")
    if signed and minutes != 0:
        return f"{'+' if minutes > 0 else '-'}{parts}"
    return parts


def _fmt_slot(slot_idx: int) -> str:
    h, m = divmod((slot_idx % 48) * 30, 60)
    ts = f"{h:02d}:{m:02d}"
    return f"завтра {ts}" if slot_idx >= 48 else ts


def next_schedule_transition(looking_for_on: bool) -> str | None:
    """Find next scheduled power-ON (True) or power-OFF (False) block.

    Returns '~16:30 - 21:30' (with end) or '~06:00' (no end), or None.
    """
    if not schedule_cache:
        return None

    now_kyiv = datetime.now(UA_TZ)
    cur_slot = now_kyiv.hour * 2 + (1 if now_kyiv.minute >= 30 else 0)

    combined: list[str] = []
    for key in ("today", "tomorrow"):
        day = schedule_cache.get(key)
        combined.extend(day["grid"] if day else ["ok"] * 48)

    target_ok = looking_for_on

    i = cur_slot
    while i < len(combined):
        if (combined[i] == "ok") != target_ok:
            break
        i += 1
    while i < len(combined):
        if (combined[i] == "ok") == target_ok:
            break
        i += 1

    if i >= len(combined):
        return None

    start = i
    while i < len(combined):
        if (combined[i] == "ok") != target_ok:
            break
        i += 1

    start_str = _fmt_slot(start)
    if i < len(combined):
        return f"~{start_str} - {_fmt_slot(i)}"
    return f"~{start_str}"


_UA_WEEKDAYS = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"]
UA_WEEKDAYS = _UA_WEEKDAYS  # public alias for power_monitor use


def grid_text_summary(grid: list[str], date_str: str, day_label: str) -> str:
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

    off_slots = sum(1 for s in grid if s != "ok")
    on_slots = 48 - off_slots
    off_min = off_slots * 30
    on_min = on_slots * 30

    def _hm(minutes: int) -> str:
        h, m = divmod(minutes, 60)
        return f"{h}год {m}хв" if m else f"{h}год"

    off_pct = round(off_slots / 48 * 100)
    on_pct = 100 - off_pct
    lines.append(
        f"\U0001f4ca Зі світлом: {_hm(on_min)} ({on_pct}%) · "
        f"Без світла: {_hm(off_min)} ({off_pct}%)"
    )

    return '<div class="sg-text">' + "<br>".join(lines) + "</div>"


def _slot_time(i: int) -> str:
    h, m = divmod(i * 30, 60)
    return f"{h:02d}:{m:02d}"


_GRID_LABEL = {"ok": "світло", "maybe": "можливе", "off": "відключення"}


def describe_grid_diff(old: list[str], new: list[str]) -> str:
    """Describe what changed between two 48-slot grids, merging consecutive ranges."""
    changes = []
    i = 0
    while i < 48:
        if old[i] == new[i]:
            i += 1
            continue
        kind = (old[i], new[i])
        start = i
        while i < 48 and (old[i], new[i]) == kind:
            i += 1
        t = f"{_slot_time(start)}-{_slot_time(i)}"
        o, n = kind
        if o == "ok" and n != "ok":
            changes.append(f"+{t} ({_GRID_LABEL[n]})")
        elif o != "ok" and n == "ok":
            changes.append(f"\u2212{t}")
        else:
            changes.append(f"{t}: {_GRID_LABEL[o]}\u2192{_GRID_LABEL[n]}")
    return ", ".join(changes) if changes else "Без змін"


# ─── Fetch functions ───────────────────────────────────────────

async def fetch_dtek_schedule():
    """Fetch planned outages from DTEK proxy API and cache parsed grids."""
    global schedule_cache, _schedule_fetched_at

    now = time.time()
    cache_stale = now - _schedule_fetched_at >= 1800
    date_changed = False
    if schedule_cache and schedule_cache.get("today"):
        cached_date = schedule_cache["today"]["date"]
        actual_today = datetime.now(UA_TZ).strftime("%Y-%m-%d")
        if cached_date != actual_today:
            date_changed = True
    if not cache_stale and not date_changed:
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
    now_kyiv = datetime.now(UA_TZ)
    today_iso = now_kyiv.strftime("%Y-%m-%d")
    tomorrow_iso = (now_kyiv + timedelta(days=1)).strftime("%Y-%m-%d")

    result = {}
    for date_str in dates:
        if date_str == today_iso:
            day_key = "today"
        elif date_str == tomorrow_iso:
            day_key = "tomorrow"
        else:
            continue
        day_slots = queue_data[date_str]
        grid = _day_slots_to_48(day_slots)
        result[day_key] = {"date": date_str, "grid": grid}
        _save_schedule_if_changed(date_str, grid)

    schedule_cache = result
    _schedule_fetched_at = now
    log.info("DTEK schedule updated for %s queue %s", DTEK_REGION, DTEK_QUEUE)


async def fetch_weather():
    global weather_cache, _weather_fetched_at

    now = time.time()
    if now - _weather_fetched_at < 1800:
        return

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(WEATHER_URL)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log.warning("Weather fetch failed: %s", e)
        return

    cur = data.get("current", {})
    daily = data.get("daily", {})
    t_min_list = daily.get("temperature_2m_min", [])
    t_max_list = daily.get("temperature_2m_max", [])
    weather_cache = {
        "temp": cur.get("temperature_2m"),
        "humidity": cur.get("relative_humidity_2m"),
        "wind": cur.get("wind_speed_10m"),
        "code": cur.get("weather_code", -1),
        "t_min": t_min_list[0] if t_min_list else None,
        "t_max": t_max_list[0] if t_max_list else None,
    }
    _weather_fetched_at = now
    log.info("Weather updated: %s", weather_cache)

    w = weather_cache
    save_weather_log(w["temp"], w["humidity"], w["wind"], w["code"], w["t_min"], w["t_max"], now)


async def fetch_alert():
    global alert_cache, _alert_fetched_at

    now = time.time()
    if now - _alert_fetched_at < 120:
        return

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                ALERT_API_URL,
                headers={"X-API-Key": "test"},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log.warning("Alert fetch failed: %s", e)
        return

    active = False
    changed = ""
    for s in data.get("states", []):
        if s.get("id") in ALERT_REGION_IDS and s.get("alert"):
            active = True
            changed = s.get("changed", "")
            break

    was_active = alert_cache.get("active") if alert_cache else None
    if was_active is not None and active != was_active:
        event = "alert_on" if active else "alert_off"
        save_alert_event(event)
        log.info("Alert status changed: %s", event)

    alert_cache = {"active": active, "changed": changed}
    _alert_fetched_at = now
