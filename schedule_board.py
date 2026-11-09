"""Pure schedule-board math and the read-only day payload.

Writers live in database.py. This module does not query deye_log or power_events.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from config import (
    DTEK_QUEUE,
    UA_TZ,
    VOLTAGE_HIGH_ABOVE,
    VOLTAGE_LOW_BELOW,
    VOLTAGE_PRESENT_MIN,
    VOLTAGE_SAMPLE_GAP_SEC,
)


def kyiv_day_bounds(date_str: str) -> tuple[float, float]:
    year, month, day = (int(part) for part in date_str.split("-"))
    start = datetime(year, month, day, tzinfo=UA_TZ)
    end = start + timedelta(days=1)
    return start.timestamp(), end.timestamp()


def kyiv_date_str(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UA_TZ).strftime("%Y-%m-%d")


def shift_date(date_str: str, days: int) -> str:
    year, month, day = (int(part) for part in date_str.split("-"))
    shifted = datetime(year, month, day, tzinfo=UA_TZ) + timedelta(days=days)
    return shifted.strftime("%Y-%m-%d")


def voltage_sample_band(v1, v2, v3) -> str | None:
    """Problem band of one sample. None means the open interval ends."""
    present: list[float] = []
    for value in (v1, v2, v3):
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number >= VOLTAGE_PRESENT_MIN:
            present.append(number)
    if not present:
        return None
    if any(number > VOLTAGE_HIGH_ABOVE for number in present):
        return "high"
    if any(number < VOLTAGE_LOW_BELOW for number in present):
        return "low"
    return None


def apply_voltage_sample(voltage_json: list | None, ts: float, v1, v2, v3) -> list:
    """Fold one sample into the stored voltage intervals. Does not read the log."""
    intervals = [dict(item) for item in (voltage_json or [])]
    band = voltage_sample_band(v1, v2, v3)
    open_index = _open_voltage_index(intervals)
    if open_index is None:
        if band is None:
            return intervals
        intervals.append({"band": band, "start": ts, "last_ts": ts, "end": None})
        return intervals

    current = intervals[open_index]
    last_ts = float(current["last_ts"])
    same_band = band is not None and band == current.get("band")
    if same_band and ts - last_ts <= VOLTAGE_SAMPLE_GAP_SEC:
        current["last_ts"] = ts
        intervals[open_index] = current
        return intervals

    intervals[open_index] = {
        "band": current["band"],
        "start": current["start"],
        "end": last_ts,
    }
    if band is not None:
        intervals.append({"band": band, "start": ts, "last_ts": ts, "end": None})
    return intervals


def apply_power_event(actual_json: list | None, event: str, ts: float, day_start: float, day_end: float) -> list:
    """Apply one down/up to a single day's stored intervals."""
    intervals = [dict(item) for item in (actual_json or [])]
    if event == "down":
        if _open_actual(intervals) is not None:
            return intervals
        start = max(float(ts), day_start)
        if start >= day_end:
            return intervals
        intervals.append({"start": start, "end": None})
        return intervals
    if event == "up":
        for index in range(len(intervals) - 1, -1, -1):
            if intervals[index].get("end") is None:
                end = min(float(ts), day_end)
                if end < intervals[index]["start"]:
                    end = intervals[index]["start"]
                intervals[index]["end"] = end
                return intervals
    return intervals


def close_open_at(actual_json: list | None, end_ts: float) -> list:
    intervals = [dict(item) for item in (actual_json or [])]
    for item in intervals:
        if item.get("end") is None:
            item["end"] = end_ts
    return intervals


def has_open_actual(actual_json: list | None) -> bool:
    return _open_actual(actual_json or []) is not None


def _planned_outage(status: str) -> bool:
    """A possible slot counts as an outage. That is how the queue is running."""
    return status in ("off", "maybe")


