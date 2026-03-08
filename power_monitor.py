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
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI, Query, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response

from config import (
    API_KEYS,
    AVATAR_ON_START,
    DASHBOARD_SECTION_ORDER,
    DELETE_PHOTO_MSG,
    DTEK_QUEUE,
    DB_PATH,
    DEYE_BATTERY_KWH,
    GIT_COMMIT,
    OUTAGE_CONFIRM_COUNT,
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
    boiler_schedule_for_dates,
    cleanup_old,
    first_heartbeat_ts,
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


def _wrap_dashboard_section(section_id: str, content: str) -> str:
    """Wrap section HTML in draggable container. Returns empty string if content empty."""
    if not content or not content.strip():
        return ""
    return f'<div class="dashboard-section" data-section-id="{section_id}"><span class="drag-handle" draggable="true" title="Перетягніть для зміни порядку">⋮⋮</span>{content}</div>'


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("power_monitor")


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
_PHOTO_ON = (_ICONS_DIR / "icon_on.png").read_bytes()
_PHOTO_OFF = (_ICONS_DIR / "icon_off.png").read_bytes()


async def _delete_service_msg(client: httpx.AsyncClient, api: str):
    """Send temp message, delete it and the service message before it."""
    r = await client.post(f"{api}/sendMessage", json={"chat_id": TG_CHAT_ID, "text": "."})
    if r.status_code == 200:
        tid = r.json().get("result", {}).get("message_id", 0)
        if tid:
            await client.post(f"{api}/deleteMessage", json={"chat_id": TG_CHAT_ID, "message_id": tid - 1})
            await client.post(f"{api}/deleteMessage", json={"chat_id": TG_CHAT_ID, "message_id": tid})


async def update_chat_photo(is_down: bool):
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
                await asyncio.sleep(2)
                await _delete_service_msg(client, api)
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

        if len(rows) < OUTAGE_CONFIRM_COUNT:
            return

        all_dead = all(r["plug204"] == 0 and r["plug175"] == 0 for r in rows)
        latest_alive = rows[0]["plug204"] > 0 or rows[0]["plug175"] > 0
        is_down = kv_get("power_down") == "1"

        if all_dead and not is_down:
            now = time.time()
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
            msg = f"\u274c {_ts_fmt_hm(now)} Світло зникло{sched_label}"
            if since_ts:
                dur = _format_duration(int(now - since_ts))
                msg += f"\n\U0001f553 Воно було {dur} ({_ts_fmt_hm(since_ts)} - {_ts_fmt_hm(now)})"
            # Для позапланових відключень — показуємо останню напругу (допоможе: вимкнули світло / висока / низька)
            if dev is not None and abs(dev) > 30:
                v = last_nonzero_grid_voltage()
                if v:
                    parts = []
                    for phase, key in (("L1", "grid_v_l1"), ("L2", "grid_v_l2"), ("L3", "grid_v_l3")):
                        val = v.get(key)
                        if val is not None:
                            parts.append(f"{phase}={val:.0f} В")
                        else:
                            parts.append(f"{phase}=—")
                    msg += f"\n\U0001f4a0 Остання напруга: {', '.join(parts)}"
            # Для позапланових відключень не показуємо наступне включення за графіком
            if dev is None or abs(dev) <= 30:
                nxt = dtek.next_schedule_transition(looking_for_on=True)
                if nxt:
                    msg += f"\n\U0001f4c5 Включення за графіком: {nxt}"
            await update_chat_photo(True)
            await tg_send(msg)

        elif latest_alive and is_down:
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
                    sched_label = f" (\u26a1Позапланове, відхилення {dtek.fmt_deviation(dev, signed=False)})"
            msg = f"\u2705 {_ts_fmt_hm(now)} Світло з'явилось{sched_label}"
            if prev:
                since_ts = prev[0]["ts"]
                dur = _format_duration(int(now - since_ts))
                msg += f"\n\U0001f553 Його не було {dur} ({_ts_fmt_hm(since_ts)} - {_ts_fmt_hm(now)})"
            # Планове відключення — завжди показуємо (корисно навіть якщо включення було позаплановим)
            nxt = dtek.next_schedule_transition(looking_for_on=False)
            if nxt:
                msg += f"\n\U0001f4c5 Відключення за графіком: {nxt}"
            await update_chat_photo(False)
            await tg_send(msg)


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

async def bg_loop():
    cleanup_tick = 0
    schedule_tick = 0
    alert_tick = 0
    while True:
        try:
            await watchdog()
            cleanup_tick += 1
            if cleanup_tick >= 2880:  # ~24h at 30s interval
                cleanup_old()
                cleanup_tick = 0
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
        await update_chat_photo(kv_get("power_down") == "1")
    else:
        log.info("Skipping avatar update on start (AVATAR_ON_START=0)")
    log.info("Power monitor started, DB=%s", DB_PATH)
    yield
    task.cancel()


app = FastAPI(title="Power Monitor", lifespan=lifespan)


def _check_key(key: str):
    if key not in API_KEYS:
        raise HTTPException(403, "forbidden")


@app.get("/api/heartbeat")
async def ep_heartbeat(
    plug204: int = Query(0),
    plug175: int = Query(0),
    key: str = Query(""),
):
    _check_key(key)
    save_heartbeat(plug204, plug175)
    kv_set("stale_alerted", "0")
    log.debug("HB plug204=%d plug175=%d", plug204, plug175)
    await analyze()
    return {"ok": True}


@app.get("/api/status")
async def ep_status(key: str = Query("")):
    _check_key(key)
    return {
        "power_down": kv_get("power_down") == "1",
        "heartbeats": recent_heartbeats(20),
        "events": recent_events(30),
    }


def _build_update_fragments() -> dict:
    """Build HTML fragments for partial dashboard update (no full reload)."""
    is_down = kv_get("power_down") == "1"
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

    status_cls = "down" if is_down else "up"
    status_text = "Світло ВІДСУТНЄ" if is_down else "Світло є"
    icon = "icon_off.png" if is_down else "icon_on.png"
    dur_ext = f"&nbsp;&nbsp;{schedule_note}" if schedule_note else ""

    hb_rows = ""
    for r in hb:
        c204 = "down" if r["plug204"] == 0 else "up"
        c175 = "down" if r["plug175"] == 0 else "up"
        hb_rows += f'<tr><td>{_ts_fmt(r["ts"])}</td><td class="{c204}">{r["plug204"]}/3</td><td class="{c175}">{r["plug175"]}/3</td></tr>\n'

    ev_rows = ""
    for i, e in enumerate(ev):
        cls = "down" if e["event"] == "down" else "up"
        label = "Пропало" if e["event"] == "down" else "З'явилось"
        if i == 0:
            dur_sec = int(time.time() - e["ts"])
            dur_fmt = _format_duration(dur_sec)
            dur_str = f"нема {dur_fmt} ▸" if (e["event"] == "down" and is_down) else f"є {dur_fmt} ▸" if (e["event"] == "up" and not is_down) else dur_fmt
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
            is_down_ev = e["event"] == "down"
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
        parts1 = []
        if load_w is not None:
            parts1.append(f"Споживання: {int(load_w)} Вт")
        if soc is not None:
            parts1.append(f"АКБ: {int(soc)}%")
        if v1 is not None and v2 is not None and v3 is not None:
            parts1.append(f"Напруга: {(v1+v2+v3)/3:.0f} В")
        deye_summary = (" | ".join(parts1) if parts1 else "Дані отримано") + f" ({age_sec}с тому)"
        if DEYE_BATTERY_KWH > 0 and soc is not None:
            cap_kwh = DEYE_BATTERY_KWH
            consumed_kwh = cap_kwh * (100 - soc) / 100
            remaining_kwh = cap_kwh * soc / 100
            parts2 = [f"{cap_kwh:.0f} кВт·год", f"спожито {consumed_kwh:.1f}", f"залиш. {remaining_kwh:.1f}"]
            if load_w is not None and load_w > 0 and remaining_kwh > 0:
                hrs = remaining_kwh / (load_w / 1000)
                time_str = f"{int(hrs//24)}д {int(hrs%24)}год" if hrs >= 24 else f"{int(hrs)}год {int((hrs%1)*60)}хв" if hrs >= 1 else f"{int(hrs*60)}хв"
                parts2.append(f"~{time_str} до 0")
            deye_summary_line2 = " | ".join(parts2)
        for r in deye_log:
            load_w = r.get("load_power_w")
            soc = r.get("battery_soc")
            v1 = r.get("grid_v_l1")
            v2 = r.get("grid_v_l2")
            v3 = r.get("grid_v_l3")
            bat_w = r.get("battery_power_w")
            load_s = f"{int(load_w)}" if load_w is not None else "—"
            soc_s = f"{int(soc)}" if soc is not None else "—"
            v1_s = f"{v1:.1f}" if v1 is not None else "—"
            v2_s = f"{v2:.1f}" if v2 is not None else "—"
            v3_s = f"{v3:.1f}" if v3 is not None else "—"
            bat_s = f"{int(bat_w)}" if bat_w is not None else "—"
            deye_rows += f'<tr><td>{_ts_fmt_full(r["ts"])}</td><td>{load_s}</td><td>{soc_s}</td><td>{v1_s}</td><td>{v2_s}</td><td>{v3_s}</td><td>{bat_s}</td></tr>\n'

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
        "pm_weather": weather_html,
        "pm_alert": alert_html,
        "pm_mk": f'<div class="mk {mk_cls}" id="mkStatus">{mk_text}</div>',
        "pm_ev_tbody": ev_rows,
        "pm_hb_tbody": hb_rows,
        "pm_tg_tbody": tg_rows,
        "pm_alert_ev_tbody": alert_ev_rows,
        "pm_deye": f'<div class="{"mk up" if deye_log else "mk"}" style="margin-bottom:0.5rem;color:var(--muted)">⚡ {deye_summary}{f"<br>{deye_summary_line2}" if deye_summary_line2 else ""}</div><details id="deye_table_details" open><summary style="font-size:0.85rem;color:var(--muted)">Історія показників</summary><table><tr><th>Час</th><th>Споживання (Вт)</th><th>АКБ %</th><th>L1 В</th><th>L2 В</th><th>L3 В</th><th>Батарея (Вт)</th></tr>{deye_rows}</table></details>',
        "title": ("❌ Світло нема" if is_down else "✅ Світло є") + " — Power Monitor",
        "favicon": icon,
    }


