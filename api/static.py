"""Static files and PWA routes."""
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, JSONResponse, Response

from api.deps import check_permission
router = APIRouter(tags=["static"])

_ICONS_DIR = Path(__file__).resolve().parent.parent
_STATIC_DIR = _ICONS_DIR / "static"
_ALLOWED_ICONS = {p.name for p in _ICONS_DIR.glob("icon_*.png")}


@router.get("/style.css")
async def serve_css():
    return FileResponse(
        _STATIC_DIR / "style.css",
        media_type="text/css",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/app.js")
async def serve_js():
    return FileResponse(
        _STATIC_DIR / "app.js",
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/icons/{name}")
async def serve_icon(name: str):
    if name not in _ALLOWED_ICONS:
        from fastapi import HTTPException
        raise HTTPException(404)
    data = (_ICONS_DIR / name).read_bytes()
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/manifest.json")
async def pwa_manifest(key: str = Query("")):
    check_permission(key, "dashboard")
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


@router.get("/sw.js")
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
