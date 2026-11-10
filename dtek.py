"""
DTEK schedule, weather, and alert fetch logic.

Centralizes:
- DTEK schedule API (planned outages)
- Open-Meteo weather
- alerts.in.ua air-raid levels for Brovary raion 79
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta

import httpx

from config import (
    ALERT_ACTIVE_URL,
    ALERT_BROVARY_LUID,
    DTEK_API_URL,
    DTEK_POLL_SEC,
    DTEK_QUEUE,
    DTEK_REGION,
    UA_TZ,
    WEATHER_URL,
)
from database import (
    _save_schedule_if_changed,
    recent_alert_events,
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


def current_slot_status() -> str | None:
    """Current slot status: 'ok', 'maybe', or 'off'. None if no schedule."""
    if not schedule_cache or not schedule_cache.get("today"):
        return None
    grid = schedule_cache["today"]["grid"]
    now_kyiv = datetime.now(UA_TZ)
    slot_idx = now_kyiv.hour * 2 + (1 if now_kyiv.minute >= 30 else 0)
    return grid[min(slot_idx, 47)]


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


def classify_grid_changes(old: list[str], new: list[str]) -> list[dict]:
    """Structured diff of two 48-slot grids.

    A move pairs a removed outage with an added one when their lengths differ
    by at most one slot. This is our reading of two snapshots, not a DTEK field.
    The first snapshot of a date has no old grid, so the caller writes no rows.
    """
    if len(old) != 48 or len(new) != 48:
        raise ValueError("grids must be 48 slots")

    removed: list[dict] = []
    added: list[dict] = []
    severity: list[dict] = []
    i = 0
    while i < 48:
        if old[i] == new[i]:
            i += 1
            continue
        old_status, new_status = old[i], new[i]
        start = i
        while i < 48 and old[i] == old_status and new[i] == new_status:
            i += 1
        block = {"start": start, "end": i, "from": old_status, "to": new_status}
        if old_status in ("off", "maybe") and new_status == "ok":
            removed.append(block)
        elif old_status == "ok" and new_status in ("off", "maybe"):
            added.append(block)
        elif old_status != "ok" and new_status != "ok":
            severity.append(block)

    candidates = []
    for removed_i, block in enumerate(removed):
        removed_len = block["end"] - block["start"]
        for added_i, other in enumerate(added):
            added_len = other["end"] - other["start"]
            length_diff = abs(removed_len - added_len)
            if length_diff > 1:
                continue
            candidates.append((
                length_diff,
                abs(block["start"] - other["start"]),
                block["start"],
                other["start"],
                removed_i,
                added_i,
            ))
    candidates.sort()
    used_removed: set[int] = set()
    used_added: set[int] = set()
    rows: list[dict] = []
    for _length, _distance, _removed_start, _added_start, removed_i, added_i in candidates:
        if removed_i in used_removed or added_i in used_added:
            continue
        used_removed.add(removed_i)
        used_added.add(added_i)
        old_block = removed[removed_i]
        new_block = added[added_i]
        rows.append({
            "kind": "moved",
            "start_slot": old_block["start"],
            "end_slot": old_block["end"],
            "from_status": old_block["from"],
            "to_status": new_block["to"],
            "peer_start_slot": new_block["start"],
            "peer_end_slot": new_block["end"],
        })
    for index, block in enumerate(removed):
        if index in used_removed:
            continue
        rows.append({
            "kind": "removed",
            "start_slot": block["start"],
            "end_slot": block["end"],
            "from_status": block["from"],
            "to_status": "ok",
            "peer_start_slot": None,
            "peer_end_slot": None,
        })
    for index, block in enumerate(added):
        if index in used_added:
            continue
        rows.append({
            "kind": "added",
            "start_slot": block["start"],
            "end_slot": block["end"],
            "from_status": "ok",
            "to_status": block["to"],
            "peer_start_slot": None,
            "peer_end_slot": None,
        })
    for block in severity:
        rows.append({
            "kind": "severity",
            "start_slot": block["start"],
            "end_slot": block["end"],
            "from_status": block["from"],
            "to_status": block["to"],
            "peer_start_slot": None,
            "peer_end_slot": None,
        })
    return rows


def store_published_schedule(region_data: dict, now_kyiv: datetime) -> dict | None:
    """Save every queue and date in this region payload.

    Returns the today/tomorrow fragment for our queue, or None when our queue
    is absent. None means the caller must leave schedule_cache untouched.
    A returned dict only contains keys that this payload actually published.
    """
    schedule = region_data.get("schedule") or {}
    if not isinstance(schedule, dict):
        schedule = {}
    emergency = 1 if region_data.get("emergency") else 0
    queue_count = 0
    inserted = 0
    for queue, days in schedule.items():
        if not isinstance(days, dict):
            continue
        queue_count += 1
        for date_str, slots in days.items():
            if not isinstance(date_str, str) or not isinstance(slots, dict):
                continue
            row_id = _save_schedule_if_changed(
                date_str,
                _day_slots_to_48(slots),
                str(queue),
                emergency,
            )
            if row_id is not None:
                inserted += 1
    log.info(
        "DTEK stored %s queues, %s new snapshots, emergency=%s",
        queue_count,
        inserted,
        emergency,
    )

    our_days = schedule.get(DTEK_QUEUE)
    if not isinstance(our_days, dict):
        return None
    today_iso = now_kyiv.strftime("%Y-%m-%d")
    tomorrow_iso = (now_kyiv + timedelta(days=1)).strftime("%Y-%m-%d")
    update: dict = {}
    if isinstance(our_days.get(today_iso), dict):
        update["today"] = {"date": today_iso, "grid": _day_slots_to_48(our_days[today_iso])}
    if isinstance(our_days.get(tomorrow_iso), dict):
        update["tomorrow"] = {"date": tomorrow_iso, "grid": _day_slots_to_48(our_days[tomorrow_iso])}
    return update


# ─── Fetch functions ───────────────────────────────────────────

async def fetch_dtek_schedule():
    """Fetch planned outages from DTEK proxy API and cache parsed grids."""
    global schedule_cache, _schedule_fetched_at

    now = time.time()
    cache_stale = now - _schedule_fetched_at >= DTEK_POLL_SEC
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

    now_kyiv = datetime.now(UA_TZ)
    update = store_published_schedule(region_data, now_kyiv)
    if update is None:
        log.warning(
            "DTEK: queue %s not found in %s; other published queues were stored",
            DTEK_QUEUE,
            DTEK_REGION,
        )
    else:
        schedule_cache.update(update)
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


def _record_level(item: dict) -> str:
    """Yellow is explicit. A Brovary record without a level is red."""
    named = item.get("alert_level")
    if named == "yellow":
        return "yellow"
    if named == "red":
        return "red"
    al = item.get("al")
    if al == 1 or al == "1":
        return "yellow"
    return "red"


def brovary_alert_level(alerts: list) -> str | None:
    """Yellow or red when raion 79 is in the feed. None is all-clear."""
    found = None
    for item in alerts:
        if not isinstance(item, dict):
            continue
        raw = item.get("luid", item.get("location_uid"))
        try:
            luid = int(raw)
        except (TypeError, ValueError):
            continue
        if luid != ALERT_BROVARY_LUID:
            continue
        if _record_level(item) == "red":
            return "red"
        found = "yellow"
    return found


def alert_banner_html(cache: dict) -> str:
    if not cache:
        return ""
    level = cache.get("level")
    if level == "yellow":
        return '<div class="alert-banner alert-yellow">\U0001f7e1 Жовта тривога, Бровари</div>'
    if level == "red":
        return '<div class="alert-banner alert-on">\U0001f534 Червона тривога, Бровари</div>'
    return '<div class="alert-banner alert-off">\U0001f7e2 Відбій, Бровари</div>'


def alert_event_view(event: str) -> tuple[str, str]:
    if event == "alert_yellow":
        return "alert-yellow", "\U0001f7e1 Жовта"
    if event == "alert_red":
        return "down", "\U0001f534 Червона"
    if event == "alert_on":
        return "down", "\U0001f534 Тривога"
    return "up", "\U0001f7e2 Відбій"


def alert_event_is_open(event: str, level: str | None) -> bool:
    if event == "alert_yellow":
        return level == "yellow"
    if event == "alert_red":
        return level == "red"
    if event == "alert_off":
        return level is None
    return False


def _stored_level() -> tuple[bool, str | None]:
    """Last saved level. The bool is false when the history table is empty."""
    rows = recent_alert_events(1)
    if not rows:
        return False, None
    event = rows[0]["event"]
    if event == "alert_yellow":
        return True, "yellow"
    if event in ("alert_red", "alert_on"):
        return True, "red"
    if event == "alert_off":
        return True, None
    return False, None


def _level_event(level: str | None) -> str:
    if level == "yellow":
        return "alert_yellow"
    if level == "red":
        return "alert_red"
    return "alert_off"


async def fetch_alert():
    global alert_cache, _alert_fetched_at

    now = time.time()
    if _alert_fetched_at and now - _alert_fetched_at < 20:
        return

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                ALERT_ACTIVE_URL,
                headers={"Accept": "application/json", "User-Agent": "power-monitor"},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log.warning("Alert fetch failed: %s", e)
        return

    alerts = data.get("alerts") if isinstance(data, dict) else None
    if not isinstance(alerts, list):
        log.warning("Alert payload has no alerts list")
        return

    level = brovary_alert_level(alerts)
    if alert_cache:
        known, previous = True, alert_cache.get("level")
    else:
        known, previous = _stored_level()
    if (known and previous != level) or (not known and level is not None):
        event = _level_event(level)
        save_alert_event(event)
        log.info("Alert status changed: %s", event)

    alert_cache = {"active": level is not None, "level": level}
    _alert_fetched_at = now