@app.get("/api/dashboard-fragments")
def ep_dashboard_fragments(key: str = Query("")):
    _check_key(key)
    return JSONResponse(
        _build_update_fragments(),
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@app.get("/api/debug-webhooks")
def ep_debug_webhooks(key: str = Query(""), limit: int = Query(20)):
    _check_key(key)
    with _conn() as db:
        rows = db.execute(
            "SELECT id, chat_id, text, ts FROM webhook_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {"id": r["id"], "chat_id": r["chat_id"], "text": r["text"],
         "ts": datetime.fromtimestamp(r["ts"], UA_TZ).strftime("%Y-%m-%d %H:%M:%S")}
        for r in rows
    ]


@app.get("/api/debug-boiler-parse")
def ep_debug_boiler_parse(key: str = Query(""), text: str = Query("")):
    _check_key(key)
    result = parse_boiler_schedule(text)
    return {"input_len": len(text), "parsed": result}


def _check_admin(key: str):
    _check_key(key)
    if API_KEYS.get(key) != "admin":
        raise HTTPException(403, "admin only")


@app.get("/api/heartbeats")
def ep_heartbeats(
    key: str = Query(""),
    from_ts: float = Query(0),
    to_ts: float = Query(0),
    limit: int = Query(500),
):
    _check_admin(key)
    with _conn() as db:
        if from_ts and to_ts:
            rows = db.execute(
                "SELECT plug204, plug175, ts FROM heartbeats WHERE ts BETWEEN ? AND ? ORDER BY ts",
                (from_ts, to_ts),
            ).fetchall()
        elif from_ts:
            rows = db.execute(
                "SELECT plug204, plug175, ts FROM heartbeats WHERE ts >= ? ORDER BY ts LIMIT ?",
                (from_ts, limit),
            ).fetchall()
        elif to_ts:
            rows = db.execute(
                "SELECT plug204, plug175, ts FROM heartbeats WHERE ts <= ? ORDER BY ts DESC LIMIT ?",
                (to_ts, limit),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT plug204, plug175, ts FROM heartbeats ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/events")
def ep_events(
    key: str = Query(""),
    limit: int = Query(50),
):
    _check_admin(key)
    return recent_events(limit)


@app.post("/api/test-telegram")
async def ep_test_telegram(key: str = Query("")):
    _check_key(key)
    target = TG_TEST_CHAT_ID or TG_CHAT_ID
    status = _power_status_text()
    await tg_send(status, chat_id=target)
    return {"ok": True, "sent_to": target}


@app.post("/api/deye-heartbeat")
async def ep_deye_heartbeat(request: Request, key: str = Query("")):
    """Receive Deye inverter data from local script. Requires API key."""
    _check_key(key)
    data = await request.json()
    save_deye_log(
        load_power_w=data.get("load_power_w"),
        load_l1_w=data.get("load_l1_w"),
        load_l2_w=data.get("load_l2_w"),
        load_l3_w=data.get("load_l3_w"),
        grid_v_l1=data.get("grid_v_l1"),
        grid_v_l2=data.get("grid_v_l2"),
        grid_v_l3=data.get("grid_v_l3"),
        battery_soc=data.get("battery_soc"),
        battery_power_w=data.get("battery_power_w"),
        battery_voltage=data.get("battery_voltage"),
    )
    return {"ok": True}


@app.post("/api/tg-webhook")
async def tg_webhook(request: Request):
    secret = request.headers.get("x-telegram-bot-api-secret-token", "")
    if secret != TG_WEBHOOK_SECRET:
        raise HTTPException(403, "forbidden")
    data = await request.json()

    msg = data.get("message") or data.get("channel_post") or {}
    text = (msg.get("text") or "").strip()
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    if not chat_id:
        return {"ok": True}
    cid = str(chat_id)

    log.info("TG webhook: chat=%s text_len=%d text_preview=%r", cid, len(text), text[:200])

    with _conn() as db:
        db.execute(
            "INSERT INTO webhook_log(chat_id, text, raw_json, ts) VALUES(?,?,?,?)",
            (cid, text, json.dumps(data, ensure_ascii=False), time.time()),
        )

    fwd = msg.get("forward_origin") or msg.get("forward_from_chat") or {}
    fwd_text = text

    boiler_parsed = parse_boiler_schedule(fwd_text)
    if boiler_parsed:
        for entry in boiler_parsed:
            save_boiler_schedule(entry["date"], entry["intervals"], fwd_text)
        log.info("Boiler schedule parsed: %d day(s) from chat %s", len(boiler_parsed), cid)
        return {"ok": True}

    if text == "/start":
        await tg_send(
            "Привіт! Натисни /status або скористайся меню, щоб дізнатися чи є світло.",
            chat_id=cid,
        )
    elif text == "/status":
        status = _power_status_text()
        await tg_send(status, chat_id=cid)

    return {"ok": True}


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


_ALLOWED_ICONS = {p.name for p in _ICONS_DIR.glob("icon_*.png")}

@app.get("/icons/{name}")
async def serve_icon(name: str):
    if name not in _ALLOWED_ICONS:
        raise HTTPException(404)
    data = (_ICONS_DIR / name).read_bytes()
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/manifest.json")
async def pwa_manifest(key: str = Query("")):
    _check_key(key)
    return JSONResponse(
        {
            "name": "Power Monitor — ЗК 6",
            "short_name": "Світло ЗК6",
            "start_url": f"/?key={key}",
            "scope": "/",
            "display": "standalone",
            "background_color": "#0f172a",
            "theme_color": "#0f172a",
            "icons": [
                {"src": "/icons/icon_on.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
            ],
        },
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/sw.js")
async def service_worker():
    sw_code = """\
const CACHE = 'pm-v2';
const PRECACHE = ['/icons/icon_on.png', '/icons/icon_off.png'];
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(PRECACHE)));
  self.skipWaiting();
});
self.addEventListener('activate', e => {
  e.waitUntil(self.clients.claim());
});
self.addEventListener('fetch', e => {
  if (e.request.mode === 'navigate') return;
  if (e.request.url.includes('dashboard-fragments')) return;
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
"""
    return Response(
        content=sw_code,
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


@app.get("/", response_class=HTMLResponse)
async def dashboard(key: str = Query("")):
    _check_key(key)
    is_down = kv_get("power_down") == "1"
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
        v_avg = None
        if last.get("grid_v_l1") is not None or last.get("grid_v_l2") is not None or last.get("grid_v_l3") is not None:
            vs = [last.get("grid_v_l1"), last.get("grid_v_l2"), last.get("grid_v_l3")]
            vs = [v for v in vs if v is not None]
            v_avg = round(sum(vs) / len(vs), 0) if vs else None
        age = int(time.time() - last["ts"])
        parts = []
        if load_w is not None:
            parts.append(f"Споживання: {int(load_w)} Вт")
        if soc is not None:
            parts.append(f"АКБ: {int(soc)}%")
        if v_avg is not None:
            parts.append(f"Напруга: {int(v_avg)} В")
        deye_summary = " | ".join(parts) + f" ({age}с тому)" if parts else f"Оновлено {age}с тому"
        for r in deye_log:
            load_w = r.get("load_power_w")
            soc = r.get("battery_soc")
            v1 = r.get("grid_v_l1")
            v2 = r.get("grid_v_l2")
            v3 = r.get("grid_v_l3")
            bat_w = r.get("battery_power_w")
            load_s = str(int(load_w)) if load_w is not None else "—"
            soc_s = f"{int(soc)}%" if soc is not None else "—"
            v1_s = f"{v1:.0f}" if v1 is not None else "—"
            v2_s = f"{v2:.0f}" if v2 is not None else "—"
            v3_s = f"{v3:.0f}" if v3 is not None else "—"
            bat_s = str(int(bat_w)) if bat_w is not None else "—"
            deye_rows += (
                f'<tr><td>{_ts_fmt(r["ts"])}</td>'
                f'<td>{load_s}</td><td>{soc_s}</td>'
                f'<td>{v1_s}</td><td>{v2_s}</td><td>{v3_s}</td>'
                f'<td>{bat_s}</td></tr>\n'
            )
    else:
        deye_summary = "Немає даних"

    ev_rows = ""
    for i, e in enumerate(ev):
        cls = "down" if e["event"] == "down" else "up"
        label = "Пропало" if e["event"] == "down" else "З'явилось"
        if i == 0:
            dur_sec = int(time.time() - e["ts"])
            dur_fmt = _format_duration(dur_sec)
            if e["event"] == "down" and is_down:
                dur_str = f"нема {dur_fmt} ▸"
            elif e["event"] == "up" and not is_down:
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
            is_down_ev = e["event"] == "down"
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
        if soc is not None:
            parts1.append(f"АКБ: {int(soc)}%")
        if v1 is not None and v2 is not None and v3 is not None:
            avg_v = (v1 + v2 + v3) / 3
            parts1.append(f"Напруга: {avg_v:.0f} В")
        deye_summary = " | ".join(parts1) if parts1 else "Дані отримано"
        deye_summary += f" ({age_sec}с тому)"
        if DEYE_BATTERY_KWH > 0 and soc is not None:
            cap_kwh = DEYE_BATTERY_KWH
            consumed_kwh = cap_kwh * (100 - soc) / 100
            remaining_kwh = cap_kwh * soc / 100
            parts2 = [f"{cap_kwh:.0f} кВт·год", f"спожито {consumed_kwh:.1f}", f"залиш. {remaining_kwh:.1f}"]
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
            deye_summary_line2 = " | ".join(parts2)
        for r in deye_log:
            load_w = r.get("load_power_w")
            soc = r.get("battery_soc")
            v1 = r.get("grid_v_l1")
            v2 = r.get("grid_v_l2")
            v3 = r.get("grid_v_l3")
            bat_w = r.get("battery_power_w")
            load_s = f"{int(load_w)}" if load_w is not None else "—"
            soc_s = f"{int(soc)}" if soc is not None else "—"
            v1_s = f"{v1:.1f}" if v1 is not None else "—"
            v2_s = f"{v2:.1f}" if v2 is not None else "—"
            v3_s = f"{v3:.1f}" if v3 is not None else "—"
            bat_s = f"{int(bat_w)}" if bat_w is not None else "—"
            deye_rows += (
                f'<tr><td>{_ts_fmt_full(r["ts"])}</td>'
                f'<td>{load_s}</td><td>{soc_s}</td>'
                f'<td>{v1_s}</td><td>{v2_s}</td><td>{v3_s}</td>'
                f'<td>{bat_s}</td></tr>\n'
            )
    else:
        deye_summary = "Немає даних"

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
    schedule_html = ""
    if dtek.schedule_cache:
        now_kyiv = datetime.now(UA_TZ)
        current_slot = now_kyiv.hour * 2 + (1 if now_kyiv.minute >= 30 else 0)
        sched_rows = ""
        text_blocks = ""
        today_date = ""
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
            if day_key == "today":
                today_date = date_str

        hour_headers = ""
        for h in range(24):
            hour_headers += f'<th colspan="2" class="sg-hdr">{h:02d}</th>'

        mob_grids = []
        for day_key, day_label in (("today", "Сьогодні"), ("tomorrow", "Завтра")):
            day = dtek.schedule_cache.get(day_key)
            if not day:
                continue
            mob_grids.append((day_key, day_label, day["date"][:10], day["grid"]))

        sched_mob_html = ""
        for day_key, day_label, date_str, grid in mob_grids:
            sched_mob_html += f'<div class="sg-mob-day">{day_label} <span style="font-size:0.8rem;color:var(--muted)">{date_str}</span></div>\n'
            sched_mob_html += '<table class="sg-table"><colgroup><col span="24"></colgroup>\n'
            for half in range(2):
                start_h = half * 12
                mob_hdr = ""
                for h in range(start_h, start_h + 12):
                    mob_hdr += f'<th colspan="2" class="sg-hdr">{h:02d}</th>'
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
            det_id = f"sched_hist_{day_key}_details"
            ls_key = f"sched_hist_{day_key}_open"
            history_html += f"""
<details id="{det_id}" style="margin-top:0.8rem">
<summary style="font-size:0.8rem;color:var(--muted)">Зміни графіку на {d_str} — {day_label} ({len(history)})</summary>
<table>
<tr><th>Час</th><th>Що змінилось</th></tr>
{hist_rows}</table>
</details>
<script>
(function(){{
  var d=document.getElementById('{det_id}');
  if(localStorage.getItem('{ls_key}')==='1') d.open=true;
  d.addEventListener('toggle',function(){{ localStorage.setItem('{ls_key}',d.open?'1':'0'); }});
}})();
</script>"""

        schedule_html = f"""
<details id="sched_details" open>
<summary><h2 style="display:inline">Графік відключень (черга {DTEK_QUEUE})</h2></summary>
<div class="sg-wrap sg-desktop">
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
<details id="sched_text_details" open>
<summary style="font-size:0.85rem;color:var(--muted)">Текстовий графік відключень</summary>
{text_blocks}
</details>
<script>
(function(){{
  var d=document.getElementById('sched_text_details');
  if(localStorage.getItem('sched_text_open')==='0') d.open=false;
  d.addEventListener('toggle',function(){{ localStorage.setItem('sched_text_open',d.open?'1':'0'); }});
}})();
</script>
{history_html}
</details>
<script>
(function(){{
  var d=document.getElementById('sched_details');
  if(localStorage.getItem('sched_open')==='0') d.open=false;
  d.addEventListener('toggle',function(){{ localStorage.setItem('sched_open',d.open?'1':'0'); }});
}})();
</script>
"""

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
<details id="boiler_details" open>
<summary><h2 style="display:inline">Графік котельні (генератор)</h2></summary>
{boiler_lines}
</details>
<script>
(function(){{
  var d=document.getElementById('boiler_details');
  if(localStorage.getItem('boiler_open')==='0') d.open=false;
  d.addEventListener('toggle',function(){{ localStorage.setItem('boiler_open',d.open?'1':'0'); }});
}})();
</script>
"""
    elif not boiler_data:
        boiler_html = """
<details id="boiler_details">
<summary><h2 style="display:inline">Графік котельні (генератор)</h2></summary>
<div style="color:var(--muted);font-size:0.85rem">Немає даних</div>
</details>
<script>
(function(){
  var d=document.getElementById('boiler_details');
  if(localStorage.getItem('boiler_open')==='1') d.open=true;
  d.addEventListener('toggle',function(){ localStorage.setItem('boiler_open',d.open?'1':'0'); });
})();
</script>
"""

    status_cls = "down" if is_down else "up"
    status_text = "Світло ВІДСУТНЄ" if is_down else "Світло є"

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
<script>
if('serviceWorker' in navigator){{navigator.serviceWorker.register('/sw.js');}}
</script>
<script>
(function(){{
  var old=document.querySelector('link[rel="icon"]');
  if(old) old.remove();
  var link=document.createElement('link');
  link.rel='icon';link.type='image/png';
  link.href='/icons/{"icon_off.png" if is_down else "icon_on.png"}?t='+Date.now();
  document.head.appendChild(link);
}})();
</script>
<title>{"❌ Світло нема" if is_down else "✅ Світло є"} — Power Monitor</title>
<style>
:root {{ --bg: #0f172a; --card: #1e293b; --border: #334155; --text: #e2e8f0; --muted: #94a3b8; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text);
        max-width: 800px; margin: 0 auto; padding: 1rem; opacity: 0; transition: opacity 0.15s ease; }}
body.pm-ready {{ opacity: 1; }}
h1 {{ text-align: center; font-size: 1.3rem; color: var(--muted); margin-bottom: 1rem; }}
.status {{ text-align: center; font-size: 1.8rem; font-weight: 700; padding: 1.2rem;
           border-radius: 12px; margin-bottom: 1.5rem; }}
.status.up {{ background: #064e3b; color: #6ee7b7; }}
.status.down {{ background: #7f1d1d; color: #fca5a5; animation: pulse 2s infinite; }}
@keyframes pulse {{ 0%,100% {{ opacity:1 }} 50% {{ opacity:.7 }} }}
.duration {{ text-align: center; font-size: 1rem; color: var(--muted); margin-bottom: 0.5rem; }}
.mk {{ text-align: center; font-size: 0.9rem; padding: 0.6rem; border-radius: 8px; margin-bottom: 1.5rem; }}
.mk.up {{ background: #1e293b; color: #6ee7b7; }}
.mk.down {{ background: #7f1d1d; color: #fca5a5; }}
.ver {{ text-align: center; color: #475569; font-size: 0.75rem; margin-top: 2rem; }}
h2 {{ color: var(--muted); font-size: 0.9rem; text-transform: uppercase; letter-spacing: 0.05em;
     margin: 1.2rem 0 0.5rem; }}
summary h2 {{ margin: 0; }}
table {{ width: 100%; border-collapse: collapse; background: var(--card); border-radius: 8px; overflow: hidden; }}
th, td {{ padding: 0.5rem 0.75rem; text-align: left; font-size: 0.9rem; }}
th {{ background: var(--border); color: var(--muted); font-weight: 500; }}
tr:not(:last-child) td {{ border-bottom: 1px solid var(--border); }}
td.up {{ color: #6ee7b7; }}
td.down {{ color: #fca5a5; }}
.btn {{ display: inline-block; padding: 0.5rem 1.2rem; border: none; border-radius: 8px; cursor: pointer;
        font-size: 0.9rem; font-weight: 500; background: #334155; color: #e2e8f0; margin: 0.5rem 0; }}
.btn:hover {{ background: #475569; }}
.btn:active {{ background: #1e293b; }}
.btn-row {{ text-align: center; margin-bottom: 1rem; }}
.clocks {{ display: flex; justify-content: center; gap: 1.5rem; font-size: 0.85rem; color: var(--muted); margin-bottom: 0.3rem; }}
.clocks span {{ white-space: nowrap; }}
.alert-banner {{ text-align: center; font-size: 0.95rem; font-weight: 600; padding: 0.3rem 0; margin-bottom: 0.2rem; border-radius: 6px; }}
.alert-on {{ background: rgba(220,38,38,0.15); color: #fca5a5; }}
.alert-off {{ color: var(--muted); }}
.weather {{ text-align: center; font-size: 0.9rem; color: var(--muted); margin-bottom: 1rem; }}
details {{ margin: 1.2rem 0 0.5rem; }}
summary {{ cursor: pointer; list-style: none; padding: 0.3rem 0; }}
summary::-webkit-details-marker {{ display: none; }}
summary::before {{ content: '▶ '; font-size: 0.7rem; color: var(--muted); }}
details[open] summary::before {{ content: '▼ '; }}
.sg-wrap {{ overflow-x: auto; }}
.sg-mobile {{ display: none; }}
.sg-mob-day {{ font-size: 0.85rem; font-weight: 600; color: var(--text); margin: 0.6rem 0 0.3rem; }}
.sg-mob-day:first-child {{ margin-top: 0; }}
@media (max-width: 768px) {{
  .sg-desktop {{ display: none; }}
  .sg-mobile {{ display: block; }}
}}
.sg-table {{ width: 100%; border-collapse: collapse; table-layout: fixed; background: var(--card); border-radius: 8px; overflow: hidden; }}
.sg-col-label {{ width: 90px; }}
.sg-table th, .sg-table td {{ padding: 0; text-align: center; border: 1px solid var(--border); }}
.sg-hdr {{ font-size: 0.6rem; color: var(--muted); font-weight: 400; padding: 2px 0; }}
.sg-label {{ white-space: nowrap; font-size: 0.75rem; padding: 4px 6px !important; text-align: left; overflow: hidden; }}
.sg-table td:not(.sg-label) {{ height: 22px; }}
.sg-hr {{ border-left: 2px solid #64748b !important; }}
.sg-ok {{ background: #166534; }}
.sg-off {{ background: #000000; }}
.sg-maybe {{ background: #4b5563; }}
.sg-now {{ z-index: 1; position: relative; overflow: visible; }}
.sg-now::after {{ content: "\\26A1"; position: absolute; top: 50%; left: 50%; transform: translate(-50%,-50%); font-size: 11px; line-height: 1; z-index: 2; filter: drop-shadow(0 0 2px currentColor); }}
.sg-now-on {{ box-shadow: inset 0 0 0 2px #facc15, 0 0 10px rgba(250,204,21,0.5); animation: sg-glow 2s ease-in-out infinite; }}
.sg-now-on::after {{ color: #facc15; filter: drop-shadow(0 0 3px #facc15); animation: sg-flash 2s ease-in-out infinite; }}
.sg-now-off {{ box-shadow: inset 0 0 0 3px #0f0f0f, 0 0 8px rgba(0,0,0,0.6); }}
.sg-now-off::after {{ color: #facc15; filter: none; animation: sg-breath 3s ease-in-out infinite; }}
@keyframes sg-breath {{ 0%, 100% {{ opacity: 0.8; }} 50% {{ opacity: 0.1; }} }}
@keyframes sg-glow {{ 0%, 100% {{ box-shadow: inset 0 0 0 2px #facc15, 0 0 10px rgba(250,204,21,0.5); }} 50% {{ box-shadow: inset 0 0 0 2px #fde047, 0 0 16px rgba(250,204,21,0.8); }} }}
@keyframes sg-flash {{ 0%, 100% {{ filter: drop-shadow(0 0 3px #facc15); }} 50% {{ filter: drop-shadow(0 0 6px #fde047) drop-shadow(0 0 10px rgba(250,204,21,0.5)); }} }}
.sg-legend {{ display: flex; gap: 1rem; justify-content: center; margin-top: 0.5rem; font-size: 0.75rem; color: var(--muted); flex-wrap: wrap; }}
.sg-leg-item {{ display: flex; align-items: center; gap: 4px; }}
.sg-swatch {{ display: inline-block; width: 14px; height: 14px; border-radius: 3px; }}
.sg-now-demo {{ width: 14px; height: 14px; border-radius: 3px; background: var(--card); box-shadow: inset 0 0 0 2px #facc15, 0 0 6px rgba(250,204,21,0.4); position: relative; overflow: visible; }}
.sg-now-demo::after {{ content: "\\26A1"; position: absolute; top: 50%; left: 50%; transform: translate(-50%,-50%); font-size: 10px; line-height: 1; color: #facc15; }}
.sg-text {{ font-size: 0.85rem; color: var(--text); margin-top: 0.8rem; line-height: 1.6; }}
.dashboard-section {{ position: relative; margin: 1.2rem 0 0.5rem; padding-left: 1.2rem; }}
.dashboard-section .drag-handle {{ position: absolute; left: 0; top: 0.4rem; cursor: grab; color: var(--muted); font-size: 0.8rem;
  user-select: none; opacity: 0.5; padding: 0.2rem; line-height: 1; }}
.dashboard-section .drag-handle:hover {{ opacity: 1; }}
.dashboard-section .drag-handle:active {{ cursor: grabbing; }}
.dashboard-section.dragging {{ opacity: 0.5; }}
.dashboard-section.drag-over {{ border-top: 2px dashed var(--muted); margin-top: -2px; }}
</style>
</head><body data-pm-key="{key}">
<h1>Power Monitor — ЗК 6</h1>
<div id="pm-status-block"><div class="status {status_cls}"><img src="/icons/{"icon_off.png" if is_down else "icon_on.png"}" style="width:48px;height:48px;border-radius:50%;vertical-align:middle;margin-right:0.5rem">{status_text}</div>
<div class="duration">{duration_text}{f"&nbsp;&nbsp;{schedule_note}" if schedule_note else ""}</div></div>
<div class="clocks" id="clocks"></div>
<script>
function updClocks(){{
  var now=new Date();
  var fmt=function(tz){{return now.toLocaleTimeString('uk-UA',{{timeZone:tz,hour:'2-digit',minute:'2-digit',second:'2-digit'}})}};
  document.getElementById('clocks').innerHTML=
    '<span>Київ '+fmt('Europe/Kyiv')+'</span>'+
    '<span>UTC '+fmt('UTC')+'</span>'+
    '<span>New York '+fmt('America/New_York')+'</span>';
}}
updClocks(); setInterval(updClocks,1000);
</script>
<div id="pm-weather">{weather_html}</div>
<div id="pm-alert">{alert_html}</div>

<div id="dashboard-sections">
{_wrap_dashboard_section("sched_details", schedule_html) if schedule_html else ""}
{_wrap_dashboard_section("boiler_details", boiler_html) if boiler_html else ""}
<div class="dashboard-section" data-section-id="ev_details"><span class="drag-handle" draggable="true" title="Перетягніть для зміни порядку">⋮⋮</span>
<details id="ev_details" open>
<summary><h2 style="display:inline">Події</h2></summary>
<table>
<tr><th>Час</th><th>Подія</th><th>Графік</th><th>Тривалість</th></tr>
<tbody id="pm-events-tbody">{ev_rows}</tbody></table>
</details>
<script>
(function(){{
  var d=document.getElementById('ev_details');
  if(localStorage.getItem('ev_open')==='0') d.open=false;
  d.addEventListener('toggle',function(){{ localStorage.setItem('ev_open',d.open?'1':'0'); }});
}})();
</script>
</div>

<div class="dashboard-section" data-section-id="links_details"><span class="drag-handle" draggable="true" title="Перетягніть для зміни порядку">⋮⋮</span>
<details id="links_details" open>
<summary><h2 style="display:inline">Посилання</h2></summary>
<table>
<tr><th>Опис</th><th>Посилання</th></tr>
<tr><td>Банка на паливо 6 і 6А</td><td><a href="https://send.monobank.ua/jar/7g6rEEejGE" target="_blank" style="color:#6ee7b7">send.monobank.ua/jar/7g6rEEejGE</a></td></tr>
<tr><td>Збір буд6 (вода, тепло, ДБЖ)</td><td><a href="https://send.monobank.ua/jar/faoUpWcMx" target="_blank" style="color:#6ee7b7">send.monobank.ua/jar/faoUpWcMx</a></td></tr>
<tr><td>Перевірити оплату зборів</td><td><a href="https://docs.google.com/spreadsheets/d/1q4fEVocWvtaG2-A8x4eFiZkdFAzFRaRTm7NECLcoYTs/edit?gid=2001051359#gid=2001051359" target="_blank" style="color:#6ee7b7">Таблиця зборів по квартирах</a></td></tr>
<tr><td>Форма на перепуски СКД ліфти</td><td><a href="https://docs.google.com/forms/d/e/1FAIpQLSfE2HdL7oAB88FbcQmCbDW2Du-sF3mhc2RrQE6wTjB_MDEzkg/viewform" target="_blank" style="color:#6ee7b7">Перепуски СКД ліфти Чорновола 6</a></td></tr>
<tr><td>Оселя Сервіс (ЖУС)</td><td><a href="https://www.oselya.com.ua/brovary/contact" target="_blank" style="color:#6ee7b7">oselya.com.ua/brovary/contact</a></td></tr>
</table>
</details>
<script>
(function(){{
  var d=document.getElementById('links_details');
  if(localStorage.getItem('links_open')==='0') d.open=false;
  d.addEventListener('toggle',function(){{ localStorage.setItem('links_open',d.open?'1':'0'); }});
}})();
</script>
</div>

<div class="dashboard-section" data-section-id="alert_ev_details"><span class="drag-handle" draggable="true" title="Перетягніть для зміни порядку">⋮⋮</span>
<details id="alert_ev_details">
<summary><h2 style="display:inline">Тривоги</h2></summary>
<table>
<tr><th>Час</th><th>Подія</th><th>Тривалість</th></tr>
<tbody id="pm-alert-events-tbody">{alert_ev_rows}</tbody></table>
</details>
<script>
(function(){{
  var d=document.getElementById('alert_ev_details');
  if(localStorage.getItem('alert_ev_open')==='1') d.open=true;
  d.addEventListener('toggle',function(){{ localStorage.setItem('alert_ev_open',d.open?'1':'0'); }});
}})();
</script>
</div>

<div class="dashboard-section" data-section-id="tg_details"><span class="drag-handle" draggable="true" title="Перетягніть для зміни порядку">⋮⋮</span>
<details id="tg_details">
<summary><h2 style="display:inline">Історія повідомлень Telegram</h2></summary>
<table>
<tr><th>Час</th><th>HTTP</th><th>Канал</th><th>Текст</th></tr>
<tbody id="pm-tg-tbody">{tg_rows}</tbody></table>
</details>
<script>
(function(){{
  var d=document.getElementById('tg_details');
  if(localStorage.getItem('tg_open')==='1') d.open=true;
  d.addEventListener('toggle',function(){{ localStorage.setItem('tg_open',d.open?'1':'0'); }});
}})();
</script>
</div>

<div class="dashboard-section" data-section-id="deye_details"><span class="drag-handle" draggable="true" title="Перетягніть для зміни порядку">⋮⋮</span>
<details id="deye_details">
<summary><h2 style="display:inline">Deye інвертор</h2></summary>
<div id="pm-deye"><div class="{'mk up' if deye_log else 'mk'}" style="margin-bottom:0.5rem;color:var(--muted)">⚡ {deye_summary}{f'<br>{deye_summary_line2}' if deye_summary_line2 else ''}</div>
<details id="deye_table_details" open>
<summary style="font-size:0.85rem;color:var(--muted)">Історія показників</summary>
<table>
<tr><th>Час</th><th>Споживання (Вт)</th><th>АКБ %</th><th>L1 В</th><th>L2 В</th><th>L3 В</th><th>Батарея (Вт)</th></tr>
{deye_rows}</table>
</details></div>
<script>
(function(){{
  var d=document.getElementById('deye_table_details');
  if(d){{
    var saved=localStorage.getItem('deye_table_open');
    d.open=(saved!=='0');
    d.addEventListener('toggle',function(){{ localStorage.setItem('deye_table_open',d.open?'1':'0'); }});
  }}
}})();
</script>
</details>
<script>
(function(){{
  var d=document.getElementById('deye_details');
  if(localStorage.getItem('deye_open')==='1') d.open=true;
  d.addEventListener('toggle',function(){{ localStorage.setItem('deye_open',d.open?'1':'0'); }});
}})();
</script>
</div>

<div class="dashboard-section" data-section-id="hb_details"><span class="drag-handle" draggable="true" title="Перетягніть для зміни порядку">⋮⋮</span>
<details id="hb_details">
<summary><h2 style="display:inline">Роутер / Heartbeats</h2></summary>
<div id="pm-mk-wrap"><div class="mk {mk_cls}" id="mkStatus">{mk_text}</div></div>
<table>
<tr><th>Час</th><th>Plug 204</th><th>Plug 175</th></tr>
<tbody id="pm-hb-tbody">{hb_rows}</tbody></table>
</details>
<script>
(function(){{
  var d=document.getElementById('hb_details');
  if(localStorage.getItem('hb_open')==='1') d.open=true;
  d.addEventListener('toggle',function(){{ localStorage.setItem('hb_open',d.open?'1':'0'); }});
}})();
</script>
</div>

<div class="dashboard-section" data-section-id="legend_details"><span class="drag-handle" draggable="true" title="Перетягніть для зміни порядку">⋮⋮</span>
<details id="legend_details">
<summary><h2 style="display:inline">Легенда повідомлень</h2></summary>
<table>
<tr><th>Подія</th><th>Повідомлення</th><th>Канал</th></tr>
<tr><td>Світло зникло</td><td>\u274c 13:03 Світло зникло (\U0001f4c5 За графіком, відхилення +3хв)<br>\U0001f553 Воно було 1д 9год 21хв (03:41 - 13:03)<br>\U0001f4c5 Включення за графіком: ~16:30 - 21:30</td><td>prod</td></tr>
<tr><td>Світло зникло (позапл.)</td><td>\u274c 02:15 Світло зникло (\u26a1Позапланове, відхилення 1год 30хв)<br>\U0001f553 Воно було 5год 10хв (21:05 - 02:15)<br>\U0001f4a0 Остання напруга: L1=230 В, L2=228 В, L3=231 В</td><td>prod</td></tr>
<tr><td>Світло з'явилось</td><td>\u2705 16:34 Світло з'явилось (\U0001f4c5 За графіком, відхилення -10хв)<br>\U0001f553 Його не було 3год 30хв (13:03 - 16:34)<br>\U0001f4c5 Відключення за графіком: ~завтра 10:00 - 13:30</td><td>prod</td></tr>
<tr><td>Роутер offline</td><td>\u26a0\ufe0f Роутер не відповідає вже N хв</td><td>prod</td></tr>
<tr><td>/status (є)</td><td>\u2705 Світло є 3год 30хв (з 01:15)</td><td>приват</td></tr>
<tr><td>/status (нема)</td><td>\u274c Світло ВІДСУТНЄ 15хв (з 23:31)</td><td>приват</td></tr>
</table>
</details>
</div>

<div class="dashboard-section" data-section-id="avatars_details"><span class="drag-handle" draggable="true" title="Перетягніть для зміни порядку">⋮⋮</span>
<details id="avatars_details">
<summary><h2 style="display:inline">Аватарки каналу</h2></summary>
<table>
<tr><th>Стан</th><th>Іконка</th><th>Файл</th></tr>
<tr><td>Світло є (активна)</td><td><img src="/icons/icon_on.png" style="width:64px;height:64px;border-radius:50%"></td><td>icon_on.png</td></tr>
<tr><td>Світло нема (активна)</td><td><img src="/icons/icon_off.png" style="width:64px;height:64px;border-radius:50%"></td><td>icon_off.png</td></tr>
<tr><td>Світло нема (v3)</td><td><img src="/icons/icon_off_v3.png" style="width:64px;height:64px;border-radius:50%"></td><td>icon_off_v3.png</td></tr>
<tr><td>Світло нема (v2)</td><td><img src="/icons/icon_off_v2.png" style="width:64px;height:64px;border-radius:50%"></td><td>icon_off_v2.png</td></tr>
<tr><td>Висока напруга (v1)</td><td><img src="/icons/icon_high_voltage_v1.png" style="width:64px;height:64px;border-radius:50%"></td><td>icon_high_voltage_v1.png</td></tr>
<tr><td>Висока напруга (v2)</td><td><img src="/icons/icon_high_voltage_v2.png" style="width:64px;height:64px;border-radius:50%"></td><td>icon_high_voltage_v2.png</td></tr>
<tr><td>Низька напруга (v1)</td><td><img src="/icons/icon_low_voltage_v1.png" style="width:64px;height:64px;border-radius:50%"></td><td>icon_low_voltage_v1.png</td></tr>
<tr><td>Низька напруга (v2)</td><td><img src="/icons/icon_low_voltage_v2.png" style="width:64px;height:64px;border-radius:50%"></td><td>icon_low_voltage_v2.png</td></tr>
</table>
</details>
</div>
</div>
<script>
(function(){{
  var ORDER_KEY='pm_section_order';
  var DEFAULT_ORDER={json.dumps(DASHBOARD_SECTION_ORDER)};
  var container=document.getElementById('dashboard-sections');
  if(container){{
    var sections=Array.from(container.querySelectorAll('.dashboard-section'));
    var order=JSON.parse(localStorage.getItem(ORDER_KEY)||'null');
    if(order){{
      var byId={{}};
      sections.forEach(function(s){{ byId[s.dataset.sectionId]=s; }});
      order.forEach(function(id){{
        var el=byId[id];
        if(el){{ container.appendChild(el); }}
      }});
      sections.forEach(function(s){{
        if(!order.includes(s.dataset.sectionId)) container.appendChild(s);
      }});
    }}
    var handle=null;
    container.addEventListener('dragstart',function(e){{
      if(!e.target.classList.contains('drag-handle')) return;
      handle=e.target.closest('.dashboard-section');
      if(!handle) return;
      e.dataTransfer.setData('text/plain',handle.dataset.sectionId);
      e.dataTransfer.effectAllowed='move';
      handle.classList.add('dragging');
    }});
    container.addEventListener('dragend',function(e){{
      if(handle){{ handle.classList.remove('dragging'); handle=null; }}
      container.querySelectorAll('.dashboard-section').forEach(function(s){{ s.classList.remove('drag-over'); }});
    }});
    container.addEventListener('dragover',function(e){{
      e.preventDefault();
      container.querySelectorAll('.dashboard-section').forEach(function(s){{ s.classList.remove('drag-over'); }});
      var t=e.target.closest('.dashboard-section');
      if(t&&t!==handle){{ t.classList.add('drag-over'); e.dataTransfer.dropEffect='move'; }}
    }});
    container.addEventListener('dragleave',function(e){{
      var t=e.target.closest('.dashboard-section');
      if(t) t.classList.remove('drag-over');
    }});
    container.addEventListener('drop',function(e){{
      e.preventDefault();
      var t=e.target.closest('.dashboard-section');
      if(!t||t===handle) return;
      t.classList.remove('drag-over');
      var id=e.dataTransfer.getData('text/plain');
      var dragged=container.querySelector('[data-section-id="'+id+'"]');
      if(dragged&&dragged!==t){{
        var all=Array.from(container.querySelectorAll('.dashboard-section'));
        var idx=all.indexOf(t);
        if(idx>=0) container.insertBefore(dragged,all[idx]);
        else container.appendChild(dragged);
        var newOrder=Array.from(container.querySelectorAll('.dashboard-section')).map(function(s){{ return s.dataset.sectionId; }});
        localStorage.setItem(ORDER_KEY,JSON.stringify(newOrder));
      }}
    }});
  }}
  ['legend','avatars'].forEach(function(k){{
    var d=document.getElementById(k+'_details');
    if(localStorage.getItem(k+'_open')==='1') d.open=true;
    d.addEventListener('toggle',function(){{ localStorage.setItem(k+'_open',d.open?'1':'0'); }});
  }});
}})();
</script>
<script>
(function(){{
  document.body.classList.add('pm-ready');
  var key=document.body.getAttribute('data-pm-key')||'';
  if(!key) return;
  var urlBase='/api/dashboard-fragments?key='+encodeURIComponent(key);
  function doFetch(){{
    var url=urlBase+'&_='+Date.now();
    fetch(url,{{cache:'no-store'}}).then(function(r){{ return r.json(); }}).then(function(d){{
      var el;
      if(d.pm_status_block){{ el=document.getElementById('pm-status-block'); if(el) el.innerHTML=d.pm_status_block; }}
      if(d.pm_weather!==undefined){{ el=document.getElementById('pm-weather'); if(el) el.innerHTML=d.pm_weather; }}
      if(d.pm_alert!==undefined){{ el=document.getElementById('pm-alert'); if(el) el.innerHTML=d.pm_alert; }}
      if(d.pm_ev_tbody!==undefined){{ el=document.getElementById('pm-events-tbody'); if(el) el.innerHTML=d.pm_ev_tbody; }}
      if(d.pm_hb_tbody!==undefined){{ el=document.getElementById('pm-hb-tbody'); if(el) el.innerHTML=d.pm_hb_tbody; }}
      if(d.pm_tg_tbody!==undefined){{ el=document.getElementById('pm-tg-tbody'); if(el) el.innerHTML=d.pm_tg_tbody; }}
      if(d.pm_alert_ev_tbody!==undefined){{ el=document.getElementById('pm-alert-events-tbody'); if(el) el.innerHTML=d.pm_alert_ev_tbody; }}
      if(d.pm_deye){{ el=document.getElementById('pm-deye'); if(el){{ el.innerHTML=d.pm_deye; var dt=document.getElementById('deye_table_details'); if(dt){{ dt.open=(localStorage.getItem('deye_table_open')!=='0'); dt.addEventListener('toggle',function(){{ localStorage.setItem('deye_table_open',dt.open?'1':'0'); }}); }} }} }}
      if(d.pm_mk){{ el=document.getElementById('pm-mk-wrap'); if(el) el.innerHTML=d.pm_mk; }}
      if(d.title) document.title=d.title;
      if(d.favicon){{
        var old=document.querySelector('link[rel="icon"]');
        if(old) old.remove();
        var link=document.createElement('link');
        link.rel='icon';link.type='image/png';
        link.href='/icons/'+d.favicon+'?t='+Date.now();
        document.head.appendChild(link);
      }}
    }}).catch(function(){{}});
  }}
  setInterval(doFetch,10000);
  setTimeout(doFetch,500);
}})();
</script>

<div class="ver">v {GIT_COMMIT}</div>
</body></html>"""
