"""Admin API — key management. Admin only."""
from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

from api.deps import check_admin
from config import API_KEYS, ROLES
from database import api_key_config_list, api_key_config_set_enabled, api_key_config_set_permissions

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/roles")
def ep_admin_roles(key: str = Query("")):
    """List role presets (name -> sections). Admin only."""
    check_admin(key)
    return {"roles": {k: v for k, v in ROLES.items()}}


@router.get("/keys")
def ep_admin_keys(key: str = Query("")):
    """List all keys from API_KEYS with their config (enabled, sections, endpoints). Admin only."""
    check_admin(key)
    # Build list: all labels from API_KEYS, merge with api_key_config
    configs = {c["label"]: c for c in api_key_config_list()}
    result = []
    for api_key, label in API_KEYS.items():
        cfg = configs.get(label)
        result.append({
            "label": label,
            "key_preview": api_key[:8] + "…" if len(api_key) > 8 else api_key,
            "enabled": cfg["enabled"] if cfg else True,
            "sections": cfg["sections"] if cfg else None,
            "endpoints": cfg["endpoints"] if cfg else None,
        })
    return result


@router.get("/keys/{label}/open-dashboard")
def ep_admin_key_open_dashboard(label: str, key: str = Query("")):
    """Redirect to dashboard with the full key for this label. Admin only. Opens in new tab."""
    check_admin(key)
    for api_key, lbl in API_KEYS.items():
        if lbl == label:
            return RedirectResponse(url=f"/?key={api_key}", status_code=302)
    return JSONResponse({"error": f"unknown label: {label}"}, status_code=404)


@router.post("/keys/{label}/enabled")
def ep_admin_key_set_enabled(label: str, key: str = Query(""), enabled: bool = Query(True)):
    """Enable or disable a key by label. Admin only."""
    check_admin(key)
    if label not in [v for v in API_KEYS.values()]:
        return JSONResponse({"error": f"unknown label: {label}"}, status_code=400)
    api_key_config_set_enabled(label, enabled)
    return {"ok": True, "label": label, "enabled": enabled}


@router.post("/keys/{label}/permissions")
async def ep_admin_key_set_permissions(label: str, request: Request, key: str = Query("")):
    """Set sections and/or endpoints for a key. Admin only. Body: {"sections": [...] or null, "endpoints": [...] or null}"""
    check_admin(key)
    if label not in [v for v in API_KEYS.values()]:
        return JSONResponse({"error": f"unknown label: {label}"}, status_code=400)
    try:
        body = await request.json()
    except Exception:
        body = {}
    sec = body.get("sections")
    ep = body.get("endpoints")
    api_key_config_set_permissions(label, sec, ep)
    return {"ok": True, "label": label, "sections": sec, "endpoints": ep}
