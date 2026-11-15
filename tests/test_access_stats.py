"""Dashboard visit counter: journal lines, one-day rows, no request-path database write."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import access_stats
import database
from database import access_day_for, access_day_merge


LINE = (
    '1792000000.5 host uvicorn[1]: INFO:     203.0.113.9:0 - '
    '"GET /?key=sample-key HTTP/1.0" 200 OK\n'
)
POLL = (
    '1792000300.0 host uvicorn[1]: INFO:     203.0.113.9:0 - '
    '"GET /api/dashboard-fragments?key=sample-key&chart_shift=0 HTTP/1.0" 200 OK\n'
)
PULSE = (
    '1792000001.0 host uvicorn[1]: INFO:     203.0.113.8:0 - '
    '"GET /api/heartbeat?key=sample-key HTTP/1.0" 200 OK\n'
)


class AccessParseTests(unittest.TestCase):
    def test_page_and_refresh_are_kept(self):
        self.assertEqual(access_stats.classify_target("/?key=abc"), "page")
        self.assertEqual(access_stats.classify_target("/api/dashboard-fragments?key=abc"), "poll")
        self.assertIsNone(access_stats.classify_target("/api/heartbeat?key=abc"))
        self.assertIsNone(access_stats.classify_target("/icons/icon_on.png"))

    def test_journal_line_keeps_the_visit_and_drops_the_router(self):
        hit = access_stats.parse_access_line(LINE)
        self.assertEqual(hit["ip"], "203.0.113.9")
        self.assertEqual(hit["kind"], "page")
        self.assertEqual(hit["key"], "sample-key")
        self.assertIsNone(access_stats.parse_access_line(PULSE))
        later = access_stats.parse_access_line(LINE, before=1792000000.5)
        self.assertIsNone(later)

    def test_merge_sums_a_day_and_sorts_by_last_visit(self):
        self._use_temp_db()
        access_day_merge([
            ("2026-10-15", "vasyl", "203.0.113.9", 1, 0, 100.0),
            ("2026-10-15", "vasyl", "203.0.113.9", 1, 4, 250.0),
            ("2026-10-15", "public", "203.0.113.4", 2, 0, 200.0),
            ("2026-10-14", "public", "203.0.113.4", 9, 0, 50.0),
        ])
        rows = access_day_for("2026-10-15")
        self.assertEqual([row["label"] for row in rows], ["vasyl", "public"])
        self.assertEqual(rows[0]["page_hits"], 2)
        self.assertEqual(rows[0]["poll_hits"], 4)
        self.assertEqual(rows[0]["last_ts"], 250.0)
        self.assertEqual(access_day_for("2026-10-14")[0]["page_hits"], 9)
        self.assertEqual(access_day_for("2026-10-16"), [])

    def test_live_note_stays_in_memory_until_flush(self):
        self._use_temp_db()
        database.api_key_create("guest", "sample-key")
        access_stats._labels.clear()
        access_stats._buf.clear()
        access_stats.note_access("sample-key", "203.0.113.9", "page", ts=1792000000.5)
        access_stats.note_access("sample-key", "203.0.113.9", "poll", ts=1792000300.0)
        self.assertEqual(access_day_for("2026-10-14"), [])
        access_stats.flush_access()
        rows = access_day_for("2026-10-14")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["label"], "guest")
        self.assertEqual(rows[0]["page_hits"], 1)
        self.assertEqual(rows[0]["poll_hits"], 1)
        self.assertEqual(access_stats._buf, {})

    def test_unknown_key_does_not_keep_the_secret(self):
        self._use_temp_db()
        access_stats._labels.clear()
        access_stats._buf.clear()
        access_stats.note_access("not-a-real-key", "203.0.113.7", "page", ts=1792000000.5)
        access_stats.flush_access()
        row = access_day_for("2026-10-14")[0]
        self.assertEqual(row["label"], "невідомий")
        self.assertNotIn("not-a-real-key", row["label"])

    def test_parsed_hits_fold_into_the_same_table(self):
        self._use_temp_db()
        acc = {}
        access_stats._labels.clear()
        access_stats.add_parsed(acc, access_stats.parse_access_line(LINE), lambda key: "public" if key == "sample-key" else None)
        access_stats.add_parsed(acc, access_stats.parse_access_line(POLL), lambda key: "public" if key == "sample-key" else None)
        self.assertEqual(len(acc), 1)
        (day, label, ip), hits = next(iter(acc.items()))
        self.assertEqual((day, label, ip), ("2026-10-14", "public", "203.0.113.9"))
        self.assertEqual(hits[0], 1)
        self.assertEqual(hits[1], 1)

    def test_ip_details_come_from_cache_and_skip_private_addresses(self):
        self._use_temp_db()
        rows = [
            {"ip": "203.0.113.9"},
            {"ip": "192.168.88.2"},
        ]
        asked = []

        def fetch(ips):
            asked.append(list(ips))
            return [{
                "status": "success",
                "query": "203.0.113.9",
                "country": "Ukraine",
                "regionName": "Kyiv",
                "city": "Brovary",
                "isp": "Example ISP",
                "org": "Example ISP",
                "as": "AS1 Example",
                "hosting": False,
                "proxy": False,
            }]

        access_stats.enrich_rows(rows, fetch, now=1_000_000)
        self.assertEqual(asked, [["203.0.113.9"]])
        self.assertEqual(rows[0]["country"], "Ukraine")
        self.assertEqual(rows[0]["place"], "Brovary, Kyiv")
        self.assertEqual(rows[0]["isp"], "Example ISP")
        self.assertEqual(rows[0]["net"], "")
        self.assertEqual(rows[0]["updated"], "12.01.1970")
        self.assertEqual(rows[1]["country"], "")
        access_stats.enrich_rows(rows, fetch, now=1_000_100)
        self.assertEqual(len(asked), 1)
        access_stats.enrich_rows(rows, fetch, now=1_000_000 + 31 * 86400)
        self.assertEqual(len(asked), 2)

    def test_datacenter_mark(self):
        self.assertEqual(access_stats.kind_label(1, 0), "датацентр")
        self.assertEqual(access_stats.kind_label(0, 1), "проксі")
        self.assertEqual(access_stats.place_label("Seoul", "Seoul"), "Seoul")

    def _use_temp_db(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmpdir.cleanup)
        self._old = database.DB_PATH
        database.DB_PATH = Path(self._tmpdir.name) / "t.db"
        self.addCleanup(setattr, database, "DB_PATH", self._old)
        database.init_db()


if __name__ == "__main__":
    unittest.main()
