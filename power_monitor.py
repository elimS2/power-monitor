"""
Power outage monitor server.

Receives ICMP ping results from router every ~10s for two smart plugs,
stores in SQLite, detects outages by cross-checking both plugs, and
sends Telegram notifications.

Run:
    uvicorn power_monitor:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import logging.handlers
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI, Query, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response, FileResponse

from config import (
    API_KEYS,
    AUTO_DEPLOY_ENABLED,
    AUTO_DEPLOY_INTERVAL_SEC,
    AVATAR_ON_START,
    DEYE_POLL_LOG,
    DELETE_PHOTO_MSG,
    DTEK_QUEUE,
    DB_PATH,
    DEYE_BATTERY_KWH,
    DEYE_POLL_IP,
    DEYE_POLL_INTERVAL_SEC,
    DEYE_POLL_PORT,
    DEYE_POLL_SERIAL,
    GIT_COMMIT,
    OUTAGE_CONFIRM_COUNT,
    PHASES_ONLY,
    STALE_THRESHOLD_SEC,
    TG_BOT_TOKEN,
    TG_CHAT_ID,
    TG_TEST_CHAT_ID,
    TG_WEBHOOK_SECRET,
    UA_TZ,
    WEBHOOK_HOST,
    WMO_EMOJI,
)
from database import (
    api_key_config_list,
    boiler_schedule_for_dates,
    cleanup_old,
    deye_battery_episodes_for_month,
    deye_cumulative_metrics,
    deye_daily_load_kwh,
    deye_monthly_load_kwh,
    deye_voltage_trend,
    first_heartbeat_ts,
    has_all_three_phases_voltage,
    has_grid_voltage_now,
    init_db,
    kv_get,
    kv_set,
    last_nonzero_grid_voltage,
    parse_boiler_schedule,
    recent_alert_events,
    recent_deye_log,
    recent_events,
    recent_heartbeats,
    recent_tg_log,
    save_alert_event,
    save_boiler_schedule,
    save_deye_log,
    save_event,
    save_heartbeat,
    save_tg_log,
    schedule_history_for_date,
    _conn,
)

import dtek

_REPO = Path(__file__).resolve().parent
_DEPLOY_TAGS = re.compile(r"#автооновити|#autodeploy", re.I)


def _check_and_deploy_sync() -> bool:
    """Check if remote has new commit with deploy tag; if so, pull and restart. Returns True if restart triggered."""
    try:
        log.info("Auto-deploy: checking...")
        r = subprocess.run(["git", "fetch", "origin"], cwd=_REPO, capture_output=True, text=True, check=False, timeout=30)
        if r.returncode != 0:
            log.warning("Auto-deploy: git fetch failed: %s", r.stderr or r.stdout or r.returncode)
            return False
        local = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=_REPO, capture_output=True, text=True, check=False, timeout=5
        ).stdout.strip()
        remote = subprocess.run(
            ["git", "rev-parse", "origin/main"], cwd=_REPO, capture_output=True, text=True, check=False, timeout=5
        ).stdout.strip()
        if local == remote or not remote:
            return False
        msg = subprocess.run(
            ["git", "log", "-1", "--format=%B", "origin/main"],
            cwd=_REPO, capture_output=True, text=True, check=False, timeout=5,
        ).stdout.strip()
        if not _DEPLOY_TAGS.search(msg):
            log.info("Auto-deploy: origin/main %s has no #autodeploy tag, skipping", remote[:8])
            return False
        log.info("Auto-deploy: pulling %s and restarting", remote[:8])
        subprocess.run(["git", "pull", "origin", "main"], cwd=_REPO, check=True, timeout=60)
        subprocess.run(["sudo", "systemctl", "restart", "power-monitor"], check=True, timeout=10)
        return True
    except Exception as e:
        log.warning("Auto-deploy check failed: %s", e)
        return False


def _wrap_dashboard_section(section_id: str, content: str, allowed: list[str] | None = None) -> str:
    """Wrap section HTML in draggable container. If allowed provided and section_id not in it, return ''."""
    if not content or not content.strip():
        return ""
    if allowed is not None and section_id not in allowed:
        return ""
    return f'<div class="dashboard-section" data-section-id="{section_id}"><span class="drag-handle" draggable="true" title="Перетягніть для зміни порядку">⋮⋮</span>{content}</div>'


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("power_monitor")

# Dedicated Deye poll logger with rotating file
deye_poll_log = logging.getLogger("power_monitor.deye_poll")


def _setup_deye_poll_log():
    """Configure deye_poll_log to write to rotating file."""
    deye_poll_log.setLevel(logging.INFO)
    deye_poll_log.handlers.clear()
    deye_poll_log.propagate = False
    log_dir = DEYE_POLL_LOG.parent
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        DEYE_POLL_LOG,
        maxBytes=2 * 1024 * 1024,  # 2 MB
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    deye_poll_log.addHandler(handler)


# ─── Channel photo ───────────────────────────────────────────

async def tg_send(text: str, chat_id: str = "") -> int:
    """Send message, return message_id (0 on failure)."""
    target = chat_id or TG_CHAT_ID
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": target, "text": text}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json=payload)
            save_tg_log(target, text, r.status_code)
            log.info("TG [%s] to %s: %s", r.status_code, target, text.replace("\n", " | "))
            if r.status_code == 200:
                return r.json().get("result", {}).get("message_id", 0)
    except Exception as e:
        save_tg_log(target, text, 0)
        log.error("TG send failed: %s", e)
    return 0



# ─── Channel photo ───────────────────────────────────────────

_ICONS_DIR = Path(__file__).parent
_STATIC_DIR = Path(__file__).parent / "static"
_PHOTO_ON = (_ICONS_DIR / "icon_on.png").read_bytes()
_PHOTO_OFF = (_ICONS_DIR / "icon_off.png").read_bytes()


def _photo_for_voltage(kind: str) -> bytes | None:
    """Load high/low voltage icon. kind='high' or 'low'. Returns None if file missing."""
    names = {"high": "icon_high_voltage_v1.png", "low": "icon_low_voltage_v1.png"}
    path = _ICONS_DIR / names.get(kind, "")
    return path.read_bytes() if path.exists() else None


async def _delete_service_msg(client: httpx.AsyncClient, api: str, message: str | None = None):
    """Send message (or '.'), delete service msg before it. If message provided, keep it; else delete our msg too."""
    text = message if message is not None else "."
    r = await client.post(f"{api}/sendMessage", json={"chat_id": TG_CHAT_ID, "text": text})
    if r.status_code == 200:
        if message is not None:
            save_tg_log(TG_CHAT_ID, text, r.status_code)
        tid = r.json().get("result", {}).get("message_id", 0)
        if tid:
            await client.post(f"{api}/deleteMessage", json={"chat_id": TG_CHAT_ID, "message_id": tid - 1})
            if message is None:
                await client.post(f"{api}/deleteMessage", json={"chat_id": TG_CHAT_ID, "message_id": tid})


async def update_chat_photo(is_down: bool, voltage: str | None = None, message_to_send: str | None = None):
    """voltage='high'|'low' overrides is_down. If message_to_send, send it instead of dot and keep it."""
    if voltage:
        pic = _photo_for_voltage(voltage)
        photo = pic if pic else _PHOTO_OFF
    else:
        photo = _PHOTO_OFF if is_down else _PHOTO_ON
    api = f"https://api.telegram.org/bot{TG_BOT_TOKEN}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{api}/setChatPhoto",
                data={"chat_id": TG_CHAT_ID},
                files={"photo": ("status.png", photo, "image/png")},
            )
            log.info("setChatPhoto [%s]: %s", r.status_code, r.text[:120])
            if DELETE_PHOTO_MSG and r.status_code == 200:
                await asyncio.sleep(0.5)
                await _delete_service_msg(client, api, message_to_send)
            elif message_to_send:
                await tg_send(message_to_send)
    except Exception as e:
        log.error("setChatPhoto failed: %s", e)


# ─── Telegram bot (webhook for /status command) ──────────────

async def setup_tg_bot():
    """Register webhook and set bot menu commands on startup."""
    if not WEBHOOK_HOST:
        log.warning("WEBHOOK_HOST not set — bot commands disabled")
        return
    url = f"{WEBHOOK_HOST}/api/tg-webhook"
    api = f"https://api.telegram.org/bot{TG_BOT_TOKEN}"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{api}/setWebhook",
            json={
                "url": url,
                "secret_token": TG_WEBHOOK_SECRET,
                "allowed_updates": ["message", "channel_post"],
            },
        )
        log.info("setWebhook: %s", r.json())
        r = await client.post(
            f"{api}/setMyCommands",
            json={"commands": [{"command": "status", "description": "Статус світла"}]},
        )
        log.info("setMyCommands: %s", r.json())


# ─── Detection logic ─────────────────────────────────────────

_lock = asyncio.Lock()


async def analyze():
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
                    now = time.time()
                    prev = recent_events(1)
                    kv_set("voltage_anomaly", "0")
                    kv_set("power_down", "0")
                    save_event("up")
                    log.info("VOLTAGE RESTORED (all 3 phases)")
                    msg = f"\u2705 {_ts_fmt_hm(now)} Напруга відновилась"
                    v = last_nonzero_grid_voltage()
                    if v:
                        parts = []
                        for phase, key in (("L1", "grid_v_l1"), ("L2", "grid_v_l2"), ("L3", "grid_v_l3")):
                            val = v.get(key)
                            parts.append(f"{phase}={val:.0f} В" if val is not None else f"{phase}=—")
                        msg += f"\n\U0001f4a0 Напруга: {', '.join(parts)}"
                    if prev:
                        dur = _format_duration(int(now - prev[0]["ts"]))
                        msg += f"\n\U0001f553 Проблема тривала {dur} ({_ts_fmt_hm(prev[0]['ts'])} - {_ts_fmt_hm(now)})"
                    nxt = dtek.next_schedule_transition(looking_for_on=False)
                    if nxt:
                        msg += f"\n\U0001f4c5 Наступне відключення: {nxt}"
                    await update_chat_photo(False, message_to_send=msg)
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
                    return
                if voltage_alerted and not phases_mixed:
                    # Була вже висока напруга (напр. 1 фаза працювала з >240В), тепер усі фази 0.
                    # Той самий тип проблеми — не дублюємо повідомлення в Telegram.
                    now = time.time()
                    slot = dtek.current_slot_status()
                    is_scheduled = slot in ("maybe", "off") if slot else False
                    trend = deye_voltage_trend(1000, is_scheduled=is_scheduled)
                    prev = recent_events(1)
                    since_ts = prev[0]["ts"] if prev else first_heartbeat_ts() or 0
                    kv_set("power_down", "1")
                    if trend is not None:
                        # Той самий тип аномалії (high/low/issue) — не дублюємо повідомлення в Telegram
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
                        await update_chat_photo(s["voltage"] is None, voltage=s["voltage"], message_to_send=msg)
                    else:
                        slot = dtek.current_slot_status()
                        is_scheduled = slot in ("maybe", "off") if slot else False
                        trend = deye_voltage_trend(1000, is_scheduled=is_scheduled)
                        if trend == "high":
                            s = VOLTAGE_STATUS["high"]
                            kv_set("voltage_anomaly", "1")
                            save_event(s["event"])
                            log.warning("VOLTAGE HIGH detected (all phases gone, was >240 before)")
                            msg = f"\u26a1 {_ts_fmt_hm(now)} {s['text']} (усі фази зникли)"
                            await update_chat_photo(False, voltage=s["voltage"], message_to_send=msg)
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

            # Якщо Deye бачить напругу на будь-якій фазі — це не відключення, а аномалія напруги
            if has_grid_voltage_now() and not voltage_alerted:
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
                await update_chat_photo(s["voltage"] is None, voltage=s["voltage"], message_to_send=msg)
                return

            if voltage_alerted and has_grid_voltage_now():
                if has_all_three_phases_voltage():
                    now = time.time()
                    prev = recent_events(1)
                    kv_set("voltage_anomaly", "0")
                    kv_set("power_down", "0")
                    save_event("up")
                    log.info("VOLTAGE RESTORED (all 3 phases)")
                    msg = f"\u2705 {_ts_fmt_hm(now)} Напруга відновилась"
                    v = last_nonzero_grid_voltage()
                    if v:
                        parts = []
                        for phase, key in (("L1", "grid_v_l1"), ("L2", "grid_v_l2"), ("L3", "grid_v_l3")):
                            val = v.get(key)
                            parts.append(f"{phase}={val:.0f} В" if val is not None else f"{phase}=—")
                        msg += f"\n\U0001f4a0 Напруга: {', '.join(parts)}"
                    if prev:
                        dur = _format_duration(int(now - prev[0]["ts"]))
                        msg += f"\n\U0001f553 Проблема тривала {dur} ({_ts_fmt_hm(prev[0]['ts'])} - {_ts_fmt_hm(now)})"
                    nxt = dtek.next_schedule_transition(looking_for_on=False)
                    if nxt:
                        msg += f"\n\U0001f4c5 Наступне відключення: {nxt}"
                    await update_chat_photo(False, message_to_send=msg)
                return

            # Справжнє відключення: напруги немає або немає даних Deye
            slot = dtek.current_slot_status()
            is_scheduled = slot in ("maybe", "off") if slot else False
            trend = deye_voltage_trend(1000, is_scheduled=is_scheduled)
            if trend == "high":
                s = VOLTAGE_STATUS["high"]
                kv_set("voltage_anomaly", "1")
                save_event(s["event"])
                log.warning("VOLTAGE HIGH detected (all phases gone, was >240 before)")
                msg = f"\u26a1 {_ts_fmt_hm(now)} {s['text']} (усі фази зникли)"
                await update_chat_photo(False, voltage=s["voltage"], message_to_send=msg)
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
                    sched_label = " (\u26a1Позапланове)"
                elif slot is None:
                    sched_label = " (немає даних графіку)"
            msg = f"\u2705 {_ts_fmt_hm(now)} Світло з'явилось{sched_label}"
            if prev:
                since_ts = prev[0]["ts"]
                dur = _format_duration(int(now - since_ts))
                msg += f"\n\U0001f553 Його не було {dur} ({_ts_fmt_hm(since_ts)} - {_ts_fmt_hm(now)})"
            # Планове відключення — завжди показуємо (корисно навіть якщо включення було позаплановим)
            nxt = dtek.next_schedule_transition(looking_for_on=False)
            if nxt:
                msg += f"\n\U0001f4c5 Наступне відключення: {nxt}"
            await update_chat_photo(False, message_to_send=msg)


async def watchdog():
    """Alert if no heartbeats received for too long."""
    rows = recent_heartbeats(1)
    if not rows:
        return

    age = time.time() - rows[0]["ts"]
    alerted = kv_get("stale_alerted") == "1"

    if age > STALE_THRESHOLD_SEC and not alerted:
        kv_set("stale_alerted", "1")
        minutes = int(age // 60)
        log.warning("No heartbeat for %dm", minutes)
        await tg_send(f"\u26a0\ufe0f Роутер не відповідає вже {minutes} хв")
    elif age <= STALE_THRESHOLD_SEC and alerted:
        kv_set("stale_alerted", "0")



# ─── Background loop ─────────────────────────────────────────

async def _poll_deye():
    """Poll Deye inverter and save to DB. Runs in executor (blocking I/O)."""
    try:
        from deye_to_power_monitor import read_deye

        port = DEYE_POLL_PORT if DEYE_POLL_PORT > 0 else (8899 if DEYE_POLL_SERIAL else 502)
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(
            None,
            lambda: read_deye(host=DEYE_POLL_IP, port=port, serial=DEYE_POLL_SERIAL or None),
        )
        if data:
            save_deye_log(
                load_power_w=data.get("load_power_w"),
                load_l1_w=data.get("load_l1_w"),
                load_l2_w=data.get("load_l2_w"),
                load_l3_w=data.get("load_l3_w"),
                grid_power_w=data.get("grid_power_w"),
                grid_v_l1=data.get("grid_v_l1"),
                grid_v_l2=data.get("grid_v_l2"),
                grid_v_l3=data.get("grid_v_l3"),
                battery_soc=data.get("battery_soc"),
                battery_power_w=data.get("battery_power_w"),
                battery_voltage=data.get("battery_voltage"),
                day_load_kwh=data.get("day_load_kwh"),
                total_load_kwh=data.get("total_load_kwh"),
                month_load_kwh=data.get("month_load_kwh"),
                year_load_kwh=data.get("year_load_kwh"),
                day_grid_import_kwh=data.get("day_grid_import_kwh"),
                day_grid_export_kwh=data.get("day_grid_export_kwh"),
                total_grid_import_kwh=data.get("total_grid_import_kwh"),
                total_grid_export_kwh=data.get("total_grid_export_kwh"),
            )
            load = data.get("load_power_w", "?")
            soc = data.get("battery_soc", "?")
            day_kwh = data.get("day_load_kwh")
            grid_w = data.get("grid_power_w")
            day_str = f" day={round(day_kwh, 1)}kWh" if day_kwh is not None else ""
            grid_str = f" grid={int(grid_w)}W" if grid_w is not None else ""
            msg = f"Deye poll OK: load={load}W soc={soc}%{day_str}{grid_str}"
            log.info(msg)
            deye_poll_log.info(msg)
        else:
            deye_poll_log.warning("Deye poll failed (no data)")
            log.warning("Deye poll failed (no data)")
    except Exception as e:
        deye_poll_log.warning("Deye poll error: %s", e)
        log.warning("Deye poll error: %s", e)


async def bg_loop():
    cleanup_tick = 0
    schedule_tick = 0
    alert_tick = 0
    deye_poll_tick = 0
    deploy_tick = 0
    while True:
        try:
            await watchdog()
            cleanup_tick += 1
            if cleanup_tick >= 2880:  # ~24h at 30s interval
                cleanup_old()
                cleanup_tick = 0
            if DEYE_POLL_IP:
                deye_poll_tick += 1
                if deye_poll_tick * 30 >= DEYE_POLL_INTERVAL_SEC:
                    await _poll_deye()
                    deye_poll_tick = 0
            date_rolled = (
                dtek.schedule_cache
                and dtek.schedule_cache.get("today")
                and dtek.schedule_cache["today"]["date"]
                != datetime.now(UA_TZ).strftime("%Y-%m-%d")
            )
            schedule_tick += 1
            if schedule_tick >= 60 or date_rolled:  # ~30min or midnight
                await dtek.fetch_dtek_schedule()
                await dtek.fetch_weather()
                schedule_tick = 0
            alert_tick += 1
            if alert_tick >= 4:  # ~2min at 30s interval
                await dtek.fetch_alert()
                alert_tick = 0
            if AUTO_DEPLOY_ENABLED:
                deploy_tick += 1
                if deploy_tick * 30 >= AUTO_DEPLOY_INTERVAL_SEC:
                    deploy_tick = 0
                    loop = asyncio.get_running_loop()
                    if await loop.run_in_executor(None, _check_and_deploy_sync):
                        return  # restart triggered, we're about to die
        except Exception as e:
            log.error("bg_loop: %s", e)
        await asyncio.sleep(30)


# ─── FastAPI ─────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    await dtek.fetch_dtek_schedule()
    await dtek.fetch_weather()
    await dtek.fetch_alert()
    task = asyncio.create_task(bg_loop())
    await setup_tg_bot()
    if AVATAR_ON_START:
        if kv_get("voltage_anomaly") == "1" and has_grid_voltage_now():
            trend = deye_voltage_trend(1000)
            if trend == "high":
                await update_chat_photo(False, voltage="high")
            elif trend == "low":
                await update_chat_photo(False, voltage="low")
            else:
                await update_chat_photo(True)
        else:
            await update_chat_photo(kv_get("power_down") == "1")
    else:
        log.info("Skipping avatar update on start (AVATAR_ON_START=0)")
    log.info("Power monitor started, DB=%s", DB_PATH)
    if DEYE_POLL_IP:
        _setup_deye_poll_log()
        port = DEYE_POLL_PORT if DEYE_POLL_PORT > 0 else (8899 if DEYE_POLL_SERIAL else 502)
        log.info("Deye server-side polling enabled: %s:%s every %ds", DEYE_POLL_IP, port, DEYE_POLL_INTERVAL_SEC)
    yield
    task.cancel()


app = FastAPI(title="Power Monitor", lifespan=lifespan)


# Include API routers
from api import (
    admin_router,
    dashboard_router,
    deye_router,
    debug_router,
    heartbeat_router,
    plug_router,
    static_router,
    telegram_router,
)

app.include_router(admin_router)
app.include_router(heartbeat_router)
app.include_router(dashboard_router)
app.include_router(debug_router)
app.include_router(telegram_router)
app.include_router(deye_router)
app.include_router(plug_router)
app.include_router(static_router)

# Single source for voltage status: trend -> display text, icon, event, avatar voltage param
VOLTAGE_STATUS = {
    "high": {"text": "Висока напруга", "icon": "icon_high_voltage_v1.png", "event": "voltage_high", "voltage": "high"},
    "low": {"text": "Низька напруга", "icon": "icon_low_voltage_v1.png", "event": "voltage_low", "voltage": "low"},
    None: {"text": "Проблема з напругою", "icon": "icon_off.png", "event": "voltage_issue", "voltage": None},
}


def get_display_status() -> dict:
    """
    Single source of truth for power/voltage status. Used by dashboard (and must match Telegram logic).
    Uses Deye phases only (no plugs). Returns: {status_cls, status_text, icon}
    """
    is_down = kv_get("power_down") == "1"
    voltage_anomaly = kv_get("voltage_anomaly") == "1"
    phases_ok = has_all_three_phases_voltage()
    phases_mixed = has_grid_voltage_now() and not phases_ok

    slot = dtek.current_slot_status()
    is_scheduled = slot in ("maybe", "off") if slot else False

    # Voltage anomaly: mixed phases (e.g. L1+L3 ok, L2=0)
    if phases_mixed:
        trend = deye_voltage_trend(1000)
        s = VOLTAGE_STATUS.get(trend, VOLTAGE_STATUS[None])
        return {"status_cls": "down", "status_text": s["text"], "icon": s["icon"], "voltage": s["voltage"]}

    # Voltage anomaly: all phases gone, was high before
    if voltage_anomaly and not phases_ok and not phases_mixed:
        trend = deye_voltage_trend(1000, is_scheduled=is_scheduled)
        if trend == "high":
            s = VOLTAGE_STATUS["high"]
            return {"status_cls": "down", "status_text": s["text"], "icon": s["icon"], "voltage": s["voltage"]}
        s = VOLTAGE_STATUS[None]
        return {"status_cls": "down", "status_text": s["text"], "icon": s["icon"], "voltage": s["voltage"]}

    if is_down:
        return {"status_cls": "down", "status_text": "Світло ВІДСУТНЄ", "icon": "icon_off.png", "voltage": None}

    return {"status_cls": "up", "status_text": "Світло є", "icon": "icon_on.png", "voltage": None}


def _build_update_fragments() -> dict:
    """Build HTML fragments for partial dashboard update (no full reload)."""
    is_down = kv_get("power_down") == "1"
    voltage_anomaly = kv_get("voltage_anomaly") == "1"
    hb = recent_heartbeats(30)
    ev = recent_events(30)

    mk_cls = "down"
    mk_text = "Роутер: немає даних"
    if hb:
        last_hb_age = int(time.time() - hb[0]["ts"])
        mk_online = last_hb_age < STALE_THRESHOLD_SEC
        mk_cls = "up" if mk_online else "down"
        ts_abs = datetime.fromtimestamp(hb[0]["ts"], tz=UA_TZ).strftime("%Y.%m.%d %H:%M:%S")
        age_str = f"{last_hb_age}с тому" if mk_online else f"{last_hb_age // 60} хв тому"
        mk_text = f"Роутер: online ({age_str}, {ts_abs})" if mk_online else f"Роутер: OFFLINE ({age_str}, {ts_abs})"

    duration_text = _power_status_text() if (hb or ev) else ""
    schedule_note = ""
    if dtek.schedule_cache and dtek.schedule_cache.get("today"):
        now_kyiv = datetime.now(UA_TZ)
        slot_idx = now_kyiv.hour * 2 + (1 if now_kyiv.minute >= 30 else 0)
        slot_val = dtek.schedule_cache["today"]["grid"][min(slot_idx, 47)]
        if is_down:
            schedule_note = "\U0001f4c5 Заплановане відключення" if slot_val == "off" else "\U0001f4c5 Можливе відключення (за графіком)" if slot_val == "maybe" else "\u26a1Позапланове відключення"
        else:
            schedule_note = "\U0001f389 Світло є (всупереч графіку)" if slot_val == "off" else "\U0001f4c5 За графіком (можливе відкл. не сталось)" if slot_val == "maybe" else "\U0001f4c5 За графіком"

    status = get_display_status()
    status_cls = status["status_cls"]
    status_text = status["status_text"]
    icon = status["icon"]
    dur_ext = f"&nbsp;&nbsp;{schedule_note}" if schedule_note else ""

    hb_rows = ""
    for r in hb:
        c204 = "down" if r["plug204"] == 0 else "up"
        c175 = "down" if r["plug175"] == 0 else "up"
        hb_rows += f'<tr><td>{_ts_fmt(r["ts"])}</td><td class="{c204}">{r["plug204"]}/3</td><td class="{c175}">{r["plug175"]}/3</td></tr>\n'

    _ev_labels = {"down": "Пропало", "up": "З'явилось", "voltage_high": "Висока напруга", "voltage_low": "Низька напруга", "voltage_issue": "Проблема напруги"}
    _ev_downlike = ("down", "voltage_high", "voltage_low", "voltage_issue")
    ev_rows = ""
    for i, e in enumerate(ev):
        cls = "down" if e["event"] in _ev_downlike else "up"
        label = _ev_labels.get(e["event"], e["event"])
        if i == 0:
            dur_sec = int(time.time() - e["ts"])
            dur_fmt = _format_duration(dur_sec)
            in_down_state = (e["event"] in _ev_downlike) and (is_down or voltage_anomaly)
            dur_str = f"нема {dur_fmt} ▸" if in_down_state else f"є {dur_fmt} ▸" if (e["event"] == "up" and not is_down and not voltage_anomaly) else dur_fmt
        else:
            dur_sec = int(ev[i - 1]["ts"] - e["ts"])
            dur_str = _format_duration(dur_sec) if dur_sec > 0 else ""
        ev_kyiv = datetime.fromtimestamp(e["ts"], tz=UA_TZ)
        ev_date_str = ev_kyiv.strftime("%Y-%m-%d")
        ev_grid = None
        for dk in ("today", "tomorrow"):
            d = dtek.schedule_cache.get(dk) if dtek.schedule_cache else None
            if d and d["date"] == ev_date_str:
                ev_grid = d["grid"]
                break
        if ev_grid is None:
            sh = schedule_history_for_date(ev_date_str)
            ev_grid = sh[-1]["grid"] if sh else None
        sched_tag = ""
        if ev_grid and len(ev_grid) >= 48:
            is_down_ev = e["event"] in _ev_downlike
            ev_min = ev_kyiv.hour * 60 + ev_kyiv.minute
            best_dev: int | None = None
            for si in range(1, 48):
                p_ok = ev_grid[si - 1] == "ok"
                c_ok = ev_grid[si] == "ok"
                t_min = si * 30
                if is_down_ev and p_ok and not c_ok:
                    d2 = ev_min - t_min
                    if best_dev is None or abs(d2) < abs(best_dev):
                        best_dev = d2
                elif not is_down_ev and not p_ok and c_ok:
                    d2 = ev_min - t_min
                    if best_dev is None or abs(d2) < abs(best_dev):
                        best_dev = d2
            if best_dev is not None and abs(best_dev) <= 30:
                sched_tag = f'\U0001f4c5 {dtek.fmt_deviation(best_dev)}'
            else:
                sched_tag = '<span style="color:#fbbf24">\u26a1позапл.</span>'
        ev_rows += f'<tr><td>{_ts_fmt_full(e["ts"])}</td><td class="{cls}">{label}</td><td style="color:var(--muted)">{sched_tag}</td><td style="color:var(--muted)">{dur_str}</td></tr>\n'

    tg_rows = ""
    for t in recent_tg_log(15):
        ok = "up" if t["status"] == 200 else "down"
        short_chat = "test" if t["chat_id"] == TG_TEST_CHAT_ID else "prod"
        safe_text = t["text"].replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br>")
        tg_rows += f'<tr><td>{_ts_fmt_full(t["ts"])}</td><td class="{ok}">{t["status"]}</td><td>{short_chat}</td><td>{safe_text}</td></tr>\n'

    alert_ev_rows = ""
    alert_ev = recent_alert_events(20)
    for i, ae in enumerate(alert_ev):
        cls = "down" if ae["event"] == "alert_on" else "up"
        label = "\U0001f534 Тривога" if ae["event"] == "alert_on" else "\U0001f7e2 Відбій"
        if i == 0:
            dur_sec = int(time.time() - ae["ts"])
            dur_str = f"{_format_duration(dur_sec)} \u25b8" if ((ae["event"] == "alert_on" and dtek.alert_cache.get("active")) or (ae["event"] == "alert_off" and not dtek.alert_cache.get("active"))) else _format_duration(dur_sec)
        else:
            dur_sec = int(alert_ev[i - 1]["ts"] - ae["ts"])
            dur_str = _format_duration(dur_sec) if dur_sec > 0 else ""
        alert_ev_rows += f'<tr><td>{_ts_fmt_full(ae["ts"])}</td><td class="{cls}">{label}</td><td style="color:var(--muted)">{dur_str}</td></tr>\n'

    deye_log = recent_deye_log(30)
    deye_summary = "Немає даних"
    deye_summary_line2 = ""
    deye_rows = ""
    if deye_log:
        last = deye_log[0]
        load_w = last.get("load_power_w")
        soc = last.get("battery_soc")
        v1, v2, v3 = last.get("grid_v_l1"), last.get("grid_v_l2"), last.get("grid_v_l3")
        age_sec = int(time.time() - last["ts"])
        sep = " · "
        parts_rt, parts_tot = [], []
        if load_w is not None:
            parts_rt.append(f"Споживання: {int(load_w)} Вт")
        grid_w = last.get("grid_power_w")
        if grid_w is not None:
            sign = "+" if grid_w >= 0 else "−"
            parts_rt.append(f"Мережа: {sign}{abs(int(grid_w))} Вт")
        if any(x is not None for x in (v1, v2, v3)):
            v_parts = [f"L{n}={int(v)}" for n, v in ((1, v1), (2, v2), (3, v3)) if v is not None]
            parts_rt.append("Напруга " + " ".join(v_parts) + " В")
        month_kwh = deye_monthly_load_kwh()
        if month_kwh is not None:
            month_name = ["", "січ", "лют", "бер", "кві", "тра", "чер", "лип", "сер", "вер", "жов", "лис", "гру"][datetime.now(UA_TZ).month]
            parts_tot.append(f"За {month_name}: {month_kwh} кВт·год")
        day_kwh = last.get("day_load_kwh")
        if day_kwh is not None:
            parts_tot.append(f"День (інв.): {round(day_kwh, 1)} кВт·год")
        total_kwh = last.get("total_load_kwh")
        if total_kwh is not None:
            parts_tot.append(f"Всього (інв.): {round(total_kwh, 1)} кВт·год")
        day_imp = last.get("day_grid_import_kwh")
        day_exp = last.get("day_grid_export_kwh")
        if day_imp is not None or day_exp is not None:
            imp_s = f"{round(day_imp, 1)}" if day_imp is not None else "—"
            exp_s = f"{round(day_exp, 1)}" if day_exp is not None else "—"
            parts_tot.append(f"Мережа день: імпорт {imp_s} / експорт {exp_s} кВт·год")
        line1 = sep.join(parts_rt) if parts_rt else "Дані отримано"
        line2_tot = sep.join(parts_tot) if parts_tot else ""
        age_span = f' <span style="opacity:0.85">({age_sec}с тому)</span>'
        deye_summary = f"<div class=\"deye-summary\">{line1}{'<br>' + line2_tot if line2_tot else ''}{age_span}</div>"
        if DEYE_BATTERY_KWH > 0 and soc is not None:
            cap_kwh = DEYE_BATTERY_KWH
            consumed_kwh = cap_kwh * (100 - soc) / 100
            remaining_kwh = cap_kwh * soc / 100
            parts2 = [f"{cap_kwh:.0f} кВт·год", f"АКБ: {int(soc)}%", f"спожито {consumed_kwh:.1f}", f"залиш. {remaining_kwh:.1f}"]
            if load_w is not None and load_w > 0 and remaining_kwh > 0:
                hrs = remaining_kwh / (load_w / 1000)
                time_str = f"{int(hrs//24)}д {int(hrs%24)}год" if hrs >= 24 else f"{int(hrs)}год {int((hrs%1)*60)}хв" if hrs >= 1 else f"{int(hrs*60)}хв"
                parts2.append(f"~{time_str} до 0")
            deye_summary_line2 = sep.join(parts2)
        for r in deye_log:
            load_w = r.get("load_power_w")
            soc = r.get("battery_soc")
            v1 = r.get("grid_v_l1")
            v2 = r.get("grid_v_l2")
            v3 = r.get("grid_v_l3")
            bat_w = r.get("battery_power_w")
            grid_w = r.get("grid_power_w")
            load_s = f"{int(load_w)}" if load_w is not None else "—"
            soc_s = f"{int(soc)}" if soc is not None else "—"
            grid_s = f"{int(grid_w)}" if grid_w is not None else "—"
            v1_s = f"{v1:.1f}" if v1 is not None else "—"
            v2_s = f"{v2:.1f}" if v2 is not None else "—"
            v3_s = f"{v3:.1f}" if v3 is not None else "—"
            bat_s = f"{int(bat_w)}" if bat_w is not None else "—"
            deye_rows += f'<tr><td>{_ts_fmt_full(r["ts"])}</td><td>{load_s}</td><td>{grid_s}</td><td>{soc_s}</td><td>{v1_s}</td><td>{v2_s}</td><td>{v3_s}</td><td>{bat_s}</td></tr>\n'

    deye_daily_rows = ""
    for d in deye_daily_load_kwh():
        load_s = f'{d["load_kwh"]}' if d.get("load_kwh") is not None else "—"
        grid_s = f'{d["grid_kwh"]}' if d.get("grid_kwh") is not None else "—"
        int_s = f'{d["integrated_kwh"]}'
        hr_rows = ""
        for h in d.get("hours", []):
            hr_rows += f'<tr><td>{h["hour"]:02d}:00–{h["hour"]+1:02d}:00</td><td>{h["kwh"]} кВт·год</td></tr>\n'
        hr_table = f'<table style="margin-top:0.4rem;font-size:0.85rem"><tr><th>Година</th><th>кВт·год</th></tr>{hr_rows}</table>' if d.get("hours") else ""
        deye_daily_rows += f'<tr><td><details style="margin:0.2rem 0"><summary>{d["date"]}</summary>{hr_table}</details></td><td>{load_s}</td><td>{grid_s}</td><td>{int_s}</td><td>{d["samples"]}</td></tr>\n'

    battery_daily, battery_monthly = deye_battery_episodes_for_month()
    deye_battery_html = ""
    if battery_daily or battery_monthly["cycles"] > 0:
        month_name = ["", "січ", "лют", "бер", "кві", "тра", "чер", "лип", "сер", "вер", "жов", "лис", "гру"][datetime.now(UA_TZ).month]
        m = battery_monthly
        summary_parts = [f"{m['cycles']} епізодів"]
        if DEYE_BATTERY_KWH > 0 and m["discharge_kwh"] > 0:
            efc = m["discharge_kwh"] / DEYE_BATTERY_KWH
            summary_parts.append(f"{efc:.2f} екв. циклів")
        if m["charge_kwh"] > 0:
            summary_parts.append(f"заряд +{m['charge_kwh']} кВт·год")
        if m["discharge_kwh"] > 0:
            summary_parts.append(f"розряд −{m['discharge_kwh']} кВт·год")
        bat_rows = ""
        for d in battery_daily:
            all_ep = [{"t": "розряд", **x} for x in d["discharges"]] + [{"t": "заряд", **x} for x in d["charges"]]
            all_ep.sort(key=lambda e: e["ts_start"])
            parts = []
            for x in all_ep:
                sf = int(x["soc_from"]) if x.get("soc_from") is not None else "?"
                st = int(x["soc_to"]) if x.get("soc_to") is not None else "?"
                t1 = datetime.fromtimestamp(x["ts_start"], tz=UA_TZ).strftime("%H:%M")
                t2 = datetime.fromtimestamp(x["ts_end"], tz=UA_TZ).strftime("%H:%M")
                dur = x.get("charge_duration_h") if x.get("t") == "заряд" and x.get("charge_duration_h") is not None else (x["ts_end"] - x["ts_start"]) / 3600
                parts.append(f"{x['t']} {sf}%→{st}% ({x['kwh']} кВт·год) {t1}–{t2}, {dur:.1f} год")
            if parts:
                bat_rows += f'<tr><td>{d["date"]}</td><td style="font-size:0.85rem">{("<br>").join(parts)}</td></tr>\n'
        deye_battery_html = f'<details id="deye_battery_details" data-ls-key="deye_battery_open" data-default-open="1"><summary style="font-size:0.85rem;color:var(--muted)">АКБ: розряд та заряд (за {month_name}: {", ".join(summary_parts)})</summary><table style="margin-top:0.4rem;font-size:0.85rem"><tr><th>День</th><th>Епізоди</th></tr>{bat_rows}</table></details>'

    deye_cumulative_table = _build_deye_cumulative_table(deye_log[0] if deye_log else None)

    deye_grid_html = ""
    if deye_log:
        last = deye_log[0]
        tot_imp = last.get("total_grid_import_kwh")
        tot_exp = last.get("total_grid_export_kwh")
        if tot_imp is not None or tot_exp is not None:
            imp_s = f"{round(tot_imp, 1)} кВт·год" if tot_imp is not None else "—"
            exp_s = f"{round(tot_exp, 1)} кВт·год" if tot_exp is not None else "—"
            deye_grid_html = (
                f'<details id="deye_grid_details" data-ls-key="deye_grid_open" data-default-open="0">'
                f'<summary style="font-size:0.85rem;color:var(--muted)">Grid (на вводі): всього імпорт {imp_s} / експорт {exp_s}</summary>'
                f'<div style="font-size:0.85rem;margin-top:0.3rem">Імпорт = взято з мережі (заряд АКБ + споживання). Експорт = віддано в мережу.</div></details>'
            )

    voltage_rows = ""
    voltage_summary = "Немає даних"
    if deye_log:
        last_v = deye_log[0]
        v1, v2, v3 = last_v.get("grid_v_l1"), last_v.get("grid_v_l2"), last_v.get("grid_v_l3")
        age_v = int(time.time() - last_v["ts"])
        if any(x is not None for x in (v1, v2, v3)):
            v_parts = [f"L{n}={int(v)} В" for n, v in ((1, v1), (2, v2), (3, v3)) if v is not None]
            voltage_summary = " ".join(v_parts) + f" ({age_v}с тому)"
        for r in deye_log[:20]:
            v1_s = f"{int(r['grid_v_l1'])}" if r.get("grid_v_l1") is not None else "—"
            v2_s = f"{int(r['grid_v_l2'])}" if r.get("grid_v_l2") is not None else "—"
            v3_s = f"{int(r['grid_v_l3'])}" if r.get("grid_v_l3") is not None else "—"
            voltage_rows += f'<tr><td>{_ts_fmt_full(r["ts"])}</td><td>{v1_s}</td><td>{v2_s}</td><td>{v3_s}</td></tr>\n'
    voltage_html = (
        f'<div class="mk up" style="margin-bottom:0.5rem;color:var(--muted)">\U0001f4a0 {voltage_summary}</div>'
        f'<details open data-ls-key="voltage_history_open" data-default-open="0">'
        f'<summary style="font-size:0.85rem;color:var(--muted)">Історія напруги</summary>'
        f'<table><tr><th>Час</th><th>L1 В</th><th>L2 В</th><th>L3 В</th></tr>{voltage_rows}</table></details>'
    )

    alert_html = ""
    if dtek.alert_cache:
        alert_html = '<div class="alert-banner alert-on">\U0001f534 \u0422\u0440\u0438\u0432\u043e\u0433\u0430!</div>' if dtek.alert_cache.get("active") else '<div class="alert-banner alert-off">\U0001f7e2 \u0412\u0456\u0434\u0431\u0456\u0439</div>'

    weather_html = ""
    if dtek.weather_cache and dtek.weather_cache.get("temp") is not None:
        w = dtek.weather_cache
        temp = w["temp"]
        sign = "+" if temp > 0 else ""
        emoji = WMO_EMOJI.get(w.get("code", -1), "\U0001f321\ufe0f")
        wind = w.get("wind", 0) or 0
        hum = w.get("humidity", 0) or 0
        minmax = ""
        if w.get("t_min") is not None and w.get("t_max") is not None:
            t_lo, t_hi = w["t_min"], w["t_max"]
            s_lo = "+" if t_lo > 0 else ""
            s_hi = "+" if t_hi > 0 else ""
            minmax = f' ({s_lo}{t_lo:.0f}..{s_hi}{t_hi:.0f}\u00b0)'
        weather_html = f'<div class="weather">{emoji} {sign}{temp:.0f}\u00b0C{minmax} &nbsp; \U0001f4a8 {wind:.0f} \u043a\u043c/\u0433 &nbsp; \U0001f4a7 {hum:.0f}%</div>'

    return {
        "pm_status_block": f'<div class="status {status_cls}"><img src="/icons/{icon}" style="width:48px;height:48px;border-radius:50%;vertical-align:middle;margin-right:0.5rem">{status_text}</div><div class="duration">{duration_text}{dur_ext}</div>',
        "pm_sched": _build_schedule_inner(is_down),
        "pm_weather": weather_html,
        "pm_alert": alert_html,
        "pm_mk": f'<div class="mk {mk_cls}" id="mkStatus">{mk_text}</div>',
        "pm_ev_tbody": ev_rows,
        "pm_hb_tbody": hb_rows,
        "pm_tg_tbody": tg_rows,
        "pm_alert_ev_tbody": alert_ev_rows,
        "pm_deye": f'<div class="{"mk up" if deye_log else "mk"}" style="margin-bottom:0.5rem;color:var(--muted)">⚡ {deye_summary}{f"<br>{deye_summary_line2}" if deye_summary_line2 else ""}</div>{deye_battery_html}{deye_cumulative_table}{deye_grid_html}<details id="deye_daily_details" open data-ls-key="deye_daily_open" data-default-open="1"><summary style="font-size:0.85rem;color:var(--muted)">Споживання по днях</summary><table><tr><th>День</th><th>Load</th><th>Grid</th><th>Інтеграція</th><th>Зразків</th></tr>{deye_daily_rows}</table></details><details id="deye_table_details" open data-ls-key="deye_table_open" data-default-open="1"><summary style="font-size:0.85rem;color:var(--muted)">Історія показників</summary><table><tr><th>Час</th><th>Спожив. (Вт)</th><th>Мережа (Вт)</th><th>АКБ %</th><th>L1 В</th><th>L2 В</th><th>L3 В</th><th>Батарея (Вт)</th></tr>{deye_rows}</table></details>',
        "pm_voltage": voltage_html,
        "pm_plug_state": {"on": "on", "off": "off", "unknown": "unknown"}.get(kv_get("plug_dashboard_state", "unknown"), "unknown"),
        "title": ("❌ Світло нема" if is_down else "✅ Світло є") + " — Power Monitor",
        "favicon": icon,
    }


def _build_deye_cumulative_table(last: dict | None) -> str:
    """Build HTML table for cumulative Load Energy metrics."""
    rows = deye_cumulative_metrics(last)
    trs = ""
    for r in rows:
        v_inv = f"{round(r['value_inv'], 2)} кВт·год" if r["value_inv"] is not None else "—"
        v_int = f"{round(r['value_integrated'], 2)} кВт·год" if r["value_integrated"] is not None else "—"
        trs += f'<tr><td>{r["period"]}</td><td>{r["register"]}</td><td>{r["description"]}</td><td>{v_inv}</td><td>{v_int}</td></tr>\n'
    return (
        '<details id="deye_cumulative_details" open data-ls-key="deye_cumulative_open" data-default-open="1">'
        '<summary style="font-size:0.85rem;color:var(--muted)">Кумулятивні метрики Load та Grid (3PH)</summary>'
        '<table style="margin-top:0.4rem;font-size:0.85rem"><tr><th>Період</th><th>Регістр</th><th>Що показує</th><th>Кумулятивне (інв.)</th><th>Інтеграція</th></tr>'
        f'{trs}</table>'
        '<div style="font-size:0.75rem;color:var(--muted);margin-top:0.3rem">'
        'Load: load_power_w + інтеграція. Grid: тільки лічильник інвертора (у гібридному режимі grid_power_w часто 0).'
        '</div></details>'
    )


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


def _power_status_text() -> str:
    is_down = kv_get("power_down") == "1"
    ev = recent_events(1)
    hb = recent_heartbeats(1)
    now = time.time()

    if ev:
        since_ts = ev[0]["ts"]
    elif hb:
        since_ts = first_heartbeat_ts() or hb[0]["ts"]
    else:
        return "Світло є (немає даних)"

    dur = _format_duration(int(now - since_ts))
    if is_down:
        return f"\u274c Світло ВІДСУТНЄ {dur} (з {_ts_fmt_hm(since_ts)})"
    return f"\u2705 Світло є {dur} (з {_ts_fmt_hm(since_ts)})"


def _ts_fmt_hm(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UA_TZ).strftime("%H:%M")


def _ts_fmt(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UA_TZ).strftime("%H:%M:%S")


def _ts_fmt_full(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UA_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _build_schedule_inner(is_down: bool) -> str:
    """Build schedule grid inner content (for fragment update of pm-sched-content)."""
    if not dtek.schedule_cache:
        return ""
    now_kyiv = datetime.now(UA_TZ)
    current_slot = now_kyiv.hour * 2 + (1 if now_kyiv.minute >= 30 else 0)
    sched_rows = ""
    text_blocks = ""
    for day_key, day_label in (("today", "Сьогодні"), ("tomorrow", "Завтра")):
        day = dtek.schedule_cache.get(day_key)
        if not day:
            continue
        date_str = day["date"][:10] if day["date"] else ""
        cells = ""
        grid = day["grid"]
        for i in range(48):
            cls = "sg-" + grid[i]
            if i % 2 == 0:
                cls += " sg-hr"
            if day_key == "today" and i == current_slot:
                cls += " sg-now sg-now-on" if not is_down else " sg-now sg-now-off"
            cells += f'<td class="{cls}"></td>'
        sched_rows += f'<tr><td class="sg-label">{day_label}<br><span style="font-size:0.7rem;color:var(--muted)">{date_str}</span></td>{cells}</tr>\n'
        text_blocks += dtek.grid_text_summary(grid, date_str, day_label)

    hour_headers = "".join(f'<th colspan="2" class="sg-hdr">{h:02d}</th>' for h in range(24))

    sched_mob_html = ""
    for day_key, day_label in (("today", "Сьогодні"), ("tomorrow", "Завтра")):
        day = dtek.schedule_cache.get(day_key)
        if not day:
            continue
        date_str = day["date"][:10]
        grid = day["grid"]
        sched_mob_html += f'<div class="sg-mob-day">{day_label} <span style="font-size:0.8rem;color:var(--muted)">{date_str}</span></div>\n'
        sched_mob_html += '<table class="sg-table"><colgroup><col span="24"></colgroup>\n'
        for half in range(2):
            start_h = half * 12
            mob_hdr = "".join(f'<th colspan="2" class="sg-hdr">{h:02d}</th>' for h in range(start_h, start_h + 12))
            sched_mob_html += f'<tr>{mob_hdr}</tr>\n'
            cells = ""
            for i in range(half * 24, half * 24 + 24):
                cls = "sg-" + grid[i]
                if i % 2 == 0:
                    cls += " sg-hr"
                if day_key == "today" and i == current_slot:
                    cls += " sg-now sg-now-on" if not is_down else " sg-now sg-now-off"
                cells += f'<td class="{cls}"></td>'
            sched_mob_html += f'<tr>{cells}</tr>\n'
        sched_mob_html += '</table>\n'

    history_html = ""
    for day_key, day_label in (("today", "Сьогодні"), ("tomorrow", "Завтра")):
        day = dtek.schedule_cache.get(day_key)
        if not day:
            continue
        d_str = day["date"][:10]
        history = schedule_history_for_date(d_str)
        if len(history) < 2:
            continue
        hist_rows = ""
        prev_grid = None
        for h in history:
            ts_str = _ts_fmt_full(h["ts"])
            if prev_grid is None:
                diff_text = "Перший графік"
            else:
                diff_text = dtek.describe_grid_diff(prev_grid, h["grid"])
            prev_grid = h["grid"]
            hist_rows += f"<tr><td>{ts_str}</td><td>{diff_text}</td></tr>\n"
        ls_key = f"sched_hist_{day_key}_open"
        history_html += f"""
