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
        self.assertIn('stroke="#fb7185"', html)
        self.assertIn('stroke="#facc15"', html)
        self.assertIn('stroke="#60a5fa"', html)
        self.assertIn("за 10 хв 217–222 В", html)
        self.assertIn(">зараз<", html)
        self.assertIn("09.11", html)

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
        self.assertIn('fill="#fb7185"', html)

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
        with database._conn() as db:
            db.execute(
                "INSERT INTO deye_log(grid_v_l1, grid_v_l2, grid_v_l3, ts) VALUES (?,?,?,?)",
                (230.0, 0.0, 228.0, start + 10),
            )
            db.execute(
                "INSERT INTO deye_log(grid_v_l1, grid_v_l2, grid_v_l3, ts) VALUES (?,?,?,?)",
                (0.0, 0.0, 0.0, start + 70),
            )
        rows = database.deye_voltage_buckets(start, start + 180, 60)
        self.assertEqual(len(rows), 2)
        self.assertAlmostEqual(rows[0]["l1"], 230.0)
        self.assertIsNone(rows[0]["l2"])
        self.assertEqual(rows[1]["dead"], 1)
        self.assertIsNone(rows[1]["l1"])


if __name__ == "__main__":
    unittest.main()
