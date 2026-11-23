"""
Power Monitor — outage and voltage detection logic.

analyze(): basement inverter phases decide the light letters.
watchdog(): alert when the apartment inverter sample is stale.
"""
from __future__ import annotations

import asyncio
import logging
import time

import dtek
from config import (
    VOLTAGE_CONFIRM_COUNT,
    VOLTAGE_EPISODE_MIN_INTERVAL_SEC,
    VOLTAGE_STATUS,
    VOLTAGE_UNSTABLE_CHANGES_THRESHOLD,
    VOLTAGE_UNSTABLE_SUPPRESS_SEC,
    VOLTAGE_UNSTABLE_WINDOW_SEC,
)
from database import (
    apartment_link_fresh,
    count_voltage_problem_events_since,
    deye_voltage_trend,
    has_all_three_phases_voltage,
    has_grid_voltage_now,
    house_grid_now,
    kv_get,
    kv_set,
    last_nonzero_grid_voltage,
    last_voltage_problem_ts,
    notify_grid_inverter_id,
    recent_events,
    save_event,
)

log = logging.getLogger("power_monitor")


def _grid_id() -> int:
    return notify_grid_inverter_id()

_lock = asyncio.Lock()


def _voltage_suppressed() -> bool:
    """True if in unstable suppress window."""
    until = kv_get("voltage_unstable_until")
    if not until:
        return False
    try:
        return time.time() < float(until)
    except (TypeError, ValueError):
        return False


def _voltage_can_send_problem() -> bool:
    """One problem per episode: 30 min since last voltage problem EVENT (from DB)."""
    now = time.time()
    last_ts = last_voltage_problem_ts()
    if last_ts is not None and now - last_ts < VOLTAGE_EPISODE_MIN_INTERVAL_SEC:
        return False
    return True


def _ts_fmt_hm(ts: float) -> str:
    from config import UA_TZ
    from datetime import datetime
    return datetime.fromtimestamp(ts, tz=UA_TZ).strftime("%H:%M")


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


def _remember_normal_start() -> float:
    """When the current calm stretch began.

    A missing mark, or a mark older than the latest voltage problem, starts over.
    """
    raw = kv_get("voltage_normal_since")
    now = time.time()
    try:
        start = float(raw) if raw else 0.0
    except (TypeError, ValueError):
        start = 0.0
    problem_ts = last_voltage_problem_ts()
    if start > 0 and problem_ts is not None and start < problem_ts:
        start = 0.0
    if start <= 0:
        kv_set("voltage_normal_since", str(now))
        return now
    return start


def _clear_normal_start() -> None:
    kv_set("voltage_normal_since", "")


async def _maybe_send_recovery(voltage_alerted: bool) -> None:
    """Send settled only after a real calm stretch, not merely after the clock."""
    if not voltage_alerted or _voltage_suppressed():
        return
    start = _remember_normal_start()
    if time.time() - start < VOLTAGE_EPISODE_MIN_INTERVAL_SEC:
        return
    await _send_voltage_recovery()


async def _send_voltage_recovery() -> None:
    """State updates + build + send voltage recovery message. Single place for this logic."""
    from power_monitor import update_chat_photo

    now = time.time()
    prev = recent_events(1)
    try:
        stable_start = float(kv_get("voltage_normal_since") or 0)
    except (TypeError, ValueError):
        stable_start = 0.0
    if stable_start <= 0:
        return
    kv_set("voltage_anomaly", "0")
    kv_set("voltage_ok_count", "0")
    kv_set("power_down", "0")
    _clear_normal_start()
    save_event("up")
    log.info("VOLTAGE RESTORED (all 3 phases)")
    calm = _format_duration(int(now - stable_start))
    msg = f"\u2705 {_ts_fmt_hm(now)} Напруга стабілізувалась. {calm} без понаднормових коливань."
    v = last_nonzero_grid_voltage(inverter_id=_grid_id())
    if v:
        parts = []
        for phase, key in (("L1", "grid_v_l1"), ("L2", "grid_v_l2"), ("L3", "grid_v_l3")):
            val = v.get(key)
            parts.append(f"{phase}={val:.0f} В" if val is not None else f"{phase}=—")
        msg += f"\n\U0001f4a0 Напруга: {', '.join(parts)}"
    if prev:
        dur = _format_duration(int(stable_start - prev[0]["ts"]))
        msg += f"\n\U0001f553 Проблема тривала {dur} ({_ts_fmt_hm(prev[0]['ts'])} - {_ts_fmt_hm(stable_start)})"
    nxt = dtek.next_schedule_transition(looking_for_on=False)
    if nxt:
        msg += f"\n\U0001f4c5 Наступне відключення: {nxt}"
    await update_chat_photo(False, message_to_send=msg, is_voltage_notification=True)


