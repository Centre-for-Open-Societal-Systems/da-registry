import unittest
from datetime import date, timedelta

from openg2p_registry_da_extension.register_domain.services.ethiopian_calendar import (
    ethiopic_month_length,
    ethiopic_to_gregorian,
    gregorian_to_ethiopic,
    gregorian_to_ethiopic_string,
    is_ethiopic_leap_year,
    is_valid_ethiopic_date,
    parse_ethiopic,
)


class TestEthiopianCalendar(unittest.TestCase):
    def test_known_new_year_anchors(self):
        # Ethiopian New Year falls on 11 September, or 12 September when the
        # following Gregorian year is a leap year.
        self.assertEqual(gregorian_to_ethiopic(date(2023, 9, 12)), (2016, 1, 1))
        self.assertEqual(gregorian_to_ethiopic(date(2024, 9, 11)), (2017, 1, 1))
        self.assertEqual(ethiopic_to_gregorian(2016, 1, 1), date(2023, 9, 12))
        self.assertEqual(ethiopic_to_gregorian(2017, 1, 1), date(2024, 9, 11))

    def test_pagumen_is_month_13(self):
        year, month, day = gregorian_to_ethiopic(date(2023, 9, 10))
        self.assertEqual((year, month), (2015, 13))
        self.assertEqual(day, 5)
        # month 13 is exactly why this cannot be a date column
        with self.assertRaises(ValueError):
            date(2015, 13, 5)

    def test_round_trip_over_a_full_leap_cycle(self):
        # Four Ethiopic years covers a leap year in both calendars.
        current = date(2020, 1, 1)
        end = date(2028, 1, 1)
        while current < end:
            y, m, d = gregorian_to_ethiopic(current)
            self.assertTrue(is_valid_ethiopic_date(y, m, d), f"{current} -> {y}-{m}-{d}")
            self.assertEqual(ethiopic_to_gregorian(y, m, d), current)
            current += timedelta(days=1)

    def test_pagumen_length_follows_leap_year(self):
        self.assertTrue(is_ethiopic_leap_year(2015))
        self.assertEqual(ethiopic_month_length(2015, 13), 6)
        self.assertEqual(ethiopic_month_length(2016, 13), 5)
        self.assertEqual(ethiopic_month_length(2016, 1), 30)

    def test_invalid_ethiopic_dates_are_rejected(self):
        with self.assertRaises(ValueError):
            ethiopic_to_gregorian(2016, 13, 6)   # Pagumen 6 in a common year
        with self.assertRaises(ValueError):
            ethiopic_to_gregorian(2016, 14, 1)   # no 14th month
        with self.assertRaises(ValueError):
            ethiopic_to_gregorian(2016, 2, 31)   # months are 30 days

    def test_parse_ethiopic(self):
        self.assertEqual(parse_ethiopic("2015-13-05"), (2015, 13, 5))
        self.assertEqual(parse_ethiopic("  2016-01-01 "), (2016, 1, 1))
        self.assertIsNone(parse_ethiopic(""))
        self.assertIsNone(parse_ethiopic(None))
        self.assertIsNone(parse_ethiopic("05/13/2015"))
        # legacy rows written while the column was still DATE
        self.assertEqual(parse_ethiopic(date(2016, 1, 1)), (2016, 1, 1))

    def test_string_formatting_pads(self):
        self.assertEqual(gregorian_to_ethiopic_string(date(2023, 9, 10)), "2015-13-05")


if __name__ == "__main__":
    unittest.main()
