"""Voltage day chart: samples, actual outages, and the queue ahead."""
from __future__ import annotations

import tempfile
import time
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
        self.assertIn("Остання доба, напруга", html)
        self.assertNotIn("графік відключень", html)
        self.assertIn("за 10 хв 217–222 В", html)
        self.assertIn("data-t0=", html)
        self.assertIn("vchart-main", html)
        self.assertIn("vchart-strip", html)
        self.assertIn("Колесо збільшує", html)
        self.assertIn("щипок", html)
        self.assertIn("без адресної стрічки", html)
        self.assertNotIn("свайп", html)
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

    def test_temperature_average_and_saved_sample(self):
        start = _kyiv(2026, 11, 14, 2, 0)
        apt = database.apartment_inverter_id()
        database.save_deye_log(
            grid_v_l1=230, grid_v_l2=230, grid_v_l3=230,
            temp_batt_c=22.0, temp_rad_c=50.7, temp_dc_c=48.4,
            inverter_id=apt,
        )
        saved = database.recent_deye_log(1, apt)[0]
        self.assertEqual(saved["temp_batt_c"], 22.0)
        self.assertEqual(saved["temp_rad_c"], 50.7)
        self.assertEqual(saved["temp_dc_c"], 48.4)
        with database._conn() as db:
            db.execute(
                """INSERT INTO deye_log(
                       grid_v_l1, grid_v_l2, grid_v_l3,
                       temp_batt_c, temp_rad_c, temp_dc_c, ts, inverter_id)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (230.0, 230.0, 230.0, 20.0, 40.0, 44.0, start + 10, apt),
            )
            db.execute(
                """INSERT INTO deye_log(
                       grid_v_l1, grid_v_l2, grid_v_l3,
                       temp_batt_c, temp_rad_c, temp_dc_c, ts, inverter_id)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (230.0, 230.0, 230.0, 24.0, 50.0, 48.0, start + 40, apt),
            )
        rows = database.deye_voltage_buckets(start, start + 180, 60)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["temp_batt"], 22.0)
        self.assertAlmostEqual(rows[0]["temp_rad"], 45.0)
        self.assertAlmostEqual(rows[0]["temp_dc"], 46.0)


class TempChartTests(unittest.TestCase):
    def test_three_lines_and_light_strip(self):
        from voltage_chart import build_temp_chart
        now = _kyiv(2026, 11, 14, 2, 10)
        buckets = [
            {"bucket": now - 1800, "l1": None, "l2": None, "l3": None, "dead": 4, "n": 4,
             "temp_batt": 21.0, "temp_rad": 48.0, "temp_dc": 46.0, "temp_out": 6.0},
            {"bucket": now - 120, "l1": 230.0, "l2": 230.0, "l3": 230.0, "dead": 0, "n": 1,
             "temp_batt": 22.0, "temp_rad": 50.7, "temp_dc": 48.4, "temp_out": 5.4},
            {"bucket": now - 60, "l1": 230.0, "l2": 230.0, "l3": 230.0, "dead": 0, "n": 1,
             "temp_batt": 22.4, "temp_rad": 51.0, "temp_dc": 48.8, "temp_out": 5.4},
        ]
        html = build_temp_chart(
            now=now, buckets=buckets, today=None, tomorrow=None, queue="5.1",
        )
        self.assertIn('stroke="#22d3ee"', html)
        self.assertIn('stroke="#fbbf24"', html)
        self.assertIn('stroke="#f472b6"', html)
        self.assertIn('stroke="#f8fafc"', html)
        self.assertIn("Остання доба, температура", html)
        self.assertIn("за 10 хв 22.0–22.4 °C", html)
        self.assertIn('data-ymin="-20"', html)
        self.assertIn('data-ymax="100"', html)
        self.assertIn('fill="#22c55e"', html)
        self.assertIn('fill="#fb923c"', html)
        self.assertIn("світло було", html)
        self.assertIn("світла не було", html)
        self.assertIn(">батарея<", html)
        self.assertIn(">радіатор<", html)
        self.assertIn(">вулиця<", html)
        self.assertIn(">трансформатор<", html)
        self.assertIn("<details", html)
        self.assertIn(" open", html)

    def test_board_shows_battery_temperature(self):
        from voltage_chart import build_battery_board
        html = build_battery_board(
            soc=98, cap_kwh=153.6, load_w=4000, load_avg_w=4000,
            bat_w=1000, bat_avg_w=1000, avg_samples=4,
            grid_v=(230, 230, 230), battery_c=22.0,
        )
        self.assertIn("vmeter-temp", html)
        self.assertIn(">22.0<", html)
        self.assertIn(">ТЕМП<", html)
        self.assertIn(">батарея<", html)

    def test_decode_uses_the_offset(self):
        from deye_reader import decode_temp_c
        self.assertEqual(decode_temp_c(1220), 22.0)
        self.assertEqual(decode_temp_c(1484), 48.4)
        self.assertEqual(decode_temp_c(1507), 50.7)
        self.assertIsNone(decode_temp_c(0))

    def test_outdoor_holds_for_half_an_hour_then_drops(self):
        from voltage_chart import stamp_outdoor
        start = 1_000_000.0
        buckets = [{"bucket": start + 20 * 60}, {"bucket": start + 40 * 60}]
        stamped = stamp_outdoor(buckets, [(start, 4.5)])
        self.assertEqual(stamped[0]["temp_out"], 4.5)
        self.assertIsNone(stamped[1]["temp_out"])
        self.assertNotIn("temp_out", buckets[0])


class OutdoorSampleTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._old_path = database.DB_PATH
        database.DB_PATH = Path(self._tmpdir.name) / "t.db"
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self._old_path
        self._tmpdir.cleanup()

    def test_prior_reading_is_included(self):
        start = _kyiv(2026, 11, 14, 2, 0)
        database.save_weather_log(3.0, 80, 2, 0, 1, 8, start - 600)
        database.save_weather_log(4.2, 80, 2, 0, 1, 8, start + 60)
        samples = database.weather_outdoor_samples(start, start + 3600)
        self.assertEqual(samples, [(start - 600, 3.0), (start + 60, 4.2)])

    def test_alerts_follow_the_basement_until_the_switch_is_flipped(self):
        apt = database.apartment_inverter_id()
        house = database.house_inverter_record()["id"]
        database.save_deye_log(grid_v_l1=243, grid_v_l2=0, grid_v_l3=0, inverter_id=apt)
        database.save_deye_log(grid_v_l1=247, grid_v_l2=245, grid_v_l3=246, inverter_id=house)
        previous = database.NOTIFY_GRID_SOURCE
        try:
            database.NOTIFY_GRID_SOURCE = "house"
            chosen = database.notify_grid_inverter_id()
            self.assertEqual(chosen, house)
            self.assertTrue(database.has_all_three_phases_voltage(inverter_id=chosen))
            database.NOTIFY_GRID_SOURCE = "apartment"
            chosen = database.notify_grid_inverter_id()
            self.assertEqual(chosen, apt)
            self.assertFalse(database.has_all_three_phases_voltage(inverter_id=chosen))
        finally:
            database.NOTIFY_GRID_SOURCE = previous

    def test_all_live_phases_above_250_are_high_voltage(self):
        apt = database.apartment_inverter_id()
        start = time.time()
        with database._conn() as db:
            db.execute(
                """INSERT INTO deye_log(grid_v_l1, grid_v_l2, grid_v_l3, ts, inverter_id)
                   VALUES (?,?,?,?,?)""",
                (251.0, 252.0, 253.0, start, apt),
            )
        self.assertEqual(database.deye_voltage_trend(inverter_id=apt), "high")
        with database._conn() as db:
            db.execute(
                """INSERT INTO deye_log(grid_v_l1, grid_v_l2, grid_v_l3, ts, inverter_id)
                   VALUES (?,?,?,?,?)""",
                (250.0, 260.0, 260.0, start + 30, apt),
            )
        self.assertIsNone(database.deye_voltage_trend(inverter_id=apt))
        with database._conn() as db:
            db.execute(
                """INSERT INTO deye_log(grid_v_l1, grid_v_l2, grid_v_l3, ts, inverter_id)
                   VALUES (?,?,?,?,?)""",
                (249.0, 260.0, 260.0, start + 60, apt),
            )
        self.assertIsNone(database.deye_voltage_trend(inverter_id=apt))


if __name__ == "__main__":
    unittest.main()