async def _notify_live_voltage(voltage_alerted: bool, level: str) -> None:
    """All three phases are live: one above 245 V, or one below 185 V."""
    from power_monitor import update_chat_photo

    if voltage_alerted:
        kv_set("voltage_ok_count", "0")
        _clear_normal_start()
        return
    if _voltage_suppressed() or not _voltage_can_send_problem():
        return
    now = time.time()
    problem_count = int(kv_get("voltage_problem_count") or "0") + 1
    kv_set("voltage_problem_count", str(problem_count))
    kv_set("voltage_ok_count", "0")
    if problem_count < VOLTAGE_CONFIRM_COUNT:
        return
    kv_set("voltage_problem_count", "0")
    cutoff = now - VOLTAGE_UNSTABLE_WINDOW_SEC
    if count_voltage_problem_events_since(cutoff) >= VOLTAGE_UNSTABLE_CHANGES_THRESHOLD:
        kv_set("voltage_unstable_until", str(now + VOLTAGE_UNSTABLE_SUPPRESS_SEC))
        kv_set("voltage_anomaly", "1")
        save_event("voltage_issue")
        log.warning("VOLTAGE UNSTABLE — suppress 15 min")
        msg = f"\u26a1 {_ts_fmt_hm(now)} Нестабільна напруга\nДеталі призупинено на 15 хв"
        await update_chat_photo(True, voltage=None, message_to_send=msg, is_voltage_notification=True)
        return
    v = last_nonzero_grid_voltage(inverter_id=_grid_id())
    parts = []
    if v:
        for phase, key in (("L1", "grid_v_l1"), ("L2", "grid_v_l2"), ("L3", "grid_v_l3")):
            val = v.get(key)
            parts.append(f"{phase}={val:.0f} В" if val is not None else f"{phase}=—")
    s = VOLTAGE_STATUS[level]
    msg = f"\u26a1 {_ts_fmt_hm(now)} {s['text']}"
    if parts:
        msg += f"\n\U0001f4a0 Напруга: {', '.join(parts)}"
    save_event(s["event"])
    kv_set("voltage_anomaly", "1")
    log.warning("VOLTAGE %s detected (all phases live)", level.upper())
    await update_chat_photo(False, voltage=s["voltage"], message_to_send=msg, is_voltage_notification=True)