<details id="sched_hist_{day_key}_details" style="margin-top:0.8rem" data-ls-key="{ls_key}" data-default-open="0">
<summary style="font-size:0.8rem;color:var(--muted)">Зміни графіку на {d_str} — {day_label} ({len(history)})</summary>
<table>
<tr><th>Час</th><th>Що змінилось</th></tr>
{hist_rows}</table>
</details>"""

    inner = f"""<div class="sg-wrap sg-desktop">
<table class="sg-table">
<colgroup><col class="sg-col-label"><col span="48"></colgroup>
<tr><th class="sg-label"></th>{hour_headers}</tr>
{sched_rows}</table>
</div>
<div class="sg-mobile">
{sched_mob_html}</div>
<div class="sg-legend">
<span class="sg-leg-item"><span class="sg-swatch sg-ok"></span> Світло є</span>
<span class="sg-leg-item"><span class="sg-swatch sg-off"></span> Відключення</span>
<span class="sg-leg-item"><span class="sg-swatch sg-maybe"></span> Можливе</span>
<span class="sg-leg-item"><span class="sg-swatch sg-now-demo"></span> Зараз</span>
</div>
<details id="sched_text_details" open data-ls-key="sched_text_open" data-default-open="1">
<summary style="font-size:0.85rem;color:var(--muted)">Текстовий графік відключень</summary>
{text_blocks}
</details>
{history_html}"""

    return inner


def _build_schedule_html(is_down: bool) -> str:
    """Build full schedule details block. Uses pm-sched-content wrapper for fragment updates."""
    inner = _build_schedule_inner(is_down)
    if not inner:
        return ""
    return f"""
