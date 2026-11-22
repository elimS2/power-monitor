"""Desired ITP state and the local decision to read or command. No network."""
from __future__ import annotations

import ast
import asyncio
import json
import os
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
    format_itp_card,
    itp_card_html,
    mutate_itp_auto,
    read_itp_auto,
    reset_itp_tick_clock,
    step_itp,
    tick_itp_decision,
)
import httpx
from tuya_breakers import (
    BREAKER_TIMER_FOLLOWUP_SEC,
    BREAKER_TIMER_FOLLOWUP_WINDOW_SEC,
    BreakerPollConfig,
    TokenCache,
    run_itp_auto,
)


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
        want_on = {"state": "on", "reason": "light-on", "boiler_source": "none"}
        doc, action = step_itp(_ready(), want_on, "off", self.NOW, True, "edge")
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


class TickItpTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._old_path = database.DB_PATH
        database.DB_PATH = Path(self._tmpdir.name) / "t.db"
        database.init_db()
        reset_itp_tick_clock()

    def tearDown(self):
        database.DB_PATH = self._old_path
        self._tmpdir.cleanup()
        reset_itp_tick_clock()

    def _beat(self, ts: float) -> None:
        with database._conn() as db:
            db.execute(
                "INSERT INTO heartbeats(plug204, plug175, ts) VALUES(1, 1, ?)",
                (ts,),
            )

    def _event(self, event: str, ts: float) -> None:
        with database._conn() as db:
            db.execute("INSERT INTO power_events(event, ts) VALUES(?, ?)", (event, ts))

    def test_stale_heartbeat_stores_hold(self):
        now = _at(10, 0)
        unix = now.timestamp()
        self._beat(unix - 301)
        self._event("up", unix - 20 * 60)
        with self.assertLogs("power_monitor", level="INFO") as caught:
            action = tick_itp_decision(now, unix)
        self.assertEqual(action, "none")
        last = read_itp_auto()["last"]
        self.assertEqual(last["state"], "hold")
        self.assertEqual(last["reason"], "unknown")
        self.assertTrue(any("hold unknown" in line for line in caught.output))
        self.assertIn("немає свіжого факту світла", format_itp_card(read_itp_auto()))

    def test_missing_boiler_at_18_stores_default_on(self):
        now = _at(18, 0)
        unix = now.timestamp()
        self._beat(unix - 301)
        with self.assertLogs("power_monitor", level="INFO") as caught:
            action = tick_itp_decision(now, unix)
        self.assertEqual(action, "none")
        last = read_itp_auto()["last"]
        self.assertEqual(last["state"], "on")
        self.assertEqual(last["reason"], "boiler")
        self.assertEqual(last["boiler_source"], "default")
        text = format_itp_card(read_itp_auto())
        self.assertIn("Керування: ручне.", text)
        self.assertIn("котельня", text)
        self.assertIn("Графік котельні не приходив, вікно 18:00–24:00.", text)
        self.assertTrue(any("boiler-default" in line and "commands-off" in line for line in caught.output))

    def test_light_up_for_16_minutes_stores_on(self):
        now = _at(10, 0)
        unix = now.timestamp()
        self._beat(unix)
        self._event("up", unix - 16 * 60)
        action = tick_itp_decision(now, unix)
        self.assertEqual(action, "none")
        last = read_itp_auto()["last"]
        self.assertEqual(last["state"], "on")
        self.assertEqual(last["reason"], "light-on")
        text = format_itp_card(read_itp_auto())
        self.assertIn("Керування: ручне.", text)
        self.assertIn("світло вже 15 хв", text)

    def test_tick_cannot_read_or_post(self):
        import httpx

        now = _at(10, 0)
        unix = now.timestamp()
        self._beat(unix)
        self._event("down", unix - 20 * 60)

        def plant(doc):
            doc.clear()
            doc.update(_ready())

        mutate_itp_auto(plant)
        reset_itp_tick_clock()
        calls = []
        real_client = httpx.Client
        real_async = httpx.AsyncClient

        def client(*args, **kwargs):
            calls.append("client")
            return real_client(*args, **kwargs)

        def async_client(*args, **kwargs):
            calls.append("async")
            return real_async(*args, **kwargs)

        httpx.Client = client
        httpx.AsyncClient = async_client
        try:
            action = tick_itp_decision(now, unix)
        finally:
            httpx.Client = real_client
            httpx.AsyncClient = real_async
        self.assertEqual(action, "none")
        self.assertEqual(calls, [])
        doc = read_itp_auto()
        self.assertTrue(doc["enabled"])
        self.assertEqual(doc["last"]["state"], "off")
        self.assertIsNone(doc["pending"])
        self.assertIsNone(doc["slot_spent"])
        card = itp_card_html()
        self.assertIn("Керування: автоматичне.", card)
        self.assertIn("Команди ще вимкнені.", card)
        self.assertNotIn("в адмінці", card)
        self.assertNotIn("<button", card)

    def test_second_tick_inside_a_minute_keeps_the_previous_decision(self):
        now = _at(10, 0)
        unix = now.timestamp()
        self._beat(unix)
        self._event("up", unix - 16 * 60)
        tick_itp_decision(now, unix)
        self._event("down", unix - 20 * 60)
        tick_itp_decision(now, unix + 30)
        self.assertEqual(read_itp_auto()["last"]["reason"], "light-on")

    def test_card_names_a_hand_and_a_flap(self):
        manual = format_itp_card({
            "enabled": False,
            "pause": {"reason": "manual", "at": _at(21, 5).timestamp()},
            "warn": {"kind": "rejected"},
        })
        self.assertIn("Керування: ручне. О 21:05 перемкнули вручну.", manual)
        self.assertIn("Хмара не підтвердила команду.", manual)
        flap = format_itp_card({"enabled": False, "pause": {"reason": "flap"}})
        self.assertEqual(flap, "Керування: ручне. За годину вже 4 перемикання.")

    def test_heat_card_has_the_line_and_the_light_card_does_not(self):
        from power_monitor import _breaker_lines_html

        html = _breaker_lines_html({
            "devices": {
                "svitlo": {
                    "ready": True, "switch": 1, "energy_today_kwh": 1,
                    "since_charge_kwh": 0, "since_charge_sec": 0, "updated_at": 1,
                    "phases": {}, "spans": [],
                },
                "itp": {
                    "ready": True, "switch": 0, "energy_today_kwh": 0,
                    "since_charge_kwh": 0, "since_charge_sec": 0, "updated_at": 1,
                    "phases": {"a": {"p": 0}, "b": {"p": 0}, "c": {"p": 0}},
                    "spans": [],
                },
            }
        }, 1)
        self.assertEqual(html.count("brk-auto"), 1)
        self.assertIn("Керування: ручне.", html)
        self.assertNotIn("<button", html)
        light = html.split('data-brk="svitlo"', 1)[1].split('data-brk="itp"', 1)[0]
        self.assertNotIn("Авто", light)
        self.assertNotIn("brk-auto", light)


class AdminItpTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._old_path = database.DB_PATH
        database.DB_PATH = Path(self._tmpdir.name) / "t.db"
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self._old_path
        self._tmpdir.cleanup()

    def _day(self, day: str, switch: int, watts: int, updated: float) -> None:
        phase = json.dumps({
            "a": {"v": 230, "i": 0, "p": watts},
            "b": {"v": 230, "i": 0, "p": 0},
            "c": {"v": 230, "i": 0, "p": 0},
        })
        with database._conn() as db:
            db.execute(
                """INSERT INTO breaker_day(
                       device, day, energy_base_kwh, energy_kwh, energy_today_kwh,
                       switch, span_json, phase_json, updated_at
                   ) VALUES('itp', ?, 0, 0, 0, ?, '[]', ?, ?)""",
                (day, switch, phase, updated),
            )

    def test_arm_copies_the_latest_day_and_disarm_keeps_it(self):
        import httpx
        from api.admin import set_itp_armed

        def plant(doc):
            doc.clear()
            doc.update(empty_itp_auto())
            doc["command_times"] = [10]
            doc["timer_delete_attempted"] = True
            doc["pause"] = {"at": 1, "reason": "manual", "was": "on", "now": "off"}
            doc["warn"] = {"at": 1, "kind": "rejected", "code": 2001}
            doc["applied"] = "on"

        mutate_itp_auto(plant)
        self._day("2026-11-21", 0, 100, 1)
        self._day("2026-11-22", 1, 0, 2)
        calls = []
        real_client = httpx.Client
        httpx.Client = lambda *args, **kwargs: calls.append("client")
        try:
            with self.assertLogs("power_monitor", level="INFO") as caught:
                armed = set_itp_armed(True)
        finally:
            httpx.Client = real_client
        self.assertEqual(calls, [])
        self.assertTrue(armed["enabled"])
        self.assertEqual(armed["line"], "Керування: автоматичне. Команди ще вимкнені.")
        self.assertFalse(armed["commands_on"])
        stored = read_itp_auto()
        self.assertEqual(stored["applied"], "off")
        self.assertEqual(stored["command_times"], [10])
        self.assertFalse(stored["timer_delete_attempted"])
        self.assertIsNone(stored["pause"])
        self.assertIsNone(stored["warn"])
        self.assertIsNone(stored["pending"])
        self.assertTrue(any("itp-auto: admin arm" in line for line in caught.output))
        self.assertFalse(any("post" in line for line in caught.output))

        def mark_attempt(doc):
            doc["timer_delete_attempted"] = True

        mutate_itp_auto(mark_attempt)
        disarmed = set_itp_armed(False)
        self.assertFalse(disarmed["enabled"])
        self.assertIn("Керування: ручне.", disarmed["line"])
        stored = read_itp_auto()
        self.assertEqual(stored["applied"], "off")
        self.assertEqual(stored["command_times"], [10])
        self.assertTrue(stored["timer_delete_attempted"])
        card = itp_card_html()
        self.assertIn("Керування: ручне.", card)
        self.assertNotIn("<button", card)

    def test_arm_without_a_day_row_leaves_applied_empty(self):
        from api.admin import set_itp_armed

        armed = set_itp_armed(True)
        self.assertTrue(armed["enabled"])
        self.assertIsNone(read_itp_auto()["applied"])

    def test_stranger_key_is_forbidden(self):
        from fastapi import HTTPException
        from api.admin import ep_admin_itp_auto_get, ep_admin_itp_auto_set

        for call in (
            lambda: ep_admin_itp_auto_get(key="not-admin"),
            lambda: ep_admin_itp_auto_set(key="not-admin", enabled=1),
        ):
            with self.assertRaises(HTTPException) as caught:
                call()
            self.assertEqual(caught.exception.status_code, 403)

    def test_admin_page_shows_the_button_and_the_public_card_has_none(self):
        import asyncio
        import api.deps
        import power_monitor

        original = api.deps.check_admin
        api.deps.check_admin = lambda key: None
        try:
            page = asyncio.run(power_monitor.admin_page(key="x"))
        finally:
            api.deps.check_admin = original
        self.assertIn("Увімкнути авто", page)
        self.assertIn("Обігрів, авто", page)
        self.assertIn("Ця сторінка їх не вмикає.", page)
        self.assertNotIn("/v1.0/devices", page)


