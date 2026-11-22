"""Desired heat-breaker state, and the decision to read or command it.

No network and no breaker commands. The clock matches `_clock_minutes` in
`power_monitor.py`: `24:00` is minute 1440, and a range is start-inclusive and
end-exclusive. The document lock lives here so this file does not import the
Tuya client. A caller that already holds the breaker lock must release it
before `mutate_itp_auto`.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta
from html import escape

from config import STALE_THRESHOLD_SEC, UA_TZ, itp_commands_on, itp_slot

STABLE = timedelta(minutes=15)
_DEFAULT_START = 18 * 60
_DEFAULT_END = 24 * 60
FLAP_LIMIT = 4
FLAP_WINDOW_SEC = 3600
FOLLOWUP_SEC = 60
FOLLOWUP_WINDOW_SEC = 90
KEY = "itp_auto"

log = logging.getLogger("power_monitor")
_doc_lock = threading.Lock()
_last_decision_at: float | None = None


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


def empty_itp_auto() -> dict:
    return {
        "v": 1,
        "enabled": False,
        "applied": None,
        "pending": None,
        "pause": None,
        "command_times": [],
        "last": None,
        "warn": None,
        "timers_cleared_at": None,
        "timer_delete_attempted": False,
        "slot_spent": None,
    }


def flap_blocks(times, now: float) -> bool:
    return len(_fresh(times, now)) >= FLAP_LIMIT


def command_followup_due(sent_at: float | None, now: float) -> bool:
    """Same inclusive window as the one-shot timer follow-up."""
    if sent_at is None:
        return False
    age = now - sent_at
    return FOLLOWUP_SEC <= age <= FOLLOWUP_SEC + FOLLOWUP_WINDOW_SEC


def step_itp(doc: dict, desired: dict, actual: str, now: float, commands_on: bool, slot: str):
    """Return the next document and one of none, read, or post. Does not call Tuya."""
    doc = json.loads(json.dumps(doc))
    doc["last"] = {
        "state": desired.get("state"),
        "reason": desired.get("reason"),
        "boiler_source": desired.get("boiler_source"),
        "at": now,
    }
    if not doc.get("enabled"):
        return doc, "none"
    if desired.get("state") == "hold":
        return doc, "none"
    if not commands_on:
        return doc, "none"
    if doc.get("pending"):
        return doc, "none"
    _clear_rejected_warn(doc, actual)
    if actual in ("on", "off") and actual == desired.get("state"):
        doc["applied"] = actual
        return doc, "none"
    if _manual_disarm(doc, actual, now, commands_on):
        return doc, "none"
    if desired.get("state") == doc.get("applied"):
        return doc, "none"
    if doc.get("timers_cleared_at") is None:
        return doc, "none"
    if flap_blocks(doc.get("command_times"), now):
        _disarm_flap(doc, now)
        return doc, "none"
    if actual in ("on", "off"):
        return doc, _action_after_read(doc, desired, actual)
    if slot != "edge":
        return doc, "none"
    quarter = int(now // 900)
    if doc.get("slot_spent") == quarter:
        return doc, "none"
    doc["slot_spent"] = quarter
    return doc, "read"


def _action_after_read(doc: dict, desired: dict, actual: str) -> str:
    if actual == desired.get("state"):
        doc["applied"] = actual
        return "none"
    warn = doc.get("warn") or {}
    if warn.get("kind") == "rejected":
        return "none"
    if actual == doc.get("applied") and actual != desired.get("state"):
        return "post"
    return "none"


def apply_post_result(doc: dict, state: str, now: float, outcome: str, code=None) -> dict:
    """Record a fake or real POST result. Rejected commands do not count as flaps."""
    doc = json.loads(json.dumps(doc))
    if outcome == "success":
        doc["pending"] = {"state": state, "sent_at": now, "followup_done": False}
        _count_command(doc, now)
    elif outcome == "transport":
        doc["pending"] = {"state": state, "sent_at": now, "followup_done": False}
        doc["warn"] = {"at": now, "kind": "transport", "code": code}
        _count_command(doc, now)
    elif outcome == "rejected":
        doc["pending"] = None
        doc["warn"] = {"at": now, "kind": "rejected", "code": code}
    return doc


def arm_itp(doc: dict, applied: str | None) -> dict:
    doc = json.loads(json.dumps(doc))
    doc["enabled"] = True
    doc["pause"] = None
    doc["warn"] = None
    doc["timer_delete_attempted"] = False
    doc["applied"] = applied
    return doc


def disarm_itp(doc: dict) -> dict:
    doc = json.loads(json.dumps(doc))
    doc["enabled"] = False
    doc["pending"] = None
    return doc


def mutate_itp_auto(update) -> dict:
    """Read the kv document, let update change it, and write it back."""
    import database

    with _doc_lock:
        doc = _parse_doc(database.kv_get(KEY, ""))
        update(doc)
        database.kv_set(KEY, json.dumps(doc))
        return doc


def read_itp_auto() -> dict:
    import database

    return _parse_doc(database.kv_get(KEY, ""))


def reset_itp_tick_clock() -> None:
    global _last_decision_at
    _last_decision_at = None


def tick_itp_decision(now_kyiv: datetime, now_unix: float, commands_on: bool | None = None, slot: str | None = None) -> str:
    """Decide from local rows. Commands follow the env unless a caller passes them."""
    global _last_decision_at
    if commands_on is None:
        commands_on = itp_commands_on()
    if slot is None:
        slot = itp_slot()
    if _last_decision_at is not None and now_unix - _last_decision_at < 60:
        return "none"
    light, boiler = load_itp_context(now_kyiv, now_unix)
    desired = desired_itp(now_kyiv, light, boiler)
    outcome = {"action": "none", "changed": False}

    def update(doc):
        before = _signature(doc)
        new, action = step_itp(doc, desired, "unknown", now_unix, commands_on, slot)
        doc.clear()
        doc.update(new)
        outcome["action"] = action
        outcome["changed"] = before != _signature(doc)

    stored = mutate_itp_auto(update)
    _last_decision_at = now_unix
    if outcome["changed"]:
        log.info("itp-auto: %s", decision_log_text(stored, commands_on))
    return outcome["action"]


def load_itp_context(now_kyiv: datetime, now_unix: float) -> tuple[dict, dict]:
    """Light from up/down plus heartbeat age, and today's boiler row."""
    import database

    beats = database.recent_heartbeats(1)
    fresh = bool(beats) and now_unix - float(beats[0]["ts"]) <= STALE_THRESHOLD_SEC
    if not fresh:
        light = {"kind": "unknown"}
    else:
        event = _latest_light_event()
        if event is None:
            light = {"kind": "unknown"}
        else:
            light = {"kind": event["kind"], "since": datetime.fromtimestamp(event["ts"], UA_TZ)}
    day = now_kyiv.strftime("%Y-%m-%d")
    found = database.boiler_schedule_for_dates([day])
    if day not in found:
        boiler = {"kind": "missing"}
    else:
        boiler = {"kind": "intervals", "intervals": found[day] or []}
    return light, boiler


