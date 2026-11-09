"""Decode a Tuya breaker status payload and store one day row.

No HTTP here. The poller and the message listener call this function.
The page does not.
"""
from __future__ import annotations

import base64
import json
import threading
from typing import Any

import database
from schedule_board import kyiv_date_str, kyiv_day_bounds, shift_date

_breaker_lock = threading.Lock()
_DEVICES = frozenset({"svitlo", "itp"})
_SOURCES = frozenset({"poll", "message"})


def apply_breaker_status(
    device: str,
    ts: float,
    payload: dict | None,
    source: str,
    message_id: str | None = None,
) -> None:
    """One lock, one transaction. A missing payload is the midnight carry."""
    if device not in _DEVICES:
        raise ValueError(f"unknown breaker {device}")
    if source not in _SOURCES:
        raise ValueError(f"unknown source {source}")
    if source == "poll":
        message_id = None
    elif not message_id:
        raise ValueError("message id required")

    with _breaker_lock:
        with database._conn() as db:
            if message_id is not None and _message_stops(db, device, ts, message_id):
                return
            day = kyiv_date_str(ts)
            _close_latest_open_before(db, device, day)
            if payload is None:
                _carry_day(db, device, day, ts)
                return
            fields = _status_fields(payload)
            switch = _switch_bit(fields.get("switch"))
            energy_raw = _energy_raw(fields.get("total_forward_energy"))
            phases = {
                "a": decode_phase(fields.get("phase_a")),
                "b": decode_phase(fields.get("phase_b")),
                "c": decode_phase(fields.get("phase_c")),
            }
            fault = _fault(fields.get("fault"))
            _insert_sample(
                db, device, ts, source, switch, energy_raw, phases, fault,
            )
            _apply_sample_to_day(
                db, device, day, ts, switch, energy_raw, phases, fault,
            )


def decode_phase(value: Any) -> tuple[float, float, int] | None:
    """8 or 10 byte blob. Anything else leaves the phase empty."""
    if not isinstance(value, str) or not value:
        return None
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        return None
    if len(raw) not in (8, 10):
        return None
    volts = int.from_bytes(raw[0:2], "big") / 10
    amps = int.from_bytes(raw[2:5], "big") / 1000
    watts = int.from_bytes(raw[5:8], "big")
    return volts, amps, watts


def _message_stops(db, device: str, ts: float, message_id: str) -> bool:
    """True when this message must not change the day row."""
    known = db.execute(
        "SELECT 1 FROM breaker_message WHERE message_id=?",
        (message_id,),
    ).fetchone()
    if known:
        return True
    latest = db.execute(
        "SELECT ts FROM breaker_sample WHERE device=? ORDER BY ts DESC LIMIT 1",
        (device,),
    ).fetchone()
    if latest is not None and ts < latest["ts"]:
        db.execute(
            "INSERT INTO breaker_message(message_id, device, ts) VALUES(?,?,?)",
            (message_id, device, ts),
        )
        return True
    db.execute(
        "INSERT INTO breaker_message(message_id, device, ts) VALUES(?,?,?)",
        (message_id, device, ts),
    )
    return False


def _carry_day(db, device: str, day: str, ts: float) -> None:
    yesterday = shift_date(day, -1)
    prev = _day_row(db, device, yesterday)
    if prev is None:
        return
    current = _day_row(db, device, day)
    if current is not None and _spans(current["span_json"]):
        return
    midnight = kyiv_day_bounds(day)[0]
    spans = [{"start": midnight, "end": None, "switch": prev["switch"]}]
    _write_day(
        db,
        device,
        day,
        prev["energy_kwh"],
        prev["energy_kwh"],
        0.0,
        prev["switch"],
        spans,
        prev["phase_json"],
        ts,
    )


def _apply_sample_to_day(
    db,
    device: str,
    day: str,
    ts: float,
    switch: int,
    energy_raw: int | None,
    phases: dict[str, tuple[float, float, int] | None],
    fault: int,
) -> None:
    current = _day_row(db, device, day)
    yesterday = _day_row(db, device, shift_date(day, -1))
    if current is not None and current["energy_base_kwh"] is not None:
        base = current["energy_base_kwh"]
    elif yesterday is not None and yesterday["energy_kwh"] is not None:
        base = yesterday["energy_kwh"]
    else:
        base = None
    if energy_raw is None:
        energy = current["energy_kwh"] if current is not None else None
    else:
        energy = energy_raw / 100
    today = None if base is None or energy is None else energy - base
    spans = _spans(current["span_json"]) if current is not None else []
    _update_spans(spans, ts, switch)
    phase_json = json.dumps(
        {
            "a": _phase_point(phases["a"]),
            "b": _phase_point(phases["b"]),
            "c": _phase_point(phases["c"]),
            "fault": fault,
        },
        separators=(",", ":"),
    )
    _write_day(db, device, day, base, energy, today, switch, spans, phase_json, ts)


