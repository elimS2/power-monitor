"""Breaker day rows. Phase 1 stores samples. No network and no live database."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import HTTPException

import database
from config import UA_TZ
from schedule_board import kyiv_day_bounds
from tuya_breakers import (
    BreakerPollConfig,
    TokenCache,
    apply_breaker_status,
    breaker_config_from_env,
    breaker_http_timeout,
    active_breaker_timers,
    breaker_clock_due,
    breaker_shown_on,
    breaker_slot_start,
    breaker_timer_followup_due,
    breaker_timer_is_active,
    timer_rows,
    carry_configured_breakers,
    decode_phase,
    ingest_status_message,
    poll_breakers,
    poll_breakers_http,
    poll_is_enabled,
    run_deye_then_breakers,
    sign_headers,
)


def _ts(year: int, month: int, day: int, hour: int, minute: int) -> float:
    return datetime(year, month, day, hour, minute, tzinfo=UA_TZ).timestamp()


def _blob(volts: float, amps: float, watts: int, extra: bytes = b"") -> str:
    raw = (
        int(round(volts * 10)).to_bytes(2, "big")
        + int(round(amps * 1000)).to_bytes(3, "big")
        + int(watts).to_bytes(3, "big")
        + extra
    )
    return base64.b64encode(raw).decode("ascii")


def _payload(switch: bool, energy: int | None, phase_a: str, fault: int = 0) -> dict:
    result = [
        {"code": "phase_a", "value": phase_a},
        {"code": "phase_b", "value": phase_a},
        {"code": "phase_c", "value": phase_a},
        {"code": "fault", "value": fault},
        {"code": "switch", "value": switch},
        {"code": "breaker_number", "value": "do-not-store"},
    ]
    if energy is not None:
        result.insert(0, {"code": "total_forward_energy", "value": energy})
    return {"success": True, "result": result}


class BreakerStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._old_path = database.DB_PATH
        database.DB_PATH = Path(self._tmpdir.name) / "t.db"
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self._old_path
        self._tmpdir.cleanup()

    def _charge(self, device: str):
        with database._conn() as db:
            row = db.execute(
                "SELECT accumulated_kwh, accumulated_sec FROM breaker_since_charge WHERE device=?",
                (device,),
            ).fetchone()
        return None if row is None else row

    def _grid(self, event: str, ts: float) -> None:
        with database._conn() as db:
            db.execute("INSERT INTO power_events(event, ts) VALUES(?, ?)", (event, ts))

    def test_battery_draw_grows_only_while_the_grid_is_down(self):
        start = _ts(2026, 11, 10, 2, 0)
        later = _ts(2026, 11, 10, 3, 0)
        self._grid("down", start - 60)
        apply_breaker_status("svitlo", start, _payload(True, 100000, _blob(230, 1, 100)), "poll")
        apply_breaker_status("svitlo", later, _payload(True, 100100, _blob(230, 1, 100)), "poll")
        self.assertAlmostEqual(self._charge("svitlo")["accumulated_kwh"], 1.0, places=2)
        self.assertAlmostEqual(self._charge("svitlo")["accumulated_sec"], 3600, delta=1)
        kept = _ts(2026, 11, 10, 3, 10)
        self._grid("up", later)
        apply_breaker_status("svitlo", kept, _payload(True, 100120, _blob(230, 1, 100)), "poll")
        self.assertAlmostEqual(self._charge("svitlo")["accumulated_kwh"], 1.0, places=2)
        self.assertAlmostEqual(self._charge("svitlo")["accumulated_sec"], 3600, delta=1)
        reset = later + 16 * 60
        apply_breaker_status("svitlo", reset, _payload(True, 100140, _blob(230, 1, 100)), "poll")
        self.assertAlmostEqual(self._charge("svitlo")["accumulated_kwh"], 0.0, places=2)
        self.assertAlmostEqual(self._charge("svitlo")["accumulated_sec"], 0, delta=1)

    def test_exact_zero_watts_is_off_even_when_the_bit_stays_on(self):
        self.assertFalse(breaker_shown_on(1, {"a": {"p": 0}, "b": {"p": 0}, "c": {"p": 0}}))
        self.assertTrue(breaker_shown_on(1, {"a": {"p": 1}, "b": {"p": 0}, "c": {"p": 0}}))
        self.assertFalse(breaker_shown_on(0, {"a": {"p": 100}, "b": {"p": 0}, "c": {"p": 0}}))
        self.assertTrue(breaker_shown_on(1, None))
        from power_monitor import _breaker_lines_html
        html = _breaker_lines_html({
            "devices": {
                "svitlo": {"ready": False},
                "itp": {
                    "ready": True, "switch": 1, "energy_today_kwh": 1.0,
                    "since_charge_kwh": 0.0, "since_charge_sec": 0,
                    "updated_at": _ts(2026, 11, 10, 12, 45),
                    "phases": {"a": {"p": 0}, "b": {"p": 0}, "c": {"p": 0}},
                    "spans": [],
                },
            }
        }, _ts(2026, 11, 10, 12, 45))
        self.assertIn("Вимкнено", html)
        self.assertNotIn("brk-lit", html)

    def test_off_breaker_does_not_collect_outage_time(self):
        start = _ts(2026, 11, 10, 2, 0)
        later = _ts(2026, 11, 10, 3, 30)
        self._grid("down", start - 60)
        apply_breaker_status("svitlo", start, _payload(False, 100000, _blob(230, 0, 0)), "poll")
        apply_breaker_status("svitlo", later, _payload(False, 100000, _blob(230, 0, 0)), "poll")
        row = self._charge("svitlo")
        self.assertAlmostEqual(row["accumulated_kwh"], 0.0, places=2)
        self.assertAlmostEqual(row["accumulated_sec"], 0, delta=1)

    def test_grid_on_does_not_count_as_battery_draw(self):
        start = _ts(2026, 11, 10, 12, 0)
        later = _ts(2026, 11, 10, 12, 10)
        self._grid("up", start)
        apply_breaker_status("itp", start, _payload(True, 50000, _blob(230, 1, 100)), "poll")
        apply_breaker_status("itp", later, _payload(True, 50100, _blob(230, 1, 100)), "poll")
        self.assertAlmostEqual(self._charge("itp")["accumulated_kwh"], 0.0, places=2)
        self.assertAlmostEqual(self._charge("itp")["accumulated_sec"], 0, delta=1)

    def test_short_grid_return_keeps_both_dark_stretches(self):
        start = _ts(2026, 11, 10, 4, 0)
        self._grid("down", start)
        apply_breaker_status("svitlo", start, _payload(True, 200000, _blob(230, 1, 100)), "poll")
        half = start + 30 * 60
        apply_breaker_status("svitlo", half, _payload(True, 200050, _blob(230, 1, 100)), "poll")
        self._grid("up", half)
        self._grid("down", half + 3 * 60)
        end = half + 3 * 60 + 60 * 60
        apply_breaker_status("svitlo", end, _payload(True, 200150, _blob(230, 1, 100)), "poll")
        row = self._charge("svitlo")
        self.assertAlmostEqual(row["accumulated_sec"], 90 * 60, delta=1)
        self.assertGreater(row["accumulated_kwh"], 0.5)
        self.assertLess(row["accumulated_kwh"], 1.5)

    def test_first_sample_opens_a_span_and_hides_lifetime_energy(self):
        apply_breaker_status(
            "svitlo", _ts(2026, 11, 9, 12, 0),
            _payload(True, 1000000, _blob(234.0, 2.2, 465)), "poll",
        )
        day = self._day("svitlo", "2026-11-09")
        self.assertIsNone(day["energy_base_kwh"])
        self.assertIsNone(day["energy_today_kwh"])
        self.assertEqual(day["energy_kwh"], 10000.0)
        spans = json.loads(day["span_json"])
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0]["switch"], 1)
        self.assertIsNone(spans[0]["end"])
        self.assertEqual(self._sample_count("svitlo"), 1)

    def test_same_switch_updates_volts_without_a_new_span(self):
        first = _ts(2026, 11, 9, 12, 0)
        second = _ts(2026, 11, 9, 12, 15)
        apply_breaker_status("svitlo", first, _payload(True, 1000000, _blob(230.0, 1.0, 100)), "poll")
        apply_breaker_status("svitlo", second, _payload(True, 1000100, _blob(234.0, 2.2, 465)), "poll")
        day = self._day("svitlo", "2026-11-09")
        spans = json.loads(day["span_json"])
        self.assertEqual(len(spans), 1)
        phases = json.loads(day["phase_json"])
        self.assertEqual(phases["a"]["v"], 234.0)
        self.assertEqual(phases["a"]["i"], 2.2)
        self.assertEqual(phases["a"]["p"], 465)

    def test_flipped_switch_closes_and_opens(self):
        apply_breaker_status("svitlo", _ts(2026, 11, 9, 12, 0), _payload(True, 1000000, _blob(230, 1, 100)), "poll")
        off_at = _ts(2026, 11, 9, 18, 0)
        apply_breaker_status("svitlo", off_at, _payload(False, 1000200, _blob(230, 0, 0)), "poll")
        spans = json.loads(self._day("svitlo", "2026-11-09")["span_json"])
        self.assertEqual(len(spans), 2)
        self.assertEqual(spans[0]["end"], off_at)
        self.assertEqual(spans[0]["switch"], 1)
        self.assertEqual(spans[1]["switch"], 0)
        self.assertIsNone(spans[1]["end"])

    def test_sample_just_after_midnight_uses_yesterdays_counter(self):
        apply_breaker_status("svitlo", _ts(2026, 11, 8, 23, 0), _payload(True, 1000000, _blob(230, 1, 100)), "poll")
        apply_breaker_status("svitlo", _ts(2026, 11, 9, 0, 1), _payload(True, 1000100, _blob(231, 1, 110)), "poll")
        yesterday = self._day("svitlo", "2026-11-08")
        today = self._day("svitlo", "2026-11-09")
        midnight = kyiv_day_bounds("2026-11-09")[0]
        self.assertEqual(json.loads(yesterday["span_json"])[0]["end"], midnight)
        self.assertEqual(today["energy_base_kwh"], yesterday["energy_kwh"])
        self.assertEqual(today["energy_today_kwh"], 1.0)
        self.assertEqual(self._sample_count("svitlo"), 2)

    def test_no_sample_carry_opens_today_at_midnight_once(self):
        apply_breaker_status("svitlo", _ts(2026, 11, 8, 22, 0), _payload(False, 500000, _blob(230, 0, 0)), "poll")
        before = self._sample_count("svitlo")
        carry_at = _ts(2026, 11, 9, 0, 10)
        apply_breaker_status("svitlo", carry_at, None, "poll")
        apply_breaker_status("svitlo", carry_at, None, "poll")
        today = self._day("svitlo", "2026-11-09")
        spans = json.loads(today["span_json"])
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0]["start"], kyiv_day_bounds("2026-11-09")[0])
        self.assertEqual(spans[0]["switch"], 0)
        self.assertIsNone(spans[0]["end"])
        self.assertEqual(today["energy_today_kwh"], 0.0)
        self.assertEqual(today["energy_base_kwh"], 5000.0)
        self.assertEqual(self._sample_count("svitlo"), before)

    def test_two_day_gap_does_not_borrow_the_older_counter(self):
        apply_breaker_status("svitlo", _ts(2026, 11, 7, 12, 0), _payload(True, 1000000, _blob(230, 1, 100)), "poll")
        apply_breaker_status("svitlo", _ts(2026, 11, 9, 12, 0), _payload(True, 1000500, _blob(230, 1, 100)), "poll")
        old = self._day("svitlo", "2026-11-07")
        self.assertEqual(json.loads(old["span_json"])[0]["end"], kyiv_day_bounds("2026-11-07")[1])
        self.assertIsNone(self._day("svitlo", "2026-11-08"))
        today = self._day("svitlo", "2026-11-09")
        self.assertIsNone(today["energy_base_kwh"])
        self.assertIsNone(today["energy_today_kwh"])

    def test_no_sample_after_a_gap_does_not_create_today(self):
        apply_breaker_status("svitlo", _ts(2026, 11, 7, 12, 0), _payload(True, 1000000, _blob(230, 1, 100)), "poll")
        before = self._sample_count("svitlo")
        apply_breaker_status("svitlo", _ts(2026, 11, 9, 0, 10), None, "poll")
        old = self._day("svitlo", "2026-11-07")
        self.assertEqual(json.loads(old["span_json"])[0]["end"], kyiv_day_bounds("2026-11-07")[1])
        self.assertIsNone(self._day("svitlo", "2026-11-09"))
        self.assertEqual(self._sample_count("svitlo"), before)

    def test_bad_phase_blob_keeps_the_switch(self):
        bad = base64.b64encode(b"abc").decode("ascii")
        apply_breaker_status("svitlo", _ts(2026, 11, 9, 12, 0), _payload(True, 1000000, bad), "poll")
        sample = self._samples("svitlo")[0]
        self.assertIsNone(sample["v_a"])
        self.assertEqual(sample["switch"], 1)
        self.assertEqual(sample["energy_kwh"], 10000.0)
        day = self._day("svitlo", "2026-11-09")
        self.assertEqual(day["switch"], 1)

    def test_two_devices_do_not_share_a_row(self):
        when = _ts(2026, 11, 9, 12, 0)
        apply_breaker_status("svitlo", when, _payload(True, 1000000, _blob(230, 1, 100)), "poll")
        apply_breaker_status("itp", when, _payload(False, 359700, _blob(232, 0, 0)), "poll")
        self.assertEqual(self._day("svitlo", "2026-11-09")["switch"], 1)
        self.assertEqual(self._day("itp", "2026-11-09")["energy_kwh"], 3597.0)
        self.assertEqual(self._sample_count("svitlo"), 1)
        self.assertEqual(self._sample_count("itp"), 1)

    def test_ten_byte_phase_ignores_the_tail(self):
        point = decode_phase(_blob(234.0, 2.2, 465, extra=b"\x00\x01"))
        self.assertEqual(point, (234.0, 2.2, 465))

    def test_overlapping_applies_keep_both_spans(self):
        apply_breaker_status("svitlo", _ts(2026, 11, 9, 12, 0), _payload(True, 1000000, _blob(230, 1, 100)), "poll")
        release = threading.Event()
        entered = threading.Event()
        current = {"n": 0, "max": 0}
        guard = threading.Lock()
        real = decode_phase

        def wrapped(value):
            with guard:
                current["n"] += 1
                current["max"] = max(current["max"], current["n"])
                first = current["max"] == 1 and not entered.is_set()
            if first:
                entered.set()
                self.assertTrue(release.wait(5))
            try:
                return real(value)
            finally:
                with guard:
                    current["n"] -= 1

        import tuya_breakers
        tuya_breakers.decode_phase = wrapped
        try:
            first = threading.Thread(target=lambda: apply_breaker_status(
                "svitlo", _ts(2026, 11, 9, 13, 0),
                _payload(False, 1000100, _blob(230, 0, 0)), "poll",
            ))
            second = threading.Thread(target=lambda: apply_breaker_status(
                "svitlo", _ts(2026, 11, 9, 14, 0),
                _payload(True, 1000200, _blob(231, 1, 110)), "poll",
            ))
            first.start()
            self.assertTrue(entered.wait(5))
            second.start()
            time.sleep(0.3)
            self.assertTrue(second.is_alive())
            release.set()
            first.join(5)
            second.join(5)
        finally:
            tuya_breakers.decode_phase = real
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(current["max"], 1)
        spans = json.loads(self._day("svitlo", "2026-11-09")["span_json"])
        self.assertEqual([span["switch"] for span in spans], [1, 0, 1])

    def test_duplicate_message_does_not_write_again(self):
        when = _ts(2026, 11, 9, 12, 0)
        body = _payload(True, 1000000, _blob(230, 1, 100))
        apply_breaker_status("svitlo", when, body, "message", message_id="m1")
        apply_breaker_status("svitlo", when + 60, _payload(False, 1000100, _blob(230, 0, 0)), "message", message_id="m1")
        spans = json.loads(self._day("svitlo", "2026-11-09")["span_json"])
        self.assertEqual(len(spans), 1)
        self.assertEqual(self._sample_count("svitlo"), 1)

    def test_older_message_is_stored_and_does_not_move_the_day(self):
        apply_breaker_status(
            "svitlo", _ts(2026, 11, 9, 15, 0),
            _payload(True, 1000000, _blob(230, 1, 100)), "poll",
        )
        apply_breaker_status(
            "svitlo", _ts(2026, 11, 9, 14, 0),
            _payload(False, 900000, _blob(100, 0, 0)), "message", message_id="late",
        )
        day = self._day("svitlo", "2026-11-09")
        self.assertEqual(day["switch"], 1)
        self.assertEqual(day["energy_kwh"], 10000.0)
        self.assertEqual(self._sample_count("svitlo"), 1)
        with database._conn() as db:
            row = db.execute(
                "SELECT message_id FROM breaker_message WHERE message_id='late'"
            ).fetchone()
        self.assertEqual(row["message_id"], "late")

    def _day(self, device: str, day: str):
        with database._conn() as db:
            return db.execute(
                "SELECT * FROM breaker_day WHERE device=? AND day=?",
                (device, day),
            ).fetchone()

    def _samples(self, device: str):
        with database._conn() as db:
            return db.execute(
                "SELECT * FROM breaker_sample WHERE device=? ORDER BY ts",
                (device,),
            ).fetchall()

    def _sample_count(self, device: str) -> int:
        return len(self._samples(device))


class _JsonResponse:
    def __init__(self, body: dict, status: int = 200):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class _FakeTuya:
    def __init__(self, status_body: dict, token_body: dict | None = None):
        self.urls: list[str] = []
        self._status = status_body
        self._token = token_body or {
            "success": True,
            "result": {"access_token": "tok", "expire_time": 7200},
        }

    async def get(self, url, headers=None):
        self.urls.append(url)
        if "/v1.0/token?" in url:
            return _JsonResponse(self._token)
        return _JsonResponse(self._status)


class BreakerMessageTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._old_path = database.DB_PATH
        database.DB_PATH = Path(self._tmpdir.name) / "t.db"
        database.init_db()
        self._ids = {"dev-svitlo": "svitlo", "dev-itp": "itp"}

    def tearDown(self):
        database.DB_PATH = self._old_path
        self._tmpdir.cleanup()

    def _message(self, device: str, message_id: str, switch: bool, when_ms: int, energy: int = 1000000):
        return {
            "devId": device,
            "dataId": message_id,
            "status": [
                {"code": "switch", "value": switch, "t": when_ms},
                {"code": "total_forward_energy", "value": energy, "t": when_ms},
            ],
        }

    def test_opposite_switch_appends_a_span_and_a_copy_does_not(self):
        first = int(_ts(2026, 11, 9, 12, 0) * 1000)
        later = int(_ts(2026, 11, 9, 18, 0) * 1000)
        self.assertTrue(ingest_status_message(self._message("dev-svitlo", "m1", True, first), self._ids))
        self.assertTrue(ingest_status_message(self._message("dev-svitlo", "m2", False, later), self._ids))
        self.assertTrue(ingest_status_message(self._message("dev-svitlo", "m2", True, later + 1000), self._ids))
        spans = json.loads(self._day("svitlo")["span_json"])
        self.assertEqual([span["switch"] for span in spans], [1, 0])
        self.assertEqual(self._count(), 2)

    def test_older_message_is_kept_and_does_not_move_the_day(self):
        later = int(_ts(2026, 11, 9, 18, 0) * 1000)
        earlier = int(_ts(2026, 11, 9, 12, 0) * 1000)
        ingest_status_message(self._message("dev-svitlo", "new", True, later, 1000500), self._ids)
        ingest_status_message(self._message("dev-svitlo", "old", False, earlier, 1000000), self._ids)
        day = self._day("svitlo")
        self.assertEqual(day["switch"], 1)
        self.assertEqual(day["energy_kwh"], 10005.0)
        with database._conn() as db:
            row = db.execute("SELECT message_id FROM breaker_message WHERE message_id='old'").fetchone()
        self.assertEqual(row["message_id"], "old")

    def test_other_device_does_not_write(self):
        when = int(_ts(2026, 11, 9, 12, 0) * 1000)
        self.assertFalse(ingest_status_message(self._message("someone-else", "x", False, when), self._ids))
        self.assertEqual(self._count(), 0)

    def _day(self, device: str):
        with database._conn() as db:
            return db.execute(
                "SELECT * FROM breaker_day WHERE device=?",
                (device,),
            ).fetchone()

    def _count(self) -> int:
        with database._conn() as db:
            return db.execute("SELECT COUNT(*) AS n FROM breaker_sample").fetchone()["n"]


class BreakerPageTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._old_path = database.DB_PATH
        database.DB_PATH = Path(self._tmpdir.name) / "t.db"
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self._old_path
        self._tmpdir.cleanup()

    def test_bars_are_green_then_red_and_the_other_breaker_is_empty(self):
        import power_monitor
        from database import read_breaker_board

        apply_breaker_status("svitlo", _ts(2026, 11, 9, 12, 0), _payload(True, 1000000, _blob(230, 1, 100)), "poll")
        apply_breaker_status("svitlo", _ts(2026, 11, 9, 18, 0), _payload(False, 1000200, _blob(230, 0, 0)), "poll")
        now = _ts(2026, 11, 9, 20, 0)
        payload = read_breaker_board("2026-11-09", now)
        html = power_monitor._breaker_bars_html(payload)
        self.assertLess(html.index("brk-on"), html.index("brk-off"))
        self.assertIn("увімкнено, було світло", html)
        self.assertIn("увімкнено, не було світла", html)
        with database._conn() as db:
            db.execute(
                "INSERT INTO power_events(event, ts) VALUES('down', ?)",
                (_ts(2026, 11, 9, 14, 0),),
            )
            db.execute(
                "INSERT INTO power_events(event, ts) VALUES('up', ?)",
                (_ts(2026, 11, 9, 16, 0),),
            )
        html = power_monitor._breaker_bars_html(read_breaker_board("2026-11-09", now))
        self.assertIn("brk-batt", html)
        self.assertLess(html.index("brk-on"), html.index("brk-batt"))
        self.assertIn("ІТП: ще немає знімка", html)
        self.assertIn("Графік 5.1: немає знімка", html)
        self.assertIn("Котельня: немає графіка", html)
        self.assertNotIn("<button", html.lower())

    def test_plan_lane_uses_the_queue_snapshot(self):
        import json

        import power_monitor
        from database import read_breaker_board

        grid = ["ok"] * 48
        grid[4:10] = ["maybe"] * 6
        grid[20] = "off"
        with database._conn() as db:
            db.execute(
                """INSERT INTO schedule_history(target_date, grid_json, fetched_at, queue, emergency)
                   VALUES(?,?,?,?,?)""",
                ("2026-11-09", json.dumps(grid), 1, "5.1", 0),
            )
            db.execute(
                """INSERT INTO boiler_schedule(target_date, intervals, source_text, parsed_at)
                   VALUES(?,?,?,?)""",
                ("2026-11-09", json.dumps([["17:00", "24:00"]]), "test", 1),
            )
        payload = read_breaker_board("2026-11-09", _ts(2026, 11, 9, 20, 0))
        self.assertEqual(payload["schedule_queue"], "5.1")
        self.assertEqual(payload["schedule"][4], "maybe")
        self.assertEqual(payload["boiler"], [["17:00", "24:00"]])
        html = power_monitor._breaker_bars_html(payload)
        self.assertNotIn("brk-plan-maybe", html)
        self.assertEqual(html.count("brk-bar brk-plan-off"), 2)
        self.assertIn("brk-plan-ok", html)
        self.assertIn("Графік 5.1", html)
        self.assertIn('class="brk-bar brk-boiler" style="left:70.83%;width:29.17%"', html)
        payload["timers"] = [
            {"device": "svitlo", "fire_date": "20261109", "fire_time": "20:30", "switch": 1, "loops": "0000000"},
            {"device": "itp", "fire_date": "20261110", "fire_time": "00:00", "switch": 0, "loops": "0000000"},
        ]
        marked = power_monitor._breaker_bars_html(payload)
        self.assertIn('brk-when-on" style="left:85.42%"', marked)
        self.assertIn("brk-when-off brk-pin-end", marked)
        heat = marked.split("Обігрів", 1)[1].split("Графік", 1)[0]
        light = marked.split("Освітлення", 1)[1].split("Обігрів", 1)[0]
        self.assertIn("brk-pin-end", heat)
        self.assertNotIn("brk-pin-end", light)
        self.assertNotIn("<form", html.lower())

    def test_missing_base_does_not_print_the_lifetime_total(self):
        import power_monitor
        from database import read_breaker_board

        apply_breaker_status("svitlo", _ts(2026, 11, 9, 12, 0), _payload(True, 1000000, _blob(234, 2.2, 465)), "poll")
        now = _ts(2026, 11, 9, 12, 5)
        payload = read_breaker_board("2026-11-09", now)
        html = power_monitor._breaker_lines_html(payload, now)
        self.assertIn("немає бази", html)
        self.assertNotIn("10000", html)
        self.assertNotIn("energy_kwh", json.dumps(payload))

    def test_read_fills_today_end_without_writing(self):
        from database import read_breaker_board

        apply_breaker_status("svitlo", _ts(2026, 11, 9, 12, 0), _payload(True, 1000000, _blob(230, 1, 100)), "poll")
        now = _ts(2026, 11, 9, 15, 0)
        payload = read_breaker_board("2026-11-09", now)
        self.assertEqual(payload["devices"]["svitlo"]["spans"][0]["end"], now)
        with database._conn() as db:
            raw = db.execute(
                "SELECT span_json FROM breaker_day WHERE device='svitlo' AND day='2026-11-09'"
            ).fetchone()["span_json"]
        self.assertIsNone(json.loads(raw)[0]["end"])

    def test_old_day_keeps_a_null_end(self):
        from database import read_breaker_board

        apply_breaker_status("svitlo", _ts(2026, 11, 8, 12, 0), _payload(True, 1000000, _blob(230, 1, 100)), "poll")
        payload = read_breaker_board("2026-11-08", _ts(2026, 11, 9, 12, 0))
        self.assertIsNone(payload["devices"]["svitlo"]["spans"][0]["end"])

    def test_route_rejects_a_bad_key_and_a_bad_day(self):
        import api.deps as deps
        from api.dashboard import ep_breakers

        old = deps.API_KEYS
        deps.API_KEYS = {"k": "admin"}
        try:
            with self.assertRaises(HTTPException) as denied:
                ep_breakers(key="nope", day="2026-11-09")
            self.assertEqual(denied.exception.status_code, 403)
            with self.assertRaises(HTTPException) as bad:
                ep_breakers(key="k", day="2026-13-40")
            self.assertEqual(bad.exception.status_code, 400)
            response = ep_breakers(key="k", day="2026-11-09")
        finally:
            deps.API_KEYS = old
        body = json.loads(response.body)
        self.assertFalse(body["devices"]["svitlo"]["ready"])
        self.assertEqual(body["date"], "2026-11-09")

    def test_page_and_fragment_do_not_read_samples(self):
        import inspect

        import power_monitor

        source = inspect.getsource(database.read_breaker_board)
        self.assertIn("FROM breaker_day", source)
        self.assertNotIn("breaker_sample", source)
        seen: list[str] = []

        def wrapped(day, now):
            seen.append(day)
            return {
                "date": day,
                "today": True,
                "devices": {"svitlo": {"ready": False}, "itp": {"ready": False}},
            }

        original = power_monitor.read_breaker_board
        power_monitor.read_breaker_board = wrapped
        try:
            self.assertIn("ще немає знімка", power_monitor._breaker_live_html())
        finally:
            power_monitor.read_breaker_board = original
        self.assertTrue(seen)

    def test_hidden_flag_removes_the_section(self):
        import power_monitor

        self.assertIn("Автомати підвалу", power_monitor._breaker_section_html())
        self.assertNotIn("<button", power_monitor._breaker_section_html().lower())
        self.assertNotIn("<form", power_monitor._breaker_section_html().lower())
        database.kv_set("breakers_board", "0")
        self.assertEqual(power_monitor._breaker_section_html(), "")
        self.assertEqual(power_monitor._breaker_live_html(), "")

    def test_explicit_role_gains_the_section(self):
        from database import role_create, role_list

        role_create("Лише графік", ["sched_details"])
        database.init_db()
        roles = {row["name"]: row["sections"] for row in role_list()}
        self.assertIn("breaker_details", roles["Базове"])
        self.assertIn("breaker_details", roles["Лише графік"])
        self.assertIsNone(roles["Усі"])

    def test_page_script_does_not_reuse_the_fact_lane(self):
        script = Path("static/app.js").read_text(encoding="utf-8")
        chunk = script[script.index("pm-breakers-board"):]
        self.assertNotIn("factOnSegments", chunk)
        self.assertNotIn("<button", chunk)
        self.assertIn("brk-batt", chunk)
        self.assertIn("не було світла", chunk)
        self.assertIn("brk-plan-ok", chunk)
        self.assertIn("Графік ", chunk)
        self.assertIn("Котельня", chunk)
        self.assertIn("brk-boiler", chunk)
        self.assertIn("brk-pin-end", chunk)
        self.assertNotIn("brk-plan-maybe", chunk)
        route = Path("api/dashboard.py").read_text(encoding="utf-8")
        self.assertEqual(route.count("/api/breakers"), 1)
        self.assertIn('@router.get("/api/breakers")', route)
        poller = Path("tuya_breakers.py").read_text(encoding="utf-8")
        self.assertNotIn(".post(", poller)
        self.assertNotIn(".put(", poller)
        page = Path("power_monitor.py").read_text(encoding="utf-8")
        start = page.index("def _build_update_fragments")
        fragment = page[start:page.index("\ndef ", start + 10)]
        self.assertIn("pm_breakers", fragment)
        self.assertNotIn("breaker_sample", fragment)


class BreakerPollTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._old_path = database.DB_PATH
        database.DB_PATH = Path(self._tmpdir.name) / "t.db"
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self._old_path
        self._tmpdir.cleanup()

    def test_poll_follows_the_kyiv_quarter_hour(self):
        def at(hour, minute, second=0, day=10):
            return datetime(2026, 11, day, hour, minute, second, tzinfo=UA_TZ).timestamp()

        quarter = at(0, 15, 20)
        self.assertTrue(breaker_clock_due(quarter, None, 900))
        slot = breaker_slot_start(quarter, 900)
        local = datetime.fromtimestamp(slot, UA_TZ)
        self.assertEqual((local.hour, local.minute, local.second), (0, 15, 0))
        self.assertFalse(breaker_clock_due(quarter, slot, 900))
        self.assertFalse(breaker_clock_due(at(0, 17), None, 900))
        self.assertFalse(breaker_clock_due(at(0, 14, 50), breaker_slot_start(at(0, 0, 10), 900), 900))
        self.assertTrue(breaker_clock_due(at(0, 30, 5), slot, 900))
        self.assertTrue(breaker_clock_due(at(0, 0, 10), None, 900))
        self.assertTrue(breaker_clock_due(at(0, 45, 10), None, 900))
        night = breaker_slot_start(at(23, 45, 10), 900)
        self.assertTrue(breaker_clock_due(at(0, 0, 10, day=11), night, 900))
        self.assertTrue(breaker_clock_due(at(0, 16, 30), None, 900))
        self.assertFalse(breaker_clock_due(at(0, 16, 31), None, 900))

    def test_a_future_one_shot_is_shown_and_a_past_one_is_not(self):
        payload = {"result": [
            {
                "timer_id": "912755531", "date": "20261110", "time": "02:30",
                "loops": "0000000", "timezone_id": "Europe/Kiev", "enable": True,
                "functions": [{"code": "switch", "value": False}],
            },
            {
                "timer_id": "912559137", "date": "20261109", "time": "22:30",
                "loops": "0000000", "timezone_id": "Europe/Kiev", "enable": True,
                "functions": [{"code": "switch", "value": False}],
            },
            {"code": "switch", "value": True},
        ]}
        rows = timer_rows(payload)
        self.assertEqual([row["timer_id"] for row in rows], ["912755531", "912559137"])
        database.replace_breaker_timers("svitlo", rows, _ts(2026, 11, 10, 1, 5))
        shown = active_breaker_timers(_ts(2026, 11, 10, 1, 5))
        self.assertEqual([row["timer_id"] for row in shown], ["912755531"])
        self.assertFalse(breaker_timer_is_active(shown[0], _ts(2026, 11, 10, 3, 0)))
        fired = shown[0]
        self.assertFalse(breaker_timer_followup_due(fired, _ts(2026, 11, 10, 2, 30)))
        self.assertTrue(breaker_timer_followup_due(fired, _ts(2026, 11, 10, 2, 31)))
        self.assertFalse(breaker_timer_followup_due(fired, _ts(2026, 11, 10, 2, 35)))
        from power_monitor import _breaker_timers_html
        html = _breaker_timers_html(_ts(2026, 11, 10, 1, 5))
        self.assertIn("02:30", html)
        self.assertIn("Вимкнути", html)
        self.assertIn("Освітлення", html)
        self.assertIn("10.11", html)
        self.assertIn("разовий", html)
        self.assertNotIn("brk-when-pin", html)
        self.assertNotIn("brk-when-lane", html)
        self.assertNotIn("<button", html)
        from power_monitor import _breaker_lines_html
        card = _breaker_lines_html({
            "devices": {
                "svitlo": {
                    "ready": True, "switch": 0, "energy_today_kwh": 1.5,
                    "since_charge_kwh": 0.4, "since_charge_sec": 90 * 60,
                    "updated_at": _ts(2026, 11, 10, 3, 0),
                    "phases": {}, "spans": [],
                },
                "itp": {"ready": False},
            }
        }, _ts(2026, 11, 10, 3, 0))
        self.assertIn("З акумуляторів", card)
        self.assertIn("0.40 кВт·год", card)
        self.assertIn("1 год 30 хв", card)
        self.assertNotIn("без світла", card)
        self.assertNotIn("<button", card)
        self.assertIn("Активних таймерів немає", _breaker_timers_html(_ts(2026, 11, 10, 3, 0)))

    def test_sign_uses_the_cloud_string(self):
        headers = sign_headers("id", "secret", "GET", "/v1.0/token?grant_type=1", "", "1000")
        content = hashlib.sha256(b"").hexdigest()
        string_to_sign = "GET\n" + content + "\n\n/v1.0/token?grant_type=1"
        expected = hmac.new(b"secret", ("id1000" + string_to_sign).encode(), hashlib.sha256).hexdigest().upper()
        self.assertEqual(headers["sign"], expected)
        self.assertNotIn("access_token", headers)
        business = sign_headers("id", "secret", "GET", "/v1.0/devices/abc/status", "tok", "1000")
        business_string = "GET\n" + content + "\n\n/v1.0/devices/abc/status"
        business_expected = hmac.new(
            b"secret", ("id" + "tok" + "1000" + business_string).encode(), hashlib.sha256,
        ).hexdigest().upper()
        self.assertEqual(business["sign"], business_expected)
        self.assertEqual(business["access_token"], "tok")

    def test_empty_secret_disables_the_poller(self):
        cfg = breaker_config_from_env("id", "", "deviceone", "")
        self.assertFalse(poll_is_enabled(cfg))
        one = breaker_config_from_env("id", "secret", "deviceone", "")
        self.assertEqual(one.devices, (("svitlo", "deviceone"),))
        self.assertTrue(poll_is_enabled(one))

    def test_fake_client_writes_one_sample_and_uses_a_ten_second_timeout(self):
        body = _payload(True, 1000000, _blob(234.0, 2.2, 465))
        seen: list[float] = []

        class _Opening:
            def __init__(self, timeout):
                seen.append(timeout)
                self._inner = _FakeTuya(body)

            async def __aenter__(self):
                return self._inner

            async def __aexit__(self, *_args):
                return False

        cfg = BreakerPollConfig("id", "secret", (("svitlo", "abc123"),))
        asyncio.run(poll_breakers_http(cfg, TokenCache(), 1_700_000_000.0, client_cls=_Opening))
        self.assertEqual(seen, [breaker_http_timeout()])
        self.assertEqual(breaker_http_timeout(), 10.0)
        with database._conn() as db:
            count = db.execute("SELECT COUNT(*) AS n FROM breaker_sample").fetchone()["n"]
        self.assertEqual(count, 1)

    def test_cached_token_is_not_requested_again(self):
        body = _payload(True, 1000000, _blob(230, 1, 100))
        client = _FakeTuya(body)
        cfg = BreakerPollConfig("id", "secret", (("svitlo", "abc123"),))
        cache = TokenCache()
        asyncio.run(poll_breakers(client, cfg, cache, 1_000.0))
        asyncio.run(poll_breakers(client, cfg, cache, 1_100.0))
        token_calls = [url for url in client.urls if "/token?" in url]
        self.assertEqual(len(token_calls), 1)
        self.assertEqual(len(client.urls), 5)

    def test_tuya_error_does_not_write_a_sample(self):
        client = _FakeTuya({"success": False, "code": 28841002})
        client._token = {"success": False, "code": 28841002}
        cfg = BreakerPollConfig("id", "secret", (("svitlo", "abc123"),))
        with self.assertRaises(Exception):
            asyncio.run(poll_breakers(client, cfg, TokenCache(), 1_000.0))
        with database._conn() as db:
            count = db.execute("SELECT COUNT(*) AS n FROM breaker_sample").fetchone()["n"]
        self.assertEqual(count, 0)
        self.assertEqual(len(client.urls), 1)

    def test_status_failure_does_not_drop_the_other_breaker(self):
        ok = _payload(True, 1000000, _blob(230, 1, 100))

        class _OneFails(_FakeTuya):
            async def get(self, url, headers=None):
                self.urls.append(url)
                if "/token?" in url:
                    return _JsonResponse(self._token)
                if url.endswith("/badid999/status"):
                    return _JsonResponse({"success": False, "code": 1100})
                return _JsonResponse(ok)

        client = _OneFails(ok)
        cfg = BreakerPollConfig("id", "secret", (("svitlo", "abc123"), ("itp", "badid999")))
        asyncio.run(poll_breakers(client, cfg, TokenCache(), _ts(2026, 11, 9, 12, 0)))
        with database._conn() as db:
            rows = db.execute("SELECT device FROM breaker_sample").fetchall()
        self.assertEqual([row["device"] for row in rows], ["svitlo"])

    def test_breaker_failure_still_runs_deye_first(self):
        called: list[str] = []

        async def deye():
            called.append("deye")

        async def breaker():
            called.append("breaker")
            raise httpx.ReadTimeout("slow")

        asyncio.run(run_deye_then_breakers(deye, breaker))
        self.assertEqual(called, ["deye", "breaker"])

    def test_carry_opens_today_without_a_new_sample(self):
        apply_breaker_status(
            "svitlo", _ts(2026, 11, 8, 22, 0),
            _payload(True, 1000000, _blob(230, 1, 100)), "poll",
        )
        before = 1
        carry_configured_breakers(_ts(2026, 11, 9, 0, 10), (("svitlo", "abc123"),))
        with database._conn() as db:
            count = db.execute("SELECT COUNT(*) AS n FROM breaker_sample").fetchone()["n"]
            today = db.execute(
                "SELECT energy_today_kwh FROM breaker_day WHERE device='svitlo' AND day='2026-11-09'"
            ).fetchone()
        self.assertEqual(count, before)
        self.assertEqual(today["energy_today_kwh"], 0.0)


if __name__ == "__main__":
    unittest.main()