def decision_log_text(doc: dict, commands_on: bool = False) -> str:
    last = doc.get("last") or {}
    state = last.get("state") or "hold"
    reason = last.get("reason") or "unknown"
    if state == "hold":
        return f"hold {reason}"
    source = " boiler-default" if last.get("boiler_source") == "default" else ""
    tail = "" if commands_on else " commands-off"
    return f"would {state} {reason}{source}{tail}"


def itp_card_bits(doc: dict, commands_on: bool = False) -> dict:
    """Mode word for the meter row, plus the quieter note under it."""
    pause = doc.get("pause") or {}
    enabled = bool(doc.get("enabled"))
    if not enabled and pause.get("reason") == "manual" and pause.get("at"):
        note = f"О {_hhmm(pause['at'])} перемкнули вручну."
    elif not enabled and pause.get("reason") == "flap":
        note = "За годину вже 4 перемикання."
    elif enabled and not commands_on:
        note = _join("Команди ще вимкнені.", _would(doc))
    elif enabled and doc.get("pending"):
        note = "Команда ще не підтверджена."
    elif enabled:
        note = _why(doc)
    else:
        note = _would(doc)
    if doc.get("warn"):
        note = _join(note, "Хмара не підтвердила команду.")
    word = "автоматичне" if enabled else "ручне"
    line = f"Керування: {word}."
    if note:
        line = f"{line} {note}"
    return {"word": word, "on": enabled, "note": note, "line": line}


