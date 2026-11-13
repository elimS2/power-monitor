"""Brovary raion 79: yellow and red come from the public alert feed."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import database
from dtek import (
    alert_banner_html,
    alert_event_is_open,
    alert_event_view,
    brovary_alert_level,
)
from schedule_board import kyiv_day_bounds


class BrovaryAlertLevelTests(unittest.TestCase):
    def test_yellow_code_is_brovary_only(self):
        alerts = [
            {"luid": 78, "n": "Бориспільський", "al": 1},
            {"luid": 79, "n": "Броварський", "t": "r", "al": 1},
            {"luid": 117, "n": "Конотопський"},
        ]
        self.assertEqual(brovary_alert_level(alerts), "yellow")

    def test_missing_level_on_brovary_is_red(self):
        self.assertEqual(brovary_alert_level([{"location_uid": "79"}]), "red")

    def test_other_raions_do_not_light_brovary(self):
        self.assertIsNone(brovary_alert_level([
            {"luid": 14, "n": "Київська область"},
            {"luid": 25, "al": 1},
            {"luid": 78, "al": 1},
        ]))

    def test_red_wins_when_both_records_exist(self):
        alerts = [
            {"luid": 79, "al": 1},
            {"luid": 79, "alert_level": "red"},
        ]
        self.assertEqual(brovary_alert_level(alerts), "red")

    def test_banner_uses_the_level(self):
        yellow = alert_banner_html({"level": "yellow", "active": True})
        red = alert_banner_html({"level": "red", "active": True})
        clear = alert_banner_html({"level": None, "active": False})
        self.assertIn("alert-yellow", yellow)
        self.assertIn("Жовта тривога, Бровари", yellow)
        self.assertIn("alert-on", red)
        self.assertIn("Червона тривога, Бровари", red)
        self.assertIn("Відбій, Бровари", clear)
        self.assertEqual(alert_banner_html({}), "")

    def test_history_arrow_follows_the_open_level(self):
        self.assertEqual(alert_event_view("alert_yellow")[0], "alert-yellow")
        self.assertTrue(alert_event_is_open("alert_yellow", "yellow"))
        self.assertFalse(alert_event_is_open("alert_on", "yellow"))
        self.assertFalse(alert_event_is_open("alert_yellow", "red"))
        self.assertTrue(alert_event_is_open("alert_off", None))


class AlertDayTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._old_path = database.DB_PATH
        database.DB_PATH = Path(self._tmpdir.name) / "t.db"
        database.init_db()
        self.start, self.end = kyiv_day_bounds("2026-11-10")

    def tearDown(self):
        database.DB_PATH = self._old_path
        self._tmpdir.cleanup()

    def _at(self, hour, minute=0):
        return self.start + hour * 3600 + minute * 60

    def _add(self, event, ts):
        with database._conn() as db:
            db.execute("INSERT INTO alert_events(event, ts) VALUES(?,?)", (event, ts))

    def test_day_line_paints_clear_yellow_and_red_until_now(self):
        self._add("alert_yellow", self._at(10))
        self._add("alert_red", self._at(12))
        self._add("alert_on", self._at(12, 30))
        self._add("alert_off", self._at(13))
        payload = database.read_alert_day("2026-11-10", self._at(15))
        self.assertTrue(payload["today"])
        levels = [segment["level"] for segment in payload["segments"]]
        self.assertEqual(levels, ["off", "yellow", "red", "off"])
        self.assertEqual(payload["segments"][-1]["end"], self._at(15))
        self.assertLess(payload["segments"][-1]["end"], self.end)

    def test_prior_alert_colors_the_start_of_the_day(self):
        self._add("alert_yellow", self.start - 3600)
        payload = database.read_alert_day("2026-11-10", self._at(2))
        self.assertEqual(payload["segments"][0]["level"], "yellow")
        self.assertEqual(payload["segments"][0]["start"], self.start)

    def test_a_future_day_has_no_line_yet(self):
        payload = database.read_alert_day("2026-11-11", self._at(15))
        self.assertFalse(payload["today"])
        self.assertEqual(payload["segments"], [])

    def test_alert_table_starts_closed_under_the_day_line(self):
        page = Path("power_monitor.py").read_text(encoding="utf-8")
        self.assertIn('id="pm-alert-day"', page)
        self.assertIn('id="alert_ev_table" data-ls-key="alert_ev_table_open" data-default-open="0"', page)
        self.assertNotIn('id="alert_ev_table" open', page)
        script = Path("static/app.js").read_text(encoding="utf-8")
        self.assertIn("brk-alert-yellow", script)
        self.assertIn("/api/alerts-day", script)

    def test_breaker_chart_puts_the_alert_lane_under_the_boiler(self):
        import power_monitor

        self._add("alert_yellow", self._at(10))
        self._add("alert_red", self._at(12))
        self._add("alert_off", self._at(13))
        payload = database.read_breaker_board("2026-11-10", self._at(15))
        levels = [segment["level"] for segment in payload["alerts"]]
        self.assertEqual(levels, ["off", "yellow", "red", "off"])
        html = power_monitor._breaker_bars_html(payload, self._at(15))
        self.assertLess(html.index(">Котельня<"), html.index(">Тривога<"))
        self.assertIn("brk-alert-yellow", html)
        self.assertIn("brk-alert-red", html)
        self.assertIn("brk-alert-off", html)
        script = Path("static/app.js").read_text(encoding="utf-8")
        chunk = script[script.index("pm-breakers-board"):]
        self.assertLess(chunk.index("html += breakerBoilerLane"), chunk.index("html += breakerAlertLane"))


if __name__ == "__main__":
    unittest.main()
