"""Admin API — key management. Admin only."""
from __future__ import annotations

import json
import logging
import secrets

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

from api.deps import check_admin
from itp_auto import arm_itp, disarm_itp, itp_admin_status, mutate_itp_auto
from config import API_KEYS
from database import (
    ALL_SECTIONS,
    kv_get,
    kv_set,
    SECTION_LABELS,
    tg_channel_create,
    tg_channel_delete,
    tg_channel_list,
    tg_channel_set_active,
    tg_notify_chat_id,
    api_key_config_list,
    api_key_config_set_enabled,
    api_key_config_set_permissions,
    api_key_create,
    api_key_delete,
    api_key_get_plain,
    api_key_history,
    api_key_list,
    api_key_regenerate,
    role_create,
    role_delete,
    role_get,
    role_list,
    role_update,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])
log = logging.getLogger("power_monitor")


@router.get("/roles")
def ep_admin_roles(key: str = Query("")):
    """List all roles (from DB). Admin only."""
    check_admin(key)
    roles = role_list()
    return {"roles": roles, "all_sections": ALL_SECTIONS, "section_labels": SECTION_LABELS}


@router.post("/roles")
async def ep_admin_role_create(request: Request, key: str = Query("")):
    """Create a role. Body: {name, sections}. Admin only."""
    check_admin(key)
    try:
        body = await request.json()
    except Exception:
        body = {}
    name = body.get("name", "").strip()
    sections = body.get("sections")
    footer_parts = body.get("footer_parts")
    if not name:
        return JSONResponse({"error": "name required"}, status_code=400)
    if sections is not None and not isinstance(sections, list):
        return JSONResponse({"error": "sections must be list or null"}, status_code=400)
    if footer_parts is not None and not isinstance(footer_parts, list):
        return JSONResponse({"error": "footer_parts must be list or null"}, status_code=400)
    role = role_create(name, sections, footer_parts)
    return {"ok": True, "role": role}


@router.get("/roles/{role_id:int}")
def ep_admin_role_get(role_id: int, key: str = Query("")):
    """Get single role. Admin only."""
    check_admin(key)
    r = role_get(role_id)
    if not r:
        return JSONResponse({"error": "role not found"}, status_code=404)
    return {"role": r}


@router.put("/roles/{role_id:int}")
async def ep_admin_role_update(role_id: int, request: Request, key: str = Query("")):
    """Update role. Body: {name?, sections?, footer_parts?}. Admin only. Built-in roles cannot be edited."""
    check_admin(key)
    try:
        body = await request.json()
    except Exception:
        body = {}
    name = body.get("name")
    if name is not None:
        name = str(name).strip()
    sections = body.get("sections")
    footer_parts = body.get("footer_parts")
    if footer_parts is not None and not isinstance(footer_parts, list):
        return JSONResponse({"error": "footer_parts must be list or null"}, status_code=400)
    kw = {}
    if "name" in body:
        kw["name"] = name
    if "sections" in body:
        kw["sections"] = sections
    if "footer_parts" in body:
        kw["footer_parts"] = footer_parts
    ok = role_update(role_id, **kw) if kw else False
    if not ok:
        return JSONResponse({"error": "role not found or is built-in"}, status_code=404)
    return {"ok": True}


@router.delete("/roles/{role_id:int}")
def ep_admin_role_delete(role_id: int, key: str = Query("")):
    """Delete role. Only custom roles. Admin only."""
    check_admin(key)
    ok = role_delete(role_id)
    if not ok:
        return JSONResponse({"error": "role not found or is built-in"}, status_code=404)
    return {"ok": True}


def _all_key_labels() -> set[str]:
    """Labels from env + DB."""
    labels = set(API_KEYS.values())
    for row in api_key_list():
        labels.add(row["label"])
    return labels


@router.post("/keys")
async def ep_admin_key_create(request: Request, key: str = Query("")):
    """Generate new API key, store in DB. Body: {label}. Returns key (show once). Admin only."""
    check_admin(key)
    try:
        body = await request.json()
    except Exception:
        body = {}
    label = (body.get("label") or "").strip()
    if not label:
        return JSONResponse({"error": "label required"}, status_code=400)
    if label in _all_key_labels():
        return JSONResponse({"error": f"label {label!r} already exists"}, status_code=400)
    new_key = secrets.token_urlsafe(24)
    api_key_create(label, new_key)
    return {"ok": True, "label": label, "key": new_key}