class _Reply:
    def __init__(self, status: int, body: dict):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class _Cloud:
    def __init__(self, switch_on: bool = True, timer_ok: bool = True, fail_status: bool = False):
        self.calls = []
        self.switch_on = switch_on
        self.timer_ok = timer_ok
        self.fail_status = fail_status

    async def get(self, url, headers=None):
        self.calls.append(("GET", url, None))
        if self.fail_status and url.endswith("/status"):
            raise httpx.TimeoutException("slow")
        if "/timer/" in url:
            body = {"success": True, "result": []} if self.timer_ok else {"success": False, "code": 2008}
            return _Reply(200, body)
        if url.endswith("/status"):
            return _Reply(200, {"success": True, "result": [{"code": "switch", "value": self.switch_on}]})
        raise AssertionError(url)

    async def request(self, method, url, content=None, headers=None):
        self.calls.append((method, url, content))
        return _Reply(200, {"success": True, "result": True})


class CloudItpTests(unittest.TestCase):
    ITP = "heatbreaker1"
    LIGHT = "lightbreaker1"

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._old_path = database.DB_PATH
        database.DB_PATH = Path(self._tmpdir.name) / "t.db"
        database.init_db()
        reset_itp_tick_clock()
        self._old_commands = os.environ.get("ITP_AUTO_COMMANDS")
        self._old_slot = os.environ.get("ITP_AUTO_SLOT")
        os.environ["ITP_AUTO_COMMANDS"] = "1"
        os.environ.pop("ITP_AUTO_SLOT", None)

    def tearDown(self):
        if self._old_commands is None:
            os.environ.pop("ITP_AUTO_COMMANDS", None)
        else:
            os.environ["ITP_AUTO_COMMANDS"] = self._old_commands
        if self._old_slot is None:
            os.environ.pop("ITP_AUTO_SLOT", None)
        else:
            os.environ["ITP_AUTO_SLOT"] = self._old_slot
        database.DB_PATH = self._old_path
        self._tmpdir.cleanup()
        reset_itp_tick_clock()

    def _moment(self, hour: int = 10, minute: int = 7):
        moment = _at(hour, minute)
        return moment, moment.timestamp()

    def _cfg(self):
        return BreakerPollConfig("access", "secret", (("svitlo", self.LIGHT), ("itp", self.ITP)))

    def _cache(self, now: float):
        cache = TokenCache()
        cache.token = "token"
        cache.refresh_at = now + 10_000
        return cache

    def _beat(self, ts: float) -> None:
        with database._conn() as db:
            db.execute("INSERT INTO heartbeats(plug204, plug175, ts) VALUES(1, 1, ?)", (ts,))

    def _event(self, event: str, ts: float) -> None:
        with database._conn() as db:
            db.execute("INSERT INTO power_events(event, ts) VALUES(?, ?)", (event, ts))

    def _plant(self, **fields) -> None:
        def update(doc):
            doc.clear()
            doc.update(empty_itp_auto())
            doc.update(fields)

        mutate_itp_auto(update)

    def _run(self, cloud, moment, now: float):
        asyncio.run(run_itp_auto(cloud, self._cfg(), self._cache(now), moment, now))

    def _urls(self, cloud) -> list[str]:
        return [item[1] for item in cloud.calls]

    def test_hold_and_disabled_issue_no_requests(self):
        moment, now = self._moment()
        self._beat(now - 301)
        self._plant(enabled=True, applied="on", timers_cleared_at=1, timer_delete_attempted=True)
        cloud = _Cloud()
        self._run(cloud, moment, now)
        self.assertEqual(cloud.calls, [])
        reset_itp_tick_clock()
        self._plant(enabled=False, timers_cleared_at=1, timer_delete_attempted=True)
        self._beat(now)
        self._event("up", now - 16 * 60)
        cloud = _Cloud()
        self._run(cloud, moment, now)
        self.assertEqual(cloud.calls, [])

    def test_edge_reads_once_and_posts_only_when_the_breaker_differs(self):
        moment, now = self._moment()
        self._beat(now)
        self._event("down", now - 20 * 60)
        self._plant(enabled=True, applied="on", timers_cleared_at=1, timer_delete_attempted=True)
        cloud = _Cloud(switch_on=True)
        self._run(cloud, moment, now)
        posts = [item for item in cloud.calls if item[0] == "POST"]
        self.assertEqual(len([url for url in self._urls(cloud) if url.endswith("/status")]), 1)
        self.assertEqual(len(posts), 1)
        self.assertIn(b'"code":"switch"', posts[0][2])
        self.assertNotIn("iot-03", posts[0][1])
        self.assertTrue(all(self.LIGHT not in url for url in self._urls(cloud)))
        self.assertEqual(read_itp_auto()["pending"]["state"], "off")

        reset_itp_tick_clock()
        self._plant(enabled=True, applied="on", timers_cleared_at=1, timer_delete_attempted=True)
        cloud = _Cloud(switch_on=False)
        self._run(cloud, moment, now)
        self.assertEqual(len([url for url in self._urls(cloud) if url.endswith("/status")]), 1)
        self.assertFalse(any(item[0] == "POST" for item in cloud.calls))
        self.assertEqual(read_itp_auto()["applied"], "off")

    def test_failed_read_does_not_post_or_retry_inside_the_quarter(self):
        moment, now = self._moment()
        self._beat(now)
        self._event("down", now - 20 * 60)
        self._plant(enabled=True, applied="on", timers_cleared_at=1, timer_delete_attempted=True)
        cloud = _Cloud(fail_status=True)
        self._run(cloud, moment, now)
        self.assertFalse(any(item[0] == "POST" for item in cloud.calls))
        first = len(cloud.calls)
        later = now + 60
        self._run(cloud, moment, later)
        self.assertEqual(len(cloud.calls), first)

    def test_commands_off_issues_nothing_while_armed(self):
        os.environ["ITP_AUTO_COMMANDS"] = "0"
        moment, now = self._moment()
        self._beat(now)
        self._event("down", now - 20 * 60)
        self._plant(enabled=True, applied="on", timers_cleared_at=1, timer_delete_attempted=True)
        cloud = _Cloud()
        self._run(cloud, moment, now)
        self.assertEqual(cloud.calls, [])
        self.assertIsNone(read_itp_auto()["pending"])

    def test_confirm_window_reads_the_heat_breaker_once(self):
        moment, now = self._moment()
        sent = now - 30
        self._plant(enabled=False, pending={"state": "off", "sent_at": sent, "followup_done": False})
        early = _Cloud()
        self._run(early, moment, now)
        self.assertEqual(early.calls, [])

        reset_itp_tick_clock()
        due = sent + 60
        cloud = _Cloud(switch_on=False)
        self._run(cloud, datetime.fromtimestamp(due, UA_TZ), due)
        status = [url for url in self._urls(cloud) if url.endswith("/status")]
        self.assertEqual(len(status), 1)
        self.assertTrue(all(self.LIGHT not in url for url in self._urls(cloud)))
        self.assertIsNone(read_itp_auto()["pending"])

        self._plant(enabled=False, pending={"state": "off", "sent_at": due - 60, "followup_done": False})
        reset_itp_tick_clock()
        mismatch = _Cloud(switch_on=True)
        self._run(mismatch, datetime.fromtimestamp(due, UA_TZ), due)
        stored = read_itp_auto()
        self.assertIsNotNone(stored["pending"])
        self.assertFalse(stored["enabled"])

        reset_itp_tick_clock()
        again = _Cloud()
        self._run(again, datetime.fromtimestamp(due + 10, UA_TZ), due + 10)
        self.assertEqual(again.calls, [])

        self._plant(enabled=False, pending={"state": "off", "sent_at": now, "followup_done": False})
        reset_itp_tick_clock()
        late = _Cloud()
        self._run(late, datetime.fromtimestamp(now + 151, UA_TZ), now + 151)
        self.assertEqual(late.calls, [])

    def test_failed_timer_delete_is_not_retried_until_the_next_arm(self):
        from api.admin import set_itp_armed

        moment, now = self._moment()
        self._beat(now - 301)
        self._plant(enabled=True, applied="on")
        cloud = _Cloud(timer_ok=False)
        self._run(cloud, moment, now)
        self.assertTrue(any("/timer/" in url for url in self._urls(cloud)))
        self.assertFalse(any(item[0] in ("POST", "DELETE") for item in cloud.calls))
        stored = read_itp_auto()
        self.assertTrue(stored["timer_delete_attempted"])
        self.assertIsNone(stored["timers_cleared_at"])
        self.assertEqual(stored["warn"]["kind"], "timer-delete")

        reset_itp_tick_clock()
        again = _Cloud(timer_ok=False)
        self._run(again, moment, now + 61)
        self.assertEqual(again.calls, [])

        set_itp_armed(False)
        reset_itp_tick_clock()
        after_disarm = _Cloud()
        self._run(after_disarm, moment, now + 130)
        self.assertEqual(after_disarm.calls, [])
        self.assertTrue(read_itp_auto()["timer_delete_attempted"])

        set_itp_armed(True)
        reset_itp_tick_clock()
        retried = _Cloud(timer_ok=True)
        self._run(retried, moment, now + 200)
        self.assertEqual(len([url for url in self._urls(retried) if "/timer/" in url]), 1)
        self.assertIsNotNone(read_itp_auto()["timers_cleared_at"])


if __name__ == "__main__":
    unittest.main()
