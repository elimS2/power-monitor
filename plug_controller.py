#!/usr/bin/env python3
"""
Control Nous/Tuya smart plug. Polls Power Monitor for commands, executes via tinytuya.

Run from your computer (same network as plug):
    python plug_controller.py

Requires: pip install tinytuya requests python-dotenv

Get Device ID and Local Key:
    python -m tinytuya wizard

Environment or .env:
    PLUG_DEVICE_ID=      # From tinytuya wizard
    PLUG_IP=             # Plug IP (e.g. 192.168.88.XXX)
    PLUG_LOCAL_KEY=      # From tinytuya wizard
    PLUG_VERSION=3.3     # Tuya protocol version (usually 3.3)
    POWER_MONITOR_URL=   # e.g. https://power.elims.pp.ua
    POWER_MONITOR_KEY=   # API key from Power Monitor
    INTERVAL_SEC=15
"""

import os
import sys
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

PLUG_DEVICE_ID = os.getenv("PLUG_DEVICE_ID", "")
PLUG_IP = os.getenv("PLUG_IP", "")
PLUG_LOCAL_KEY = os.getenv("PLUG_LOCAL_KEY", "")
PLUG_VERSION = float(os.getenv("PLUG_VERSION", "3.3"))
POWER_MONITOR_URL = os.getenv("POWER_MONITOR_URL", "").rstrip("/")
POWER_MONITOR_KEY = os.getenv("POWER_MONITOR_KEY", "")
INTERVAL_SEC = int(os.getenv("INTERVAL_SEC", "15"))


def get_plug():
    """Create tinytuya Device. Returns None if not configured."""
    if not all([PLUG_DEVICE_ID, PLUG_IP, PLUG_LOCAL_KEY]):
        return None
    try:
        import tinytuya
        return tinytuya.OutletDevice(PLUG_DEVICE_ID, PLUG_IP, PLUG_LOCAL_KEY, version=PLUG_VERSION)
    except ImportError:
        print("Install: pip install tinytuya", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Tinytuya init error: {e}", file=sys.stderr)
        return None


def plug_status(device) -> str:
    """Get current state: on, off, or unknown."""
    try:
        d = device.status()
        if not d:
            return "unknown"
        if "dps" in d:
            dps = d["dps"]
            for k, v in dps.items():
                if isinstance(v, bool):
                    return "on" if v else "off"
            if "1" in dps:
                return "on" if dps["1"] else "off"
        return "unknown"
    except Exception:
        return "unknown"


def plug_set(device, state: str) -> bool:
    """Set plug on/off. Returns True on success."""
    try:
        if state.lower() == "on":
            device.turn_on()
        else:
            device.turn_off()
        return True
    except Exception as e:
        print(f"Plug set error: {e}", file=sys.stderr)
        return False


def report_state(state: str):
    """Report state to Power Monitor."""
    if not POWER_MONITOR_URL or not POWER_MONITOR_KEY:
        return
    try:
        import urllib.request
        url = f"{POWER_MONITOR_URL}/api/plug-done?key={POWER_MONITOR_KEY}&state={state}"
        req = urllib.request.Request(url, method="POST")
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Report state error: {e}", file=sys.stderr)


def get_pending_cmd() -> str | None:
    """Get and clear pending command. Returns 'on', 'off', or None."""
    if not POWER_MONITOR_URL or not POWER_MONITOR_KEY:
        return None
    try:
        import urllib.request
        url = f"{POWER_MONITOR_URL}/api/plug-pending?key={POWER_MONITOR_KEY}"
        with urllib.request.urlopen(url, timeout=10) as r:
            import json
            d = json.loads(r.read().decode())
            return d.get("cmd")
    except Exception as e:
        print(f"Get pending error: {e}", file=sys.stderr)
        return None


def main():
    if not POWER_MONITOR_URL or not POWER_MONITOR_KEY:
        print("Set POWER_MONITOR_URL and POWER_MONITOR_KEY", file=sys.stderr)
        sys.exit(1)

    device = get_plug()
    if not device:
        print("Configure PLUG_DEVICE_ID, PLUG_IP, PLUG_LOCAL_KEY. Run: python -m tinytuya wizard", file=sys.stderr)
        sys.exit(1)

    print("Plug controller started. Ctrl+C to stop.")
    while True:
        try:
            cmd = get_pending_cmd()
            if cmd and cmd in ("on", "off"):
                ok = plug_set(device, cmd)
                state = plug_status(device) if ok else "unknown"
                report_state(state)
            else:
                state = plug_status(device)
                report_state(state)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Cycle error: {e}", file=sys.stderr)
        time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    main()
