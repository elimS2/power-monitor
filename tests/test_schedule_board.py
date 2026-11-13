"""Queue-scoped schedule history. Phase 1 of the compare board.

These tests use a temporary database. They do not touch the live file.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import database
import dtek
from config import DTEK_POLL_SEC, DTEK_QUEUE, UA_TZ
from datetime import datetime
from fastapi import HTTPException
from schedule_board import (
    apply_voltage_sample,
    kyiv_day_bounds,
    read_schedule_board,
    recompute_match,
)


class ScheduleHistoryQueueTests(unittest.TestCase):
    def setUp(self):
        # Windows keeps the WAL file locked until connections are collected.
        # sqlite3's context manager commits but does not close. Ignore that on cleanup.
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._old_path = database.DB_PATH
        database.DB_PATH = Path(self._tmpdir.name) / "t.db"

    def tearDown(self):
        database.DB_PATH = self._old_path
        self._tmpdir.cleanup()

    def test_two_queues_do_not_share_a_latest_row(self):
        database.init_db()
        ours = ["ok"] * 48
        other = ["off"] * 48
        database._save_schedule_if_changed("2026-11-09", ours, "5.1", 0)
        database._save_schedule_if_changed("2026-11-09", other, "1.1", 0)

        saved_ours = database.schedule_history_for_date("2026-11-09", "5.1")
        saved_other = database.schedule_history_for_date("2026-11-09", "1.1")
        self.assertEqual(len(saved_ours), 1)
        self.assertEqual(saved_ours[0]["grid"], ours)
        self.assertEqual(saved_other[0]["grid"], other)

        with database._conn() as db:
            mixed = db.execute(
                "SELECT queue, grid_json FROM schedule_history WHERE target_date=? ORDER BY id",
                ("2026-11-09",),
            ).fetchall()
        self.assertEqual(len(mixed), 2)
        self.assertNotEqual(mixed[0]["grid_json"], mixed[1]["grid_json"])

    def test_unchanged_grid_is_not_inserted_again(self):
        database.init_db()
        grid = ["maybe"] * 48
        first = database._save_schedule_if_changed("2026-11-09", grid, "5.1", 0)
        second = database._save_schedule_if_changed("2026-11-09", grid, "5.1", 0)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(len(database.schedule_history_for_date("2026-11-09", "5.1")), 1)

    def test_emergency_flip_inserts_when_the_grid_is_unchanged(self):
        database.init_db()
        grid = ["ok"] * 48
        database._save_schedule_if_changed("2026-11-09", grid, "5.1", 0)
        flipped = database._save_schedule_if_changed("2026-11-09", grid, "5.1", 1)
        self.assertIsNotNone(flipped)
        self.assertEqual(len(database.schedule_history_for_date("2026-11-09", "5.1")), 2)
        with database._conn() as db:
            flags = [
                row["emergency"]
                for row in db.execute(
                    "SELECT emergency FROM schedule_history WHERE queue=? ORDER BY id",
                    ("5.1",),
                )
            ]
        self.assertEqual(flags, [0, 1])

    def test_legacy_rows_become_queue_5_1(self):
        path = database.DB_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.execute(
            """CREATE TABLE schedule_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_date TEXT NOT NULL,
                grid_json TEXT NOT NULL,
                fetched_at REAL NOT NULL
            )"""
        )
        conn.execute(
            "INSERT INTO schedule_history(target_date, grid_json, fetched_at) VALUES (?,?,?)",
            ("2026-11-01", '["ok"]', 1.0),
        )
        conn.commit()
        conn.close()

        database.init_db()
        legacy = database.schedule_history_for_date("2026-11-01", "5.1")
        self.assertEqual(len(legacy), 1)
        self.assertEqual(legacy[0]["grid"], ["ok"])
        self.assertEqual(database.schedule_history_for_date("2026-11-01", "1.1"), [])
        database.init_db()


def _changes(db_path_queue: str, target_date: str) -> list[sqlite3.Row]:
    with database._conn() as db:
        return db.execute(
            """SELECT kind, start_slot, end_slot, from_status, to_status,
                      peer_start_slot, peer_end_slot
               FROM schedule_changes WHERE queue=? AND target_date=? ORDER BY id""",
            (db_path_queue, target_date),
        ).fetchall()


class GridChangeTests(unittest.TestCase):
    def test_off_to_ok_is_removed(self):
        rows = dtek.classify_grid_changes(["off"] * 48, ["ok"] * 48)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "removed")
        self.assertEqual((rows[0]["start_slot"], rows[0]["end_slot"]), (0, 48))

    def test_ok_to_off_is_added(self):
        rows = dtek.classify_grid_changes(["ok"] * 48, ["off"] * 48)
        self.assertEqual(rows[0]["kind"], "added")
        self.assertEqual(rows[0]["to_status"], "off")

    def test_off_to_maybe_is_severity(self):
        rows = dtek.classify_grid_changes(["off"] * 48, ["maybe"] * 48)
        self.assertEqual(rows[0]["kind"], "severity")
        self.assertEqual((rows[0]["from_status"], rows[0]["to_status"]), ("off", "maybe"))

    def test_four_hour_block_shifted_two_hours_is_one_move(self):
        old = ["ok"] * 48
        new = ["ok"] * 48
        for slot in range(16, 24):
            old[slot] = "off"
        for slot in range(20, 28):
            new[slot] = "off"
        rows = dtek.classify_grid_changes(old, new)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "moved")
        # Slots 20-23 stay off, so the diff is the leading edge moving to the trailing edge.
        self.assertEqual((rows[0]["start_slot"], rows[0]["end_slot"]), (16, 20))
        self.assertEqual((rows[0]["peer_start_slot"], rows[0]["peer_end_slot"]), (24, 28))

    def test_lengths_two_slots_apart_stay_removed_and_added(self):
        old = ["ok"] * 48
        new = ["ok"] * 48
        for slot in range(0, 8):
            old[slot] = "off"
        for slot in range(20, 26):
            new[slot] = "off"
        kinds = [row["kind"] for row in dtek.classify_grid_changes(old, new)]
        self.assertCountEqual(kinds, ["removed", "added"])


class PublishedScheduleStoreTests(ScheduleHistoryQueueTests):
    def _region(self, queues: dict, emergency: bool = False) -> dict:
        return {"cpu": "kiivska-oblast", "emergency": emergency, "schedule": queues}

    def _day(self, status: int = 1) -> dict:
        slots = {}
        for index in range(48):
            hour, minute = divmod(index * 30, 60)
            slots[f"{hour:02d}:{minute:02d}"] = status
        return slots

    def test_first_snapshot_has_no_change_rows(self):
        database.init_db()
        database._save_schedule_if_changed("2026-11-09", ["off"] * 48, "5.1", 0)
        self.assertEqual(_changes("5.1", "2026-11-09"), [])

    def test_change_rows_are_stored_with_the_snapshot(self):
        database.init_db()
        database._save_schedule_if_changed("2026-11-09", ["off"] * 48, "5.1", 0)
        database._save_schedule_if_changed("2026-11-09", ["ok"] * 48, "5.1", 0)
        rows = _changes("5.1", "2026-11-09")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "removed")

    def test_twelve_queues_are_stored_once(self):
        database.init_db()
        names = [f"{group}.{half}" for group in range(1, 7) for half in (1, 2)]
        queues = {name: {"2026-11-09": self._day(1)} for name in names}
        now = datetime(2026, 11, 9, 15, 0, tzinfo=UA_TZ)
        before = dict(dtek.schedule_cache)
        update = dtek.store_published_schedule(self._region(queues), now)
        again = dtek.store_published_schedule(self._region(queues), now)
        with database._conn() as db:
            count = db.execute("SELECT COUNT(*) AS c FROM schedule_history").fetchone()["c"]
        self.assertEqual(count, 12)
        self.assertEqual(update["today"]["date"], "2026-11-09")
        self.assertEqual(again["today"]["grid"], update["today"]["grid"])
        self.assertEqual(dtek.schedule_cache, before)

    def test_missing_our_queue_stores_others_and_leaves_cache_input(self):
        database.init_db()
        now = datetime(2026, 11, 9, 15, 0, tzinfo=UA_TZ)
        update = dtek.store_published_schedule(
            self._region({"1.1": {"2026-11-09": self._day(3)}}),
            now,
        )
        self.assertIsNone(update)
        self.assertEqual(len(database.schedule_history_for_date("2026-11-09", "1.1")), 1)
        self.assertEqual(database.schedule_history_for_date("2026-11-09", "5.1"), [])

    def test_missing_today_does_not_invent_a_cache_key(self):
        database.init_db()
        now = datetime(2026, 11, 9, 15, 0, tzinfo=UA_TZ)
        update = dtek.store_published_schedule(
            self._region({"5.1": {"2026-11-10": self._day(3)}}),
            now,
        )
        self.assertNotIn("today", update)
        self.assertEqual(update["tomorrow"]["date"], "2026-11-10")
        self.assertEqual(len(database.schedule_history_for_date("2026-11-10", "5.1")), 1)


class OverlayWriterTests(ScheduleHistoryQueueTests):
    def test_voltage_gap_and_dead_sample(self):
        start = 1_700_000_000.0
        opened = apply_voltage_sample([], start, 250, 230, 230)
        self.assertEqual(opened[0]["band"], "high")
        self.assertIsNone(opened[0]["end"])
        extended = apply_voltage_sample(opened, start + 90, 251, 230, 230)
        self.assertEqual(len(extended), 1)
        self.assertEqual(extended[0]["last_ts"], start + 90)
        split = apply_voltage_sample(opened, start + 120, 252, 230, 230)
        self.assertEqual(len(split), 2)
        self.assertEqual(split[0]["end"], start)
        self.assertEqual(split[1]["start"], start + 120)
        far = apply_voltage_sample(opened, start + 3600, 253, 230, 230)
        self.assertEqual(far[0]["end"], start)
        self.assertNotEqual(far[1]["start"], start + 90)
        dead = apply_voltage_sample(opened, start + 30, 10, 0, 0)
        self.assertEqual(dead[0]["end"], start)
        self.assertNotIn("last_ts", dead[0])

    def test_match_counts_off_and_maybe_as_outage(self):
        day_start, _day_end = kyiv_day_bounds("2026-11-09")
        off = ["ok"] * 48
        off[0] = "off"
        actual = [{"start": day_start, "end": day_start + 600}]
        scored = recompute_match(off, actual, day_start, day_start + 1800)
        self.assertEqual(scored["hit_min"], 10)
        self.assertEqual(scored["miss_min"], 20)
        unplanned = recompute_match(
            ["ok"] * 48,
            [{"start": day_start, "end": day_start + 60}],
            day_start,
            day_start + 60,
        )
        self.assertEqual(unplanned["unplanned_min"], 1)
        maybe_dark = recompute_match(
            ["maybe"] * 48,
            [{"start": day_start, "end": day_start + 600}],
            day_start,
            day_start + 600,
        )
        self.assertEqual(maybe_dark["hit_min"], 10)
        self.assertEqual(maybe_dark["miss_min"], 0)
        maybe_light = recompute_match(["maybe"] * 48, [], day_start, day_start + 60)
        self.assertEqual(maybe_light["miss_min"], 1)
        self.assertEqual(maybe_light["hit_min"], 0)

    def test_up_after_midnight_closes_yesterday_and_writes_today(self):
        database.init_db()
        yesterday, today = "2026-11-08", "2026-11-09"
        y_start, y_end = kyiv_day_bounds(yesterday)
        t_start, _t_end = kyiv_day_bounds(today)
        with database._conn() as db:
            db.execute(
                """INSERT INTO schedule_day(queue, target_date, actual_json, overlay_ready, updated_at)
                   VALUES(?,?,?,?,?)""",
                (DTEK_QUEUE, yesterday, json.dumps([{"start": y_start + 3600, "end": None}]), 1, y_start),
            )
        up_ts = t_start + 3600
        database._save_event_at("up", up_ts)
        with database._conn() as db:
            today_row = json.loads(db.execute(
                "SELECT actual_json FROM schedule_day WHERE queue=? AND target_date=?",
                (DTEK_QUEUE, today),
            ).fetchone()["actual_json"])
            yest_row = json.loads(db.execute(
                "SELECT actual_json FROM schedule_day WHERE queue=? AND target_date=?",
                (DTEK_QUEUE, yesterday),
            ).fetchone()["actual_json"])
        self.assertEqual(today_row[0]["start"], t_start)
        self.assertEqual(today_row[0]["end"], up_ts)
        self.assertEqual(yest_row[0]["end"], y_end)

    def test_voltage_event_does_not_write_schedule_day(self):
        database.init_db()
        database._save_event_at("voltage_high", 1_700_000_000.0)
        with database._conn() as db:
            events = db.execute("SELECT event FROM power_events").fetchall()
            days = db.execute("SELECT COUNT(*) AS c FROM schedule_day").fetchone()["c"]
        self.assertEqual(events[0]["event"], "voltage_high")
        self.assertEqual(days, 0)

    def test_save_deye_log_does_not_select_the_sample_log(self):
        database.init_db()
        seen = []
        real = database._conn

        def wrapped():
            conn = real()

            class Spy:
                def execute(self, sql, params=()):
                    seen.append(sql)
                    if "from deye_log" in sql.lower():
                        raise AssertionError(sql)
                    return conn.execute(sql, params)

                def __enter__(self):
                    conn.__enter__()
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return conn.__exit__(exc_type, exc, tb)

            return Spy()

        database._conn = wrapped
        try:
            database.save_deye_log(
                grid_v_l1=250,
                grid_v_l2=230,
                grid_v_l3=230,
                inverter_id=database.apartment_inverter_id(),
            )
        finally:
            database._conn = real
        self.assertTrue(any(sql.lstrip().upper().startswith("INSERT INTO DEYE_LOG") for sql in seen))

    def test_save_deye_log_rejects_a_missing_or_unknown_inverter(self):
        database.init_db()
        with self.assertRaises(ValueError):
            database.save_deye_log(grid_v_l1=230, grid_v_l2=230, grid_v_l3=230)
        with self.assertRaises(ValueError):
            database.save_deye_log(
                grid_v_l1=230, grid_v_l2=230, grid_v_l3=230, inverter_id=99999,
            )
        with database._conn() as db:
            nulls = db.execute(
                "SELECT COUNT(*) AS c FROM deye_log WHERE inverter_id IS NULL"
            ).fetchone()["c"]
        self.assertEqual(nulls, 0)

    def test_house_sample_stays_out_of_apartment_reads(self):
        database.init_db()
        apt = database.apartment_inverter_id()
        database.save_deye_log(
            grid_v_l1=0, grid_v_l2=0, grid_v_l3=0, load_power_w=10,
            inverter_id=apt,
        )
        with database._conn() as db:
            before = db.execute(
                "SELECT voltage_json FROM schedule_day WHERE queue=?",
                (DTEK_QUEUE,),
            ).fetchone()["voltage_json"]
            db.execute(
                """INSERT INTO deye_inverter(serial, mac, title, host, port, battery_kwh, poll_enabled)
                   VALUES('house-test', '74:e9:d8:39:22:8a', 'house', '10.0.0.8', 8899, 160, 0)"""
            )
            house = db.execute(
                "SELECT id FROM deye_inverter WHERE serial='house-test'"
            ).fetchone()["id"]
        database.save_deye_log(
            grid_v_l1=230, grid_v_l2=230, grid_v_l3=230, load_power_w=9000,
            inverter_id=house,
        )
        with database._conn() as db:
            after = db.execute(
                "SELECT voltage_json FROM schedule_day WHERE queue=?",
                (DTEK_QUEUE,),
            ).fetchone()["voltage_json"]
        self.assertEqual(before, after)
        self.assertFalse(database.has_grid_voltage_now())
        self.assertTrue(all(
            row.get("load_power_w") != 9000 for row in database.recent_deye_log(10)
        ))
        self.assertEqual(database.recent_deye_log(10, house)[0]["load_power_w"], 9000)

    def test_fragment_hides_apartment_block_without_the_section(self):
        from api.dashboard import hide_private_deye_fragment
        hidden = hide_private_deye_fragment({"pm_deye": "АКБ: 40%"}, ["voltage_details"])
        self.assertNotIn("pm_deye", hidden)
        shown = hide_private_deye_fragment({"pm_deye": "АКБ: 40%"}, ["deye_details"])
        self.assertEqual(shown["pm_deye"], "АКБ: 40%")
        kept = hide_private_deye_fragment(
            {"pm_deye": "АКБ: 11%", "pm_deye_house": "Немає заміру"},
            ["deye_house_details"],
        )
        self.assertNotIn("pm_deye", kept)
        self.assertEqual(kept["pm_deye_house"], "Немає заміру")
        private_voltage = hide_private_deye_fragment(
            {"pm_voltage": "230", "pm_voltage_house": "228"},
            ["voltage_house_details"],
        )
        self.assertNotIn("pm_voltage", private_voltage)
        self.assertEqual(private_voltage["pm_voltage_house"], "228")

    def test_house_block_is_on_every_explicit_list_and_stays_unpolled(self):
        database.init_db()
        with database._conn() as db:
            db.execute(
                "INSERT INTO roles(name, sections, is_builtin, created_at) VALUES(?,?,0,?)",
                ("limited", json.dumps(["sched_details"]), 0),
            )
        database.init_db()
        with database._conn() as db:
            limited = json.loads(db.execute(
                "SELECT sections FROM roles WHERE name='limited'"
            ).fetchone()["sections"])
            bare = json.loads(db.execute(
                "SELECT sections FROM roles WHERE name='Без Deye'"
            ).fetchone()["sections"])
            house = db.execute(
                "SELECT host, mac, battery_kwh, poll_enabled FROM deye_inverter WHERE title=?",
                (database.HOUSE_INVERTER_TITLE,),
            ).fetchone()
        self.assertIn("deye_house_details", limited)
        self.assertNotIn("deye_details", limited)
        self.assertIn("deye_house_details", bare)
        self.assertNotIn("deye_details", bare)
        self.assertEqual(house["host"], "192.168.0.104")
        self.assertEqual(house["mac"], "74:e9:d8:39:22:8a")
        self.assertEqual(house["battery_kwh"], 153.6)
        self.assertEqual(house["poll_enabled"], 0)
        self.assertNotIn(
            database.HOUSE_INVERTER_TITLE,
            [row["title"] for row in database.enabled_inverter_targets()],
        )

    def test_public_voltage_list_moves_to_the_house_chart(self):
        database.init_db()
        with database._conn() as db:
            db.execute(
                "INSERT INTO roles(name, sections, is_builtin, created_at) VALUES(?,?,0,?)",
                ("public-like", json.dumps(["voltage_details", "sched_details"]), 0),
            )
            db.execute(
                "INSERT INTO roles(name, sections, is_builtin, created_at) VALUES(?,?,0,?)",
                ("both", json.dumps(["voltage_details", "deye_details"]), 0),
            )
        database.init_db()
        with database._conn() as db:
            public_like = json.loads(db.execute(
                "SELECT sections FROM roles WHERE name='public-like'"
            ).fetchone()["sections"])
            both = json.loads(db.execute(
                "SELECT sections FROM roles WHERE name='both'"
            ).fetchone()["sections"])
        self.assertIn("voltage_house_details", public_like)
        self.assertNotIn("voltage_details", public_like)
        self.assertIn("voltage_house_details", both)
        self.assertIn("voltage_details", both)
        self.assertIn("deye_details", both)

    def test_house_block_says_there_is_no_sample(self):
        from power_monitor import house_deye_inner_html
        database.init_db()
        database.save_deye_log(battery_soc=11, load_power_w=10, inverter_id=database.apartment_inverter_id())
        html = house_deye_inner_html()
        self.assertIn("Немає заміру", html)
        self.assertNotIn("АКБ: 11%", html)
        self.assertNotIn("pm-voltage", html)

    def test_recent_samples_follow_the_clock_not_the_row_id(self):
        database.init_db()
        apt = database.apartment_inverter_id()
        database.save_deye_log(load_power_w=111, inverter_id=apt)
        database.save_deye_log(load_power_w=222, inverter_id=apt)
        with database._conn() as db:
            ids = [row["id"] for row in db.execute("SELECT id FROM deye_log ORDER BY id").fetchall()]
            db.execute("UPDATE deye_log SET ts=? WHERE id=?", (2_000, ids[0]))
            db.execute("UPDATE deye_log SET ts=? WHERE id=?", (1_000, ids[1]))
        self.assertEqual(database.recent_deye_log(1)[0]["load_power_w"], 111)

    def test_board_read_does_not_scan_samples_or_events(self):
        database.init_db()
        seen = []
        real = database._conn

        def wrapped():
            conn = real()

            class Spy:
                def execute(self, sql, params=()):
                    seen.append(sql)
                    lowered = sql.lower()
                    if "from deye_log" in lowered or "from power_events" in lowered:
                        raise AssertionError(sql)
                    return conn.execute(sql, params)

                def __enter__(self):
                    conn.__enter__()
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return conn.__exit__(exc_type, exc, tb)

            return Spy()

        database._conn = wrapped
        database.deye_voltage_trend = lambda *a, **k: (_ for _ in ()).throw(AssertionError("trend"))
        database.events_in_range = lambda *a, **k: (_ for _ in ()).throw(AssertionError("events"))
        database.recent_events = lambda *a, **k: (_ for _ in ()).throw(AssertionError("recent"))
        database.deye_aggregates_refresh = lambda *a, **k: (_ for _ in ()).throw(AssertionError("agg"))
        try:
            first = read_schedule_board("2026-11-09", 1_762_646_400.0)
            updated = None
            with real() as db:
                row = db.execute(
                    "SELECT updated_at FROM schedule_day WHERE queue=? AND target_date=?",
                    (DTEK_QUEUE, "2026-11-09"),
                ).fetchone()
                updated = None if row is None else row["updated_at"]
            second = read_schedule_board("2026-11-09", 1_762_646_500.0)
            with real() as db:
                row = db.execute(
                    "SELECT updated_at FROM schedule_day WHERE queue=? AND target_date=?",
                    (DTEK_QUEUE, "2026-11-09"),
                ).fetchone()
                updated_again = None if row is None else row["updated_at"]
        finally:
            database._conn = real
        self.assertEqual(first["our_queue"], DTEK_QUEUE)
        self.assertIsNone(first["match"])
        self.assertFalse(first["groups"][DTEK_QUEUE]["has_snapshot"])
        self.assertEqual(second["date"], first["date"])
        self.assertEqual(updated_again, updated)

    def test_missing_key_is_rejected(self):
        database.init_db()
        from api.dashboard import ep_schedule_board

        with self.assertRaises(HTTPException) as caught:
            ep_schedule_board(key="not-a-real-key", date="2026-11-09")
        self.assertEqual(caught.exception.status_code, 403)

    def test_board_flag_is_on_unless_explicitly_off(self):
        database.init_db()
        import power_monitor
        self.assertTrue(power_monitor._schedule_board_on())
        database.kv_set("schedule_board", "0")
        self.assertFalse(power_monitor._schedule_board_on())
        database.kv_set("schedule_board", "1")
        self.assertTrue(power_monitor._schedule_board_on())
        page = power_monitor._build_schedule_html(False)
        fragment = power_monitor._build_schedule_fragment(False)
        self.assertIn('id="pm-sched-board"', page)
        self.assertNotIn("pm-sched-board", fragment)
        self.assertNotIn("schedule_history_for_date", fragment)

    def test_fragment_builder_does_not_call_the_board(self):
        text = Path("power_monitor.py").read_text(encoding="utf-8")
        start = text.index("def _build_update_fragments")
        end = text.index("\ndef ", start + 10)
        body = text[start:end]
        self.assertNotIn("schedule-board", body)
        self.assertNotIn("read_schedule_board", body)


class ScheduleChangesFoldTests(unittest.TestCase):
    def test_changes_table_starts_closed(self):
        script = Path("static/app.js").read_text(encoding="utf-8")
        start = script.index("visibleChanges")
        chunk = script[start:script.index("schedBoard.innerHTML", start)]
        self.assertIn("pm_sched_changes_open", chunk)
        self.assertIn("<details class=\"sb-changes-details\"", chunk)
        self.assertLess(chunk.index("<details"), chunk.index("<table class=\"sb-changes\">"))
        self.assertNotIn("<details class=\"sb-changes-details\" open", chunk)


class SchedulePollTests(unittest.TestCase):
    def test_outage_schedule_is_polled_every_fifteen_minutes(self):
        self.assertEqual(DTEK_POLL_SEC, 15 * 60)
        fetch = Path("dtek.py").read_text(encoding="utf-8")
        self.assertIn("_schedule_fetched_at >= DTEK_POLL_SEC", fetch)
        loop = Path("power_monitor.py").read_text(encoding="utf-8")
        self.assertIn("schedule_tick * 30 >= DTEK_POLL_SEC", loop)


if __name__ == "__main__":
    unittest.main()
