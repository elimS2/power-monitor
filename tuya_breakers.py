"""Decode a Tuya breaker status payload and store one day row.

The poller in this file reads status. It does not send switch commands.
The page does not call Tuya.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

import database
from config import UA_TZ
from schedule_board import kyiv_date_str, kyiv_day_bounds, shift_date

log = logging.getLogger("power_monitor.breakers")
TUYA_HOST = "https://openapi.tuyaeu.com"
_DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9]+$")

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
            loaded = 1 if breaker_shown_on(switch, phases) else 0
            _apply_sample_to_day(
                db, device, day, ts, loaded, energy_raw, phases, fault,
            )
            if energy_raw is not None:
                update_since_charge(db, device, ts, energy_raw / 100, loaded)


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


# Grid must be back for longer than this before the battery draw goes back to zero.
GRID_UP_RESET_SEC = 15 * 60


def _grid_events(db) -> list[dict]:
    return [
        {"event": row["event"], "ts": float(row["ts"])}
        for row in db.execute(
            "SELECT event, ts FROM power_events WHERE event IN ('up', 'down') ORDER BY ts, id"
        )
    ]


def _grid_state_at(events: list[dict], ts: float) -> str | None:
    state = None
    for event in events:
        if event["ts"] > ts:
            break
        state = event["event"]
    return state


def _dark_seconds(events: list[dict], start: float, end: float) -> float:
    if end <= start:
        return 0.0
    cuts = [start]
    for event in events:
        if start < event["ts"] < end:
            cuts.append(event["ts"])
    cuts.append(end)
    dark = 0.0
    for left, right in zip(cuts, cuts[1:]):
        if _grid_state_at(events, left) == "down":
            dark += right - left
    return dark


def _up_since(events: list[dict], ts: float) -> float | None:
    if _grid_state_at(events, ts) != "up":
        return None
    started = None
    for event in events:
        if event["ts"] > ts:
            break
        started = event["ts"] if event["event"] == "up" else None
    return started


def _phase_watts(point) -> float | None:
    if isinstance(point, tuple) and len(point) >= 3 and point[2] is not None:
        return float(point[2])
    if isinstance(point, dict) and point.get("p") is not None:
        return float(point["p"])
    return None


def breaker_shown_on(switch, phases) -> bool:
    """Watts decide when a phase reports them. Any watt is on, exact zero is off. No watts, trust the bit."""
    if isinstance(phases, dict):
        watts = []
        for name in ("a", "b", "c"):
            value = _phase_watts(phases.get(name))
            if value is not None:
                watts.append(value)
        if watts:
            return sum(watts) != 0
    return bool(switch)


def _step_since_charge(
    acc: float,
    acc_sec: float,
    last_energy: float | None,
    last_ts: float | None,
    last_switch: int | None,
    ts: float,
    energy: float,
    switch: int,
    events: list[dict],
) -> tuple[float, float, float, float, int]:
    """Count the gap only when this breaker was on. The new switch applies from ts."""
    if last_ts is not None and ts > last_ts and last_switch == 1:
        dark = _dark_seconds(events, last_ts, ts)
        acc_sec += dark
        if last_energy is not None and energy >= last_energy and dark > 0:
            span = ts - last_ts
            if span > 0:
                acc += (energy - last_energy) * (dark / span)
    up_since = _up_since(events, ts)
    if up_since is not None and ts - up_since > GRID_UP_RESET_SEC:
        acc = 0.0
        acc_sec = 0.0
    return acc, acc_sec, energy, ts, switch


def update_since_charge(db, device: str, ts: float, energy_kwh: float, switch: int) -> None:
    """Add energy and time only while this breaker is on and the grid is down."""
    events = _grid_events(db)
    row = db.execute(
        """SELECT accumulated_kwh, accumulated_sec, last_energy_kwh, last_switch, last_ts
           FROM breaker_since_charge WHERE device=?""",
        (device,),
    ).fetchone()
    needs_replay = (
        row is None
        or row["last_ts"] is None
        or row["accumulated_sec"] is None
        or row["last_switch"] is None
    )
    if needs_replay:
        samples = [
            (
                float(item["ts"]),
                float(item["energy_kwh"]),
                1 if breaker_shown_on(item["switch"], {
                    "a": {"p": item["p_a"]},
                    "b": {"p": item["p_b"]},
                    "c": {"p": item["p_c"]},
                }) else 0,
            )
            for item in db.execute(
                """SELECT ts, energy_kwh, switch, p_a, p_b, p_c FROM breaker_sample
                   WHERE device=? AND energy_kwh IS NOT NULL ORDER BY ts""",
                (device,),
            )
        ]
        acc, acc_sec, last_energy, last_ts, last_switch = 0.0, 0.0, None, None, None
        for sample_ts, sample_energy, sample_switch in samples:
            acc, acc_sec, last_energy, last_ts, last_switch = _step_since_charge(
                acc, acc_sec, last_energy, last_ts, last_switch,
                sample_ts, sample_energy, sample_switch, events,
            )
    elif ts <= float(row["last_ts"]):
        return
    else:
        acc, acc_sec, last_energy, last_ts, last_switch = _step_since_charge(
            float(row["accumulated_kwh"]),
            float(row["accumulated_sec"] or 0),
            None if row["last_energy_kwh"] is None else float(row["last_energy_kwh"]),
            float(row["last_ts"]),
            None if row["last_switch"] is None else int(row["last_switch"]),
            ts,
            energy_kwh,
            int(switch),
            events,
        )
    db.execute(
        """
        INSERT INTO breaker_since_charge(
            device, accumulated_kwh, accumulated_sec, last_energy_kwh, last_switch, last_ts
        ) VALUES(?,?,?,?,?,?)
        ON CONFLICT(device) DO UPDATE SET
            accumulated_kwh=excluded.accumulated_kwh,
            accumulated_sec=excluded.accumulated_sec,
            last_energy_kwh=excluded.last_energy_kwh,
            last_switch=excluded.last_switch,
            last_ts=excluded.last_ts
        """,
        (device, acc, acc_sec, last_energy, last_switch, last_ts),
    )


def since_charge_display(db, now: float) -> dict[str, tuple[float, float]]:
    """kWh and dark seconds, including the open outage up to now. Zero after 15 minutes of grid."""
    rows = db.execute(
        """SELECT device, accumulated_kwh, accumulated_sec, last_switch, last_ts
           FROM breaker_since_charge"""
    ).fetchall()
    events = _grid_events(db)
    up_since = _up_since(events, now)
    reset = up_since is not None and now - up_since > GRID_UP_RESET_SEC
    shown = {}
    for row in rows:
        if reset:
            shown[row["device"]] = (0.0, 0.0)
            continue
        seconds = float(row["accumulated_sec"] or 0)
        last_ts = row["last_ts"]
        if row["last_switch"] == 1 and last_ts is not None and now > float(last_ts):
            seconds += _dark_seconds(events, float(last_ts), now)
        shown[row["device"]] = (float(row["accumulated_kwh"] or 0), seconds)
    return shown


def backfill_breaker_since_charge() -> None:
    """Fill the battery-draw row from samples already stored. Skips a device that has one."""
    with database._conn() as db:
        for device in ("svitlo", "itp"):
            exists = db.execute(
                "SELECT accumulated_sec, last_switch FROM breaker_since_charge WHERE device=?",
                (device,),
            ).fetchone()
            rule = db.execute(
                "SELECT val FROM kv WHERE key=?",
                ("breaker_since_charge_rule",),
            ).fetchone()
            if rule is None or rule["val"] != "exact-zero":
                db.execute("DELETE FROM breaker_since_charge")
                db.execute(
                    """INSERT INTO kv(key, val) VALUES(?, ?)
                       ON CONFLICT(key) DO UPDATE SET val=excluded.val""",
                    ("breaker_since_charge_rule", "exact-zero"),
                )
                exists = None
            if exists is not None and exists["accumulated_sec"] is not None and exists["last_switch"] is not None:
                continue
            if exists is not None:
                db.execute("DELETE FROM breaker_since_charge WHERE device=?", (device,))
            last = db.execute(
                """SELECT ts, energy_kwh, switch FROM breaker_sample
                   WHERE device=? AND energy_kwh IS NOT NULL ORDER BY ts DESC LIMIT 1""",
                (device,),
            ).fetchone()
            if last is None:
                continue
            update_since_charge(
                db, device, float(last["ts"]), float(last["energy_kwh"]), int(last["switch"]),
            )


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


def ingest_status_message(message: dict, id_to_name: dict[str, str]) -> bool:
    """Apply one decrypted device report. Unknown devices are ignored.

    The live listener is not started. On 2026-11-09 the project screen offered
    only a Pulsar queue, and that queue was left off.
    """
    if not isinstance(message, dict):
        return False
    biz = message.get("bizData") if isinstance(message.get("bizData"), dict) else {}
    device_id = message.get("devId") or biz.get("devId")
    name = id_to_name.get(device_id) if isinstance(device_id, str) else None
    if not name:
        return False
    message_id = message.get("dataId") or biz.get("dataId")
    if not isinstance(message_id, str) or not message_id:
        return False
    status = message.get("status")
    if not isinstance(status, list):
        status = biz.get("properties") if isinstance(biz.get("properties"), list) else biz.get("status")
    if not isinstance(status, list):
        return False
    ts_ms = _status_time_ms(status)
    if ts_ms is None:
        return False
    payload = {
        "success": True,
        "result": [
            {"code": item["code"], "value": item.get("value")}
            for item in status
            if isinstance(item, dict) and isinstance(item.get("code"), str)
        ],
    }
    if not payload["result"]:
        return False
    apply_breaker_status(name, ts_ms / 1000, payload, "message", message_id=message_id)
    return True


def _status_time_ms(status: list) -> int | None:
    for item in status:
        if not isinstance(item, dict):
            continue
        stamp = item.get("t", item.get("time"))
        if isinstance(stamp, int) and not isinstance(stamp, bool):
            return stamp
    return None


# ─── Cloud poll (no commands) ───────────────────────────────────


@dataclass(frozen=True)
class BreakerPollConfig:
    access_id: str
    access_secret: str
    devices: tuple[tuple[str, str], ...]
    host: str = TUYA_HOST


class TokenCache:
    def __init__(self) -> None:
        self.token = ""
        self.refresh_at = 0.0


class TuyaCallError(Exception):
    def __init__(self, code: object) -> None:
        self.code = code
        super().__init__(str(code))


def breaker_config_from_env(access_id: str, secret: str, svitlo: str, itp: str) -> BreakerPollConfig:
    devices: list[tuple[str, str]] = []
    if svitlo:
        devices.append(("svitlo", svitlo))
    if itp:
        devices.append(("itp", itp))
    return BreakerPollConfig(access_id.strip(), secret.strip(), tuple(devices))


def poll_is_enabled(cfg: BreakerPollConfig) -> bool:
    return bool(cfg.access_id and cfg.access_secret and cfg.devices)


# The loop wakes about every 30s. A mark is still taken if the wake is this late.
BREAKER_SLOT_GRACE_SEC = 90


def breaker_slot_start(now: float, interval_sec: int, tz=UA_TZ) -> float:
    """Kyiv midnight, then the interval mark that contains now. 900s is :00 :15 :30 :45."""
    if interval_sec <= 0:
        raise ValueError("interval")
    local = datetime.fromtimestamp(now, tz)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = (local - midnight).total_seconds()
    index = int(elapsed // interval_sec)
    return midnight.timestamp() + index * interval_sec


def breaker_clock_due(
    now: float,
    last_slot: float | None,
    interval_sec: int,
    tz=UA_TZ,
    grace_sec: float = BREAKER_SLOT_GRACE_SEC,
) -> bool:
    """True once, near a clock mark. A restart in the middle of a slot waits for the next mark."""
    slot = breaker_slot_start(now, interval_sec, tz)
    if last_slot is not None and abs(last_slot - slot) < 0.5:
        return False
    return (now - slot) <= grace_sec


def breaker_http_timeout() -> float:
    return 10.0


def sign_headers(
    access_id: str,
    secret: str,
    method: str,
    path: str,
    token: str,
    now_ms: str,
    body: bytes = b"",
) -> dict[str, str]:
    """The string that opened the EU status route on 2026-11-09."""
    content = hashlib.sha256(body).hexdigest()
    string_to_sign = f"{method}\n{content}\n\n{path}"
    message = f"{access_id}{token}{now_ms}{string_to_sign}"
    # Tuya returns sign invalid (1004) unless this hex is uppercase.
    # The body hash inside string_to_sign stays lowercase.
    sign = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest().upper()
    headers = {
        "client_id": access_id,
        "sign": sign,
        "t": now_ms,
        "sign_method": "HMAC-SHA256",
    }
    if token:
        headers["access_token"] = token
    return headers


def carry_configured_breakers(ts: float, devices: tuple[tuple[str, str], ...]) -> None:
    """Close yesterday and open today. No HTTP and no new sample."""
    for name, _device_id in devices:
        apply_breaker_status(name, ts, None, "poll")


def _public_error(exc: Exception) -> str:
    if isinstance(exc, TuyaCallError):
        return str(exc.code)
    return exc.__class__.__name__


async def run_deye_then_breakers(deye_step, breaker_step) -> None:
    """Deye first. A breaker error must not cancel the rest of the tick."""
    await deye_step()
    try:
        await breaker_step()
    except Exception as exc:
        log.error("breaker poll: %s", _public_error(exc))


async def poll_breakers_http(cfg: BreakerPollConfig, cache: TokenCache, now: float, client_cls=None) -> None:
    if client_cls is None:
        client_cls = httpx.AsyncClient
    async with client_cls(timeout=breaker_http_timeout()) as client:
        await poll_breakers(client, cfg, cache, now)


def timer_rows(payload: dict) -> list[dict]:
    """Cloud timer list. Items without a timer id are ignored."""
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, list):
        return []
    return [_timer_row(item) for item in result if isinstance(item, dict) and item.get("timer_id")]


def _timer_row(item: dict) -> dict:
    functions = item.get("functions") if isinstance(item.get("functions"), list) else []
    switch = None
    for fn in functions:
        if isinstance(fn, dict) and fn.get("code") == "switch":
            switch = 1 if fn.get("value") else 0
    enable = item.get("enable", True)
    return {
        "timer_id": str(item["timer_id"]),
        "fire_date": str(item.get("date") or ""),
        "fire_time": str(item.get("time") or ""),
        "loops": str(item.get("loops") or ""),
        "timezone_id": str(item.get("timezone_id") or ""),
        "switch": switch,
        "enable": 1 if enable else 0,
    }


# The loop wakes about every 30s. One extra read lands once in this window after a timer.
BREAKER_TIMER_FOLLOWUP_SEC = 60
BREAKER_TIMER_FOLLOWUP_WINDOW_SEC = 90


def _timer_fire_ts(row: dict) -> float | None:
    """Clock time of a one-shot. A weekly loop has no single instant."""
    if "1" in str(row.get("loops") or ""):
        return None
    fire_date = str(row.get("fire_date") or "")
    fire_time = str(row.get("fire_time") or "")
    if len(fire_date) != 8 or len(fire_time) != 5:
        return None
    local = datetime.strptime(fire_date + fire_time, "%Y%m%d%H:%M").replace(tzinfo=UA_TZ)
    return local.timestamp()


def breaker_timer_followup_due(row: dict, now: float) -> bool:
    """True about a minute after the timer, while one loop wake can still catch it."""
    fire = _timer_fire_ts(row)
    if fire is None:
        return False
    age = now - fire
    return BREAKER_TIMER_FOLLOWUP_SEC <= age <= BREAKER_TIMER_FOLLOWUP_SEC + BREAKER_TIMER_FOLLOWUP_WINDOW_SEC


def breaker_timer_is_active(row: dict, now: float) -> bool:
    """A one-shot stays visible until its minute has passed. A weekly loop stays while enabled."""
    if not row.get("enable"):
        return False
    loops = str(row.get("loops") or "")
    if "1" in loops:
        return True
    fire_date = str(row.get("fire_date") or "")
    fire_time = str(row.get("fire_time") or "")
    if len(fire_date) != 8 or len(fire_time) != 5:
        return False
    local = datetime.strptime(fire_date + fire_time, "%Y%m%d%H:%M").replace(tzinfo=UA_TZ)
    return local.timestamp() + 60 > now


def active_breaker_timers(now: float) -> list[dict]:
    return [row for row in database.list_breaker_timers() if breaker_timer_is_active(row, now)]


async def poll_breakers(client, cfg: BreakerPollConfig, cache: TokenCache, now: float) -> None:
    token = await _ensure_token(client, cfg, cache, now)
    for name, device_id in cfg.devices:
        try:
            payload = await _device_status(client, cfg, token, device_id, now)
        except TuyaCallError as exc:
            log.warning("breaker %s code %s", name, exc.code)
            continue
        apply_breaker_status(name, now, payload, "poll")
    await sync_breaker_timers(client, cfg, cache, now)


async def sync_breaker_timers_http(cfg: BreakerPollConfig, cache: TokenCache, now: float, client_cls=None) -> None:
    if client_cls is None:
        client_cls = httpx.AsyncClient
    async with client_cls(timeout=breaker_http_timeout()) as client:
        await sync_breaker_timers(client, cfg, cache, now)


async def sync_breaker_timers(client, cfg: BreakerPollConfig, cache: TokenCache, now: float) -> None:
    token = await _ensure_token(client, cfg, cache, now)
    for name, device_id in cfg.devices:
        try:
            payload = await _device_timers(client, cfg, token, device_id, now)
        except TuyaCallError as exc:
            log.warning("breaker timers %s code %s", name, exc.code)
            continue
        database.replace_breaker_timers(name, timer_rows(payload), now)


async def _device_timers(client, cfg: BreakerPollConfig, token: str, device_id: str, now: float) -> dict:
    if not _DEVICE_ID_RE.fullmatch(device_id):
        raise TuyaCallError("bad-id")
    path = f"/v2.0/cloud/timer/device/{device_id}"
    headers = sign_headers(
        cfg.access_id, cfg.access_secret, "GET", path, token, str(int(now * 1000)),
    )
    return await _get_json(client, cfg.host + path, headers)


async def _ensure_token(client, cfg: BreakerPollConfig, cache: TokenCache, now: float) -> str:
    if cache.token and now < cache.refresh_at:
        return cache.token
    path = "/v1.0/token?grant_type=1"
    headers = sign_headers(
        cfg.access_id, cfg.access_secret, "GET", path, "", str(int(now * 1000)),
    )
    body = await _get_json(client, cfg.host + path, headers)
    result = body.get("result") if isinstance(body, dict) else None
    token = result.get("access_token") if isinstance(result, dict) else ""
    if not token:
        raise TuyaCallError("no-token")
    try:
        expire = int(result.get("expire_time") or 0)
    except (TypeError, ValueError):
        expire = 0
    cache.token = token
    cache.refresh_at = now + max(0, expire - 60)
    return token


async def _device_status(client, cfg: BreakerPollConfig, token: str, device_id: str, now: float) -> dict:
    if not _DEVICE_ID_RE.fullmatch(device_id):
        raise TuyaCallError("bad-id")
    path = f"/v1.0/devices/{device_id}/status"
    headers = sign_headers(
        cfg.access_id, cfg.access_secret, "GET", path, token, str(int(now * 1000)),
    )
    return await _get_json(client, cfg.host + path, headers)


async def _get_json(client, url: str, headers: dict[str, str]) -> dict:
    try:
        response = await client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        raise TuyaCallError("timeout") from exc
    except httpx.HTTPError as exc:
        raise TuyaCallError("http") from exc
    if response.status_code != 200:
        raise TuyaCallError(response.status_code)
    try:
        body = response.json()
    except Exception as exc:
        raise TuyaCallError("bad-json") from exc
    if not isinstance(body, dict) or not body.get("success"):
        code = body.get("code") if isinstance(body, dict) else "error"
        raise TuyaCallError(code)
    return body