def recompute_match(grid: list[str] | None, actual_json: list | None, day_start: float, scored_until: float) -> dict | None:
    """Score minutes in [day_start, scored_until). Maybe counts as off."""
    if not grid or len(grid) != 48:
        return None
    intervals = actual_json or []
    limit = scored_until
    if limit < day_start:
        limit = day_start
    minute_count = int((limit - day_start) // 60)
    if minute_count > 24 * 60:
        minute_count = 24 * 60
    hit = miss = unplanned = 0
    for minute in range(minute_count):
        minute_start = day_start + minute * 60
        status = grid[minute // 30]
        down = _minute_is_down(intervals, minute_start, minute_start + 60, limit)
        if _planned_outage(status) and down:
            hit += 1
        elif _planned_outage(status):
            miss += 1
        elif status == "ok" and down:
            unplanned += 1
    return {
        "hit_min": hit,
        "miss_min": miss,
        "unplanned_min": unplanned,
        "scored_until": limit,
    }


def extend_open_match(match: dict | None, grid: list[str] | None, actual_json: list | None, day_start: float, day_end: float, now: float) -> dict | None:
    """Add minutes after the stored score while an outage is still open. Does not write."""
    if match is None or not grid:
        return None
    if _open_actual(actual_json or []) is None:
        return match
    scored_until = float(match["scored_until"])
    limit = min(now, day_end)
    if limit <= scored_until:
        return match
    window = _score_window(grid, actual_json, scored_until, limit)
    return {
        "hit_min": int(match["hit_min"]) + window["hit_min"],
        "miss_min": int(match["miss_min"]) + window["miss_min"],
        "unplanned_min": int(match["unplanned_min"]) + window["unplanned_min"],
        "scored_until": limit,
    }


def present_actual(actual_json: list | None, day_end: float, now: float) -> list[dict]:
    presented = []
    for item in actual_json or []:
        end = item.get("end")
        if end is None:
            end = min(now, day_end)
        presented.append({"start": item["start"], "end": end})
    return presented


def present_voltage(voltage_json: list | None, now: float) -> list[dict]:
    presented = []
    for item in voltage_json or []:
        end = item.get("end")
        if end is None:
            last_ts = float(item["last_ts"])
            if now - last_ts <= VOLTAGE_SAMPLE_GAP_SEC:
                _start, day_end = kyiv_day_bounds(kyiv_date_str(float(item["start"])))
                end = min(now, day_end)
            else:
                end = last_ts
        presented.append({"start": item["start"], "end": end, "band": item["band"]})
    return presented


def slot_set_from_changes(changes: list[dict], grid: list[str] | None) -> tuple[list[int], list[int]]:
    """Latest revision outlines, and cancelled slots still ok in the latest grid."""
    if not changes:
        return [], []
    latest_id = max(change["history_id"] for change in changes)
    changed: set[int] = set()
    cancelled: set[int] = set()
    for change in changes:
        if change["history_id"] == latest_id:
            changed.update(_span(change["start_slot"], change["end_slot"]))
            if change["kind"] == "moved":
                changed.update(_span(change["peer_start_slot"], change["peer_end_slot"]))
        if change["kind"] in ("removed", "moved"):
            for slot in _span(change["start_slot"], change["end_slot"]):
                if grid and slot < len(grid) and grid[slot] == "ok":
                    cancelled.add(slot)
    return sorted(changed), sorted(cancelled)


def read_schedule_board(target_date: str, now: float) -> dict:
    """Indexed reads only. Does not scan deye_log or power_events and does not write."""
    datetime.strptime(target_date, "%Y-%m-%d")
    from database import _conn

    our_queue = DTEK_QUEUE
    with _conn() as db:
        history_rows = db.execute(
            """SELECT queue, grid_json, fetched_at, emergency FROM schedule_history
               WHERE target_date=?
               ORDER BY id ASC""",
            (target_date,),
        ).fetchall()
        change_rows = db.execute(
            """SELECT queue, fetched_at, history_id, kind, start_slot, end_slot,
                      from_status, to_status, peer_start_slot, peer_end_slot, emergency
               FROM schedule_changes WHERE target_date=? ORDER BY id ASC""",
            (target_date,),
        ).fetchall()
        day_row = db.execute(
            """SELECT actual_json, voltage_json, match_json, overlay_ready, updated_at
               FROM schedule_day WHERE queue=? AND target_date=?""",
            (our_queue, target_date),
        ).fetchone()
        date_rows = db.execute(
            "SELECT DISTINCT target_date FROM schedule_history WHERE queue=? ORDER BY target_date",
            (our_queue,),
        ).fetchall()
        queue_rows = db.execute(
            "SELECT DISTINCT queue FROM schedule_history ORDER BY queue"
        ).fetchall()

    latest: dict[str, dict] = {}
    for row in history_rows:
        latest[row["queue"]] = {
            "grid": json.loads(row["grid_json"]),
            "fetched_at": row["fetched_at"],
            "emergency": int(row["emergency"] or 0),
        }
    queues = {row["queue"] for row in queue_rows}
    queues.add(our_queue)
    groups = {}
    for queue in sorted(queues):
        item = latest.get(queue)
        if item is None:
            groups[queue] = {
                "has_snapshot": False,
                "grid": None,
                "fetched_at": None,
                "emergency": False,
            }
        else:
            groups[queue] = {
                "has_snapshot": True,
                "grid": item["grid"],
                "fetched_at": item["fetched_at"],
                "emergency": bool(item["emergency"]),
            }

    changes_by_queue: dict[str, list[dict]] = {}
    changes_out = []
    for row in change_rows:
        change = {
            "queue": row["queue"],
            "fetched_at": row["fetched_at"],
            "history_id": row["history_id"],
            "kind": row["kind"],
            "start_slot": row["start_slot"],
            "end_slot": row["end_slot"],
            "from_status": row["from_status"],
            "to_status": row["to_status"],
            "peer_start_slot": row["peer_start_slot"],
            "peer_end_slot": row["peer_end_slot"],
            "emergency": bool(row["emergency"]),
        }
        changes_out.append(change)
        changes_by_queue.setdefault(row["queue"], []).append(change)

    changed_slots = {}
    cancelled_slots = {}
    for queue, group in groups.items():
        changed, cancelled = slot_set_from_changes(
            changes_by_queue.get(queue, []),
            group["grid"],
        )
        changed_slots[queue] = changed
        cancelled_slots[queue] = cancelled

    available = [row["target_date"] for row in date_rows]
    today = kyiv_date_str(now)
    if today not in available:
        available.append(today)
        available.sort()

    day_start, day_end = kyiv_day_bounds(target_date)
    our = groups[our_queue]
    if day_row is None:
        actual_raw: list = []
        voltage_raw: list = []
        match = None
        overlay_ready = False
        updated_at = None
    else:
        actual_raw = json.loads(day_row["actual_json"]) if day_row["actual_json"] else []
        voltage_raw = json.loads(day_row["voltage_json"]) if day_row["voltage_json"] else []
        match = json.loads(day_row["match_json"]) if day_row["match_json"] else None
        overlay_ready = bool(day_row["overlay_ready"])
        updated_at = day_row["updated_at"]

    if not our["has_snapshot"] or not overlay_ready:
        match = None
    else:
        # Rescore the loaded row. A stored counter would keep the old rule that skipped maybe.
        score_end = day_end
        if target_date == today:
            score_end = min(now, day_end)
        if now < day_start:
            score_end = day_start
        match = recompute_match(our["grid"], actual_raw, day_start, score_end)

    our_emergency = bool(our["emergency"]) if our["has_snapshot"] else False
    return {
        "date": target_date,
        "our_queue": our_queue,
        "overlay_ready": overlay_ready,
        "available_dates": available,
        "emergency": our_emergency,
        "groups": groups,
        "changes": changes_out,
        "changed_slots": changed_slots,
        "cancelled_slots": cancelled_slots,
        "actual": present_actual(actual_raw, day_end, now),
        "voltage": present_voltage(voltage_raw, now),
        "match": match,
        "updated_at": updated_at,
    }


def _open_voltage_index(intervals: list[dict]) -> int | None:
    for index, item in enumerate(intervals):
        if item.get("end") is None and "last_ts" in item:
            return index
    return None


def _open_actual(intervals: list[dict]) -> dict | None:
    for item in intervals:
        if item.get("end") is None:
            return item
    return None


def _minute_is_down(intervals: list, minute_start: float, minute_end: float, open_until: float) -> bool:
    for item in intervals:
        end = item.get("end")
        if end is None:
            end = open_until
        if item["start"] < minute_end and end > minute_start:
            return True
    return False


def _score_window(grid: list[str], actual_json: list | None, window_start: float, window_end: float) -> dict:
    """Score [window_start, window_end) without treating window_start as midnight."""
    if window_end < window_start:
        window_end = window_start
    minute_count = int((window_end - window_start) // 60)
    hit = miss = unplanned = 0
    for minute in range(minute_count):
        minute_start = window_start + minute * 60
        day_start, _day_end = kyiv_day_bounds(kyiv_date_str(minute_start))
        minute_index = int((minute_start - day_start) // 60)
        if minute_index < 0 or minute_index >= 24 * 60:
            continue
        status = grid[minute_index // 30]
        down = _minute_is_down(actual_json or [], minute_start, minute_start + 60, window_end)
        if _planned_outage(status) and down:
            hit += 1
        elif _planned_outage(status):
            miss += 1
        elif status == "ok" and down:
            unplanned += 1
    return {"hit_min": hit, "miss_min": miss, "unplanned_min": unplanned}


def _span(start, end) -> range:
    if start is None or end is None:
        return range(0)
    return range(int(start), int(end))
