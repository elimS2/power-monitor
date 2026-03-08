"""Debug API routes."""
from datetime import datetime

from fastapi import APIRouter, Query

from api.deps import check_key
from config import UA_TZ
from database import _conn, parse_boiler_schedule

router = APIRouter(tags=["debug"])


@router.get("/api/debug-webhooks")
def ep_debug_webhooks(key: str = Query(""), limit: int = Query(20)):
    check_key(key)
    with _conn() as db:
        rows = db.execute(
            "SELECT id, chat_id, text, ts FROM webhook_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "chat_id": r["chat_id"],
            "text": r["text"],
            "ts": datetime.fromtimestamp(r["ts"], tz=UA_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        }
        for r in rows
    ]


@router.get("/api/debug-boiler-parse")
def ep_debug_boiler_parse(key: str = Query(""), text: str = Query("")):
    check_key(key)
    result = parse_boiler_schedule(text)
    return {"input_len": len(text), "parsed": result}