async def analyze():
    """Detect outages and voltage anomalies from the basement inverter."""
    from power_monitor import update_chat_photo

    async with _lock:
        if house_grid_now() == "unknown":
            _clear_normal_start()
            return

        is_down = kv_get("power_down") == "1"
        voltage_alerted = kv_get("voltage_anomaly") == "1"

        phases_ok = has_all_three_phases_voltage(inverter_id=_grid_id())
        phases_mixed = has_grid_voltage_now(inverter_id=_grid_id()) and not phases_ok

        if phases_ok:
            level = deye_voltage_trend(1000, inverter_id=_grid_id())
            if level not in ("high", "low"):
                level = None
            if level and not is_down:
                _clear_normal_start()
                await _notify_live_voltage(voltage_alerted, level)
                return
            if voltage_alerted and not level:
                kv_set("voltage_problem_count", "0")
                await _maybe_send_recovery(True)
                return
            _clear_normal_start()
            if is_down:
                now = time.time()
                prev = recent_events(1)
                kv_set("power_down", "0")
                save_event("up")
                log.info("POWER RESTORED")
                dev = dtek.schedule_deviation(is_down_event=False)
                if dev is not None:
                    sched_label = f" (\U0001f4c5 За графіком, відхилення {dtek.fmt_deviation(dev)})" if abs(dev) <= 30 else (f" (\u26a1Позапланове, відхилення {dtek.fmt_deviation(dev, signed=False)})" if abs(dev) <= 60 else " (\u26a1Позапланове)")
                else:
                    slot = dtek.current_slot_status()
                    sched_label = " (\U0001f4c5 За графіком)" if slot in ("maybe", "off") else " (\u26a1Позапланове)" if slot == "ok" else ""
                msg = f"\u2705 {_ts_fmt_hm(now)} Світло з'явилось{sched_label}"
                if prev:
                    dur = _format_duration(int(now - prev[0]["ts"]))
                    msg += f"\n\U0001f553 Його не було {dur} ({_ts_fmt_hm(prev[0]['ts'])} - {_ts_fmt_hm(now)})"
                nxt = dtek.next_schedule_transition(looking_for_on=False)
                if nxt:
                    msg += f"\n\U0001f4c5 Наступне відключення: {nxt}"
                await update_chat_photo(False, message_to_send=msg)
                if level:
                    await _notify_live_voltage(voltage_alerted, level)
        else:
            _clear_normal_start()
            if voltage_alerted and phases_mixed:
                kv_set("voltage_ok_count", "0")
                return
            if voltage_alerted and not phases_mixed:
                now = time.time()
                slot = dtek.current_slot_status()
                is_scheduled = slot in ("maybe", "off") if slot else False
                trend = deye_voltage_trend(1000, is_scheduled=is_scheduled, inverter_id=_grid_id())
                prev = recent_events(1)
                since_ts = prev[0]["ts"] if prev else 0
                kv_set("power_down", "1")
                if trend is not None:
                    kv_set("voltage_anomaly", "1")
                    log.info("All phases gone (was voltage anomaly) — no new TG message")
                else:
                    kv_set("voltage_anomaly", "0")
                    kv_set("power_down", "1")
                    save_event("down")
                    log.warning("POWER OUTAGE (was anomaly, now no voltage)")
                    dev = dtek.schedule_deviation(is_down_event=True)
                    sched_label = ""
                    if dev is not None:
                        sched_label = f" (\U0001f4c5 За графіком, відхилення {dtek.fmt_deviation(dev)})" if abs(dev) <= 30 else f" (\u26a1Позапланове, відхилення {dtek.fmt_deviation(dev, signed=False)})"
                    elif slot == "ok":
                        sched_label = " (\u26a1Позапланове)"
                    elif slot in ("maybe", "off"):
                        sched_label = " (\U0001f4c5 За графіком)"
                    msg = f"\u274c {_ts_fmt_hm(now)} Світло зникло{sched_label}"
                    if since_ts:
                        msg += f"\n\U0001f553 Проблема тривала {_format_duration(int(now - since_ts))} ({_ts_fmt_hm(since_ts)} - {_ts_fmt_hm(now)})"
                    if dev is None or abs(dev) <= 30:
                        nxt = dtek.next_schedule_transition(looking_for_on=True)
                        if nxt:
                            msg += f"\n\U0001f4c5 Включення за графіком: {nxt}"
                    await update_chat_photo(True, message_to_send=msg)
                return
            if is_down:
                return
            if not voltage_alerted:
                now = time.time()
                if phases_mixed:
                    if _voltage_suppressed():
                        return
                    if not _voltage_can_send_problem():
                        return
                    problem_count = int(kv_get("voltage_problem_count") or "0") + 1
                    kv_set("voltage_problem_count", str(problem_count))
                    kv_set("voltage_ok_count", "0")
                    if problem_count < VOLTAGE_CONFIRM_COUNT:
                        return
                    kv_set("voltage_problem_count", "0")
                    cutoff = now - VOLTAGE_UNSTABLE_WINDOW_SEC
                    n_recent = count_voltage_problem_events_since(cutoff)
                    if n_recent >= VOLTAGE_UNSTABLE_CHANGES_THRESHOLD:
                        kv_set("voltage_unstable_until", str(now + VOLTAGE_UNSTABLE_SUPPRESS_SEC))
                        kv_set("voltage_anomaly", "1")
                        save_event("voltage_issue")
                        log.warning("VOLTAGE UNSTABLE — suppress 15 min")
                        msg = f"\u26a1 {_ts_fmt_hm(now)} Нестабільна напруга\nДеталі призупинено на 15 хв"
                        await update_chat_photo(True, voltage=None, message_to_send=msg, is_voltage_notification=True)
                    else:
                        trend = deye_voltage_trend(1000, inverter_id=_grid_id())
                        v = last_nonzero_grid_voltage(inverter_id=_grid_id())
                        parts_v = []
                        if v:
                            for phase, key in (("L1", "grid_v_l1"), ("L2", "grid_v_l2"), ("L3", "grid_v_l3")):
                                val = v.get(key)
                                parts_v.append(f"{phase}={val:.0f} В" if val is not None else f"{phase}=—")
                        v_str = ", ".join(parts_v) if parts_v else ""
                        s = VOLTAGE_STATUS.get(trend, VOLTAGE_STATUS[None])
                        msg = f"\u26a1 {_ts_fmt_hm(now)} {s['text']}"
                        if v_str:
                            msg += f"\n\U0001f4a0 Напруга: {v_str}"
                        save_event(s["event"])
                        kv_set("voltage_anomaly", "1")
                        log.warning("VOLTAGE ANOMALY detected")
                        await update_chat_photo(s["voltage"] is None, voltage=s["voltage"], message_to_send=msg, is_voltage_notification=True)
                else:
                    slot = dtek.current_slot_status()
                    is_scheduled = slot in ("maybe", "off") if slot else False
                    trend = deye_voltage_trend(1000, is_scheduled=is_scheduled, inverter_id=_grid_id())
                    if trend == "high":
                        if _voltage_suppressed():
                            return
                        if not _voltage_can_send_problem():
                            return
                        problem_count = int(kv_get("voltage_problem_count") or "0") + 1
                        kv_set("voltage_problem_count", str(problem_count))
                        kv_set("voltage_ok_count", "0")
                        if problem_count < VOLTAGE_CONFIRM_COUNT:
                            return
                        kv_set("voltage_problem_count", "0")
                        s = VOLTAGE_STATUS["high"]
                        kv_set("voltage_anomaly", "1")
                        save_event(s["event"])
                        log.warning("VOLTAGE HIGH detected (all phases gone, was >240 before)")
                        msg = f"\u26a1 {_ts_fmt_hm(now)} {s['text']} (усі фази зникли)"
                        await update_chat_photo(False, voltage=s["voltage"], message_to_send=msg, is_voltage_notification=True)
                    else:
                        kv_set("voltage_anomaly", "0")
                        prev = recent_events(1)
                        since_ts = prev[0]["ts"] if prev else 0
                        kv_set("power_down", "1")
                        save_event("down")
                        log.warning("POWER OUTAGE detected")
                        dev = dtek.schedule_deviation(is_down_event=True)
                        if dev is not None:
                            sched_label = " (\U0001f4c5 За графіком)" if abs(dev) <= 30 else " (\u26a1Позапланове)"
                        else:
                            sched_label = " (\U0001f4c5 За графіком)" if slot in ("maybe", "off") else " (\u26a1Позапланове)" if slot == "ok" else ""
                        msg = f"\u274c {_ts_fmt_hm(now)} Світло зникло{sched_label}"
                        if since_ts:
                            msg += f"\n\U0001f553 Воно було {_format_duration(int(now - since_ts))} ({_ts_fmt_hm(since_ts)} - {_ts_fmt_hm(now)})"
                        nxt = dtek.next_schedule_transition(looking_for_on=True)
                        if nxt:
                            msg += f"\n\U0001f4c5 Включення за графіком: {nxt}"
                        await update_chat_photo(True, message_to_send=msg)


async def watchdog():
    """Alert when the apartment inverter sample is stale. Not a building outage."""
    from power_monitor import tg_send, _tg_inline_button

    fresh = apartment_link_fresh()
    alerted = kv_get("stale_alerted") == "1"
    if not fresh and not alerted:
        kv_set("stale_alerted", "1")
        log.warning("No fresh apartment inverter sample")
        await tg_send(
            "⚠️ Немає зв'язку з інвертором квартири",
            reply_markup=_tg_inline_button(),
        )
    elif fresh and alerted:
        kv_set("stale_alerted", "0")
        log.info("Apartment inverter sample is fresh again")
        await tg_send(
            "✅ Зв'язок з інвертором квартири відновився",
            reply_markup=_tg_inline_button(),
        )
