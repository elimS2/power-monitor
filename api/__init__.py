"""API routers for Power Monitor."""
from .admin import router as admin_router
from .deploy import router as deploy_router
from .heartbeat import router as heartbeat_router
from .dashboard import router as dashboard_router
from .debug import router as debug_router
from .telegram import router as telegram_router
from .deye import router as deye_router
from .static import router as static_router

__all__ = [
    "admin_router",
    "deploy_router",
    "heartbeat_router",
    "dashboard_router",
    "debug_router",
    "telegram_router",
    "deye_router",
    "static_router",
]