@router.get("/keys")
def ep_admin_keys(key: str = Query("")):
    """List all keys: from API_KEYS (env) + DB, with config. Admin only."""
    check_admin(key)
    configs = {c["label"]: c for c in api_key_config_list()}
    result = []
    for api_key, label in API_KEYS.items():
        cfg = configs.get(label)
        result.append({
            "label": label,
            "key_preview": api_key[:8] + "…" if len(api_key) > 8 else api_key,
            "source": "env",
            "enabled": cfg["enabled"] if cfg else True,
            "sections": cfg["sections"] if cfg else None,
            "role_id": cfg.get("role_id") if cfg else None,
            "endpoints": cfg["endpoints"] if cfg else None,
        })
    for row in api_key_list():
        cfg = configs.get(row["label"])
        result.append({
            "label": row["label"],
            "key_preview": row["key_preview"],
            "source": "db",
            "enabled": cfg["enabled"] if cfg else True,
            "sections": cfg["sections"] if cfg else None,
            "role_id": cfg.get("role_id") if cfg else None,
            "endpoints": cfg["endpoints"] if cfg else None,
        })
    return result


@router.post("/keys/{label}/regenerate")
def ep_admin_key_regenerate(label: str, key: str = Query("")):
    """Regenerate key: deactivate old, create new. Returns new key. DB keys only. Admin only."""
    check_admin(key)
    if label in API_KEYS.values():
        return JSONResponse({"error": "cannot regenerate env key"}, status_code=400)
    result = api_key_regenerate(label)
    if not result:
        return JSONResponse({"error": f"unknown label: {label}"}, status_code=404)
    return {"ok": True, **result}


@router.get("/keys/{label}/history")
def ep_admin_key_history(label: str, key: str = Query("")):
    """Get key history (created_at, deactivated_at) for label. DB keys only. Admin only."""
    check_admin(key)
    if label in API_KEYS.values():
        return JSONResponse({"error": "env keys have no history"}, status_code=400)
    history = api_key_history(label)
    return {"label": label, "history": history}


@router.get("/keys/{label}/open-dashboard")
def ep_admin_key_open_dashboard(label: str, key: str = Query("")):
    """Redirect to dashboard with the full key. Works for env and DB keys."""
    check_admin(key)
    for api_key, lbl in API_KEYS.items():
        if lbl == label:
            return RedirectResponse(url=f"/?key={api_key}", status_code=302)
    plain = api_key_get_plain(label)
    if plain:
        return RedirectResponse(url=f"/?key={plain}", status_code=302)
    return JSONResponse({"error": "key not found or not stored"}, status_code=404)


@router.delete("/keys/{label}")
def ep_admin_key_delete(label: str, key: str = Query("")):
    """Delete key from DB. Only for keys created in admin (not env keys). Admin only."""
    check_admin(key)
    if label in API_KEYS.values():
        return JSONResponse({"error": "cannot delete env key — remove from .env"}, status_code=400)
    if not api_key_delete(label):
        return JSONResponse({"error": f"unknown label: {label}"}, status_code=404)
    return {"ok": True, "label": label}


@router.post("/keys/{label}/enabled")
def ep_admin_key_set_enabled(label: str, key: str = Query(""), enabled: bool = Query(True)):
    """Enable or disable a key by label. Admin only."""
    check_admin(key)
    if label not in _all_key_labels():
        return JSONResponse({"error": f"unknown label: {label}"}, status_code=400)
    api_key_config_set_enabled(label, enabled)
    return {"ok": True, "label": label, "enabled": enabled}


@router.get("/voltage-notify")
def ep_admin_voltage_notify_get(key: str = Query("")):
    """Get voltage notification setting. Admin only."""
    check_admin(key)
    enabled = kv_get("tg_voltage_notify") != "0"
    return {"enabled": enabled}


@router.post("/voltage-notify")
def ep_admin_voltage_notify_set(key: str = Query(""), enabled: bool = Query(True)):
    """Enable or disable Telegram voltage notifications. Admin only."""
    check_admin(key)
    kv_set("tg_voltage_notify", "1" if enabled else "0")
    return {"ok": True, "enabled": enabled}


def latest_itp_applied() -> str | None:
    """On/off from the newest stored heat-breaker day. Missing row stays unknown."""
    from database import _conn
    from tuya_breakers import breaker_shown_on

    with _conn() as db:
        row = db.execute(
            """SELECT switch, phase_json FROM breaker_day
               WHERE device=?
               ORDER BY day DESC, updated_at DESC
               LIMIT 1""",
            ("itp",),
        ).fetchone()
    if row is None:
        return None
    phases = None
    raw = row["phase_json"]
    if raw:
        try:
            loaded = json.loads(raw)
        except (TypeError, ValueError):
            loaded = None
        if isinstance(loaded, dict):
            phases = loaded
    return "on" if breaker_shown_on(row["switch"], phases) else "off"


