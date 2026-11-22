"""Read data from Deye inverter via Modbus TCP / Solarman V5.

Used by server-side polling (power_monitor._poll_deye).
Requires: pymodbus (Modbus TCP), pysolarmanv5 (Solarman port 8899).
"""

import logging
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


_FAST_BLOCK_LEN = 56


def decode_fast_block(registers) -> Optional[dict]:
    """Volts and watts from one 598×56 holding-register read. None unless the list is exactly 56 words."""
    try:
        if len(registers) != _FAST_BLOCK_LEN:
            return None
        words = [int(word) for word in registers]
    except (TypeError, ValueError):
        return None
    return {
        "grid_v_l1": words[0] * 0.1,
        "grid_v_l2": words[1] * 0.1,
        "grid_v_l3": words[2] * 0.1,
        "grid_power_w": _to_signed16(words[27]),
        "load_l1_w": _to_signed16(words[52]),
        "load_l2_w": _to_signed16(words[53]),
        "load_l3_w": _to_signed16(words[54]),
        "load_power_w": _to_signed16(words[55]),
    }


def _parse_reg_val(val: int, signed: bool, scale: float) -> float:
    if signed:
        val = _to_signed16(val)
    else:
        val = val * scale
    return val


def decode_hv_battery_volts(raw_voltage: int) -> float:
    """HV pack voltage. Register 587 is tenths of a volt, not hundredths."""
    return float(raw_voltage) * 0.1


def decode_hv_battery_watts(raw_power: int, raw_power_2: Optional[int] = None) -> float:
    """Sum of the two HV battery ports. Each register is signed watts times 10."""
    watts = _to_signed16(int(raw_power)) * 10
    if raw_power_2 is not None:
        watts += _to_signed16(int(raw_power_2)) * 10
    return float(watts)


def _apply_hv_battery(data: dict, block) -> None:
    if not block or len(block) < 9:
        return
    data["battery_voltage"] = decode_hv_battery_volts(block[0])
    data["battery_power_w"] = decode_hv_battery_watts(block[3], block[8])


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


_log = logging.getLogger(__name__)


def _words_or_none(raw, quantity: int):
    if not raw or len(raw) < quantity:
        return None
    try:
        return [int(word) for word in raw[:quantity]]
    except (TypeError, ValueError):
        return None


def _scaled_u32(hi: int, lo: int, scale: float, name: str):
    """High word first, same guards as the old per-register loop."""
    value = (int(hi) << 16) | int(lo)
    if value == 0xFFFFFFFF:
        return None
    scaled = value * scale
    if name == "year_load_kwh" and scaled > 1_000:
        return None
    if name in ("total_grid_import_kwh", "total_grid_export_kwh") and scaled > 100_000:
        return None
    return round(scaled, 2)


def _store_energy_block(data: dict, block) -> None:
    if not block or len(block) < 9:
        return
    data["day_grid_import_kwh"] = block[0] * 0.1
    data["day_grid_export_kwh"] = block[1] * 0.1
    total_import = _scaled_u32(block[2], block[3], 0.000001, "total_grid_import_kwh")
    total_export = _scaled_u32(block[4], block[5], 0.000001, "total_grid_export_kwh")
    data["day_load_kwh"] = block[6] * 0.1
    total_load = _scaled_u32(block[7], block[8], 0.000001, "total_load_kwh")
    if total_import is not None:
        data["total_grid_import_kwh"] = total_import
    if total_export is not None:
        data["total_grid_export_kwh"] = total_export
    if total_load is not None:
        data["total_load_kwh"] = total_load


def _store_apartment_battery(data: dict, block) -> None:
    if not block or len(block) < 5:
        return
    temp = decode_temp_c(block[0])
    if temp is not None:
        data["temp_batt_c"] = temp
    data["battery_voltage"] = block[1] * 0.01
    data["battery_soc"] = block[2]
    data["battery_power_w"] = _to_signed16(block[4])


def _store_house_battery(data: dict, block) -> None:
    if not block or len(block) < 10:
        return
    temp = decode_temp_c(block[0])
    if temp is not None:
        data["temp_batt_c"] = temp
    data["battery_soc"] = block[2]
    _apply_hv_battery(data, block[1:10])


def _store_apartment_battery_singles(data: dict, read) -> bool:
    """Illegal-address fallback. Apartment scales only. False if a single read raised."""
    ok = True
    temp, raised = _attempt(read, 586, 1)
    ok = ok and not raised
    if temp:
        decoded = decode_temp_c(temp[0])
        if decoded is not None:
            data["temp_batt_c"] = decoded
    volts, raised = _attempt(read, 587, 1)
    ok = ok and not raised
    if volts:
        data["battery_voltage"] = volts[0] * 0.01
    soc, raised = _attempt(read, 588, 1)
    ok = ok and not raised
    if soc:
        data["battery_soc"] = soc[0]
    power, raised = _attempt(read, 590, 1)
    ok = ok and not raised
    if power:
        data["battery_power_w"] = _to_signed16(power[0])
    return ok


