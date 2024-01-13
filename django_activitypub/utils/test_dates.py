import unittest
import datetime
from .dates import parse_datetime


class DatetimeParsingTests(unittest.TestCase):
    def test_parse_datetime_pleroma(self):
        self.assertEqual(
            parse_datetime('2024-01-13T05:59:20.296128Z'),
            datetime.datetime(2024, 1, 13, 5, 59, 20, 296128),
        )

    def test_parse_datetime_mastodon(self):
        self.assertEqual(
            parse_datetime('2018-10-14T19:23:31Z'),
            datetime.datetime(2018, 10, 14, 19, 23, 31),
        )