<details id="sched_details" open data-ls-key="sched_open" data-default-open="1">
<summary><h2 style="display:inline">Графік відключень (черга {DTEK_QUEUE})</h2></summary>
<div id="pm-sched-content">{inner}</div>
</details>
"""


@app.get("/", response_class=HTMLResponse)
async def dashboard(key: str = Query("")):
    from api.deps import allowed_sections, check_permission

    check_permission(key, "dashboard")
    allowed = allowed_sections(key)
    is_down = kv_get("power_down") == "1"
    voltage_anomaly = kv_get("voltage_anomaly") == "1"
    hb = recent_heartbeats(30)
    ev = recent_events(30)

    if hb:
        last_hb_age = int(time.time() - hb[0]["ts"])
        mk_online = last_hb_age < STALE_THRESHOLD_SEC
        mk_cls = "up" if mk_online else "down"
        ts_abs = datetime.fromtimestamp(hb[0]["ts"], tz=UA_TZ).strftime("%Y.%m.%d %H:%M:%S")
        age_str = f"{last_hb_age}с тому" if mk_online else f"{last_hb_age // 60} хв тому"
        mk_text = f"Роутер: online ({age_str}, {ts_abs})" if mk_online else f"Роутер: OFFLINE ({age_str}, {ts_abs})"
    else:
        mk_cls = "down"
        mk_text = "Роутер: немає даних"

    duration_text = _power_status_text() if (hb or ev) else ""

    schedule_note = ""
    if dtek.schedule_cache and dtek.schedule_cache.get("today"):
        now_kyiv = datetime.now(UA_TZ)
        slot_idx = now_kyiv.hour * 2 + (1 if now_kyiv.minute >= 30 else 0)
        slot_val = dtek.schedule_cache["today"]["grid"][min(slot_idx, 47)]
        if is_down:
            if slot_val == "off":
                schedule_note = "\U0001f4c5 Заплановане відключення"
            elif slot_val == "maybe":
                schedule_note = "\U0001f4c5 Можливе відключення (за графіком)"
            else:
                schedule_note = "\u26a1Позапланове відключення"
        else:
            if slot_val == "off":
                schedule_note = "\U0001f389 Світло є (всупереч графіку)"
            elif slot_val == "maybe":
                schedule_note = "\U0001f4c5 За графіком (можливе відкл. не сталось)"
            else:
                schedule_note = "\U0001f4c5 За графіком"

    hb_rows = ""
    for r in hb:
        c204 = "down" if r["plug204"] == 0 else "up"
        c175 = "down" if r["plug175"] == 0 else "up"
        hb_rows += (
            f'<tr><td>{_ts_fmt(r["ts"])}</td>'
            f'<td class="{c204}">{r["plug204"]}/3</td>'
            f'<td class="{c175}">{r["plug175"]}/3</td></tr>\n'
        )

    # ─── Deye inverter ───
    deye_log = recent_deye_log(30)
    deye_summary = ""
    deye_rows = ""
    if deye_log:
        last = deye_log[0]
        load_w = last.get("load_power_w")
        soc = last.get("battery_soc")
        v1, v2, v3 = last.get("grid_v_l1"), last.get("grid_v_l2"), last.get("grid_v_l3")
        age = int(time.time() - last["ts"])
        parts = []
        if load_w is not None:
            parts.append(f"Споживання: {int(load_w)} Вт")
        grid_w = last.get("grid_power_w")
        if grid_w is not None:
            sign = "+" if grid_w >= 0 else "−"
            parts.append(f"Мережа: {sign}{abs(int(grid_w))} Вт")
        if soc is not None:
            parts.append(f"АКБ: {int(soc)}%")
        if any(x is not None for x in (v1, v2, v3)):
            v_parts = [f"L{n}={int(v)}" for n, v in ((1, v1), (2, v2), (3, v3)) if v is not None]
            parts.append("Напруга " + " ".join(v_parts) + " В")
        month_kwh = deye_monthly_load_kwh()
        if month_kwh is not None:
            month_name = ["", "січ", "лют", "бер", "кві", "тра", "чер", "лип", "сер", "вер", "жов", "лис", "гру"][datetime.now(UA_TZ).month]
            parts.append(f"За {month_name}: {month_kwh} кВт·год")
        day_kwh = last.get("day_load_kwh")
        if day_kwh is not None:
            parts.append(f"День (інв.): {round(day_kwh, 1)} кВт·год")
        total_kwh = last.get("total_load_kwh")
        if total_kwh is not None:
            parts.append(f"Всього (інв.): {round(total_kwh, 1)} кВт·год")
        day_imp = last.get("day_grid_import_kwh")
        day_exp = last.get("day_grid_export_kwh")
        if day_imp is not None or day_exp is not None:
            imp_s = f"{round(day_imp, 1)}" if day_imp is not None else "—"
            exp_s = f"{round(day_exp, 1)}" if day_exp is not None else "—"
            parts.append(f"Мережа день: імпорт {imp_s} / експорт {exp_s} кВт·год")
        sep = " · "
        deye_summary = sep.join(parts) + f" ({age}с тому)" if parts else f"Оновлено {age}с тому"
        deye_daily_rows = ""
        for d in deye_daily_load_kwh():
            load_s = f'{d["load_kwh"]}' if d.get("load_kwh") is not None else "—"
            grid_s = f'{d["grid_kwh"]}' if d.get("grid_kwh") is not None else "—"
            int_s = f'{d["integrated_kwh"]}'
            hr_rows = ""
            for h in d.get("hours", []):
                hr_rows += f'<tr><td>{h["hour"]:02d}:00–{h["hour"]+1:02d}:00</td><td>{h["kwh"]} кВт·год</td></tr>\n'
            hr_table = f'<table style="margin-top:0.4rem;font-size:0.85rem"><tr><th>Година</th><th>кВт·год</th></tr>{hr_rows}</table>' if d.get("hours") else ""
            deye_daily_rows += f'<tr><td><details style="margin:0.2rem 0"><summary>{d["date"]}</summary>{hr_table}</details></td><td>{load_s}</td><td>{grid_s}</td><td>{int_s}</td><td>{d["samples"]}</td></tr>\n'
        battery_daily, battery_monthly = deye_battery_episodes_for_month()
        deye_battery_html = ""
        if battery_daily or battery_monthly["cycles"] > 0:
            month_name = ["", "січ", "лют", "бер", "кві", "тра", "чер", "лип", "сер", "вер", "жов", "лис", "гру"][datetime.now(UA_TZ).month]
            m = battery_monthly
            summary_parts = [f"{m['cycles']} епізодів"]
            if DEYE_BATTERY_KWH > 0 and m["discharge_kwh"] > 0:
                efc = m["discharge_kwh"] / DEYE_BATTERY_KWH
                summary_parts.append(f"{efc:.2f} екв. циклів")
            if m["charge_kwh"] > 0:
                summary_parts.append(f"заряд +{m['charge_kwh']} кВт·год")
            if m["discharge_kwh"] > 0:
                summary_parts.append(f"розряд −{m['discharge_kwh']} кВт·год")
            bat_rows = ""
            for d in battery_daily:
                all_ep = [{"t": "розряд", **x} for x in d["discharges"]] + [{"t": "заряд", **x} for x in d["charges"]]
                all_ep.sort(key=lambda e: e["ts_start"])
                parts_b = []
                for x in all_ep:
                    sf = int(x["soc_from"]) if x.get("soc_from") is not None else "?"
                    st = int(x["soc_to"]) if x.get("soc_to") is not None else "?"
                    t1 = datetime.fromtimestamp(x["ts_start"], tz=UA_TZ).strftime("%H:%M")
                    t2 = datetime.fromtimestamp(x["ts_end"], tz=UA_TZ).strftime("%H:%M")
                    dur = x.get("charge_duration_h") if x.get("t") == "заряд" and x.get("charge_duration_h") is not None else (x["ts_end"] - x["ts_start"]) / 3600
                    parts_b.append(f"{x['t']} {sf}%→{st}% ({x['kwh']} кВт·год) {t1}–{t2}, {dur:.1f} год")
                if parts_b:
                    bat_rows += f'<tr><td>{d["date"]}</td><td style="font-size:0.85rem">{("<br>").join(parts_b)}</td></tr>\n'
            deye_battery_html = f'<details id="deye_battery_details" data-ls-key="deye_battery_open" data-default-open="1"><summary style="font-size:0.85rem;color:var(--muted)">АКБ: розряд та заряд (за {month_name}: {", ".join(summary_parts)})</summary><table style="margin-top:0.4rem;font-size:0.85rem"><tr><th>День</th><th>Епізоди</th></tr>{bat_rows}</table></details>'
        for r in deye_log:
            load_w = r.get("load_power_w")
            soc = r.get("battery_soc")
            v1 = r.get("grid_v_l1")
            v2 = r.get("grid_v_l2")
            v3 = r.get("grid_v_l3")
            bat_w = r.get("battery_power_w")
            grid_w = r.get("grid_power_w")
            load_s = str(int(load_w)) if load_w is not None else "—"
            soc_s = f"{int(soc)}%" if soc is not None else "—"
            grid_s = str(int(grid_w)) if grid_w is not None else "—"
            v1_s = f"{v1:.0f}" if v1 is not None else "—"
            v2_s = f"{v2:.0f}" if v2 is not None else "—"
            v3_s = f"{v3:.0f}" if v3 is not None else "—"
            bat_s = str(int(bat_w)) if bat_w is not None else "—"
            deye_rows += (
                f'<tr><td>{_ts_fmt(r["ts"])}</td>'
                f'<td>{load_s}</td><td>{grid_s}</td><td>{soc_s}</td>'
                f'<td>{v1_s}</td><td>{v2_s}</td><td>{v3_s}</td>'
                f'<td>{bat_s}</td></tr>\n'
            )
    else:
        deye_summary = "Немає даних"
        deye_daily_rows = ""
        deye_battery_html = ""
        deye_rows = ""

    _ev_labels = {"down": "Пропало", "up": "З'явилось", "voltage_high": "Висока напруга", "voltage_low": "Низька напруга", "voltage_issue": "Проблема напруги"}
    _ev_downlike = ("down", "voltage_high", "voltage_low", "voltage_issue")
    ev_rows = ""
    for i, e in enumerate(ev):
        cls = "down" if e["event"] in _ev_downlike else "up"
        label = _ev_labels.get(e["event"], e["event"])
        if i == 0:
            dur_sec = int(time.time() - e["ts"])
            dur_fmt = _format_duration(dur_sec)
            in_down_state = (e["event"] in _ev_downlike) and (is_down or voltage_anomaly)
            if in_down_state:
                dur_str = f"нема {dur_fmt} ▸"
            elif e["event"] == "up" and not is_down and not voltage_anomaly:
                dur_str = f"є {dur_fmt} ▸"
            else:
                dur_str = dur_fmt
        elif i < len(ev):
            dur_sec = int(ev[i - 1]["ts"] - e["ts"])
            dur_str = _format_duration(dur_sec) if dur_sec > 0 else ""
        sched_tag = ""
        ev_kyiv = datetime.fromtimestamp(e["ts"], tz=UA_TZ)
        ev_date_str = ev_kyiv.strftime("%Y-%m-%d")
        ev_grid = None
        for dk in ("today", "tomorrow"):
            d = dtek.schedule_cache.get(dk) if dtek.schedule_cache else None
            if d and d["date"] == ev_date_str:
                ev_grid = d["grid"]
                break
        if ev_grid is None:
            sh = schedule_history_for_date(ev_date_str)
            if sh:
                ev_grid = sh[-1]["grid"]
        if ev_grid:
            is_down_ev = e["event"] in _ev_downlike
            ev_min = ev_kyiv.hour * 60 + ev_kyiv.minute
            best_dev: int | None = None
            for si in range(1, 48):
                p_ok = ev_grid[si - 1] == "ok"
                c_ok = ev_grid[si] == "ok"
                t_min = si * 30
                if is_down_ev and p_ok and not c_ok:
                    d2 = ev_min - t_min
                    if best_dev is None or abs(d2) < abs(best_dev):
                        best_dev = d2
                elif not is_down_ev and not p_ok and c_ok:
                    d2 = ev_min - t_min
                    if best_dev is None or abs(d2) < abs(best_dev):
                        best_dev = d2
            if best_dev is not None and abs(best_dev) <= 30:
                sched_tag = f'\U0001f4c5 {dtek.fmt_deviation(best_dev)}'
            elif best_dev is not None:
                sched_tag = f'<span style="color:#fbbf24">\u26a1позапл.</span>'
            elif is_down_ev:
                sched_tag = f'<span style="color:#fbbf24">\u26a1позапл.</span>'
        ev_rows += (
            f'<tr><td>{_ts_fmt_full(e["ts"])}</td><td class="{cls}">{label}</td>'
            f'<td style="color:var(--muted)">{sched_tag}</td>'
            f'<td style="color:var(--muted)">{dur_str}</td></tr>\n'
        )

    tg_rows = ""
    for t in recent_tg_log(15):
        ok = "up" if t["status"] == 200 else "down"
        short_chat = "test" if t["chat_id"] == TG_TEST_CHAT_ID else "prod"
        safe_text = t["text"].replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br>")
        tg_rows += (
            f'<tr><td>{_ts_fmt_full(t["ts"])}</td>'
            f'<td class="{ok}">{t["status"]}</td>'
            f'<td>{short_chat}</td>'
            f'<td>{safe_text}</td></tr>\n'
        )

    # ─── Deye inverter ───
    deye_log = recent_deye_log(30)
    deye_summary = ""
    deye_summary_line2 = ""
    deye_rows = ""
    if deye_log:
        last = deye_log[0]
        load_w = last.get("load_power_w")
        soc = last.get("battery_soc")
        v1, v2, v3 = last.get("grid_v_l1"), last.get("grid_v_l2"), last.get("grid_v_l3")
        age_sec = int(time.time() - last["ts"])
        parts1 = []
        if load_w is not None:
            parts1.append(f"Споживання: {int(load_w)} Вт")
        grid_w = last.get("grid_power_w")
        if grid_w is not None:
            sign = "+" if grid_w >= 0 else "−"
            parts1.append(f"Мережа: {sign}{abs(int(grid_w))} Вт")
        if any(x is not None for x in (v1, v2, v3)):
            v_parts = [f"L{n}={int(v)}" for n, v in ((1, v1), (2, v2), (3, v3)) if v is not None]
            parts1.append("Напруга " + " ".join(v_parts) + " В")
        month_kwh = deye_monthly_load_kwh()
        if month_kwh is not None:
            month_name = ["", "січ", "лют", "бер", "кві", "тра", "чер", "лип", "сер", "вер", "жов", "лис", "гру"][datetime.now(UA_TZ).month]
            parts1.append(f"За {month_name}: {month_kwh} кВт·год")
        day_kwh = last.get("day_load_kwh")
        if day_kwh is not None:
            parts1.append(f"День (інв.): {round(day_kwh, 1)} кВт·год")
        total_kwh = last.get("total_load_kwh")
        if total_kwh is not None:
            parts1.append(f"Всього (інв.): {round(total_kwh, 1)} кВт·год")
        day_imp = last.get("day_grid_import_kwh")
        day_exp = last.get("day_grid_export_kwh")
        if day_imp is not None or day_exp is not None:
            imp_s = f"{round(day_imp, 1)}" if day_imp is not None else "—"
            exp_s = f"{round(day_exp, 1)}" if day_exp is not None else "—"
            parts1.append(f"Мережа день: імпорт {imp_s} / експорт {exp_s} кВт·год")
        sep = " · "
        deye_summary = (sep.join(parts1) if parts1 else "Дані отримано") + f" ({age_sec}с тому)"
        if DEYE_BATTERY_KWH > 0 and soc is not None:
            cap_kwh = DEYE_BATTERY_KWH
            consumed_kwh = cap_kwh * (100 - soc) / 100
            remaining_kwh = cap_kwh * soc / 100
            parts2 = [f"{cap_kwh:.0f} кВт·год", f"АКБ: {int(soc)}%", f"спожито {consumed_kwh:.1f}", f"залиш. {remaining_kwh:.1f}"]
            if load_w is not None and load_w > 0 and remaining_kwh > 0:
                hrs = remaining_kwh / (load_w / 1000)
                if hrs >= 24:
                    d, h = int(hrs // 24), int(hrs % 24)
                    time_str = f"{d}д {h}год" if h else f"{d}д"
                elif hrs >= 1:
                    h, m = int(hrs), int((hrs % 1) * 60)
                    time_str = f"{h}год {m}хв" if m else f"{h}год"
                else:
                    m = int(hrs * 60)
                    time_str = f"{m}хв"
                parts2.append(f"~{time_str} до 0")
            deye_summary_line2 = sep.join(parts2)
        deye_daily_rows = ""
        for d in deye_daily_load_kwh():
            load_s = f'{d["load_kwh"]}' if d.get("load_kwh") is not None else "—"
            grid_s = f'{d["grid_kwh"]}' if d.get("grid_kwh") is not None else "—"
            int_s = f'{d["integrated_kwh"]}'
            hr_rows = ""
            for h in d.get("hours", []):
                hr_rows += f'<tr><td>{h["hour"]:02d}:00–{h["hour"]+1:02d}:00</td><td>{h["kwh"]} кВт·год</td></tr>\n'
            hr_table = f'<table style="margin-top:0.4rem;font-size:0.85rem"><tr><th>Година</th><th>кВт·год</th></tr>{hr_rows}</table>' if d.get("hours") else ""
            deye_daily_rows += f'<tr><td><details style="margin:0.2rem 0"><summary>{d["date"]}</summary>{hr_table}</details></td><td>{load_s}</td><td>{grid_s}</td><td>{int_s}</td><td>{d["samples"]}</td></tr>\n'
        battery_daily, battery_monthly = deye_battery_episodes_for_month()
        deye_battery_html = ""
        if battery_daily or battery_monthly["cycles"] > 0:
            month_name = ["", "січ", "лют", "бер", "кві", "тра", "чер", "лип", "сер", "вер", "жов", "лис", "гру"][datetime.now(UA_TZ).month]
            m = battery_monthly
            summary_parts = [f"{m['cycles']} епізодів"]
            if DEYE_BATTERY_KWH > 0 and m["discharge_kwh"] > 0:
                efc = m["discharge_kwh"] / DEYE_BATTERY_KWH
                summary_parts.append(f"{efc:.2f} екв. циклів")
            if m["charge_kwh"] > 0:
                summary_parts.append(f"заряд +{m['charge_kwh']} кВт·год")
            if m["discharge_kwh"] > 0:
                summary_parts.append(f"розряд −{m['discharge_kwh']} кВт·год")
            bat_rows = ""
            for d in battery_daily:
                all_ep = [{"t": "розряд", **x} for x in d["discharges"]] + [{"t": "заряд", **x} for x in d["charges"]]
                all_ep.sort(key=lambda e: e["ts_start"])
                parts_b = []
                for x in all_ep:
                    sf = int(x["soc_from"]) if x.get("soc_from") is not None else "?"
                    st = int(x["soc_to"]) if x.get("soc_to") is not None else "?"
                    t1 = datetime.fromtimestamp(x["ts_start"], tz=UA_TZ).strftime("%H:%M")
                    t2 = datetime.fromtimestamp(x["ts_end"], tz=UA_TZ).strftime("%H:%M")
                    dur = x.get("charge_duration_h") if x.get("t") == "заряд" and x.get("charge_duration_h") is not None else (x["ts_end"] - x["ts_start"]) / 3600
                    parts_b.append(f"{x['t']} {sf}%→{st}% ({x['kwh']} кВт·год) {t1}–{t2}, {dur:.1f} год")
                if parts_b:
                    bat_rows += f'<tr><td>{d["date"]}</td><td style="font-size:0.85rem">{("<br>").join(parts_b)}</td></tr>\n'
            deye_battery_html = f'<details id="deye_battery_details" data-ls-key="deye_battery_open" data-default-open="1"><summary style="font-size:0.85rem;color:var(--muted)">АКБ: розряд та заряд (за {month_name}: {", ".join(summary_parts)})</summary><table style="margin-top:0.4rem;font-size:0.85rem"><tr><th>День</th><th>Епізоди</th></tr>{bat_rows}</table></details>'
        for r in deye_log:
            load_w = r.get("load_power_w")
            soc = r.get("battery_soc")
            v1 = r.get("grid_v_l1")
            v2 = r.get("grid_v_l2")
            v3 = r.get("grid_v_l3")
            bat_w = r.get("battery_power_w")
            grid_w = r.get("grid_power_w")
            load_s = f"{int(load_w)}" if load_w is not None else "—"
            soc_s = f"{int(soc)}" if soc is not None else "—"
            grid_s = f"{int(grid_w)}" if grid_w is not None else "—"
            v1_s = f"{v1:.1f}" if v1 is not None else "—"
            v2_s = f"{v2:.1f}" if v2 is not None else "—"
            v3_s = f"{v3:.1f}" if v3 is not None else "—"
            bat_s = f"{int(bat_w)}" if bat_w is not None else "—"
            deye_rows += (
                f'<tr><td>{_ts_fmt_full(r["ts"])}</td>'
                f'<td>{load_s}</td><td>{grid_s}</td><td>{soc_s}</td>'
                f'<td>{v1_s}</td><td>{v2_s}</td><td>{v3_s}</td>'
                f'<td>{bat_s}</td></tr>\n'
            )
    else:
        deye_summary = "Немає даних"
        deye_daily_rows = ""
        deye_battery_html = ""
        deye_rows = ""
    deye_cumulative_table = _build_deye_cumulative_table(deye_log[0] if deye_log else None)

    deye_grid_html = ""
    if deye_log:
        last = deye_log[0]
        tot_imp = last.get("total_grid_import_kwh")
        tot_exp = last.get("total_grid_export_kwh")
        if tot_imp is not None or tot_exp is not None:
            imp_s = f"{round(tot_imp, 1)} кВт·год" if tot_imp is not None else "—"
            exp_s = f"{round(tot_exp, 1)} кВт·год" if tot_exp is not None else "—"
            deye_grid_html = (
                f'<details id="deye_grid_details" data-ls-key="deye_grid_open" data-default-open="0">'
                f'<summary style="font-size:0.85rem;color:var(--muted)">Grid (на вводі): всього імпорт {imp_s} / експорт {exp_s}</summary>'
                f'<div style="font-size:0.85rem;margin-top:0.3rem">Імпорт = взято з мережі (заряд АКБ + споживання). Експорт = віддано в мережу.</div></details>'
            )

    # ─── Voltage (L1/L2/L3) standalone block ───
    voltage_rows = ""
    voltage_summary = "Немає даних"
    if deye_log:
        last_v = deye_log[0]
        v1, v2, v3 = last_v.get("grid_v_l1"), last_v.get("grid_v_l2"), last_v.get("grid_v_l3")
        age_v = int(time.time() - last_v["ts"])
        if any(x is not None for x in (v1, v2, v3)):
            v_parts = [f"L{n}={int(v)} В" for n, v in ((1, v1), (2, v2), (3, v3)) if v is not None]
            voltage_summary = " ".join(v_parts) + f" ({age_v}с тому)"
        for r in deye_log[:20]:
            v1_s = f"{int(r['grid_v_l1'])}" if r.get("grid_v_l1") is not None else "—"
            v2_s = f"{int(r['grid_v_l2'])}" if r.get("grid_v_l2") is not None else "—"
            v3_s = f"{int(r['grid_v_l3'])}" if r.get("grid_v_l3") is not None else "—"
            voltage_rows += f'<tr><td>{_ts_fmt_full(r["ts"])}</td><td>{v1_s}</td><td>{v2_s}</td><td>{v3_s}</td></tr>\n'
    voltage_html = (
        f'<div class="mk up" style="margin-bottom:0.5rem;color:var(--muted)">\U0001f4a0 {voltage_summary}</div>'
        f'<details open data-ls-key="voltage_history_open" data-default-open="0">'
        f'<summary style="font-size:0.85rem;color:var(--muted)">Історія напруги</summary>'
        f'<table><tr><th>Час</th><th>L1 В</th><th>L2 В</th><th>L3 В</th></tr>{voltage_rows}</table></details>'
    )

    # ─── Alert events ───
    alert_ev = recent_alert_events(20)
    alert_ev_rows = ""
    for i, ae in enumerate(alert_ev):
        cls = "down" if ae["event"] == "alert_on" else "up"
        label = "\U0001f534 Тривога" if ae["event"] == "alert_on" else "\U0001f7e2 Відбій"
        if i == 0:
            dur_sec = int(time.time() - ae["ts"])
            dur_fmt = _format_duration(dur_sec)
            if ae["event"] == "alert_on" and dtek.alert_cache.get("active"):
                dur_str = f"{dur_fmt} \u25b8"
            elif ae["event"] == "alert_off" and not dtek.alert_cache.get("active"):
                dur_str = f"{dur_fmt} \u25b8"
            else:
                dur_str = dur_fmt
        else:
            dur_sec = int(alert_ev[i - 1]["ts"] - ae["ts"])
            dur_str = _format_duration(dur_sec) if dur_sec > 0 else ""
        alert_ev_rows += (
            f'<tr><td>{_ts_fmt_full(ae["ts"])}</td><td class="{cls}">{label}</td>'
            f'<td style="color:var(--muted)">{dur_str}</td></tr>\n'
        )

    # ─── DTEK schedule grid ───
    schedule_html = _build_schedule_html(is_down)

    # ─── Alert + Weather ───
    alert_html = ""
    if dtek.alert_cache:
        if dtek.alert_cache.get("active"):
            alert_html = '<div class="alert-banner alert-on">\U0001f534 \u0422\u0440\u0438\u0432\u043e\u0433\u0430!</div>'
        else:
            alert_html = '<div class="alert-banner alert-off">\U0001f7e2 \u0412\u0456\u0434\u0431\u0456\u0439</div>'

    weather_html = ""
    if dtek.weather_cache and dtek.weather_cache.get("temp") is not None:
        w = dtek.weather_cache
        temp = w["temp"]
        sign = "+" if temp > 0 else ""
        emoji = WMO_EMOJI.get(w.get("code", -1), "\U0001f321\ufe0f")
        wind = w.get("wind", 0) or 0
        hum = w.get("humidity", 0) or 0
        minmax = ""
        if w.get("t_min") is not None and w.get("t_max") is not None:
            t_lo = w["t_min"]
            t_hi = w["t_max"]
            s_lo = "+" if t_lo > 0 else ""
            s_hi = "+" if t_hi > 0 else ""
            minmax = f' ({s_lo}{t_lo:.0f}..{s_hi}{t_hi:.0f}\u00b0)'
        weather_html = f'<div class="weather">{emoji} {sign}{temp:.0f}\u00b0C{minmax} &nbsp; \U0001f4a8 {wind:.0f} \u043a\u043c/\u0433 &nbsp; \U0001f4a7 {hum:.0f}%</div>'

    now_kyiv = datetime.now(UA_TZ)
    today_str = now_kyiv.strftime("%Y-%m-%d")
    tomorrow_str = (now_kyiv + timedelta(days=1)).strftime("%Y-%m-%d")
    boiler_data = boiler_schedule_for_dates([today_str, tomorrow_str])
    boiler_html = ""
    if boiler_data:
        boiler_lines = ""
        for d, label in [(today_str, "Сьогодні"), (tomorrow_str, "Завтра")]:
            intervals = boiler_data.get(d)
            if not intervals:
                continue
            try:
                dt = datetime.strptime(d, "%Y-%m-%d")
                date_fmt = dt.strftime("%d.%m.%Y")
                weekday = dtek.UA_WEEKDAYS[dt.weekday()]
            except Exception:
                date_fmt = d
                weekday = ""
            ranges = ", ".join(f"{s}-{e}" for s, e in intervals)
            boiler_lines += f'<div style="margin-bottom:0.3rem">\U0001f535 {label}, {date_fmt} ({weekday}): <b>{ranges}</b></div>\n'
        if boiler_lines:
            boiler_html = f"""
