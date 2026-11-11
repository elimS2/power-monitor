"""Keep the lighting breaker's one-shot timers five minutes after today's outage edges.

Heat timers are never read for changes and never deleted. A matching list logs
one line. Each removal and each new timer logs its own line.

Paused on 11.11.2026 until the on-delay rules are ready. While paused, a schedule
fetch logs one line and does not read or change timers.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

import httpx

import database
from config import DTEK_QUEUE, TUYA_ACCESS_ID, TUYA_ACCESS_SECRET, TUYA_BREAKER_SVITLO, UA_TZ
from tuya_breakers import (
    TokenCache,
    TuyaCallError,
    _device_timers,
    _ensure_token,
    sign_headers,
    sync_breaker_timers,
    timer_rows,
)
from tuya_breakers import BreakerPollConfig

log = logging.getLogger("power_monitor")

LIGHT_LAG = timedelta(minutes=5)
LIGHT_SCHEDULE_PAUSED = True


def _dark(status: str) -> bool:
    return status != "ok"


def light_edges(grid: list[str], yesterday_last: str | None) -> list[tuple[int, int]]:
    """Schedule minutes where light appears (1) or disappears (0)."""
    if len(grid) != 48:
        return []
    edges: list[tuple[int, int]] = []
    if yesterday_last is not None and _dark(yesterday_last) != _dark(grid[0]):
        edges.append((0, 0 if _dark(grid[0]) else 1))
    for index in range(1, 48):
        if _dark(grid[index - 1]) == _dark(grid[index]):
            continue
        edges.append((index * 30, 0 if _dark(grid[index]) else 1))
    return edges


def desired_light_timers(
    grid: list[str],
    day: str,
    now: datetime,
    yesterday_last: str | None,
) -> list[dict]:
    """Future one-shots. Each edge is followed five minutes later."""
    start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UA_TZ)
    wanted = []
    for minute, switch in light_edges(grid, yesterday_last):
        fire = start + timedelta(minutes=minute) + LIGHT_LAG
        if fire <= now:
            continue
        wanted.append({
            "fire_date": fire.strftime("%Y%m%d"),
            "fire_time": fire.strftime("%H:%M"),
            "switch": switch,
        })
    return wanted


def _key(row: dict) -> tuple[str, str, int]:
    return (str(row.get("fire_date") or ""), str(row.get("fire_time") or ""), int(row.get("switch")))


def plan_light_changes(desired: list[dict], current: list[dict]) -> tuple[list[dict], list[dict]]:
    """Timers to delete, then timers to create. Heat rows must not be passed in."""
    wanted = {_key(row): row for row in desired}
    seen: set[tuple[str, str, int]] = set()
    deletes = []
    for row in current:
        key = _key(row)
        if key in seen or key not in wanted:
            deletes.append(row)
            continue
        seen.add(key)
    creates = [wanted[key] for key in wanted if key not in seen]
    deletes.sort(key=_key)
    creates.sort(key=_key)
    return deletes, creates


def _verb(switch: int) -> str:
    return "on" if switch else "off"


def _when(row: dict) -> str:
    raw = str(row.get("fire_date") or "")
    clock = str(row.get("fire_time") or "")
    if len(raw) == 8:
        raw = f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
    return f"{raw} {clock}".strip()


def light_change_lines(deletes: list[dict], creates: list[dict]) -> list[str]:
    if not deletes and not creates:
        return ["already matches, nothing to change"]
    lines = [f"removed {_verb(int(row['switch']))} {_when(row)}" for row in deletes]
    lines.extend(f"added {_verb(int(row['switch']))} {_when(row)}" for row in creates)
    return lines


def _grid_row(day: str) -> tuple[list[str] | None, bool]:
    with database._conn() as db:
        row = db.execute(
            """SELECT grid_json, emergency FROM schedule_history
               WHERE target_date=? AND queue=? ORDER BY id DESC LIMIT 1""",
            (day, DTEK_QUEUE),
        ).fetchone()
    if row is None:
        return None, False
    try:
        parsed = json.loads(row["grid_json"])
    except (TypeError, ValueError):
        parsed = None
    grid = parsed if isinstance(parsed, list) and len(parsed) == 48 else None
    return grid, bool(row["emergency"])


def _yesterday_last(day: str) -> str | None:
    yesterday = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    grid, _emergency = _grid_row(yesterday)
    if not grid:
        return None
    return str(grid[-1])


def _future_light_timers(rows: list[dict], today_compact: str, now: datetime) -> list[dict]:
    kept = []
    for row in rows:
        if "1" in str(row.get("loops") or ""):
            continue
        if int(row.get("enable") or 0) != 1 or row.get("switch") not in (0, 1):
            continue
        if str(row.get("fire_date") or "") != today_compact:
            continue
        fire_date = str(row["fire_date"])
        fire_time = str(row.get("fire_time") or "")
        try:
            fire = datetime.strptime(fire_date + fire_time, "%Y%m%d%H:%M").replace(tzinfo=UA_TZ)
        except ValueError:
            continue
        if fire <= now:
            continue
        kept.append(row)
    return kept


async def _tuya_json(client, cfg: BreakerPollConfig, method: str, path: str, token: str, body: dict | None) -> dict:
    data = b"" if body is None else json.dumps(body, separators=(",", ":")).encode()
    headers = sign_headers(cfg.access_id, cfg.access_secret, method, path, token, str(int(datetime.now(UA_TZ).timestamp() * 1000)), data)
    if body is not None:
        headers["Content-Type"] = "application/json"
    response = await client.request(method, cfg.host + path, content=None if body is None else data, headers=headers)
    if response.status_code != 200:
        raise TuyaCallError(response.status_code)
    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("success"):
        code = payload.get("code") if isinstance(payload, dict) else "error"
        raise TuyaCallError(code)
    return payload


def _log_lines(lines: list[str]) -> None:
    for line in lines:
        log.info("light-schedule: %s", line)


async def align_light_breakers() -> None:
    """Read today's outage snapshot and make the lighting timers match it."""
    if LIGHT_SCHEDULE_PAUSED:
        log.info("light-schedule: automatic schedule is paused, leaving timers unchanged")
        return
    if not TUYA_ACCESS_ID or not TUYA_ACCESS_SECRET or not TUYA_BREAKER_SVITLO:
        log.info("light-schedule: lighting breaker is not configured, leaving timers unchanged")
        return
    now = datetime.now(UA_TZ)
    day = now.strftime("%Y-%m-%d")
    grid, emergency = _grid_row(day)
    if emergency:
        _log_lines(["emergency outages, leaving lighting timers unchanged"])
        return
    if grid is None:
        _log_lines(["no schedule snapshot for today, leaving lighting timers unchanged"])
        return
    desired = desired_light_timers(grid, day, now, _yesterday_last(day))
    cfg = BreakerPollConfig(TUYA_ACCESS_ID, TUYA_ACCESS_SECRET, (("svitlo", TUYA_BREAKER_SVITLO),))
    cache = TokenCache()
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            token = await _ensure_token(client, cfg, cache, now.timestamp())
            payload = await _device_timers(client, cfg, token, TUYA_BREAKER_SVITLO, now.timestamp())
            current = _future_light_timers(timer_rows(payload), day.replace("-", ""), now)
            deletes, creates = plan_light_changes(desired, current)
            if not deletes and not creates:
                _log_lines(light_change_lines(deletes, creates))
                await sync_breaker_timers(client, cfg, cache, now.timestamp())
                return
            if deletes:
                ids = ",".join(str(row["timer_id"]) for row in deletes)
                path = f"/v2.0/cloud/timer/device/{TUYA_BREAKER_SVITLO}/batch?timer_ids={ids}"
                await _tuya_json(client, cfg, "DELETE", path, token, {"timer_ids": ids})
                _log_lines(light_change_lines(deletes, []))
            for row in creates:
                body = {
                    "category": "Dp_Spray",
                    "date": row["fire_date"],
                    "enable": True,
                    "loops": "0000000",
                    "time": row["fire_time"],
                    "timezone_id": "Europe/Kiev",
                    "functions": [{"code": "switch", "value": bool(row["switch"])}],
                }
                await _tuya_json(
                    client, cfg, "POST",
                    f"/v2.0/cloud/timer/device/{TUYA_BREAKER_SVITLO}",
                    token, body,
                )
                _log_lines(light_change_lines([], [row]))
            await sync_breaker_timers(client, cfg, cache, now.timestamp())
        except TuyaCallError as exc:
            log.info("light-schedule: failed to change the lighting schedule, code %s", exc.code)
