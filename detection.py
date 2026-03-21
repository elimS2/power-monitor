"""
Power Monitor — outage and voltage detection logic.

analyze(): check heartbeats/Deye phases, detect outages and voltage anomalies.
watchdog(): alert if no heartbeats received for too long.
"""
from __future__ import annotations

import asyncio
import logging
import time

import dtek
from config import (
    OUTAGE_CONFIRM_COUNT,
    PHASES_ONLY,
    STALE_THRESHOLD_SEC,
    VOLTAGE_CONFIRM_COUNT,
    VOLTAGE_EPISODE_MIN_INTERVAL_SEC,
    VOLTAGE_STATUS,
    VOLTAGE_UNSTABLE_CHANGES_THRESHOLD,
    VOLTAGE_UNSTABLE_SUPPRESS_SEC,
    VOLTAGE_UNSTABLE_WINDOW_SEC,
)
from database import (
    count_voltage_problem_events_since,
    deye_voltage_trend,
    first_heartbeat_ts,
    has_all_three_phases_voltage,
    has_grid_voltage_now,
    kv_get,
    kv_set,
    last_nonzero_grid_voltage,
    last_voltage_problem_ts,
    recent_events,
    recent_heartbeats,
    save_event,
)

log = logging.getLogger("power_monitor")

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
    """One problem per episode: 60 min since last voltage problem EVENT (from DB)."""
    now = time.time()
    last_ts = last_voltage_problem_ts()
    if last_ts is not None and now - last_ts < VOLTAGE_EPISODE_MIN_INTERVAL_SEC:
        return False
    return True


def _voltage_can_send_recovery() -> bool:
    """One recovery per episode: 60 min since last voltage problem EVENT (from DB)."""
    if _voltage_suppressed():
        return False
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


async def _send_voltage_recovery() -> None:
    """State updates + build + send voltage recovery message. Single place for this logic."""
    from power_monitor import update_chat_photo

    now = time.time()
    prev = recent_events(1)
    kv_set("voltage_anomaly", "0")
    kv_set("voltage_ok_count", "0")
    kv_set("power_down", "0")
    save_event("up")
    log.info("VOLTAGE RESTORED (all 3 phases)")
    stable_mins = VOLTAGE_EPISODE_MIN_INTERVAL_SEC // 60
    stable_start = now - VOLTAGE_EPISODE_MIN_INTERVAL_SEC
    msg = f"\u2705 {_ts_fmt_hm(now)} Напруга стабілізувалась. {stable_mins} останніх хвилин без понаднормових коливань."
    v = last_nonzero_grid_voltage()
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