<details id="boiler_details" open data-ls-key="boiler_open" data-default-open="1">
<summary><h2 style="display:inline">Графік котельні (генератор)</h2></summary>
{boiler_lines}
</details>
"""
    elif not boiler_data:
        boiler_html = """
<details id="boiler_details" data-ls-key="boiler_open" data-default-open="0">
<summary><h2 style="display:inline">Графік котельні (генератор)</h2></summary>
<div style="color:var(--muted);font-size:0.85rem">Немає даних</div>
</details>
"""

    status = get_display_status()
    status_cls = status["status_cls"]
    status_text = status["status_text"]
    status_icon = status["icon"]

    plug_state_raw = kv_get("plug_dashboard_state", "unknown")
    plug_state = {"on": "Увімкнено", "off": "Вимкнено", "unknown": "невідомо"}.get(plug_state_raw, plug_state_raw)

    is_admin = key in API_KEYS and API_KEYS.get(key) == "admin"
    key_label = API_KEYS.get(key, "")

    legend_html = '<details id="legend_details" data-ls-key="legend_open" data-default-open="0"><summary><h2 style="display:inline">Легенда повідомлень</h2></summary><table><tr><th>Подія</th><th>Повідомлення</th><th>Канал</th></tr><tr><td>Світло зникло</td><td>\u274c 13:03 Світло зникло (\U0001f4c5 За графіком, відхилення +3хв)<br>\U0001f553 Воно було 1д 9год 21хв (03:41 - 13:03)<br>\U0001f4c5 Включення за графіком: ~16:30 - 21:30</td><td>prod</td></tr><tr><td>Світло зникло (позапл.)</td><td>\u274c 02:15 Світло зникло (\u26a1Позапланове, відхилення 1год 30хв)<br>\U0001f553 Воно було 5год 10хв (21:05 - 02:15)<br>\U0001f4a0 Остання напруга: L1=230 В, L2=228 В, L3=231 В</td><td>prod</td></tr><tr><td>Світло з\'явилось</td><td>\u2705 16:34 Світло з\'явилось (\U0001f4c5 За графіком, відхилення -10хв)<br>\U0001f553 Його не було 3год 30хв (13:03 - 16:34)<br>\U0001f4c5 Наступне відключення: ~завтра 10:00 - 13:30</td><td>prod</td></tr><tr><td>Роутер offline</td><td>\u26a0\ufe0f Роутер не відповідає вже N хв</td><td>prod</td></tr><tr><td>/status (є)</td><td>\u2705 Світло є 3год 30хв (з 01:15)</td><td>приват</td></tr><tr><td>/status (нема)</td><td>\u274c Світло ВІДСУТНЄ 15хв (з 23:31)</td><td>приват</td></tr></table></details>'

    return f"""<!DOCTYPE html>
