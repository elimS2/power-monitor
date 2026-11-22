"""Fast Deye block decode and the archive table. No socket and no SSH."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

import database
from config import CLEANUP_KEEP_DAYS
from deye_reader import decode_fast_block


def _words(values: dict[int, int] | None = None) -> list[int]:
    words = [0] * 56
    for offset, value in (values or {}).items():
        words[offset] = value
    return words


class DecodeFastBlockTests(unittest.TestCase):
    def test_known_offsets_and_signed_watts(self):
        negative = decode_fast_block(_words({0: 2300, 1: 2310, 2: 2295, 27: 65535, 52: 1, 53: 2, 54: 3, 55: 6}))
        self.assertIsNotNone(negative)
        self.assertAlmostEqual(negative["grid_v_l1"], 230.0)
        self.assertAlmostEqual(negative["grid_v_l2"], 231.0)
        self.assertAlmostEqual(negative["grid_v_l3"], 229.5)
        self.assertEqual(negative["grid_power_w"], -1)
        self.assertEqual(negative["load_l1_w"], 1)
        self.assertEqual(negative["load_l2_w"], 2)
        self.assertEqual(negative["load_l3_w"], 3)
        self.assertEqual(negative["load_power_w"], 6)

        plain = decode_fast_block(_words({27: 4000}))
        self.assertEqual(plain["grid_power_w"], 4000)

    def test_short_block_is_not_a_row(self):
        self.assertIsNone(decode_fast_block([0] * 55))
        self.assertIsNone(decode_fast_block([0] * 57))
        self.assertIsNone(decode_fast_block(None))
        self.assertIsNone(decode_fast_block(["x"] * 56))


class DeyeFastTableTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._old_path = database.DB_PATH
        database.DB_PATH = Path(self._tmpdir.name) / "t.db"
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self._old_path
        self._tmpdir.cleanup()

    def _counts(self) -> tuple[int, int]:
        with database._conn() as db:
            fast = db.execute("SELECT COUNT(*) AS n FROM deye_fast").fetchone()["n"]
            slow = db.execute("SELECT COUNT(*) AS n FROM deye_log").fetchone()["n"]
        return int(fast), int(slow)

    def test_save_writes_one_fast_row_and_leaves_deye_log_alone(self):
        decoded = decode_fast_block(_words({0: 2200, 27: 4000, 55: 1500}))
        before_fast, before_slow = self._counts()
        database.save_deye_fast(inverter_id=database.apartment_inverter_id(), **decoded)
        fast, slow = self._counts()
        self.assertEqual(before_fast, 0)
        self.assertEqual(fast, 1)
        self.assertEqual(slow, before_slow)

    def test_short_decode_inserts_nothing(self):
        decoded = decode_fast_block([0] * 55)
        self.assertIsNone(decoded)
        fast, slow = self._counts()
        self.assertEqual(fast, 0)
        self.assertEqual(slow, 0)

    def test_unknown_inverter_raises_and_inserts_nothing(self):
        decoded = decode_fast_block(_words())
        with self.assertRaises(ValueError):
            database.save_deye_fast(inverter_id=999999, **decoded)
        fast, slow = self._counts()
        self.assertEqual(fast, 0)
        self.assertEqual(slow, 0)

    def test_cleanup_keeps_old_and_new_fast_rows(self):
        apt = database.apartment_inverter_id()
        old_ts = time.time() - (CLEANUP_KEEP_DAYS + 1) * 86400
        decoded = decode_fast_block(_words({55: 100}))
        with database._conn() as db:
            db.execute(
                """INSERT INTO deye_fast (
                    inverter_id, ts, grid_v_l1, grid_v_l2, grid_v_l3, grid_power_w,
                    load_l1_w, load_l2_w, load_l3_w, load_power_w
                ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (apt, old_ts, 0, 0, 0, 0, 0, 0, 0, 1),
            )
            db.execute(
                "INSERT INTO heartbeats(plug204, plug175, ts) VALUES (1, 1, ?)",
                (old_ts,),
            )
        database.save_deye_fast(inverter_id=apt, **decoded)
        database.cleanup_old()
        with database._conn() as db:
            fast = db.execute("SELECT COUNT(*) AS n FROM deye_fast").fetchone()["n"]
            beats = db.execute("SELECT COUNT(*) AS n FROM heartbeats").fetchone()["n"]
            slow = db.execute("SELECT COUNT(*) AS n FROM deye_log").fetchone()["n"]
        self.assertEqual(fast, 2)
        self.assertEqual(beats, 0)
        self.assertEqual(slow, 0)