def format_itp_card(doc: dict, commands_on: bool = False) -> str:
    """Full sentence for the admin block."""
    return itp_card_bits(doc, commands_on)["line"]


def itp_admin_status(doc: dict | None = None) -> dict:
    """Fields the admin block and the arm route both show. The env flag is display-only."""
    if doc is None:
        doc = read_itp_auto()
    last = doc.get("last") or {}
    stamp = last.get("at")
    when = "—" if stamp is None else datetime.fromtimestamp(float(stamp), UA_TZ).strftime("%d.%m.%Y %H:%M")
    warn = doc.get("warn") or {}
    return {
        "enabled": bool(doc.get("enabled")),
        "line": format_itp_card(doc, commands_on=itp_commands_on()),
        "last_state": last.get("state") or "—",
        "last_reason": last.get("reason") or "—",
        "last_at": when,
        "warn_code": warn.get("code") if warn else None,
        "commands_on": os.getenv("ITP_AUTO_COMMANDS") == "1",
    }


def itp_meter_html() -> str:
    """One meter row: label on the left, manual in red or automatic in green."""
    try:
        bits = itp_card_bits(read_itp_auto(), commands_on=itp_commands_on())
    except Exception:
        log.info("itp-auto: card read failed")
        bits = {"word": "ручне", "on": False}
    kind = "on" if bits["on"] else "off"
    return f'<div><dt>Керування</dt><dd class="brk-mode-{kind}">{escape(bits["word"])}</dd></div>'


def itp_note_html() -> str:
    """Quieter sentence under the meters. Empty when there is nothing extra to say."""
    try:
        note = itp_card_bits(read_itp_auto(), commands_on=itp_commands_on())["note"]
    except Exception:
        log.info("itp-auto: card read failed")
        return ""
    if not note:
        return ""
    return f'<p class="brk-mode-note">{escape(note)}</p>'


def _parse_doc(raw) -> dict:
    try:
        doc = json.loads(raw) if raw else empty_itp_auto()
    except (TypeError, ValueError):
        log.info("itp-auto: stored document is not json")
        return empty_itp_auto()
    if not isinstance(doc, dict):
        return empty_itp_auto()
    return doc


def _latest_light_event():
    import database

    with database._conn() as db:
        row = db.execute(
            """SELECT event, ts FROM power_events
               WHERE event IN ('up', 'down')
               ORDER BY ts DESC, id DESC LIMIT 1"""
        ).fetchone()
    if row is None:
        return None
    return {"kind": row["event"], "ts": float(row["ts"])}


def _signature(doc: dict) -> tuple:
    last = doc.get("last") or {}
    pause = doc.get("pause") or {}
    warn = doc.get("warn") or {}
    return (
        bool(doc.get("enabled")),
        last.get("state"),
        last.get("reason"),
        last.get("boiler_source"),
        pause.get("reason"),
        warn.get("kind"),
    )


def _hhmm(stamp) -> str:
    return datetime.fromtimestamp(float(stamp), UA_TZ).strftime("%H:%M")


def _join(head: str, tail: str) -> str:
    return f"{head} {tail}".strip() if tail else head


