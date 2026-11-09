"""Breaker day rows. Phase 1 stores samples. No network and no live database."""
from __future__ import annotations

import base64
import json
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path

import database
from config import UA_TZ
from schedule_board import kyiv_day_bounds
from tuya_breakers import apply_breaker_status, decode_phase


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


if __name__ == "__main__":
    unittest.main()
