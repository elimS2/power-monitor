#!/usr/bin/env python3
"""
Read data from Deye inverter via Modbus TCP and send to Power Monitor server.

Run from your computer (same network as inverter):
    python deye_to_power_monitor.py

Requires: pip install pymodbus requests

Environment or .env:
    DEYE_IP=                   # Inverter IP on local network
    DEYE_PORT=8899             # 8899=Solarman, 502=Modbus TCP
    DEYE_SERIAL=               # Required for Solarman (WiFi module serial)
    POWER_MONITOR_URL=         # e.g. https://your-server.example.com
    POWER_MONITOR_KEY=         # API key from Power Monitor
    INTERVAL_SEC=30
    DEYE_LOG_FILE=             # Optional: path to log file (default: script_dir/deye_to_power_monitor.log)
"""

import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Optional: load .env from power-monitor folder
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SCRIPT_PATH = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT_PATH.parent
DEYE_LOG_FILE = os.getenv("DEYE_LOG_FILE", str(SCRIPT_DIR / "deye_to_power_monitor.log"))

DEYE_IP = os.getenv("DEYE_IP", "")
DEYE_PORT = int(os.getenv("DEYE_PORT", "8899"))
DEYE_SERIAL = os.getenv("DEYE_SERIAL", "")  # Required for Solarman (port 8899)
POWER_MONITOR_URL = os.getenv("POWER_MONITOR_URL", "").rstrip("/")
POWER_MONITOR_KEY = os.getenv("POWER_MONITOR_KEY", "")
INTERVAL_SEC = int(os.getenv("INTERVAL_SEC", "30"))

# Deye SUN-20K-SG05LP3 3-phase registers (from Sunsynk/Deye definitions)
# Holding registers, unit/slave=1
# https://kellerza.github.io/sunsynk/reference/definitions
REGS = {
    "load_power_w": (653, True),      # signed
    "load_l1_w": (650, True),
    "load_l2_w": (651, True),
    "load_l3_w": (652, True),
    "grid_v_l1": (598, False, 0.1),   # value * 0.1
    "grid_v_l2": (599, False, 0.1),
    "grid_v_l3": (600, False, 0.1),
    "battery_soc": (588, False),
    "battery_power_w": (590, True),
    "battery_voltage": (587, False, 0.01),
    "day_load_kwh": (526, False, 0.1),    # Day load energy, kWh (resets daily)
    "month_load_kwh": (66, False, 0.001),  # 3PH: ×0.001 (65.535); 1PH docs say ×0.1
}
# 32-bit registers: (addr_high, addr_low), scale. Value = (high << 16) | low
# 3PH/Solarman: total ×0.000001 (≈582 kWh за ~міс); year ×0.0001 або ×0.000001
REGS_32BIT = {
    "total_load_kwh": (527, 528, 0.000001),   # Total: ×0.000001 (~582 за міс)
    "year_load_kwh": (87, 88, 0.000001),     # Year: той самий масштаб
}


