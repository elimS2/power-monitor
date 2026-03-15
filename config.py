"""
Power Monitor — configuration and constants.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import timezone, timedelta
from pathlib import Path


def _parse_keys(raw: str) -> dict:
    """Parse 'label:key,label2:key2' or plain 'key1,key2' into {key: label}."""
    result = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            label, key = entry.split(":", 1)
            result[key.strip()] = label.strip()
        else:
            result[entry] = ""
    return result


def _git_version() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).parent,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"


# ─── Telegram ────────────────────────────────────────────────

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "YOUR_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "YOUR_CHAT_ID")
TG_TEST_CHAT_ID = os.getenv("TG_TEST_CHAT_ID", "")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "")
AVATAR_ON_START = os.getenv("AVATAR_ON_START", "1") == "1"
DELETE_PHOTO_MSG = os.getenv("DELETE_PHOTO_MSG", "0") == "1"
TG_WEBHOOK_SECRET = hashlib.sha256(TG_BOT_TOKEN.encode()).hexdigest()[:32]

API_KEYS = _parse_keys(os.getenv("API_KEYS", os.getenv("API_KEY", "changeme")))

# ─── Database ────────────────────────────────────────────────

DB_PATH = Path(os.getenv("DB_PATH", str(Path(__file__).parent / "power_monitor.db")))

# When 1: ignore plug status, use only L1/L2/L3 phases from Deye for detection
PHASES_ONLY = os.getenv("PHASES_ONLY", "0") == "1"

# Both plugs must be dead for this many consecutive heartbeats → outage (ignored if PHASES_ONLY)
OUTAGE_CONFIRM_COUNT = 18  # 18 × 10s = ~3 minutes

# Voltage anti-spam: require N consecutive readings before notify
VOLTAGE_CONFIRM_COUNT = 2
# Min 5 min between "problem" notifications
VOLTAGE_PROBLEM_MIN_INTERVAL_SEC = 300
# Min 3 min after "recovery" before next "problem"
VOLTAGE_RECOVERY_TO_PROBLEM_MIN_SEC = 180
# Unstable mode: if ≥3 voltage state changes in 10 min → suppress for 15 min
VOLTAGE_UNSTABLE_CHANGES_THRESHOLD = 3
VOLTAGE_UNSTABLE_WINDOW_SEC = 600
VOLTAGE_UNSTABLE_SUPPRESS_SEC = 900

# No heartbeat for this long → router/internet alert
STALE_THRESHOLD_SEC = int(os.getenv("STALE_THRESHOLD_SEC", "300"))

# Keep heartbeat data for this many days
CLEANUP_KEEP_DAYS = 90

# ─── Timezone ────────────────────────────────────────────────

UA_TZ = timezone(timedelta(hours=2))

# ─── DTEK schedule ───────────────────────────────────────────

DTEK_API_URL = os.getenv("DTEK_API_URL", "https://dtek-api.svitlo-proxy.workers.dev/")
DTEK_REGION = os.getenv("DTEK_REGION", "kiivska-oblast")
DTEK_QUEUE = os.getenv("DTEK_QUEUE", "5.1")

# ─── Deye ───────────────────────────────────────────────────

DEYE_BATTERY_KWH = float(os.getenv("DEYE_BATTERY_KWH", "0") or "0")

# Server-side polling: when set, GCP server polls Deye directly (via port forward)
# DEYE_POLL_IP = your public IP or DynDNS hostname
# DEYE_POLL_PORT = external port (e.g. 18899 for Solarman, 1502 for Modbus)
DEYE_POLL_IP = os.getenv("DEYE_POLL_IP", "").strip()
DEYE_POLL_PORT = int(os.getenv("DEYE_POLL_PORT", "0") or "0")
DEYE_POLL_SERIAL = os.getenv("DEYE_POLL_SERIAL", "").strip()  # Required for Solarman (8899)
DEYE_POLL_INTERVAL_SEC = int(os.getenv("DEYE_POLL_INTERVAL_SEC", "30") or "30")
DEYE_POLL_LOG = Path(os.getenv("DEYE_POLL_LOG", str(Path(__file__).parent / "logs" / "deye_poll.log")))

# ─── Weather ────────────────────────────────────────────────

WEATHER_LAT = 50.5114
WEATHER_LON = 30.7911
WEATHER_URL = (
    f"https://api.open-meteo.com/v1/forecast"
    f"?latitude={WEATHER_LAT}&longitude={WEATHER_LON}"
    f"&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
    f"&daily=temperature_2m_min,temperature_2m_max&forecast_days=1"
    f"&timezone=Europe%2FKyiv"
)

WMO_EMOJI = {
    0: "\u2600\ufe0f",
    1: "\U0001f324\ufe0f",
    2: "\u26c5",
    3: "\u2601\ufe0f",
    45: "\U0001f32b\ufe0f",
    48: "\U0001f32b\ufe0f",
    51: "\U0001f326\ufe0f",
    53: "\U0001f326\ufe0f",
    55: "\U0001f326\ufe0f",
    61: "\U0001f327\ufe0f",
    63: "\U0001f327\ufe0f",
    65: "\U0001f327\ufe0f",
    66: "\U0001f327\ufe0f",
    67: "\U0001f327\ufe0f",
    71: "\U0001f328\ufe0f",
    73: "\U0001f328\ufe0f",
    75: "\U0001f328\ufe0f",
    77: "\U0001f328\ufe0f",
    80: "\U0001f326\ufe0f",
    81: "\U0001f327\ufe0f",
    82: "\U0001f327\ufe0f",
    85: "\U0001f328\ufe0f",
    86: "\U0001f328\ufe0f",
    95: "\u26c8\ufe0f",
    96: "\u26c8\ufe0f",
    99: "\u26c8\ufe0f",
}

# ─── Alert ───────────────────────────────────────────────────

ALERT_API_URL = "https://alerts.com.ua/api/states"
ALERT_REGION_IDS = [9, 25]  # 9=Київська область, 25=Київ

# ─── Auto-deploy ──────────────────────────────────────────────

# When 1: bg_loop periodically checks for commits with #автооновити and runs pull + restart
AUTO_DEPLOY_ENABLED = os.getenv("AUTO_DEPLOY", "1") == "1"
AUTO_DEPLOY_INTERVAL_SEC = int(os.getenv("AUTO_DEPLOY_INTERVAL_SEC", "60") or "60")

# GitHub webhook: secret for X-Hub-Signature-256 verification. If set, /api/deploy-hook accepts pushes.
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")

# ─── Dashboard ────────────────────────────────────────────────

DASHBOARD_SECTION_ORDER = [
    "voltage_details", "sched_details", "boiler_details", "ev_details", "links_details",
    "alert_ev_details", "tg_details", "deye_details",
    "hb_details", "legend_details", "avatars_details",
]

GIT_COMMIT = _git_version()