def _would(doc: dict) -> str:
    last = doc.get("last") or {}
    state = last.get("state")
    reason = last.get("reason")
    if state == "on" and reason == "boiler":
        text = "За правилом зараз увімкнути: котельня."
    elif state == "on" and reason == "light-on":
        text = "За правилом зараз увімкнути: світло вже 15 хв."
    elif state == "off":
        text = "За правилом зараз вимкнути."
    elif state == "hold" and reason == "settling":
        text = "За правилом ще чекати."
    elif state == "hold" and reason == "unknown":
        text = "За правилом тримати: немає свіжого факту світла."
    else:
        text = ""
    if reason == "boiler" and last.get("boiler_source") == "default":
        text = f"{text} Графік котельні не приходив, вікно 18:00–24:00.".strip()
    return text


def _why(doc: dict) -> str:
    reason = (doc.get("last") or {}).get("reason")
    if reason == "boiler":
        return "Котельня."
    if reason in ("light-on", "light-off"):
        return "Світло."
    return ""


def _fresh(times, now: float) -> list:
    return [stamp for stamp in (times or []) if now - float(stamp) <= FLAP_WINDOW_SEC]


def _count_command(doc: dict, now: float) -> None:
    doc["command_times"] = _fresh(doc.get("command_times"), now) + [now]
    if flap_blocks(doc["command_times"], now):
        _disarm_flap(doc, now)


def _disarm_flap(doc: dict, now: float) -> None:
    doc["enabled"] = False
    doc["pause"] = {"at": now, "reason": "flap", "was": doc.get("applied"), "now": doc.get("applied")}
    log.info("itp-auto: flap stop, 4 commands in 60 minutes")


def _clear_rejected_warn(doc: dict, actual: str) -> bool:
    warn = doc.get("warn") or {}
    if warn.get("kind") == "rejected" and actual == doc.get("applied"):
        doc["warn"] = None
        return True
    return False


def _manual_disarm(doc: dict, actual: str, now: float, commands_on: bool) -> bool:
    warn = doc.get("warn")
    if not (
        commands_on
        and doc.get("timers_cleared_at") is not None
        and actual in ("on", "off")
        and doc.get("applied") in ("on", "off")
        and actual != doc.get("applied")
        and not doc.get("pending")
        and not warn
    ):
        return False
    doc["enabled"] = False
    doc["pause"] = {"at": now, "reason": "manual", "was": doc.get("applied"), "now": actual}
    return True


_SWITCH_ON = {
    "boiler": "Обігрів увімкнено автоматично, котельня",
    "light-on": "Обігрів увімкнено автоматично, світло вже 15 хв",
    "admin": "Обігрів увімкнено автоматично",
}
_SWITCH_OFF = {
    "light-off": "Обігрів вимкнено автоматично, світла немає 15 хв",
    "admin": "Обігрів вимкнено автоматично",
}
_MODE_LINE = {
    ("mode-auto", "admin"): "Керування стало автоматичним",
    ("mode-manual", "admin"): "Керування стало ручним",
    ("mode-manual", "hand"): "Керування стало ручним, перемкнули руками",
    ("mode-manual", "flap"): "Керування стало ручним, за годину вже 4 перемикання",
}


def itp_journal_line(kind: str, reason: str, confirmed: int = 1) -> str:
    """Ukrainian sentence for one stored journal row. Does not raise."""
    if kind == "switch-on":
        text = _SWITCH_ON.get(reason, _SWITCH_ON["admin"])
    elif kind == "switch-off":
        text = _SWITCH_OFF.get(reason, _SWITCH_OFF["admin"])
    elif kind == "mode-auto":
        text = _MODE_LINE.get((kind, reason), _MODE_LINE[("mode-auto", "admin")])
    elif kind == "mode-manual":
        text = _MODE_LINE.get((kind, reason), _MODE_LINE[("mode-manual", "admin")])
    else:
        text = ""
    if kind in ("switch-on", "switch-off") and not confirmed:
        text += " ще не підтверджено"
    return text


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
