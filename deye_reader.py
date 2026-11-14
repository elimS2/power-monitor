"""Read data from Deye inverter via Modbus TCP / Solarman V5.

Used by server-side polling (power_monitor._poll_deye).
Requires: pymodbus (Modbus TCP), pysolarmanv5 (Solarman port 8899).
"""

import sys
from typing import Optional

# Deye SUN-20K-SG05LP3 3-phase registers (from Sunsynk/Deye definitions)
# Holding registers, unit/slave=1
# https://kellerza.github.io/sunsynk/reference/definitions
REGS = {
    "load_power_w": (653, True),      # signed
    "load_l1_w": (650, True),
    "load_l2_w": (651, True),
    "load_l3_w": (652, True),
    "grid_power_w": (625, True),      # signed, + = import, − = export
    "grid_v_l1": (598, False, 0.1),
    "grid_v_l2": (599, False, 0.1),
    "grid_v_l3": (600, False, 0.1),
    "battery_soc": (588, False),
    "battery_power_w": (590, True),
    "battery_voltage": (587, False, 0.01),
    "day_load_kwh": (526, False, 0.1),
    "day_grid_import_kwh": (520, False, 0.1),
    "day_grid_export_kwh": (521, False, 0.1),
    "month_load_kwh": (66, False, 0.1),
}
REGS_32BIT = {
    "total_load_kwh": (527, 528, 0.000001),
    "year_load_kwh": (87, 88, 0.1),
    "total_grid_import_kwh": (522, 523, 0.000001),
    "total_grid_export_kwh": (524, 525, 0.000001),
}


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


def decode_temp_c(raw: int) -> Optional[float]:
    """Deye temperature: raw tenths, then minus 100. Reject values a pack cannot have."""
    try:
        value = round(float(raw) * 0.1 - 100.0, 1)
    except (TypeError, ValueError):
        return None
    if value < -20.0 or value > 150.0:
        return None
    return value


def _store_temps(data: dict, pair, battery) -> None:
    if pair and len(pair) >= 2:
        dc = decode_temp_c(pair[0])
        radiator = decode_temp_c(pair[1])
        if dc is not None:
            data["temp_dc_c"] = dc
        if radiator is not None:
            data["temp_rad_c"] = radiator
    if battery:
        batt = decode_temp_c(battery[0])
        if batt is not None:
            data["temp_batt_c"] = batt


def read_deye_solarman(
    host: str, port: int = 8899, serial: str = "", socket_timeout: float = 10,
) -> Optional[dict]:
    """Read via Solarman V5 (port 8899). Requires serial number."""
    try:
        from pysolarmanv5 import PySolarmanV5
    except ImportError:
        print("Install: pip install pysolarmanv5", file=sys.stderr)
        return None

    if not host or not serial:
        return None

    try:
        modbus = PySolarmanV5(
            host, int(serial), port=port, mb_slave_id=1, socket_timeout=socket_timeout,
        )
    except Exception:
        return None

    data = {}
    try:
        # Read grid voltage L1/L2/L3 in one request (registers 598-600)
        try:
            rr = modbus.read_holding_registers(register_addr=598, quantity=3)
            if rr and len(rr) >= 3:
                data["grid_v_l1"] = rr[0] * 0.1
                data["grid_v_l2"] = rr[1] * 0.1
                data["grid_v_l3"] = rr[2] * 0.1
        except Exception:
            pass
        try:
            pair = modbus.read_holding_registers(register_addr=540, quantity=2)
            _store_temps(data, pair, None)
        except Exception:
            pass
        try:
            battery = modbus.read_holding_registers(register_addr=586, quantity=1)
            _store_temps(data, None, battery)
        except Exception:
            pass
        for name, spec in REGS.items():
            if name in data:
                continue
            addr = spec[0]
            signed = spec[1] if len(spec) >= 2 else False
            scale = spec[2] if len(spec) >= 3 else 1.0
            try:
                rr = modbus.read_holding_registers(register_addr=addr, quantity=1)
                if rr:
                    data[name] = _parse_reg_val(rr[0], signed, scale)
            except Exception:
                pass
        for name, spec in REGS_32BIT.items():
            addr_hi, addr_lo, scale = spec
            try:
                rr = modbus.read_holding_registers(register_addr=addr_hi, quantity=2)
                if rr and len(rr) >= 2:
                    val_32 = (rr[0] << 16) | rr[1]
                    if val_32 == 0xFFFFFFFF:
                        continue
                    v = val_32 * scale
                    if name == "year_load_kwh" and v > 1_000:
                        continue
                    if name in ("total_grid_import_kwh", "total_grid_export_kwh") and v > 100_000:
                        continue
                    data[name] = round(v, 2)
            except Exception:
                pass
    finally:
        modbus.disconnect()
    return data if data else None


def read_deye_modbus(host: str, port: int = 502) -> Optional[dict]:
    """Read via Modbus TCP (port 502)."""
    try:
        from pymodbus.client import ModbusTcpClient
    except ImportError:
        print("Install: pip install pymodbus", file=sys.stderr)
        return None

    if not host:
        return None

    client = ModbusTcpClient(host, port=port)
    try:
        if not client.connect():
            return None
        data = {}
        # Read grid voltage L1/L2/L3 in one request (registers 598-600)
        rr = client.read_holding_registers(598, 3, slave=1)
        if not rr.isError() and rr.registers and len(rr.registers) >= 3:
            data["grid_v_l1"] = rr.registers[0] * 0.1
            data["grid_v_l2"] = rr.registers[1] * 0.1
            data["grid_v_l3"] = rr.registers[2] * 0.1
        try:
            pair_rr = client.read_holding_registers(540, 2, slave=1)
            pair = pair_rr.registers if not pair_rr.isError() and pair_rr.registers else None
            batt_rr = client.read_holding_registers(586, 1, slave=1)
            battery = batt_rr.registers if not batt_rr.isError() and batt_rr.registers else None
            _store_temps(data, pair, battery)
        except Exception:
            pass
        for name, spec in REGS.items():
            if name in data:
                continue
            addr = spec[0]
            signed = spec[1] if len(spec) >= 2 else False
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
                if name in ("total_grid_import_kwh", "total_grid_export_kwh") and v > 100_000:
                    continue
                data[name] = round(v, 2)
    finally:
        client.close()
    return data if data else None


def read_deye(
    host: Optional[str] = None,
    port: Optional[int] = None,
    serial: Optional[str] = None,
    socket_timeout: float = 10,
) -> Optional[dict]:
    """Read registers. Uses Solarman if serial set and port 8899, else Modbus TCP."""
    if not host:
        return None
    p = port if port is not None else 502
    s = serial or ""
    if s and p == 8899:
        return read_deye_solarman(host=host, port=p, serial=s, socket_timeout=socket_timeout)
    return read_deye_modbus(host=host, port=p)
