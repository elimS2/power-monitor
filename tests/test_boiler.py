"""Oselya boiler notices: a date owns the ranges before the next date."""
from __future__ import annotations

import unittest
from datetime import datetime

from api.telegram import incoming_text
from config import UA_TZ
from database import parse_boiler_schedule

TODAY = datetime(2026, 11, 10, 16, 0, tzinfo=UA_TZ)

LETTER = """Графік роботи котельні від генератора

Шановні мешканці!

За відсутності централізованого електропостачання котельня працюватиме від генератора за графіком:

10 листопада 2026 року з 17:00-24:00

У зазначені години просимо забезпечити роботу альтернативних джерел живлення будинку.
"""


class BoilerParseTests(unittest.TestCase):
    def test_oselya_letter_with_year_and_z(self):
        parsed = parse_boiler_schedule(LETTER, TODAY)
        self.assertEqual(parsed, [{"date": "2026-11-10", "intervals": [["17:00", "24:00"]]}])

    def test_colon_line_keeps_several_ranges(self):
        text = "Котельня\n2 березня: 16:00-20:00, 21:00-23:00\n3 березня: 8:00-12:00"
        parsed = parse_boiler_schedule(text, TODAY)
        self.assertEqual(parsed, [
            {"date": "2026-03-02", "intervals": [["16:00", "20:00"], ["21:00", "23:00"]]},
            {"date": "2026-03-03", "intervals": [["08:00", "12:00"]]},
        ])

    def test_do_and_dotted_clocks(self):
        text = "Генератор. 10 листопада з 17.00 до 24.00 та 6:05–8:10"
        parsed = parse_boiler_schedule(text, TODAY)
        self.assertEqual(parsed, [{
            "date": "2026-11-10",
            "intervals": [["17:00", "24:00"], ["06:05", "08:10"]],
        }])

    def test_numeric_date(self):
        text = "Котельня 10.11.2026 з 17:00 до 24:00"
        parsed = parse_boiler_schedule(text, TODAY)
        self.assertEqual(parsed, [{"date": "2026-11-10", "intervals": [["17:00", "24:00"]]}])

    def test_december_reads_january_as_next_year(self):
        today = datetime(2026, 12, 30, tzinfo=UA_TZ)
        parsed = parse_boiler_schedule("Котельня\n2 січня: 16:00-20:00", today)
        self.assertEqual(parsed[0]["date"], "2027-01-02")

    def test_explicit_year_wins_in_december(self):
        today = datetime(2026, 12, 30, tzinfo=UA_TZ)
        parsed = parse_boiler_schedule("Котельня\n2 січня 2026 року: 16:00-20:00", today)
        self.assertEqual(parsed[0]["date"], "2026-01-02")

    def test_ranges_stay_with_their_day(self):
        text = "Генератор\n10 листопада: 17:00-24:00\n11 листопада: 06:00-09:00"
        parsed = parse_boiler_schedule(text, TODAY)
        self.assertEqual([row["date"] for row in parsed], ["2026-11-10", "2026-11-11"])
        self.assertEqual(parsed[0]["intervals"], [["17:00", "24:00"]])
        self.assertEqual(parsed[1]["intervals"], [["06:00", "09:00"]])

    def test_broken_clock_does_not_erase_a_valid_range(self):
        text = "Котельня 10 листопада: 25:00-26:00, 17:00-24:00, 20:00-17:00"
        parsed = parse_boiler_schedule(text, TODAY)
        self.assertEqual(parsed, [{"date": "2026-11-10", "intervals": [["17:00", "24:00"]]}])

    def test_impossible_day_is_skipped(self):
        text = "Котельня\n32 листопада: 17:00-24:00\n10 листопада: 18:00-20:00"
        parsed = parse_boiler_schedule(text, TODAY)
        self.assertEqual(parsed, [{"date": "2026-11-10", "intervals": [["18:00", "20:00"]]}])

    def test_keyword_or_range_missing(self):
        self.assertEqual(parse_boiler_schedule("10 листопада: 17:00-24:00", TODAY), [])
        self.assertEqual(parse_boiler_schedule("Котельня завтра не працює", TODAY), [])

    def test_caption_is_the_notice_when_the_photo_has_no_text(self):
        self.assertEqual(incoming_text({"caption": "Котельня 10 листопада: 17:00-24:00"}), "Котельня 10 листопада: 17:00-24:00")
        self.assertEqual(incoming_text({"text": "є", "caption": "ні"}), "є")
