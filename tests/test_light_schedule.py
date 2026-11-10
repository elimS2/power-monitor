"""Lighting timers follow today's outage edges, five minutes later."""
from __future__ import annotations

import unittest
from datetime import datetime

from config import UA_TZ
from light_schedule import desired_light_timers, light_change_lines, plan_light_changes

NOW = datetime(2026, 11, 11, 0, 30, tzinfo=UA_TZ)


def _grid() -> list[str]:
    """Dark until 05:00, light until 10:00, dark again."""
    grid = ["maybe"] * 48
    for index in range(10, 20):
        grid[index] = "ok"
    return grid


class LightScheduleTests(unittest.TestCase):
    def test_edges_are_five_minutes_later(self):
        wanted = desired_light_timers(_grid(), "2026-11-11", NOW, "maybe")
        self.assertEqual(wanted, [
            {"fire_date": "20261111", "fire_time": "05:05", "switch": 1},
            {"fire_date": "20261111", "fire_time": "10:05", "switch": 0},
        ])

    def test_off_and_maybe_are_the_same_darkness(self):
        grid = ["ok"] * 48
        for index in range(20, 48):
            grid[index] = "off" if index == 20 else "maybe"
        wanted = desired_light_timers(grid, "2026-11-11", NOW, "ok")
        self.assertEqual([row["fire_time"] for row in wanted], ["10:05"])
        self.assertEqual(wanted[0]["switch"], 0)

    def test_midnight_follows_yesterday(self):
        grid = ["ok"] * 48
        early = datetime(2026, 11, 11, 0, 0, tzinfo=UA_TZ)
        wanted = desired_light_timers(grid, "2026-11-11", early, "maybe")
        self.assertEqual(wanted, [
            {"fire_date": "20261111", "fire_time": "00:05", "switch": 1},
        ])

    def test_a_passed_edge_is_not_set_again(self):
        later = datetime(2026, 11, 11, 6, 0, tzinfo=UA_TZ)
        wanted = desired_light_timers(_grid(), "2026-11-11", later, "maybe")
        self.assertEqual([row["fire_time"] for row in wanted], ["10:05"])

    def test_a_moved_edge_deletes_the_old_timer_and_adds_the_new_one(self):
        current = [{
            "timer_id": "1", "fire_date": "20261111", "fire_time": "10:05", "switch": 0,
        }]
        desired = [{
            "fire_date": "20261111", "fire_time": "11:05", "switch": 0,
        }]
        deletes, creates = plan_light_changes(desired, current)
        self.assertEqual(deletes, current)
        self.assertEqual(creates, desired)
        self.assertEqual(light_change_lines(deletes, creates), [
            "removed off 2026-11-11 10:05",
            "added off 2026-11-11 11:05",
        ])

    def test_a_matching_list_changes_nothing(self):
        row = {"timer_id": "1", "fire_date": "20261111", "fire_time": "05:05", "switch": 1}
        deletes, creates = plan_light_changes([row], [row])
        self.assertEqual(deletes, [])
        self.assertEqual(creates, [])
        self.assertEqual(light_change_lines(deletes, creates), ["already matches, nothing to change"])


if __name__ == "__main__":
    unittest.main()
