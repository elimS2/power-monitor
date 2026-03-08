"""Shared dependencies for API routes."""
from fastapi import HTTPException

from config import API_KEYS


def check_key(key: str) -> None:
    if key not in API_KEYS:
        raise HTTPException(403, "forbidden")


def check_admin(key: str) -> None:
    check_key(key)
    if API_KEYS.get(key) != "admin":
        raise HTTPException(403, "admin only")
