"""Queue-scoped schedule history. Phase 1 of the compare board.

These tests use a temporary database. They do not touch the live file.
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

import database


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


if __name__ == "__main__":
    unittest.main()
