"""Brovary raion 79: yellow and red come from the public alert feed."""
from __future__ import annotations

import unittest

from dtek import (
    alert_banner_html,
    alert_event_is_open,
    alert_event_view,
    brovary_alert_level,
)


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


if __name__ == "__main__":
    unittest.main()
