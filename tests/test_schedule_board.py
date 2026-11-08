"""Queue-scoped schedule history. Phase 1 of the compare board.

These tests use a temporary database. They do not touch the live file.
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

import database
import dtek
from config import UA_TZ
from datetime import datetime


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


if __name__ == "__main__":
    unittest.main()