<html lang="uk"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#0f172a">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Світло ЗК6">
<link rel="apple-touch-icon" href="/icons/icon_on.png">
<link rel="manifest" href="/manifest.json?key={key}">
<title>{"❌ " + status_text if status_cls == "down" else "✅ " + status_text} — Power Monitor</title>
<link rel="stylesheet" href="/style.css">
</head><body data-pm-key="{key}" data-pm-down={"1" if status_cls == "down" else "0"}>
<h1>Power Monitor — ЗК 6</h1>
<div id="pm-status-block"><div class="status {status_cls}"><img src="/icons/{status_icon}" style="width:48px;height:48px;border-radius:50%;vertical-align:middle;margin-right:0.5rem">{status_text}</div>
<div class="duration">{duration_text}{f"&nbsp;&nbsp;{schedule_note}" if schedule_note else ""}</div></div>
<div class="clocks" id="clocks"></div>
<div id="pm-weather">{weather_html}</div>
<div id="pm-alert">{alert_html}</div>

<div id="dashboard-sections">
{_wrap_dashboard_section("sched_details", schedule_html, allowed) if schedule_html else ""}
{_wrap_dashboard_section("boiler_details", boiler_html, allowed) if boiler_html else ""}
{f'<div class="dashboard-section" data-section-id="ev_details"><span class="drag-handle" draggable="true" title="Перетягніть для зміни порядку">⋮⋮</span><details id="ev_details" open data-ls-key="ev_open" data-default-open="1"><summary><h2 style="display:inline">Події</h2></summary><table><tr><th>Час</th><th>Подія</th><th>Графік</th><th>Тривалість</th></tr><tbody id="pm-events-tbody">{ev_rows}</tbody></table></details></div>' if "ev_details" in allowed else ""}
{f'<div class="dashboard-section" data-section-id="links_details"><span class="drag-handle" draggable="true" title="Перетягніть для зміни порядку">⋮⋮</span><details id="links_details" open data-ls-key="links_open" data-default-open="1"><summary><h2 style="display:inline">Посилання</h2></summary><table><tr><th>Опис</th><th>Посилання</th></tr><tr><td>Банка на паливо 6 і 6А</td><td><a href="https://send.monobank.ua/jar/7g6rEEejGE" target="_blank" style="color:#6ee7b7">send.monobank.ua/jar/7g6rEEejGE</a></td></tr><tr><td>Збір буд6 (вода, тепло, ДБЖ)</td><td><a href="https://send.monobank.ua/jar/faoUpWcMx" target="_blank" style="color:#6ee7b7">send.monobank.ua/jar/faoUpWcMx</a></td></tr><tr><td>Перевірити оплату зборів</td><td><a href="https://docs.google.com/spreadsheets/d/1q4fEVocWvtaG2-A8x4eFiZkdFAzFRaRTm7NECLcoYTs/edit?gid=2001051359#gid=2001051359" target="_blank" style="color:#6ee7b7">Таблиця зборів по квартирах</a></td></tr><tr><td>Форма на перепуски СКД ліфти</td><td><a href="https://docs.google.com/forms/d/e/1FAIpQLSfE2HdL7oAB88FbcQmCbDW2Du-sF3mhc2RrQE6wTjB_MDEzkg/viewform" target="_blank" style="color:#6ee7b7">Перепуски СКД ліфти Чорновола 6</a></td></tr><tr><td>Оселя Сервіс (ЖУС)</td><td><a href="https://www.oselya.com.ua/brovary/contact" target="_blank" style="color:#6ee7b7">oselya.com.ua/brovary/contact</a></td></tr></table></details></div>' if "links_details" in allowed else ""}
{(f'<div class="dashboard-section" data-section-id="plug_details"><span class="drag-handle" draggable="true" title="Перетягніть для зміни порядку">⋮⋮</span><details id="plug_details" open data-ls-key="plug_open" data-default-open="1"><summary><h2 style="display:inline">Розумна розетка (Nous)</h2></summary><div id="pm-plug" style="margin:0.5rem 0"><span id="plug-state" style="color:var(--muted)">{plug_state}</span><button type="button" id="plug-btn-on" style="margin-left:0.5rem;padding:0.3rem 0.6rem;cursor:pointer">Увімкнути</button><button type="button" id="plug-btn-off" style="margin-left:0.3rem;padding:0.3rem 0.6rem;cursor:pointer">Вимкнути</button></div></details></div>' if "plug_details" in allowed else "")}
{(f'<div class="dashboard-section" data-section-id="alert_ev_details"><span class="drag-handle" draggable="true" title="Перетягніть для зміни порядку">⋮⋮</span><details id="alert_ev_details" data-ls-key="alert_ev_open" data-default-open="0"><summary><h2 style="display:inline">Тривоги</h2></summary><table><tr><th>Час</th><th>Подія</th><th>Тривалість</th></tr><tbody id="pm-alert-events-tbody">{alert_ev_rows}</tbody></table></details></div>' if "alert_ev_details" in allowed else "")}
{(f'<div class="dashboard-section" data-section-id="tg_details"><span class="drag-handle" draggable="true" title="Перетягніть для зміни порядку">⋮⋮</span><details id="tg_details" data-ls-key="tg_open" data-default-open="0"><summary><h2 style="display:inline">Історія повідомлень Telegram</h2></summary><table><tr><th>Час</th><th>HTTP</th><th>Канал</th><th>Текст</th></tr><tbody id="pm-tg-tbody">{tg_rows}</tbody></table></details></div>' if "tg_details" in allowed else "")}
{_wrap_dashboard_section("voltage_details", f'<details id="voltage_details" open data-ls-key="voltage_open" data-default-open="1"><summary><h2 style="display:inline">Напруга мережі</h2></summary><div id="pm-voltage">{voltage_html}</div></details>', allowed) if "voltage_details" in allowed else ""}
{(_wrap_dashboard_section("deye_details", f'<details id="deye_details" data-ls-key="deye_open" data-default-open="0"><summary><h2 style="display:inline">Deye інвертор</h2></summary><div id="pm-deye"><div class="{"mk up" if deye_log else "mk"}" style="margin-bottom:0.5rem;color:var(--muted)">⚡ {deye_summary}{f"<br>{deye_summary_line2}" if deye_summary_line2 else ""}</div>{deye_battery_html}{deye_cumulative_table}{deye_grid_html}<details id="deye_daily_details" open data-ls-key="deye_daily_open" data-default-open="1"><summary style="font-size:0.85rem;color:var(--muted)">Споживання по днях</summary><table><tr><th>День</th><th>Load</th><th>Grid</th><th>Інтеграція</th><th>Зразків</th></tr>{deye_daily_rows}</table></details><details id="deye_table_details" open data-ls-key="deye_table_open" data-default-open="1"><summary style="font-size:0.85rem;color:var(--muted)">Історія показників</summary><table><tr><th>Час</th><th>Спожив. (Вт)</th><th>Мережа (Вт)</th><th>АКБ %</th><th>L1 В</th><th>L2 В</th><th>L3 В</th><th>Батарея (Вт)</th></tr>{deye_rows}</table></details></div></details>', allowed) if "deye_details" in allowed else "")}
{(f'<div class="dashboard-section" data-section-id="hb_details"><span class="drag-handle" draggable="true" title="Перетягніть для зміни порядку">⋮⋮</span><details id="hb_details" data-ls-key="hb_open" data-default-open="0"><summary><h2 style="display:inline">Роутер / Heartbeats</h2></summary><div id="pm-mk-wrap"><div class="mk {mk_cls}" id="mkStatus">{mk_text}</div></div><table><tr><th>Час</th><th>Plug 204</th><th>Plug 175</th></tr><tbody id="pm-hb-tbody">{hb_rows}</tbody></table></details></div>' if "hb_details" in allowed else "")}
{_wrap_dashboard_section("legend_details", legend_html, allowed) if "legend_details" in allowed else ""}
{_wrap_dashboard_section("avatars_details", '<details id="avatars_details" data-ls-key="avatars_open" data-default-open="0"><summary><h2 style="display:inline">Аватарки каналу</h2></summary><table><tr><th>Стан</th><th>Іконка</th><th>Файл</th></tr><tr><td>Світло є (активна)</td><td><img src="/icons/icon_on.png" style="width:64px;height:64px;border-radius:50%"></td><td>icon_on.png</td></tr><tr><td>Світло нема (активна)</td><td><img src="/icons/icon_off.png" style="width:64px;height:64px;border-radius:50%"></td><td>icon_off.png</td></tr><tr><td>Світло нема (v3)</td><td><img src="/icons/icon_off_v3.png" style="width:64px;height:64px;border-radius:50%"></td><td>icon_off_v3.png</td></tr><tr><td>Світло нема (v2)</td><td><img src="/icons/icon_off_v2.png" style="width:64px;height:64px;border-radius:50%"></td><td>icon_off_v2.png</td></tr><tr><td>Висока напруга (v1)</td><td><img src="/icons/icon_high_voltage_v1.png" style="width:64px;height:64px;border-radius:50%"></td><td>icon_high_voltage_v1.png</td></tr><tr><td>Висока напруга (v2)</td><td><img src="/icons/icon_high_voltage_v2.png" style="width:64px;height:64px;border-radius:50%"></td><td>icon_high_voltage_v2.png</td></tr><tr><td>Низька напруга (v1)</td><td><img src="/icons/icon_low_voltage_v1.png" style="width:64px;height:64px;border-radius:50%"></td><td>icon_low_voltage_v1.png</td></tr><tr><td>Низька напруга (v2)</td><td><img src="/icons/icon_low_voltage_v2.png" style="width:64px;height:64px;border-radius:50%"></td><td>icon_low_voltage_v2.png</td></tr></table></details>', allowed) if "avatars_details" in allowed else ""}

