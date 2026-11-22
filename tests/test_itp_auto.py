"""Desired ITP state and the local decision to read or command. No network."""
from __future__ import annotations

import ast
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import database
from config import UA_TZ
from itp_auto import (
    FOLLOWUP_SEC,
    FOLLOWUP_WINDOW_SEC,
    apply_post_result,
    arm_itp,
    command_followup_due,
    desired_itp,
    disarm_itp,
    empty_itp_auto,
    mutate_itp_auto,
    step_itp,
)
from tuya_breakers import BREAKER_TIMER_FOLLOWUP_SEC, BREAKER_TIMER_FOLLOWUP_WINDOW_SEC


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


def _ready(**overrides) -> dict:
    doc = empty_itp_auto()
    doc.update({
        "enabled": True,
        "applied": "on",
        "timers_cleared_at": 1,
    })
    doc.update(overrides)
    return doc


def _off() -> dict:
    return {"state": "off", "reason": "light-off", "boiler_source": "none"}


class StepItpTests(unittest.TestCase):
    NOW = 1_700_000_100.0

    def test_followup_window_matches_timer_followup(self):
        self.assertEqual(FOLLOWUP_SEC, BREAKER_TIMER_FOLLOWUP_SEC)
        self.assertEqual(FOLLOWUP_WINDOW_SEC, BREAKER_TIMER_FOLLOWUP_WINDOW_SEC)
        sent = self.NOW
        self.assertFalse(command_followup_due(sent, sent + 30))
        self.assertTrue(command_followup_due(sent, sent + 60))
        self.assertTrue(command_followup_due(sent, sent + 150))
        self.assertFalse(command_followup_due(sent, sent + 151))

    def test_disabled_document_does_nothing(self):
        doc, action = step_itp(empty_itp_auto(), _off(), "on", self.NOW, True, "edge")
        self.assertEqual(action, "none")
        self.assertIsNone(doc["applied"])
        self.assertEqual(doc["last"]["state"], "off")

    def test_hold_returns_none_while_enabled(self):
        doc, action = step_itp(_ready(), {"state": "hold", "reason": "settling"}, "on", self.NOW, True, "edge")
        self.assertEqual(action, "none")
        self.assertTrue(doc["enabled"])

    def test_commands_off_stores_last_without_acting(self):
        doc, action = step_itp(_ready(), _off(), "unknown", self.NOW, False, "edge")
        self.assertEqual(action, "none")
        self.assertEqual(doc["last"]["reason"], "light-off")
        self.assertEqual(doc["applied"], "on")

    def test_first_edge_reads_once_per_quarter(self):
        first, action = step_itp(_ready(), _off(), "unknown", self.NOW, True, "edge")
        self.assertEqual(action, "read")
        self.assertEqual(first["slot_spent"], int(self.NOW // 900))
        second, again = step_itp(first, _off(), "unknown", self.NOW + 30, True, "edge")
        self.assertEqual(again, "none")
        self.assertIsNone(second["pending"])

    def test_read_that_matches_applied_then_posts(self):
        doc, action = step_itp(_ready(), _off(), "on", self.NOW, True, "edge")
        self.assertEqual(action, "post")
        self.assertIsNone(doc["pending"])
        saved = apply_post_result(doc, "off", self.NOW, "success")
        self.assertEqual(saved["pending"]["state"], "off")
        self.assertFalse(saved["pending"]["followup_done"])

    def test_rejected_post_does_not_count_and_blocks_the_quarter(self):
        read, action = step_itp(_ready(), _off(), "unknown", self.NOW, True, "edge")
        self.assertEqual(action, "read")
        rejected = apply_post_result(read, "off", self.NOW, "rejected", code=2001)
        self.assertIsNone(rejected["pending"])
        self.assertEqual(rejected["warn"]["kind"], "rejected")
        self.assertEqual(rejected["command_times"], [])
        _, again = step_itp(rejected, _off(), "unknown", self.NOW + 20, True, "edge")
        self.assertEqual(again, "none")

    def test_transport_failure_writes_pending(self):
        saved = apply_post_result(_ready(), "off", self.NOW, "transport")
        self.assertFalse(saved["pending"]["followup_done"])
        self.assertEqual(saved["warn"]["kind"], "transport")
        self.assertEqual(saved["command_times"], [self.NOW])

    def test_hand_disarms_only_when_commands_and_timers_are_ready(self):
        doc, action = step_itp(_ready(), _off(), "off", self.NOW, True, "edge")
        self.assertEqual(action, "none")
        self.assertFalse(doc["enabled"])
        self.assertEqual(doc["pause"]["reason"], "manual")

    def test_hand_does_not_disarm_while_commands_are_off(self):
        doc, action = step_itp(_ready(), _off(), "off", self.NOW, False, "edge")
        self.assertEqual(action, "none")
        self.assertTrue(doc["enabled"])
        self.assertIsNone(doc["pause"])

    def test_hand_does_not_disarm_before_timers_are_cleared(self):
        doc, action = step_itp(_ready(timers_cleared_at=None), _off(), "off", self.NOW, True, "edge")
        self.assertEqual(action, "none")
        self.assertTrue(doc["enabled"])

    def test_hand_does_not_disarm_while_a_warning_is_set(self):
        warned = _ready(warn={"at": 1, "kind": "transport", "code": None})
        doc, _action = step_itp(warned, _off(), "off", self.NOW, True, "edge")
        self.assertTrue(doc["enabled"])

    def test_pending_disagreement_is_not_a_hand(self):
        pending = _ready(pending={"state": "off", "sent_at": self.NOW, "followup_done": False})
        doc, action = step_itp(pending, _off(), "on", self.NOW, True, "edge")
        self.assertEqual(action, "none")
        self.assertTrue(doc["enabled"])

    def test_uncleared_timers_do_not_read_or_post(self):
        doc, action = step_itp(_ready(timers_cleared_at=None), _off(), "unknown", self.NOW, True, "edge")
        self.assertEqual(action, "none")
        self.assertIsNone(doc["slot_spent"])

    def test_three_commands_still_post_on_the_quarter_slot(self):
        times = [self.NOW - 30, self.NOW - 20, self.NOW - 10]
        doc, action = step_itp(_ready(command_times=times), _off(), "on", self.NOW, True, "quarter")
        self.assertEqual(action, "post")
        self.assertTrue(doc["enabled"])

    def test_four_commands_disarm_before_another_post(self):
        times = [self.NOW - 40, self.NOW - 30, self.NOW - 20, self.NOW - 10]
        doc, action = step_itp(_ready(command_times=times), _off(), "on", self.NOW, True, "quarter")
        self.assertEqual(action, "none")
        self.assertFalse(doc["enabled"])
        self.assertEqual(doc["pause"]["reason"], "flap")

    def test_old_command_falls_out_of_the_hour(self):
        times = [self.NOW - 3601, self.NOW - 30, self.NOW - 20, self.NOW - 10]
        doc, action = step_itp(_ready(command_times=times), _off(), "on", self.NOW, True, "quarter")
        self.assertEqual(action, "post")
        self.assertTrue(doc["enabled"])

    def test_arm_keeps_recent_commands(self):
        armed = arm_itp(_ready(enabled=False, command_times=[self.NOW - 10]), "on")
        self.assertEqual(armed["command_times"], [self.NOW - 10])
        self.assertFalse(armed["timer_delete_attempted"])

    def test_fourth_counted_success_disarms_after_it_is_sent(self):
        times = [self.NOW - 30, self.NOW - 20, self.NOW - 10]
        saved = apply_post_result(_ready(command_times=times), "off", self.NOW, "success")
        self.assertEqual(saved["pending"]["state"], "off")
        self.assertFalse(saved["enabled"])
        self.assertEqual(saved["pause"]["reason"], "flap")

    def test_quarter_slot_with_unknown_actual_does_nothing(self):
        _doc, action = step_itp(_ready(), _off(), "unknown", self.NOW, True, "quarter")
        self.assertEqual(action, "none")


class MutateItpTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._old_path = database.DB_PATH
        database.DB_PATH = Path(self._tmpdir.name) / "t.db"
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self._old_path
        self._tmpdir.cleanup()

    def test_arm_and_disarm_round_trip(self):
        def arm(doc):
            doc.clear()
            doc.update(arm_itp(empty_itp_auto(), "off"))
            doc["command_times"] = [10]
            doc["timer_delete_attempted"] = True

        stored = mutate_itp_auto(arm)
        self.assertTrue(stored["enabled"])
        self.assertEqual(stored["command_times"], [10])

        def disarm(doc):
            fresh = disarm_itp(doc)
            doc.clear()
            doc.update(fresh)

        stored = mutate_itp_auto(disarm)
        self.assertFalse(stored["enabled"])
        self.assertTrue(stored["timer_delete_attempted"])
        self.assertEqual(stored["command_times"], [10])


if __name__ == "__main__":
    unittest.main()
