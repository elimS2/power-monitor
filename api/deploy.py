"""GitHub webhook for deploy-on-push."""
import hashlib
import hmac
import json
import logging
import re

from fastapi import APIRouter, Request, HTTPException

from config import GITHUB_WEBHOOK_SECRET

router = APIRouter(tags=["deploy"])
log = logging.getLogger("power_monitor")

_DEPLOY_TAGS = re.compile(r"#автооновити|#autodeploy", re.I)


def _verify_signature(body: bytes, signature: str) -> bool:
    """Verify X-Hub-Signature-256. Expects 'sha256=<hex>'."""
    if not GITHUB_WEBHOOK_SECRET:
        return False
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        GITHUB_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


@router.post("/api/deploy-hook")
async def deploy_webhook(request: Request):
    """
    GitHub repository webhook. On push to main with #autodeploy in commit message,
    runs git pull and systemctl restart.
    """
    if not GITHUB_WEBHOOK_SECRET:
        raise HTTPException(503, "GITHUB_WEBHOOK_SECRET not configured")

    body = await request.body()
    sig = request.headers.get("x-hub-signature-256", "")
    if not _verify_signature(body, sig):
        raise HTTPException(403, "Invalid signature")

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")

    ref = data.get("ref", "")
    if ref != "refs/heads/main":
        return {"ok": True, "deploy": False, "reason": "not main"}

    head = data.get("head_commit") or {}
    msg = (head.get("message") or "").strip()
    if not _DEPLOY_TAGS.search(msg):
        return {"ok": True, "deploy": False, "reason": "no #autodeploy in message"}

    commit_id = (head.get("id") or "")[:8]
    log.info("Deploy webhook: push %s with #autodeploy, deploying", commit_id)

    import asyncio

    from power_monitor import _do_deploy_sync

    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(None, _do_deploy_sync)

    return {"ok": True, "deploy": True, "restarted": ok}
