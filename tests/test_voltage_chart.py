"""Voltage day chart: samples, actual outages, and the queue ahead."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import database
from config import UA_TZ
from voltage_chart import build_voltage_chart


def _kyiv(year, month, day, hour, minute=0) -> float:
    return datetime(year, month, day, hour, minute, tzinfo=UA_TZ).timestamp()


class VoltageChartTests(unittest.TestCase):
    def test_live_phase_is_drawn_and_ten_minute_span_is_shown(self):
        now = _kyiv(2026, 11, 9, 1, 4)
        buckets = [
            {"bucket": now - 120, "l1": 222.0, "l2": 220.0, "l3": 217.0, "dead": 0, "n": 2},
            {"bucket": now - 60, "l1": 222.0, "l2": 220.0, "l3": 220.0, "dead": 0, "n": 2},
        ]
        html = build_voltage_chart(
            now=now, buckets=buckets, today=None, tomorrow=None, queue="5.1",
        )
        self.assertIn('stroke="#facc15"', html)
        self.assertIn('stroke="#4ade80"', html)
        self.assertIn('stroke="#f87171"', html)
        self.assertIn("за 10 хв 217–222 В", html)
        self.assertIn("data-t0=", html)
        self.assertIn("vchart-main", html)
        self.assertIn("vchart-strip", html)
        self.assertIn("Колесо збільшує", html)
        self.assertIn("щипок", html)
        self.assertIn("vchart-full", html)
        self.assertIn("На весь екран", html)
        self.assertIn('preserveAspectRatio="none"', html)
        self.assertEqual(html.count('preserveAspectRatio="none"'), 2)
        self.assertIn("vchart-next", html)
        self.assertIn("disabled", html)

    def test_previous_calendar_day_has_no_now_marker(self):
        now = _kyiv(2026, 11, 9, 1, 4)
        html = build_voltage_chart(
            now=now, buckets=[], today=None, tomorrow=None, queue="5.1", shift_days=1,
        )
        self.assertNotIn("vchart-now", html)
        self.assertIn("8 лис, нд", html)
        self.assertIn('data-shift="1"', html)
        self.assertNotIn("disabled", html)

    def test_dead_minutes_are_orange_and_do_not_draw_zero_volts(self):
        now = _kyiv(2026, 11, 9, 1, 4)
        buckets = [
            {"bucket": now - 3600, "l1": 230.0, "l2": 230.0, "l3": 230.0, "dead": 0, "n": 1},
            {"bucket": now - 1800, "l1": None, "l2": None, "l3": None, "dead": 4, "n": 4},
        ]
        html = build_voltage_chart(
            now=now, buckets=buckets, today=None, tomorrow=None, queue="5.1",
        )
        self.assertIn('fill="#fb923c"', html)
        self.assertIn('fill="#facc15"', html)

    def test_future_off_slot_is_a_brown_column(self):
        now = _kyiv(2026, 11, 9, 1, 0)
        grid = ["ok"] * 48
        for slot in range(6, 12):  # 03:00–06:00
            grid[slot] = "off"
        html = build_voltage_chart(
            now=now,
            buckets=[],
            today={"date": "2026-11-09", "grid": grid},
            tomorrow=None,
            queue="5.1",
        )
        self.assertIn('fill="#7c4a32"', html)
        self.assertIn("без світла за графіком", html)


class VoltageBucketQueryTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._old_path = database.DB_PATH
        database.DB_PATH = Path(self._tmpdir.name) / "t.db"
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self._old_path
        self._tmpdir.cleanup()

    def test_zero_samples_stay_out_of_the_average(self):
        start = _kyiv(2026, 11, 9, 0, 0)
        apt = database.apartment_inverter_id()
        with database._conn() as db:
            db.execute(
                "INSERT INTO deye_log(grid_v_l1, grid_v_l2, grid_v_l3, ts, inverter_id) VALUES (?,?,?,?,?)",
                (230.0, 0.0, 228.0, start + 10, apt),
            )
            db.execute(
                "INSERT INTO deye_log(grid_v_l1, grid_v_l2, grid_v_l3, ts, inverter_id) VALUES (?,?,?,?,?)",
                (0.0, 0.0, 0.0, start + 70, apt),
            )
        rows = database.deye_voltage_buckets(start, start + 180, 60)
        self.assertEqual(len(rows), 2)
        self.assertAlmostEqual(rows[0]["l1"], 230.0)
        self.assertIsNone(rows[0]["l2"])
        self.assertEqual(rows[1]["dead"], 1)
        self.assertIsNone(rows[1]["l1"])


class LoadChartTests(unittest.TestCase):
    def test_consumption_line_and_light_strip(self):
        from voltage_chart import build_load_chart
        now = _kyiv(2026, 11, 9, 1, 4)
        buckets = [
            {"bucket": now - 3600, "l1": 230.0, "l2": 230.0, "l3": 230.0, "dead": 0, "n": 1, "load_w": 3200.0},
            {"bucket": now - 1800, "l1": None, "l2": None, "l3": None, "dead": 4, "n": 4, "load_w": 40.0},
        ]
        html = build_load_chart(
            now=now, buckets=buckets, today=None, tomorrow=None, queue="5.1",
        )
        self.assertIn('fill="#38bdf8"', html)
        self.assertIn("Остання доба, споживання", html)
        self.assertIn("черга 5.1", html)
        self.assertIn('fill="#22c55e"', html)
        self.assertIn('fill="#fb923c"', html)
        self.assertIn("світло було", html)
        self.assertIn("світла не було", html)


class SocChartTests(unittest.TestCase):
    def test_charge_line_and_light_strip(self):
        from voltage_chart import build_soc_chart
        now = _kyiv(2026, 11, 9, 1, 4)
        buckets = [
            {"bucket": now - 1800, "l1": None, "l2": None, "l3": None, "dead": 4, "n": 4, "soc": 40.0},
            {"bucket": now - 120, "l1": 230.0, "l2": 230.0, "l3": 230.0, "dead": 0, "n": 1, "soc": 90.0},
            {"bucket": now - 60, "l1": 230.0, "l2": 230.0, "l3": 230.0, "dead": 0, "n": 1, "soc": 88.0},
        ]
        html = build_soc_chart(
            now=now, buckets=buckets, today=None, tomorrow=None, queue="5.1",
        )
        self.assertIn('stroke="#a78bfa"', html)
        self.assertIn("Остання доба, заряд", html)
        self.assertIn("за 10 хв 88–90 %", html)
        self.assertIn("черга 5.1", html)
        self.assertIn('data-ymin="0"', html)
        self.assertIn('data-ymax="100"', html)
        self.assertIn('fill="#22c55e"', html)
        self.assertIn('fill="#fb923c"', html)
        self.assertIn("світло було", html)
        self.assertIn("світла не було", html)
        self.assertIn(">заряд<", html)
        self.assertIn("<details", html)
        self.assertIn(" open", html)


class BatteryBoardTests(unittest.TestCase):
    def test_outage_runtime_uses_now_and_ten_minute_average(self):
        from voltage_chart import build_battery_board
        html = build_battery_board(
            soc=50, cap_kwh=60, load_w=2000, load_avg_w=2500,
            bat_w=2100, bat_avg_w=2400, avg_samples=8,
            grid_v=(0, 0, 0),
        )
        self.assertIn(">50<", html)
        self.assertIn(">30.0<", html)
        self.assertIn("з 60", html)
        self.assertIn(">2.0<", html)
        self.assertIn(">2.5<", html)
        self.assertIn("Без світла вистачить зараз 15 год, за 10 хв 12 год", html)
        self.assertNotIn("До повної", html)

    def test_charge_time_uses_charge_power(self):
        from voltage_chart import build_battery_board
        html = build_battery_board(
            soc=80, cap_kwh=60, load_w=1500, load_avg_w=1500,
            bat_w=-4000, bat_avg_w=-3000, avg_samples=6,
            grid_v=(230, 230, 228),
        )
        self.assertIn("Заряд 4.0 кВт, до повної зараз 3 год, за 10 хв 4 год", html)
        self.assertNotIn("Без світла", html)
        self.assertNotIn("Мережа є", html)

    def test_grid_without_charge_does_not_invent_a_runtime(self):
        from voltage_chart import build_battery_board
        html = build_battery_board(
            soc=90, cap_kwh=160, load_w=8000, load_avg_w=7000,
            bat_w=500, bat_avg_w=400, avg_samples=5,
            grid_v=(228, 227, 226),
        )
        self.assertIn("Мережа є", html)
        self.assertIn("з 160 кВт·год", html)
        self.assertNotIn("Без світла", html)
        self.assertNotIn("До повної", html)
        self.assertNotIn("vmeter-ghost", html)

    def test_pack_caption_keeps_the_tenth_and_colors_split_high_charge(self):
        from voltage_chart import build_battery_board, soc_color
        html = build_battery_board(
            soc=98, cap_kwh=153.6, load_w=4000, load_avg_w=4000,
            bat_w=1000, bat_avg_w=1000, avg_samples=4,
            grid_v=(230, 230, 230),
        )
        self.assertIn("з 153.6 кВт·год", html)
        self.assertIn("width:98.0%", html)
        self.assertIn("background-size:102.04% 100%", html)
        self.assertNotEqual(soc_color(75), soc_color(98))
        self.assertGreater(int(soc_color(10)[1:3], 16), int(soc_color(98)[1:3], 16))

    def test_chart_fold_is_open_and_remembers_its_key(self):
        html = build_voltage_chart(
            now=_kyiv(2026, 11, 9, 1, 4), buckets=[], today=None, tomorrow=None,
            queue="5.1", fold_key="house-voltage",
        )
        self.assertIn("<details", html)
        self.assertIn('data-ls-key="house-voltage"', html)
        self.assertIn('data-default-open="1"', html)
        self.assertIn(" open", html)


class SocBucketQueryTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._old_path = database.DB_PATH
        database.DB_PATH = Path(self._tmpdir.name) / "t.db"
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self._old_path
        self._tmpdir.cleanup()

    def test_charge_average_stays_with_the_minute(self):
        start = _kyiv(2026, 11, 9, 0, 0)
        apt = database.apartment_inverter_id()
        with database._conn() as db:
            db.execute(
                """INSERT INTO deye_log(grid_v_l1, grid_v_l2, grid_v_l3, battery_soc, ts, inverter_id)
                   VALUES (?,?,?,?,?,?)""",
                (230.0, 230.0, 230.0, 80.0, start + 10, apt),
            )
            db.execute(
                """INSERT INTO deye_log(grid_v_l1, grid_v_l2, grid_v_l3, battery_soc, ts, inverter_id)
                   VALUES (?,?,?,?,?,?)""",
                (231.0, 230.0, 229.0, 60.0, start + 40, apt),
            )
        rows = database.deye_voltage_buckets(start, start + 180, 60)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["soc"], 70.0)

    def test_recent_power_and_capacity(self):
        start = _kyiv(2026, 11, 9, 0, 0)
        apt = database.apartment_inverter_id()
        with database._conn() as db:
            db.execute("UPDATE deye_inverter SET battery_kwh=? WHERE id=?", (60, apt))
            db.execute(
                """INSERT INTO deye_log(load_power_w, battery_power_w, battery_soc, grid_v_l1, ts, inverter_id)
                   VALUES (?,?,?,?,?,?)""",
                (1000, -2000, 50, 0, start, apt),
            )
            db.execute(
                """INSERT INTO deye_log(load_power_w, battery_power_w, battery_soc, grid_v_l1, ts, inverter_id)
                   VALUES (?,?,?,?,?,?)""",
                (3000, -4000, 50, 0, start + 1, apt),
            )
        means = database.deye_recent_power(apt, start - 1, start + 10)
        self.assertEqual(means["n"], 2)
        self.assertAlmostEqual(means["load_w"], 2000)
        self.assertAlmostEqual(means["bat_w"], -3000)
        self.assertAlmostEqual(database.inverter_battery_kwh(apt), 60)


if __name__ == "__main__":
    unittest.main()
