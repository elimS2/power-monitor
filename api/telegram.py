"""Telegram API routes."""
import json
import logging
import time

from fastapi import APIRouter, Query, Request, HTTPException

from api.deps import check_permission
from config import TG_CHAT_ID, TG_TEST_CHAT_ID, TG_WEBHOOK_SECRET
from database import _conn, parse_boiler_schedule, save_boiler_schedule

router = APIRouter(tags=["telegram"])
log = logging.getLogger("power_monitor")


@router.post("/api/test-telegram")
async def ep_test_telegram(key: str = Query("")):
    check_permission(key, "dashboard")
    from power_monitor import _power_status_text, tg_send

    target = TG_TEST_CHAT_ID or TG_CHAT_ID
    status = _power_status_text()
    await tg_send(status, chat_id=target)
    return {"ok": True, "sent_to": target}


@router.post("/api/tg-webhook")
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

    from power_monitor import _power_status_text, tg_send

    if text == "/start":
        await tg_send(
            "Привіт! Натисни /status або скористайся меню, щоб дізнатися чи є світло.",
            chat_id=cid,
        )
    elif text == "/status":
        status = _power_status_text()
        await tg_send(status, chat_id=cid)

    return {"ok": True}
