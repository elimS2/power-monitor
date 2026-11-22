"""Desired ITP state. No network and no database."""
from __future__ import annotations

import ast
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from config import UA_TZ
from itp_auto import desired_itp


def _at(hour: int, minute: int) -> datetime:
    return datetime(2026, 11, 22, hour, minute, tzinfo=UA_TZ)


def _light(kind: str, now: datetime, minutes: int) -> dict:
    return {"kind": kind, "since": now - timedelta(minutes=minutes)}


class DesiredItpTests(unittest.TestCase):
    def test_light_up_for_14_minutes_holds(self):
        now = _at(10, 0)
        got = desired_itp(now, _light("up", now, 14), {"kind": "missing"})
        self.assertEqual(got, {"state": "hold", "reason": "settling", "boiler_source": "none"})

    def test_light_up_for_15_minutes_turns_on(self):
        now = _at(10, 0)
        got = desired_itp(now, _light("up", now, 15), {"kind": "missing"})
        self.assertEqual(got, {"state": "on", "reason": "light-on", "boiler_source": "none"})

    def test_light_down_for_15_minutes_turns_off(self):
        now = _at(10, 0)
        got = desired_itp(now, _light("down", now, 15), {"kind": "missing"})
        self.assertEqual(got, {"state": "off", "reason": "light-off", "boiler_source": "none"})

    def test_missing_boiler_at_18_turns_on(self):
        now = _at(18, 0)
        got = desired_itp(now, _light("down", now, 20), {"kind": "missing"})
        self.assertEqual(got, {"state": "on", "reason": "boiler", "boiler_source": "default"})

    def test_missing_boiler_at_17_59_stays_off(self):
        now = _at(17, 59)
        got = desired_itp(now, _light("down", now, 20), {"kind": "missing"})
        self.assertEqual(got, {"state": "off", "reason": "light-off", "boiler_source": "none"})

    def test_light_up_at_midnight_stays_on_without_default_window(self):
        now = _at(0, 0)
        got = desired_itp(now, _light("up", now, 20), {"kind": "missing"})
        self.assertEqual(got, {"state": "on", "reason": "light-on", "boiler_source": "none"})

    def test_light_down_at_midnight_is_off(self):
        now = _at(0, 0)
        got = desired_itp(now, _light("down", now, 20), {"kind": "missing"})
        self.assertEqual(got, {"state": "off", "reason": "light-off", "boiler_source": "none"})

    def test_explicit_evening_window_is_closed_at_18_30(self):
        now = _at(18, 30)
        boiler = {"kind": "intervals", "intervals": [["19:00", "24:00"]]}
        got = desired_itp(now, _light("down", now, 20), boiler)
        self.assertEqual(got, {"state": "off", "reason": "light-off", "boiler_source": "none"})

    def test_empty_intervals_do_not_open_the_boiler(self):
        now = _at(19, 0)
        got = desired_itp(now, _light("down", now, 20), {"kind": "intervals", "intervals": []})
        self.assertEqual(got, {"state": "off", "reason": "light-off", "boiler_source": "none"})

    def test_unknown_light_with_open_boiler_turns_on(self):
        now = _at(19, 0)
        boiler = {"kind": "intervals", "intervals": [["19:00", "24:00"]]}
        got = desired_itp(now, {"kind": "unknown"}, boiler)
        self.assertEqual(got, {"state": "on", "reason": "boiler", "boiler_source": "row"})

    def test_unknown_light_with_closed_boiler_holds(self):
        now = _at(10, 0)
        got = desired_itp(now, {"kind": "unknown"}, {"kind": "missing"})
        self.assertEqual(got, {"state": "hold", "reason": "unknown", "boiler_source": "none"})

    def test_window_includes_start_and_excludes_end(self):
        boiler = {"kind": "intervals", "intervals": [["18:00", "24:00"]]}
        start = desired_itp(_at(18, 0), {"kind": "unknown"}, boiler)
        late = desired_itp(_at(23, 59), {"kind": "unknown"}, boiler)
        self.assertEqual(start["boiler_source"], "row")
        self.assertEqual(late["state"], "on")
        self.assertEqual(late["reason"], "boiler")

    def test_bad_pair_is_ignored(self):
        now = _at(19, 0)
        boiler = {"kind": "intervals", "intervals": [["nope", "later"], ["19:00", "24:00"]]}
        got = desired_itp(now, {"kind": "unknown"}, boiler)
        self.assertEqual(got["state"], "on")
        self.assertEqual(got["boiler_source"], "row")

    def test_only_bad_pairs_do_not_crash(self):
        now = _at(19, 0)
        boiler = {"kind": "intervals", "intervals": [["bad", "clock"], "19:00"]}
        got = desired_itp(now, _light("down", now, 20), boiler)
        self.assertEqual(got, {"state": "off", "reason": "light-off", "boiler_source": "none"})

    def test_module_has_no_io_imports(self):
        source = Path(__file__).resolve().parents[1].joinpath("itp_auto.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
        blocked = ("httpx", "tuya", "kv_", "power_events")
        self.assertFalse(any(any(part in name for part in blocked) for name in names))


if __name__ == "__main__":
    unittest.main()
