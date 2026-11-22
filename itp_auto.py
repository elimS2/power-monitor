"""Desired heat-breaker state from city power and the boiler window.

No network, no database, no breaker commands. The clock matches `_clock_minutes`
in `power_monitor.py`: `24:00` is minute 1440, and a range is start-inclusive
and end-exclusive.
"""
from __future__ import annotations

from datetime import datetime, timedelta

STABLE = timedelta(minutes=15)
_DEFAULT_START = 18 * 60
_DEFAULT_END = 24 * 60


def desired_itp(now_kyiv: datetime, light: dict, boiler: dict) -> dict:
    """Return on, off, or hold, plus why, plus where the boiler window came from."""
    minute = now_kyiv.hour * 60 + now_kyiv.minute
    window_open, boiler_source = _window(boiler, minute)
    if window_open:
        return _answer("on", "boiler", boiler_source)
    kind = light.get("kind")
    if kind in ("up", "down") and _stable(now_kyiv, light.get("since")):
        if kind == "up":
            return _answer("on", "light-on", boiler_source)
        return _answer("off", "light-off", boiler_source)
    if kind == "unknown":
        return _answer("hold", "unknown", boiler_source)
    return _answer("hold", "settling", boiler_source)


def _answer(state: str, reason: str, boiler_source: str) -> dict:
    return {"state": state, "reason": reason, "boiler_source": boiler_source}


def _stable(now_kyiv: datetime, since: datetime | None) -> bool:
    if since is None:
        return False
    return now_kyiv - since >= STABLE


def _window(boiler: dict, minute: int) -> tuple[bool, str]:
    if boiler.get("kind") == "missing":
        if _DEFAULT_START <= minute < _DEFAULT_END:
            return True, "default"
        return False, "none"
    for pair in boiler.get("intervals") or []:
        start, end = _pair_minutes(pair)
        if start is None or end is None or end <= start:
            continue
        if start <= minute < end:
            return True, "row"
    return False, "none"


def _pair_minutes(pair) -> tuple[int | None, int | None]:
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        return None, None
    return _clock_minutes(pair[0]), _clock_minutes(pair[1])


def _clock_minutes(text) -> int | None:
    if not isinstance(text, str) or ":" not in text:
        return None
    hour_text, minute_text = text.split(":", 1)
    if not hour_text.isdigit() or not minute_text.isdigit():
        return None
    hour, minute = int(hour_text), int(minute_text)
    if hour == 24 and minute == 0:
        return 24 * 60
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour * 60 + minute
    return None