def _update_spans(spans: list[dict], ts: float, switch: int) -> None:
    open_span = next((span for span in spans if span.get("end") is None), None)
    if open_span is None:
        spans.append({"start": ts, "end": None, "switch": switch})
        return
    if open_span["switch"] == switch:
        return
    open_span["end"] = ts
    spans.append({"start": ts, "end": None, "switch": switch})


def _close_latest_open_before(db, device: str, day: str) -> None:
    row = db.execute(
        """
        SELECT day, span_json FROM breaker_day
        WHERE device=? AND day < ?
        ORDER BY day DESC LIMIT 1
        """,
        (device, day),
    ).fetchone()
    if row is None:
        return
    spans = _spans(row["span_json"])
    open_span = next((span for span in spans if span.get("end") is None), None)
    if open_span is None:
        return
    open_span["end"] = kyiv_day_bounds(row["day"])[1]
    db.execute(
        "UPDATE breaker_day SET span_json=? WHERE device=? AND day=?",
        (_dump_spans(spans), device, row["day"]),
    )


def _insert_sample(
    db,
    device: str,
    ts: float,
    source: str,
    switch: int,
    energy_raw: int | None,
    phases: dict[str, tuple[float, float, int] | None],
    fault: int,
) -> None:
    points = {name: _phase_point(phases[name]) for name in ("a", "b", "c")}
    energy = None if energy_raw is None else energy_raw / 100
    db.execute(
        """
        INSERT INTO breaker_sample(
            ts, device, switch, energy_raw, energy_kwh,
            v_a, i_a, p_a, v_b, i_b, p_b, v_c, i_c, p_c,
            fault, source
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            ts, device, switch, energy_raw, energy,
            points["a"]["v"], points["a"]["i"], points["a"]["p"],
            points["b"]["v"], points["b"]["i"], points["b"]["p"],
            points["c"]["v"], points["c"]["i"], points["c"]["p"],
            fault, source,
        ),
    )


def _write_day(
    db,
    device: str,
    day: str,
    base: float | None,
    energy: float | None,
    today: float | None,
    switch: int | None,
    spans: list[dict],
    phase_json: str | None,
    updated_at: float,
) -> None:
    db.execute(
        """
        INSERT INTO breaker_day(
            device, day, energy_base_kwh, energy_kwh, energy_today_kwh,
            switch, span_json, phase_json, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(device, day) DO UPDATE SET
            energy_base_kwh=excluded.energy_base_kwh,
            energy_kwh=excluded.energy_kwh,
            energy_today_kwh=excluded.energy_today_kwh,
            switch=excluded.switch,
            span_json=excluded.span_json,
            phase_json=excluded.phase_json,
            updated_at=excluded.updated_at
        """,
        (
            device, day, base, energy, today, switch,
            _dump_spans(spans), phase_json, updated_at,
        ),
    )


def _day_row(db, device: str, day: str):
    return db.execute(
        "SELECT * FROM breaker_day WHERE device=? AND day=?",
        (device, day),
    ).fetchone()


def _spans(raw: str | None) -> list[dict]:
    if not raw:
        return []
    loaded = json.loads(raw)
    return loaded if isinstance(loaded, list) else []


def _dump_spans(spans: list[dict]) -> str:
    return json.dumps(spans, separators=(",", ":"))


def _phase_point(point: tuple[float, float, int] | None) -> dict:
    if point is None:
        return {"v": None, "i": None, "p": None}
    volts, amps, watts = point
    return {"v": volts, "i": amps, "p": watts}


def _status_fields(payload: dict) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("status payload")
    result = payload.get("result")
    if not isinstance(result, list):
        raise ValueError("status result")
    fields: dict[str, Any] = {}
    for item in result:
        if isinstance(item, dict) and isinstance(item.get("code"), str):
            fields[item["code"]] = item.get("value")
    return fields


def _switch_bit(value: Any) -> int:
    if value is True:
        return 1
    if value is False:
        return 0
    raise ValueError("switch")


def _energy_raw(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("total_forward_energy")
    return value


def _fault(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("fault")
    return value