def _git_version() -> str:
    """Return short git commit hash, or 'unknown' if not in repo."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=SCRIPT_DIR, timeout=2,
        )
        return r.stdout.strip() if r.returncode == 0 and r.stdout else "unknown"
    except Exception:
        return "unknown"


def _setup_logging() -> logging.Logger:
    """Configure logging to console and file. Returns logger."""
    log = logging.getLogger("deye_to_power_monitor")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    # Console
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    # File
    fh = logging.FileHandler(DEYE_LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    return log


def _log_startup(log: logging.Logger) -> None:
    """Log script path, log file, start time (UTC), git version."""
    start_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    git_ver = _git_version()
    msgs = [
        f"Script path: {SCRIPT_PATH}",
        f"Log file: {DEYE_LOG_FILE}",
        f"Start time (UTC): {start_utc}",
        f"Git version: {git_ver}",
    ]
    for m in msgs:
        log.info(m)
        print(m, flush=True)


def _to_signed16(val: int) -> int:
    if val > 32767:
        return val - 65536
    return val


def _parse_reg_val(val: int, signed: bool, scale: float) -> float:
    if signed:
        val = _to_signed16(val)
    else:
        val = val * scale
    return val


def read_deye_solarman() -> dict | None:
    """Read via Solarman V5 (port 8899). Requires DEYE_SERIAL."""
    try:
        from pysolarmanv5 import PySolarmanV5
    except ImportError:
        print("Install: pip install pysolarmanv5", file=sys.stderr)
        return None

    try:
        modbus = PySolarmanV5(DEYE_IP, int(DEYE_SERIAL), port=DEYE_PORT, mb_slave_id=1)
    except Exception as e:
        print(f"Solarman connect error: {e}", file=sys.stderr)
        return None

    data = {}
    try:
        for name, spec in REGS.items():
            addr, signed = spec[0], spec[1] if len(spec) >= 2 else False
            scale = spec[2] if len(spec) >= 3 else 1.0
            try:
                rr = modbus.read_holding_registers(register_addr=addr, quantity=1)
                if rr:
                    val = _parse_reg_val(rr[0], signed, scale)
                    data[name] = val
            except Exception:
                pass
        for name, spec in REGS_32BIT.items():
            addr_hi, addr_lo, scale = spec
            try:
                rr = modbus.read_holding_registers(register_addr=addr_hi, quantity=2)
                if rr and len(rr) >= 2:
                    val_32 = (rr[0] << 16) | rr[1]
                    if val_32 == 0xFFFFFFFF:  # invalid / not supported on 3PH
                        continue
                    v = val_32 * scale
                    # Year: 0xFFFFFFFF → 4295 kWh, нереально для року з початку
                    if name == "year_load_kwh" and v > 1_000:
                        continue
                    data[name] = round(v, 2)
            except Exception:
                pass
    finally:
        modbus.disconnect()
    return data if data else None


def read_deye_modbus() -> dict | None:
    """Read via Modbus TCP (port 502)."""
    try:
        from pymodbus.client import ModbusTcpClient
    except ImportError:
        print("Install: pip install pymodbus", file=sys.stderr)
        return None

    client = ModbusTcpClient(DEYE_IP, port=DEYE_PORT)
    try:
        if not client.connect():
            return None
        data = {}
        for name, spec in REGS.items():
            addr, signed = spec[0], spec[1] if len(spec) >= 2 else False
            scale = spec[2] if len(spec) >= 3 else 1.0
            rr = client.read_holding_registers(addr, 1, slave=1)
            if not rr.isError() and rr.registers:
                data[name] = _parse_reg_val(rr.registers[0], signed, scale)
        for name, spec in REGS_32BIT.items():
            addr_hi, addr_lo, scale = spec
            rr = client.read_holding_registers(addr_hi, 2, slave=1)
            if not rr.isError() and rr.registers and len(rr.registers) >= 2:
                val_32 = (rr.registers[0] << 16) | rr.registers[1]
                if val_32 == 0xFFFFFFFF:
                    continue
                v = val_32 * scale
                if name == "year_load_kwh" and v > 1_000:
                    continue
                data[name] = round(v, 2)
    finally:
        client.close()
    return data if data else None


def read_deye() -> dict | None:
    """Read registers. Uses Solarman if DEYE_SERIAL set, else Modbus TCP."""
    if DEYE_SERIAL and DEYE_PORT == 8899:
        return read_deye_solarman()
    return read_deye_modbus()


def send_to_server(data: dict, log: logging.Logger | None = None) -> bool:
    """POST data to Power Monitor API."""
    try:
        import requests
    except ImportError:
        print("Install: pip install requests", file=sys.stderr)
        sys.exit(1)

    url = f"{POWER_MONITOR_URL}/api/deye-heartbeat?key={POWER_MONITOR_KEY}"
    try:
        r = requests.post(url, json=data, timeout=10)
        if r.status_code == 200:
            return True
        err = f"POST {r.status_code}: {r.text[:500]}"
        print(err, file=sys.stderr)
        if log:
            log.warning(err)
        return False
    except Exception as e:
        err = f"POST error: {e}"
        print(err, file=sys.stderr)
        if log:
            log.warning(err)
        return False


def main():
    log = _setup_logging()
    _log_startup(log)

    if not DEYE_IP:
        log.error("Set DEYE_IP (inverter IP on your network)")
        sys.exit(1)
    if not POWER_MONITOR_URL:
        log.error("Set POWER_MONITOR_URL (Power Monitor server URL)")
        sys.exit(1)
    if not POWER_MONITOR_KEY:
        log.error("Set POWER_MONITOR_KEY (API key from Power Monitor .env)")
        sys.exit(1)
    if DEYE_PORT == 8899 and not DEYE_SERIAL:
        log.error("For Solarman (port 8899) set DEYE_SERIAL (WiFi module serial from Deye Cloud or sticker)")
        sys.exit(1)

    msg = f"Deye {DEYE_IP}:{DEYE_PORT} -> {POWER_MONITOR_URL} every {INTERVAL_SEC}s"
    log.info(msg)
    print(msg, flush=True)
    log.info("Ctrl+C to stop")
    print("Ctrl+C to stop", flush=True)

    while True:
        data = read_deye()
        if data:
            ok = send_to_server(data, log)
            load = data.get("load_power_w", "?")
            soc = data.get("battery_soc", "?")
            day_kwh = data.get("day_load_kwh")
            day_str = f" day={round(day_kwh, 1)}kWh" if day_kwh is not None else ""
            status = "OK" if ok else "FAIL"
            line = f"{time.strftime('%H:%M:%S')} load={load}W soc={soc}%{day_str} send={status}"
            log.info(line)
            print(line, flush=True)
        else:
            line = f"{time.strftime('%H:%M:%S')} read failed"
            log.warning(line)
            print(line, flush=True)
        time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    main()