</div>

<div class="ver">v <a href="https://github.com/elimS2/power-monitor/commit/{GIT_COMMIT}" target="_blank" rel="noopener">{GIT_COMMIT}</a>{f' · {key_label}' if key_label else ''}{f' · <a href="/admin?key={key}" style="color:var(--muted)">Адмін</a>' if is_admin else ''}</div>
<script src="/app.js?v={GIT_COMMIT}"></script>
</body></html>"""


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(key: str = Query("")):
    """Admin-only page: keys and roles management. Link from dashboard footer."""
    from html import escape
    from json import dumps
    from urllib.parse import quote

    from api.deps import check_admin
    from database import ALL_SECTIONS, SECTION_LABELS, api_key_config_list, role_list

    check_admin(key)
    configs = {c["label"]: c for c in api_key_config_list()}
    roles_data = role_list()
    qk = quote(key, safe="")

    # Keys table rows
    rows = []
    for api_key, label in API_KEYS.items():
        cfg = configs.get(label)
        enabled = cfg["enabled"] if cfg else True
        status = "✅ Увімкнено" if enabled else "❌ Вимкнено"
        preview = api_key[:8] + "…" if len(api_key) > 8 else api_key
        open_url = f"/api/admin/keys/{quote(label, safe='')}/open-dashboard?key={qk}"
        btn = '—' if label == "admin" else (
            f'<button type="button" class="admin-key-toggle btn" data-label="{escape(label)}" '
            f'data-enabled="{str(enabled).lower()}">{"Вимкнути" if enabled else "Увімкнути"}</button>'
        )
        current_role_id = cfg.get("role_id") if cfg else None
        if label == "admin":
            role_sel = "—"
        else:
            role_sel = '<select class="admin-role-select" data-label="' + escape(label) + '" style="font-size:0.85rem;padding:0.2rem">'
            role_sel += '<option value="">— Не встановлено</option>'
            for r in roles_data:
                sel = ' selected' if current_role_id == r["id"] else ''
                role_sel += f'<option value="{r["id"]}"{sel}>{escape(r["name"])}</option>'
            role_sel += "</select>"
        rows.append(
            f'<tr><td>{escape(label)} <small>(<a href="{escape(open_url)}" target="_blank" rel="noopener" style="color:#6ee7b7">'
            f'{escape(preview)}</a>)</small></td><td class="{"up" if enabled else "down"}">{status}</td><td>{role_sel}</td><td>{btn}</td></tr>'
        )
    table_rows = "\n".join(rows)

    # Roles table rows
    role_rows = []
    for r in roles_data:
        sec_list = r["sections"] if r["sections"] else ["(усі)"]
        sec_display = ", ".join(SECTION_LABELS.get(s, s) for s in sec_list[:5])
        if len(sec_list) > 5:
            sec_display += "…"
        edit_btn = "" if r["is_builtin"] else f'<button type="button" class="admin-role-edit btn" data-id="{r["id"]}" data-name="{escape(r["name"])}" data-sections=\'{dumps(r["sections"] or [])}\'>Змінити</button>'
        del_btn = "" if r["is_builtin"] else f'<button type="button" class="admin-role-del btn" data-id="{r["id"]}">Видалити</button>'
        role_rows.append(
            f'<tr><td>{escape(r["name"])}</td><td style="font-size:0.85rem;color:var(--muted)">{escape(sec_display)}</td>'
            f'<td>{"Вбудована" if r["is_builtin"] else "Користувацька"}</td><td>{edit_btn} {del_btn}</td></tr>'
        )
    roles_table_rows = "\n".join(role_rows)

    all_sections_json = dumps(ALL_SECTIONS)
    section_labels_json = dumps(SECTION_LABELS)

    return f"""<!DOCTYPE html>