def set_itp_armed(enabled: bool) -> dict:
    """Arm or disarm the local flag. Does not call Tuya and does not delete timers."""
    applied = latest_itp_applied() if enabled else None

    def update(doc):
        fresh = arm_itp(doc, applied) if enabled else disarm_itp(doc)
        doc.clear()
        doc.update(fresh)

    mutate_itp_auto(update)
    log.info("itp-auto: admin %s", "arm" if enabled else "disarm")
    return {"ok": True, **itp_admin_status()}


@router.get("/itp-auto")
def ep_admin_itp_auto_get(key: str = Query("")):
    """Heat-breaker auto flag. Admin only. Does not call Tuya."""
    check_admin(key)
    return {"ok": True, **itp_admin_status()}


@router.post("/itp-auto")
def ep_admin_itp_auto_set(key: str = Query(""), enabled: int = Query(...)):
    """Arm with enabled=1 or disarm with enabled=0. Admin only. Does not call Tuya."""
    check_admin(key)
    if enabled not in (0, 1):
        return JSONResponse({"error": "enabled must be 0 or 1"}, status_code=400)
    return set_itp_armed(bool(enabled))


@router.get("/tg-channels")
def ep_admin_tg_channels(key: str = Query("")):
    """List Telegram channels and active notification target. Admin only."""
    check_admin(key)
    channels = tg_channel_list()
    active_id = next((c["id"] for c in channels if c["is_active"]), None)
    return {"channels": channels, "active_id": active_id, "notify_chat_id": tg_notify_chat_id()}


@router.post("/tg-channels")
async def ep_admin_tg_channel_create(request: Request, key: str = Query("")):
    """Add Telegram channel. Body: {name, chat_id}. Admin only."""
    check_admin(key)
    try:
        body = await request.json()
    except Exception:
        body = {}
    name = (body.get("name") or "").strip()
    chat_id = (body.get("chat_id") or "").strip()
    if not name or not chat_id:
        return JSONResponse({"error": "name and chat_id required"}, status_code=400)
    try:
        ch = tg_channel_create(name, chat_id)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True, "channel": ch}


@router.post("/tg-channels/{channel_id:int}/activate")
def ep_admin_tg_channel_activate(channel_id: int, key: str = Query("")):
    """Set active notification channel. Admin only."""
    check_admin(key)
    ch = tg_channel_set_active(channel_id)
    if not ch:
        return JSONResponse({"error": "channel not found"}, status_code=404)
    return {"ok": True, "channel": ch, "notify_chat_id": tg_notify_chat_id()}


@router.delete("/tg-channels/{channel_id:int}")
def ep_admin_tg_channel_delete(channel_id: int, key: str = Query("")):
    """Delete Telegram channel. Admin only."""
    check_admin(key)
    try:
        ok = tg_channel_delete(channel_id)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if not ok:
        return JSONResponse({"error": "channel not found"}, status_code=404)
    return {"ok": True, "channels": tg_channel_list(), "notify_chat_id": tg_notify_chat_id()}


@router.post("/keys/{label}/permissions")
async def ep_admin_key_set_permissions(label: str, request: Request, key: str = Query("")):
    """Set permissions for a key. Body: {sections?, role_id?, endpoints?}. If role_id set, sections come from role."""
    check_admin(key)
    if label not in _all_key_labels():
        return JSONResponse({"error": f"unknown label: {label}"}, status_code=400)
    try:
        body = await request.json()
    except Exception:
        body = {}
    sec = body.get("sections")
    role_id = body.get("role_id")
    ep = body.get("endpoints")
    if role_id is not None:
        role_id = int(role_id) if role_id else None
    api_key_config_set_permissions(label, sections=sec, endpoints=ep, role_id=role_id)
    return {"ok": True, "label": label, "sections": sec, "role_id": role_id, "endpoints": ep}


@router.get("/access")
def ep_admin_access(key: str = Query(""), day: str = Query("")):
    """One Kyiv day of dashboard visits. Admin only. Does not build the public page."""
    from datetime import datetime

    from access_stats import access_view, parse_day
    from config import UA_TZ

    check_admin(key)
    if not day:
        day = datetime.now(UA_TZ).strftime("%Y-%m-%d")
    try:
        day = parse_day(day)
    except ValueError:
        return JSONResponse({"error": "bad day"}, status_code=400)
    return access_view(day)


@router.post("/ip-note")
async def ep_admin_ip_note(request: Request, key: str = Query("")):
    """Save a nickname and a note for one address. Admin only."""
    import re

    from database import ip_profile_save

    check_admin(key)
    try:
        body = await request.json()
    except Exception:
        body = {}
    ip = str(body.get("ip") or "").strip()[:64]
    if not re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", ip):
        return JSONResponse({"error": "bad ip"}, status_code=400)
    alias = str(body.get("alias") or "").strip()[:80]
    note = str(body.get("note") or "").strip()[:400]
    ip_profile_save(ip, alias, note)
    return {"ok": True, "ip": ip}