async def analyze():
    """Detect outages and voltage anomalies. Uses power_monitor for notifications (lazy import)."""
    from power_monitor import tg_send, update_chat_photo, _tg_inline_button

    async with _lock:
        rows = recent_heartbeats(OUTAGE_CONFIRM_COUNT)
        min_rows = 3 if PHASES_ONLY else OUTAGE_CONFIRM_COUNT
        if len(rows) < min_rows:
            return

        is_down = kv_get("power_down") == "1"
        voltage_alerted = kv_get("voltage_anomaly") == "1"

        if PHASES_ONLY:
            phases_ok = has_all_three_phases_voltage()
            phases_mixed = has_grid_voltage_now() and not phases_ok

            if phases_ok:
                if voltage_alerted:
                    ok_count = int(kv_get("voltage_ok_count") or "0") + 1
                    kv_set("voltage_ok_count", str(ok_count))
                    kv_set("voltage_problem_count", "0")
                    if not _voltage_can_send_recovery() or ok_count < VOLTAGE_CONFIRM_COUNT:
                        return
                    await _send_voltage_recovery()
                elif is_down:
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
            else:
                if voltage_alerted and phases_mixed:
                    kv_set("voltage_ok_count", "0")
                    return
                if voltage_alerted and not phases_mixed:
                    now = time.time()
                    slot = dtek.current_slot_status()
                    is_scheduled = slot in ("maybe", "off") if slot else False
                    trend = deye_voltage_trend(1000, is_scheduled=is_scheduled)
                    prev = recent_events(1)
                    since_ts = prev[0]["ts"] if prev else first_heartbeat_ts() or 0
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
                            trend = deye_voltage_trend(1000)
                            v = last_nonzero_grid_voltage()
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
                            log.warning("VOLTAGE ANOMALY detected (phases_only)")
                            await update_chat_photo(s["voltage"] is None, voltage=s["voltage"], message_to_send=msg, is_voltage_notification=True)
                    else:
                        slot = dtek.current_slot_status()
                        is_scheduled = slot in ("maybe", "off") if slot else False
                        trend = deye_voltage_trend(1000, is_scheduled=is_scheduled)
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
                            since_ts = prev[0]["ts"] if prev else first_heartbeat_ts() or 0
                            kv_set("power_down", "1")
                            save_event("down")
                            log.warning("POWER OUTAGE detected (phases_only)")
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
            return

        all_dead = all(r["plug204"] == 0 and r["plug175"] == 0 for r in rows)
        latest_alive = rows[0]["plug204"] > 0 or rows[0]["plug175"] > 0

        if all_dead and not is_down:
            now = time.time()
            voltage_alerted = kv_get("voltage_anomaly") == "1"

            if has_grid_voltage_now() and not voltage_alerted:
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
                    trend = deye_voltage_trend(1000)
                    v = last_nonzero_grid_voltage()
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
                    log.warning("VOLTAGE ANOMALY detected (not power outage)")
                    await update_chat_photo(s["voltage"] is None, voltage=s["voltage"], message_to_send=msg, is_voltage_notification=True)
                return

            if voltage_alerted and has_grid_voltage_now():
                if has_all_three_phases_voltage():
                    ok_count = int(kv_get("voltage_ok_count") or "0") + 1
                    kv_set("voltage_ok_count", str(ok_count))
                    kv_set("voltage_problem_count", "0")
                    if not _voltage_can_send_recovery() or ok_count < VOLTAGE_CONFIRM_COUNT:
                        return
                    await _send_voltage_recovery()
                else:
                    kv_set("voltage_ok_count", "0")
                return

            slot = dtek.current_slot_status()
            is_scheduled = slot in ("maybe", "off") if slot else False
            trend = deye_voltage_trend(1000, is_scheduled=is_scheduled)
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
                return
            kv_set("voltage_anomaly", "0")
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
            dev = dtek.schedule_deviation(is_down_event=True)
            sched_label = ""
            if dev is not None:
                if abs(dev) <= 30:
                    sched_label = f" (\U0001f4c5 За графіком, відхилення {dtek.fmt_deviation(dev)})"
                else:
                    sched_label = f" (\u26a1Позапланове, відхилення {dtek.fmt_deviation(dev, signed=False)})"
            else:
                if slot == "ok":
                    sched_label = " (\u26a1Позапланове)"
                elif slot in ("maybe", "off"):
                    sched_label = " (\U0001f4c5 За графіком)"
                elif slot is None:
                    sched_label = " (немає даних графіку)"
            msg = f"\u274c {_ts_fmt_hm(now)} Світло зникло{sched_label}"
            if since_ts:
                dur = _format_duration(int(now - since_ts))
                msg += f"\n\U0001f553 Воно було {dur} ({_ts_fmt_hm(since_ts)} - {_ts_fmt_hm(now)})"
            v = last_nonzero_grid_voltage()
            if v:
                parts = []
                for phase, key in (("L1", "grid_v_l1"), ("L2", "grid_v_l2"), ("L3", "grid_v_l3")):
                    val = v.get(key)
                    parts.append(f"{phase}={val:.0f} В" if val is not None else f"{phase}=—")
                msg += f"\n\U0001f4a0 Остання напруга: {', '.join(parts)}"
            if dev is None or abs(dev) <= 30:
                nxt = dtek.next_schedule_transition(looking_for_on=True)
                if nxt:
                    msg += f"\n\U0001f4c5 Включення за графіком: {nxt}"
            await update_chat_photo(True, message_to_send=msg)

        elif latest_alive:
            kv_set("voltage_anomaly", "0")
            if not is_down:
                return
            now = time.time()
            prev = recent_events(1)
            kv_set("power_down", "0")
            save_event("up")
            log.info("POWER RESTORED")
            dev = dtek.schedule_deviation(is_down_event=False)
            sched_label = ""
            if dev is not None:
                if abs(dev) <= 30:
                    sched_label = f" (\U0001f4c5 За графіком, відхилення {dtek.fmt_deviation(dev)})"
                else:
                    sched_label = f" (\u26a1Позапланове, відхилення {dtek.fmt_deviation(dev, signed=False)})" if abs(dev) <= 60 else " (\u26a1Позапланове)"
            else:
                slot = dtek.current_slot_status()
                if slot == "ok":
                    sched_label = " (\U0001f4c5 За графіком)"
                elif slot in ("maybe", "off"):
                    sched_label = " (\U0001f4c5 За графіком)"
                elif slot is None:
                    sched_label = " (немає даних графіку)"
            msg = f"\u2705 {_ts_fmt_hm(now)} Світло з'явилось{sched_label}"
            if prev:
                since_ts = prev[0]["ts"]
                dur = _format_duration(int(now - since_ts))
                msg += f"\n\U0001f553 Його не було {dur} ({_ts_fmt_hm(since_ts)} - {_ts_fmt_hm(now)})"
            nxt = dtek.next_schedule_transition(looking_for_on=False)
            if nxt:
                msg += f"\n\U0001f4c5 Наступне відключення: {nxt}"
            await update_chat_photo(False, message_to_send=msg)


async def watchdog():
    """Alert if no heartbeats received for too long."""
    from power_monitor import tg_send, _tg_inline_button

    rows = recent_heartbeats(1)
    if not rows:
        return

    age = time.time() - rows[0]["ts"]
    alerted = kv_get("stale_alerted") == "1"

    if age > STALE_THRESHOLD_SEC and not alerted:
        kv_set("stale_alerted", "1")
        minutes = int(age // 60)
        log.warning("No heartbeat for %dm", minutes)
        await tg_send(f"\u26a0\ufe0f Роутер не відповідає вже {minutes} хв", reply_markup=_tg_inline_button())
    elif age <= STALE_THRESHOLD_SEC and alerted:
        kv_set("stale_alerted", "0")