<html lang="uk"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#0f172a">
<title>Адмін-портал — Power Monitor</title>
<link rel="stylesheet" href="/style.css">
</head><body data-pm-key="{escape(key)}">
<h1>Power Monitor — Адмін-портал</h1>
<p style="margin-bottom:1rem"><a href="/?key={escape(qk)}" style="color:#6ee7b7">← Назад на дашборд</a></p>
<div class="admin-tabs" style="margin-bottom:1.5rem">
  <button type="button" class="admin-tab btn active" data-tab="keys">Ключі API</button>
  <button type="button" class="admin-tab btn" data-tab="roles">Ролі</button>
</div>
<div id="admin-tab-keys">
<h2>Ключі API</h2>
<table>
<tr><th>Ключ</th><th>Стан</th><th>Роль</th><th>Дії</th></tr>
{table_rows}
</table>
</div>
<div id="admin-tab-roles" style="display:none">
<h2>Ролі</h2>
<p style="margin-bottom:0.5rem;color:var(--muted)">Ролі визначають, які секції дашборду бачить ключ.</p>
<button type="button" class="admin-role-create btn" style="margin-bottom:1rem">+ Створити роль</button>
<table>
<tr><th>Назва</th><th>Секції</th><th>Тип</th><th>Дії</th></tr>
{roles_table_rows}
</table>
</div>
<div id="admin-role-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:100;align-items:center;justify-content:center" class="admin-modal">
<div style="background:var(--bg);padding:1.5rem;border-radius:8px;max-width:400px;width:90%">
<h3 id="admin-role-modal-title" style="margin-top:0">Нова роль</h3>
<input type="text" id="admin-role-name" placeholder="Назва ролі" style="width:100%;margin-bottom:1rem;padding:0.4rem">
<div id="admin-role-sections" style="margin-bottom:1rem;max-height:200px;overflow-y:auto"></div>
<button type="button" class="admin-role-save btn">Зберегти</button>
<button type="button" class="admin-role-cancel btn" style="margin-left:0.5rem">Скасувати</button>
</div>
</div>
<div class="ver" style="margin-top:1.5rem"><a href="/?key={escape(qk)}">Дашборд</a></div>
<script src="/app.js?v={GIT_COMMIT}"></script>
<script>
(function() {{
  var key = document.body.getAttribute('data-pm-key') || '';
  if (!key) return;
  var allSections = {all_sections_json};
  var sectionLabels = {section_labels_json};
  function qs() {{ return '?key=' + encodeURIComponent(key); }}
  document.querySelectorAll('.admin-tab').forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      document.querySelectorAll('.admin-tab').forEach(function(b) {{ b.classList.remove('active'); }});
      btn.classList.add('active');
      document.getElementById('admin-tab-keys').style.display = btn.dataset.tab === 'keys' ? 'block' : 'none';
      document.getElementById('admin-tab-roles').style.display = btn.dataset.tab === 'roles' ? 'block' : 'none';
    }});
  }});
  document.querySelectorAll('.admin-key-toggle').forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      var label = btn.dataset.label;
      var enabled = btn.dataset.enabled !== 'true';
      fetch('/api/admin/keys/' + encodeURIComponent(label) + '/enabled' + qs() + '&enabled=' + enabled, {{ method: 'POST' }})
        .then(function(r) {{ return r.json(); }})
        .then(function() {{
          btn.dataset.enabled = enabled;
          btn.textContent = enabled ? 'Вимкнути' : 'Увімкнути';
          var td = btn.closest('tr').querySelector('td:nth-child(2)');
          if (td) {{ td.innerHTML = enabled ? '\\u2705 Увімкнено' : '\\u274c Вимкнено'; td.className = enabled ? 'up' : 'down'; }}
        }});
    }});
  }});
  document.querySelectorAll('.admin-role-select').forEach(function(sel) {{
    sel.addEventListener('change', function() {{
      var label = sel.dataset.label;
      var roleId = sel.value;
      var body = roleId ? {{ role_id: parseInt(roleId) }} : {{ role_id: null }};
      fetch('/api/admin/keys/' + encodeURIComponent(label) + '/permissions' + qs(), {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(body)
      }}).then(function(r) {{ return r.json(); }}).then(function(d) {{
        if (d.ok) {{ var t = document.createElement('span'); t.textContent = ' Збережено'; t.style.color='var(--accent)'; sel.parentElement.appendChild(t); setTimeout(function() {{ t.remove(); }}, 1500); }}
      }});
    }});
  }});
  function buildSectionsCheckboxes(container, selected) {{
    container.innerHTML = '';
    var addAll = document.createElement('label');
    addAll.innerHTML = '<input type="checkbox" id="role-all" ' + (!selected || selected.length === 0 ? 'checked' : '') + '> Усі секції';
    addAll.style.display = 'block';
    addAll.style.marginBottom = '0.5rem';
    container.appendChild(addAll);
    allSections.forEach(function(sid) {{
      var lbl = sectionLabels[sid] || sid;
      var cb = document.createElement('label');
      cb.style.display = 'block';
      cb.style.marginBottom = '0.25rem';
      var checked = !selected || selected.length === 0 || selected.indexOf(sid) >= 0;
      cb.innerHTML = '<input type="checkbox" class="role-section-cb" data-id="' + sid + '" ' + (checked ? 'checked' : '') + '> ' + lbl;
      container.appendChild(cb);
    }});
    addAll.querySelector('input').addEventListener('change', function() {{
      container.querySelectorAll('.role-section-cb').forEach(function(c) {{ c.checked = addAll.querySelector('input').checked; }});
    }});
  }}
  var modal = document.getElementById('admin-role-modal');
  var editingRoleId = null;
  document.querySelector('.admin-role-create').addEventListener('click', function() {{
    editingRoleId = null;
    document.getElementById('admin-role-modal-title').textContent = 'Нова роль';
    document.getElementById('admin-role-name').value = '';
    buildSectionsCheckboxes(document.getElementById('admin-role-sections'), null);
    modal.style.display = 'flex';
  }});
  document.querySelectorAll('.admin-role-edit').forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      editingRoleId = parseInt(btn.dataset.id);
      document.getElementById('admin-role-modal-title').textContent = 'Редагувати роль';
      document.getElementById('admin-role-name').value = btn.dataset.name;
      var sections = JSON.parse(btn.dataset.sections || '[]');
      buildSectionsCheckboxes(document.getElementById('admin-role-sections'), sections);
      modal.style.display = 'flex';
    }});
  }});
  document.querySelector('.admin-role-save').addEventListener('click', function() {{
    var name = document.getElementById('admin-role-name').value.trim();
    if (!name) return;
    var allCb = document.getElementById('role-all');
    var sections = allCb.checked ? null : Array.from(document.querySelectorAll('.role-section-cb:checked')).map(function(c) {{ return c.dataset.id; }});
    var url = editingRoleId ? '/api/admin/roles/' + editingRoleId + qs() : '/api/admin/roles' + qs();
    var method = editingRoleId ? 'PUT' : 'POST';
    var body = {{ name: name, sections: sections }};
    fetch(url, {{ method: method, headers: {{ 'Content-Type': 'application/json' }}, body: JSON.stringify(body) }})
      .then(function(r) {{ return r.json(); }})
      .then(function(d) {{
        if (d.ok) {{ location.reload(); }}
      }});
  }});
  document.querySelector('.admin-role-cancel').addEventListener('click', function() {{ modal.style.display = 'none'; }});
  document.querySelectorAll('.admin-role-del').forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      if (!confirm('Видалити цю роль? Ключі з цією роллю отримають порожній доступ.')) return;
      fetch('/api/admin/roles/' + btn.dataset.id + qs(), {{ method: 'DELETE' }})
        .then(function(r) {{ return r.json(); }})
        .then(function(d) {{ if (d.ok) location.reload(); }});
    }});
  }});
}})();
</script>
</body></html>"""
