"""Shared dependencies for API routes — key validation and permissions."""
from __future__ import annotations

from fastapi import HTTPException

from config import API_KEYS
from database import ALL_SECTIONS, api_key_config_get, api_key_lookup


def get_key_label(key: str) -> str | None:
    """Return label for key. Checks API_KEYS (env) first, then DB."""
    if key in API_KEYS:
        return API_KEYS[key]
    return api_key_lookup(key)


def check_key(key: str) -> None:
    """Verify key exists and is enabled."""
    label = get_key_label(key)
    if label is None:
        raise HTTPException(403, "forbidden")
    if label == "admin":
        return  # admin is always enabled
    cfg = api_key_config_get(label)
    if cfg is not None and not cfg["enabled"]:
        raise HTTPException(403, "key disabled")


def check_admin(key: str) -> None:
    """Verify key is admin."""
    check_key(key)
    if get_key_label(key) != "admin":
        raise HTTPException(403, "admin only")


# Permission tags for endpoints: dashboard, heartbeat, deye, debug, admin
# Default for keys without config: ["dashboard", "heartbeat"]


def check_permission(key: str, required: str) -> None:
    """Verify key has permission. Calls check_key first. Use after check_key for non-admin endpoints."""
    check_key(key)
    label = get_key_label(key)
    if label == "admin":
        return
    cfg = api_key_config_get(label or "")
    allowed = cfg["endpoints"] if cfg and cfg["endpoints"] else ["dashboard", "heartbeat"]
    if required not in allowed and "admin" not in allowed:
        raise HTTPException(403, f"permission required: {required}")


def allowed_sections(key: str) -> list[str]:
    """Return list of section IDs this key can see. Admin sees all."""
    label = get_key_label(key)
    if label is None:
        return []
    if label == "admin":
        return ALL_SECTIONS
    cfg = api_key_config_get(label)
    if cfg is None:
        return ALL_SECTIONS  # no config = full access (backward compat)
    if not cfg["enabled"]:
        return []
    if cfg["sections"] is None or len(cfg["sections"]) == 0:
        return ALL_SECTIONS
    return [s for s in cfg["sections"] if s in ALL_SECTIONS]