class _FakeRegisters:
    def __init__(self, words: dict[int, int], fail=()):
        self.words = words
        self.fail = set(fail)
        self.calls = []

    def __call__(self, register_addr, quantity):
        self.calls.append((register_addr, quantity))
        if (register_addr, quantity) in self.fail:
            raise OSError("illegal address")
        return [self.words.get(register_addr + offset, 0) for offset in range(quantity)]


def _slow_words() -> dict[int, int]:
    words = {
        520: 10,
        521: 20,
        523: 1_000_000,
        525: 2_000_000,
        526: 30,
        528: 5_000_000,
        88: 100,
        66: 40,
        540: 1250,
        541: 1300,
        586: 1200,
        587: 5370,
        588: 80,
        590: 65535,
        598: 2300,
        599: 2310,
        600: 2290,
        625: 4000,
        650: 100,
        651: 200,
        652: 300,
        653: 600,
    }
    return words


class SlowBlockTests(unittest.TestCase):
    def test_apartment_reads_six_blocks_with_old_scales(self):
        from deye_reader import read_deye_blocks

        fake = _FakeRegisters(_slow_words())
        data = read_deye_blocks(fake, hv=False)
        self.assertEqual(
            fake.calls,
            [(520, 9), (87, 2), (66, 1), (540, 2), (586, 5), (598, 56)],
        )
        self.assertAlmostEqual(data["day_grid_import_kwh"], 1.0)
        self.assertAlmostEqual(data["day_grid_export_kwh"], 2.0)
        self.assertAlmostEqual(data["total_grid_import_kwh"], 1.0)
        self.assertAlmostEqual(data["total_grid_export_kwh"], 2.0)
        self.assertAlmostEqual(data["day_load_kwh"], 3.0)
        self.assertAlmostEqual(data["total_load_kwh"], 5.0)
        self.assertAlmostEqual(data["year_load_kwh"], 10.0)
        self.assertAlmostEqual(data["month_load_kwh"], 4.0)
        self.assertAlmostEqual(data["temp_dc_c"], 25.0)
        self.assertAlmostEqual(data["temp_rad_c"], 30.0)
        self.assertAlmostEqual(data["temp_batt_c"], 20.0)
        self.assertAlmostEqual(data["battery_voltage"], 53.7)
        self.assertEqual(data["battery_soc"], 80)
        self.assertEqual(data["battery_power_w"], -1)
        self.assertAlmostEqual(data["grid_v_l1"], 230.0)
        self.assertEqual(data["grid_power_w"], 4000)
        self.assertEqual(data["load_power_w"], 600)

    def test_house_uses_quantity_10_and_tenth_volt_scale(self):
        from deye_reader import read_deye_blocks

        words = _slow_words()
        words[587] = 5424
        words[588] = 99
        words[590] = 100
        words[595] = 3
        fake = _FakeRegisters(words)
        data = read_deye_blocks(fake, hv=True)
        self.assertEqual(fake.calls[4], (586, 10))
        self.assertEqual(data["battery_soc"], 99)
        self.assertAlmostEqual(data["battery_voltage"], 542.4)
        self.assertEqual(data["battery_power_w"], 1030)

    def test_apartment_quantity_5_fallback_does_not_repeat_other_blocks(self):
        from deye_reader import read_deye_blocks

        fake = _FakeRegisters(_slow_words(), fail=[(586, 5)])
        with self.assertLogs("deye_reader", level="WARNING"):
            data = read_deye_blocks(fake, hv=False)
        self.assertEqual(
            fake.calls,
            [
                (520, 9), (87, 2), (66, 1), (540, 2), (586, 5),
                (586, 1), (587, 1), (588, 1), (590, 1),
                (598, 56),
            ],
        )
        self.assertEqual(fake.calls.count((520, 9)), 1)
        self.assertAlmostEqual(data["battery_voltage"], 53.7)
        self.assertEqual(data["battery_power_w"], -1)
        self.assertNotAlmostEqual(data["battery_voltage"], 537.0)

    def test_house_quantity_10_fallback_uses_the_nine_register_slice(self):
        from deye_reader import read_deye_blocks

        words = _slow_words()
        words[587] = 5424
        words[588] = 99
        words[590] = 100
        words[595] = 3
        fake = _FakeRegisters(words, fail=[(586, 10)])
        data = read_deye_blocks(fake, hv=True)
        self.assertEqual(
            [call for call in fake.calls if call[0] in (586, 587, 588)],
            [(586, 10), (586, 1), (588, 1), (587, 9)],
        )
        self.assertNotIn((590, 1), fake.calls)
        self.assertEqual(data["battery_soc"], 99)
        self.assertAlmostEqual(data["battery_voltage"], 542.4)
        self.assertEqual(data["battery_power_w"], 1030)

    def test_a_failed_counter_block_keeps_the_voltages(self):
        from deye_reader import read_deye_blocks

        words = _slow_words()
        words[522] = 65535
        words[523] = 65535
        words[88] = 20_000
        fake = _FakeRegisters(words, fail=[(540, 2)])
        data = read_deye_blocks(fake, hv=False)
        self.assertNotIn("total_grid_import_kwh", data)
        self.assertNotIn("year_load_kwh", data)
        self.assertNotIn("temp_dc_c", data)
        self.assertAlmostEqual(data["day_grid_import_kwh"], 1.0)
        self.assertAlmostEqual(data["grid_v_l1"], 230.0)
        self.assertEqual(fake.calls.count((598, 56)), 1)

    def test_modbus_tcp_reader_stays_on_the_old_loop(self):
        import inspect

        from deye_reader import read_deye_modbus, read_deye_solarman

        modbus = inspect.getsource(read_deye_modbus)
        solarman = inspect.getsource(read_deye_solarman)
        self.assertIn("587, 9", modbus)
        self.assertNotIn("read_deye_blocks", modbus)
        self.assertNotIn("PySolarmanV5", solarman)
        self.assertIn("Does not open a socket", solarman)


class FastLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_short_reads_sleep_the_leftover_once(self):
        from power_monitor import run_fast_cycle

        clock = {"t": 0.0}
        sleeps = []
        reads = []

        def monotonic():
            return clock["t"]

        async def read(row):
            reads.append(row["id"])
            clock["t"] += 0.2

        async def sleep(delay):
            sleeps.append(delay)

        delay = await run_fast_cycle(
            [{"id": 1}, {"id": 2}], 1, read, sleep, monotonic, set(), lambda: None,
        )
        self.assertEqual(reads, [1, 2])
        self.assertAlmostEqual(delay, 0.6)
        self.assertEqual(sleeps, [0.6])

    async def test_overrun_sleeps_zero_and_does_not_read_again(self):
        from power_monitor import run_fast_cycle

        clock = {"t": 0.0}
        sleeps = []
        reads = []
        overruns = []

        def monotonic():
            return clock["t"]

        async def read(row):
            reads.append(row["id"])
            clock["t"] += 0.6

        async def sleep(delay):
            sleeps.append(delay)

        delay = await run_fast_cycle(
            [{"id": 1}, {"id": 2}], 1, read, sleep, monotonic, set(), lambda: overruns.append(1),
        )
        self.assertEqual(reads, [1, 2])
        self.assertEqual(delay, 0)
        self.assertEqual(sleeps, [0])
        self.assertEqual(overruns, [1])

    async def test_held_id_is_skipped_and_a_free_id_is_read(self):
        from power_monitor import run_fast_cycle

        reads = []

        async def read(row):
            reads.append(row["id"])

        await run_fast_cycle(
            [{"id": 7}, {"id": 8}], 1, read, self._noop, lambda: 0, {7}, lambda: None,
        )
        self.assertEqual(reads, [8])

    async def test_a_claim_taken_again_is_not_discarded(self):
        import asyncio

        import power_monitor

        power_monitor._inflight_polls.clear()
        power_monitor._inflight_polls.add(7)
        waiting = asyncio.create_task(power_monitor._claim_when_free(7))
        await asyncio.sleep(0.12)
        waiting.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiting
        self.assertEqual(power_monitor._inflight_polls, {7})
        power_monitor._inflight_polls.clear()

    async def _noop(self, _delay):
        return None


class FastIntervalTests(unittest.TestCase):
    def test_only_zero_one_and_two_are_accepted(self):
        from config import fast_interval_sec

        self.assertEqual(fast_interval_sec("0"), 0)
        self.assertEqual(fast_interval_sec("1"), 1)
        self.assertEqual(fast_interval_sec("2"), 2)
        self.assertEqual(fast_interval_sec("9"), 0)
        self.assertEqual(fast_interval_sec(None), 0)


if __name__ == "__main__":
    unittest.main()
