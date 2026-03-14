"""Admin API — key management. Admin only."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

from api.deps import check_admin
from config import API_KEYS
from database import (
    ALL_SECTIONS,
    SECTION_LABELS,
    api_key_config_list,
    api_key_config_set_enabled,
    api_key_config_set_permissions,
    api_key_create,
    api_key_delete,
    api_key_list,
    role_create,
    role_delete,
    role_get,
    role_list,
    role_update,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


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
    if not name:
        return JSONResponse({"error": "name required"}, status_code=400)
    if sections is not None and not isinstance(sections, list):
        return JSONResponse({"error": "sections must be list or null"}, status_code=400)
    role = role_create(name, sections)
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
    """Update role. Body: {name?, sections?}. Admin only. Built-in roles cannot be edited."""
    check_admin(key)
    try:
        body = await request.json()
    except Exception:
        body = {}
    name = body.get("name")
    if name is not None:
        name = str(name).strip()
    sections = body.get("sections")
    ok = role_update(role_id, name, sections)
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


@router.get("/keys/{label}/open-dashboard")
def ep_admin_key_open_dashboard(label: str, key: str = Query("")):
    """Redirect to dashboard with the full key. Only for env keys (DB keys are not stored)."""
    check_admin(key)
    for api_key, lbl in API_KEYS.items():
        if lbl == label:
            return RedirectResponse(url=f"/?key={api_key}", status_code=302)
    return JSONResponse({"error": "key from DB — use saved key, open link not available"}, status_code=400)


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