def _store_house_battery_singles(data: dict, read) -> bool:
    """Today's house sequence. Do not use the apartment 0.01 scale."""
    ok = True
    temp, raised = _attempt(read, 586, 1)
    ok = ok and not raised
    if temp:
        decoded = decode_temp_c(temp[0])
        if decoded is not None:
            data["temp_batt_c"] = decoded
    soc, raised = _attempt(read, 588, 1)
    ok = ok and not raised
    if soc:
        data["battery_soc"] = soc[0]
    block, raised = _attempt(read, 587, 9)
    ok = ok and not raised
    if block:
        _apply_hv_battery(data, block)
    return ok


def _attempt(read, addr: int, quantity: int):
    try:
        raw = read(register_addr=addr, quantity=quantity)
    except Exception as exc:
        _log.warning(
            "Deye block %s x %s failed: %s",
            addr, quantity, exc.__class__.__name__,
        )
        return None, True
    return _words_or_none(raw, quantity), False


class SlowRead:
    """data is the partial or full snapshot. complete is false when a block raised and was not recovered."""

    def __init__(self, data: dict, complete: bool):
        self.data = data
        self.complete = complete


def read_deye_slow(read_holding_registers, hv: bool = False) -> SlowRead:
    """Six holding-register reads. A failed block omits only its own keys."""
    data: dict = {}
    failed = False

    def take(addr: int, qty: int):
        nonlocal failed
        words, raised = _attempt(read_holding_registers, addr, qty)
        if raised:
            failed = True
        return words

    _store_energy_block(data, take(520, 9))
    year = take(87, 2)
    if year:
        scaled = _scaled_u32(year[0], year[1], 0.1, "year_load_kwh")
        if scaled is not None:
            data["year_load_kwh"] = scaled
    month = take(66, 1)
    if month:
        data["month_load_kwh"] = month[0] * 0.1
    temps = take(540, 2)
    if temps:
        _store_temps(data, temps, None)
    battery_qty = 10 if hv else 5
    battery, raised = _attempt(read_holding_registers, 586, battery_qty)
    if battery:
        if hv:
            _store_house_battery(data, battery)
        else:
            _store_apartment_battery(data, battery)
    elif raised:
        if hv:
            recovered = _store_house_battery_singles(data, read_holding_registers)
        else:
            recovered = _store_apartment_battery_singles(data, read_holding_registers)
        if not recovered:
            failed = True
    fast = take(598, _FAST_BLOCK_LEN)
    if fast:
        decoded = decode_fast_block(fast)
        if decoded:
            data.update(decoded)
    return SlowRead(data, not failed)


def read_deye_blocks(read_holding_registers, hv: bool = False) -> dict:
    """Six holding-register reads. A failed block omits only its own keys."""
    return read_deye_slow(read_holding_registers, hv=hv).data


def read_fast_sample(read_holding_registers):
    """One 598×56 read. Returns (decoded or None, raised)."""
    words, raised = _attempt(read_holding_registers, 598, _FAST_BLOCK_LEN)
    if raised or not words:
        return None, raised
    return decode_fast_block(words), False


def read_deye_solarman(
    host: str, port: int = 8899, serial: str = "", socket_timeout: float = 10,
    hv: bool = False,
) -> Optional[dict]:
    """Does not open a socket. The poller keeps the one Solarman client per inverter."""
    return None


def read_deye_modbus(host: str, port: int = 502, hv: bool = False) -> Optional[dict]:
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
        if hv:
            try:
                block_rr = client.read_holding_registers(587, 9, slave=1)
                block = block_rr.registers if not block_rr.isError() and block_rr.registers else None
                _apply_hv_battery(data, block)
            except Exception:
                pass
    finally:
        client.close()
    return data if data else None


def read_deye(
    host: Optional[str] = None,
    port: Optional[int] = None,
    serial: Optional[str] = None,
    socket_timeout: float = 10,
    hv: bool = False,
) -> Optional[dict]:
    """Read registers. Uses Solarman if serial set and port 8899, else Modbus TCP."""
    if not host:
        return None
    p = port if port is not None else 502
    s = serial or ""
    if s and p == 8899:
        return None
    return read_deye_modbus(host=host, port=p, hv=hv)
