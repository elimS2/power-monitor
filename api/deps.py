"""Shared dependencies for API routes — key validation and permissions."""
from __future__ import annotations

from fastapi import HTTPException

from config import API_KEYS
from database import ALL_SECTIONS, api_key_config_get


def get_key_label(key: str) -> str | None:
    """Return label for key (e.g. admin, vasyl), or None if invalid."""
    return API_KEYS.get(key) if key in API_KEYS else None


def check_key(key: str) -> None:
    """Verify key exists and is enabled."""
    if key not in API_KEYS:
        raise HTTPException(403, "forbidden")
    label = API_KEYS[key]
    if label == "admin":
        return  # admin is always enabled
    cfg = api_key_config_get(label)
    if cfg is not None and not cfg["enabled"]:
        raise HTTPException(403, "key disabled")


def check_admin(key: str) -> None:
    """Verify key is admin."""
    check_key(key)
    if API_KEYS.get(key) != "admin":
        raise HTTPException(403, "admin only")


# Permission tags for endpoints: dashboard, heartbeat, deye, plug, debug, admin
# Default for keys without config: ["dashboard", "heartbeat"]


def check_permission(key: str, required: str) -> None:
    """Verify key has permission. Calls check_key first. Use after check_key for non-admin endpoints."""
    check_key(key)
    label = API_KEYS.get(key)
    if label == "admin":
        return
    cfg = api_key_config_get(label or "")
    allowed = cfg["endpoints"] if cfg and cfg["endpoints"] else ["dashboard", "heartbeat", "plug"]
    if required not in allowed and "admin" not in allowed:
        raise HTTPException(403, f"permission required: {required}")


def allowed_sections(key: str) -> list[str]:
    """Return list of section IDs this key can see. Admin sees all."""
    if key not in API_KEYS:
        return []
    label = API_KEYS[key]
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
