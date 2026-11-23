"""Basement phases decide the light letters. Plugs do not."""
from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import database
import detection
from power_monitor import _build_update_fragments, _power_status_text, get_display_status

UNKNOWN = "Немає свіжого заміру підвалу"


class VoltageSettledTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._old_path = database.DB_PATH
        database.DB_PATH = Path(self._tmpdir.name) / "t.db"
        database.init_db()
        self.house_id = database.house_inverter_record()["id"]
        self.apartment_id = database.apartment_inverter_id()
        self.messages: list[str] = []
        detection._lock = asyncio.Lock()

        async def photo(is_down, voltage=None, message_to_send=None, is_voltage_notification=False):
            self.messages.append(message_to_send or "")

        async def tg(text, chat_id="", reply_markup=None):
            self.messages.append(text)
            return 200

        self._photo = patch("power_monitor.update_chat_photo", new=photo)
        self._tg = patch("power_monitor.tg_send", new=tg)
        self._photo.start()
        self._tg.start()

    def tearDown(self):
        self._photo.stop()
        self._tg.stop()
        database.DB_PATH = self._old_path
        self._tmpdir.cleanup()

    def _phases(self, l1, l2, l3, age, inverter_id=None):
        iid = self.house_id if inverter_id is None else inverter_id
        with database._conn() as db:
            db.execute(
                """INSERT INTO deye_log(grid_v_l1, grid_v_l2, grid_v_l3, ts, inverter_id)
                   VALUES (?,?,?,?,?)""",
                (l1, l2, l3, time.time() - age, iid),
            )

    def _event(self, name: str, age: float) -> None:
        with database._conn() as db:
            db.execute(
                "INSERT INTO power_events(event, ts) VALUES (?, ?)",
                (name, time.time() - age),
            )

    def _run(self, times: int = 1) -> None:
        async def go():
            for _ in range(times):
                await detection.analyze()

        asyncio.run(go())

    def _watch(self) -> None:
        asyncio.run(detection.watchdog())

    def _joined(self) -> str:
        return "\n".join(self.messages)

    def test_fresh_blackout_sends_one_outage_without_heartbeats(self):
        self._phases(0, 0, 0, 10)
        self._run()
        self.assertEqual(self._joined().count("Світло зникло"), 1)
        self.assertEqual(database.kv_get("power_down"), "1")

    def test_high_trend_waits_for_the_third_confirm(self):
        self._phases(0, 0, 0, 10)
        with patch("detection.deye_voltage_trend", return_value="high"):
            self._run(2)
            self.assertEqual(self.messages, [])
            self.assertEqual(database.kv_get("power_down"), "")
            self._run()
        self.assertIn("усі фази зникли", self._joined())
        self.assertNotIn("Світло зникло", self._joined())
        self.assertEqual(database.kv_get("power_down"), "")

    def test_open_anomaly_with_high_trend_sets_the_flag_and_sends_nothing(self):
        database.kv_set("voltage_anomaly", "1")
        database.kv_set("voltage_normal_since", str(time.time() - 600))
        self._phases(0, 0, 0, 10)
        with patch("detection.deye_voltage_trend", return_value="high"):
            self._run()
        self.assertEqual(self.messages, [])
        self.assertEqual(database.kv_get("power_down"), "1")
        self.assertEqual(database.kv_get("voltage_normal_since"), "")

    def test_open_anomaly_with_empty_trend_sends_outage_and_clears_the_mark(self):
        database.kv_set("voltage_anomaly", "1")
        database.kv_set("voltage_normal_since", str(time.time() - 600))
        self._phases(0, 0, 0, 10)
        self._run()
        self.assertEqual(self._joined().count("Світло зникло"), 1)
        self.assertEqual(database.kv_get("voltage_normal_since"), "")

    def test_power_down_and_high_trend_sends_light_returned(self):
        database.kv_set("power_down", "1")
        self._phases(230, 230, 230, 10)
        with patch("detection.deye_voltage_trend", return_value="high"):
            self._run()
        self.assertEqual(self._joined().count("Світло з'явилось"), 1)

    def test_calm_mark_younger_than_half_an_hour_does_not_send_light_returned(self):
        database.kv_set("power_down", "1")
        database.kv_set("voltage_anomaly", "1")
        database.kv_set("voltage_normal_since", str(time.time() - 600))
        self._phases(230, 230, 230, 10)
        self._run()
        self.assertNotIn("Світло з'явилось", self._joined())
        self.assertNotIn("Напруга стабілізувалась", self._joined())

    def test_stale_live_voltage_is_unknown(self):
        database.kv_set("power_down", "1")
        self._phases(230, 230, 230, 301)
        self._run()
        self.assertEqual(self.messages, [])
        self.assertEqual(database.kv_get("power_down"), "1")
        self.assertEqual(get_display_status()["status_text"], UNKNOWN)
        title = _build_update_fragments()["title"]
        self.assertIn(UNKNOWN, title)

    def test_missing_basement_row_is_unknown(self):
        database.kv_set("power_down", "0")
        database.kv_set("voltage_normal_since", str(time.time() - 100))
        self.assertEqual(get_display_status()["status_text"], UNKNOWN)
        self.assertIn(UNKNOWN, _build_update_fragments()["title"])
        self._run()
        self.assertEqual(self.messages, [])
        self.assertEqual(database.kv_get("power_down"), "0")
        self.assertEqual(database.kv_get("voltage_normal_since"), "")

    def test_stale_blackout_does_not_start_an_outage(self):
        self._phases(0, 0, 0, 301)
        self._run()
        self.assertEqual(self.messages, [])
        self.assertEqual(database.kv_get("power_down"), "")

    def test_apartment_silence_is_not_a_building_outage(self):
        self._phases(230, 230, 230, 10)
        self._phases(230, 230, 230, 301, self.apartment_id)
        self._run()
        self._watch()
        self.assertNotIn("Світло зникло", self._joined())
        self.assertNotIn("Світло з'явилось", self._joined())
        self.assertIn("Немає зв'язку з інвертором квартири", self._joined())

    def test_plug_row_does_not_block_the_outage_letter(self):
        with database._conn() as db:
            db.execute(
                "INSERT INTO heartbeats(plug204, plug175, ts) VALUES (0, 3, ?)",
                (time.time(),),
            )
        self._phases(0, 0, 0, 10)
        self._run()
        self.assertEqual(self._joined().count("Світло зникло"), 1)

    def test_second_blackout_call_does_not_repeat_the_letter(self):
        self._phases(0, 0, 0, 10)
        self._run(2)
        self.assertEqual(self._joined().count("Світло зникло"), 1)

    def test_blackout_clears_a_young_calm_mark(self):
        database.kv_set("voltage_anomaly", "1")
        database.kv_set("voltage_normal_since", str(time.time() - 600))
        self._phases(0, 0, 0, 10)
        self._run()
        self.assertEqual(database.kv_get("voltage_normal_since"), "")
        self.assertIn("Світло зникло", self._joined())

    def test_mark_older_than_the_problem_starts_over(self):
        self._event("voltage_high", 100)
        database.kv_set("voltage_anomaly", "1")
        database.kv_set("voltage_normal_since", str(time.time() - 500))
        self._phases(230, 230, 230, 10)
        self._run()
        started = float(database.kv_get("voltage_normal_since"))
        self.assertLess(time.time() - started, 5)
        self.assertNotIn("Напруга стабілізувалась", self._joined())

    def test_fresh_up_does_not_send_the_settled_letter(self):
        database.kv_set("voltage_normal_since", str(time.time() - 1802))
        self._phases(230, 230, 230, 10)
        self._run()
        self.assertNotIn("Напруга стабілізувалась", self._joined())
        self.assertEqual(database.kv_get("voltage_normal_since"), "")

    def test_settled_letter_after_a_real_calm_stretch(self):
        self._event("voltage_issue", 4000)
        database.kv_set("voltage_anomaly", "1")
        database.kv_set("voltage_normal_since", str(time.time() - 1802))
        self._phases(230, 230, 230, 10)
        self._run()
        self.assertEqual(self._joined().count("Напруга стабілізувалась"), 1)
        self.assertEqual(get_display_status()["status_text"], "Світло є")

    def test_one_live_phase_is_not_up(self):
        self._phases(230, 0, 0, 10)
        self.assertEqual(database.house_grid_now(), "voltage")

    def test_high_trend_lamp_and_low_trend_lamp(self):
        database.kv_set("voltage_anomaly", "1")
        self._phases(0, 0, 0, 10)
        with patch("power_monitor.deye_voltage_trend", return_value="high"):
            self.assertEqual(get_display_status()["status_text"], "Висока напруга")
        with patch("power_monitor.deye_voltage_trend", return_value="low"):
            self.assertEqual(get_display_status()["status_text"], "Проблема з напругою")

    def test_duration_uses_the_light_event_only(self):
        self.assertEqual(_power_status_text(), "")
        with database._conn() as db:
            db.execute(
                "INSERT INTO heartbeats(plug204, plug175, ts) VALUES (1, 1, ?)",
                (time.time() - 100,),
            )
        self.assertEqual(_power_status_text(), "")
        database.kv_set("power_down", "1")
        self._event("down", 120)
        self.assertIn("Світло ВІДСУТНЄ", _power_status_text())

    def test_fragments_do_not_include_the_plug_table(self):
        payload = _build_update_fragments()
        self.assertNotIn("pm_hb_tbody", payload)
        self.assertNotIn("pm_mk", payload)
        blob = " ".join(str(value) for value in payload.values())
        self.assertNotIn("Plug 204", blob)
        self.assertNotIn("pm-hb-tbody", blob)
        self.assertNotIn("hb_details", blob)


if __name__ == "__main__":
    unittest.main()
