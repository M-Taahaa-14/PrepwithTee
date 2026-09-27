"""Study streaks (website/streaks.py)."""
from datetime import date

from streaks import local_day, streaks, valid_client_day, zone


def test_current_streak_counts_back_from_today():
    days = {"2026-09-26", "2026-09-27", "2026-09-28"}
    assert streaks(days, date(2026, 9, 28)) == (3, 3)


def test_today_without_activity_yet_keeps_yesterdays_streak():
    days = {"2026-09-26", "2026-09-27"}
    assert streaks(days, date(2026, 9, 28)) == (2, 2)


def test_a_missed_day_breaks_the_streak_but_best_remembers():
    days = {"2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-27"}
    assert streaks(days, date(2026, 9, 28)) == (1, 4)
    assert streaks(set(), date(2026, 9, 28)) == (0, 0)


def test_utc_timestamps_land_on_the_students_local_day():
    pk = zone("Asia/Karachi")                       # UTC+5
    # 21:30 UTC on the 27th is 02:30 on the 28th in Lahore
    assert local_day("2026-09-27T21:30:00+00:00", pk) == "2026-09-28"
    assert local_day("2026-09-27 21:30:00", pk) == "2026-09-28"      # naive = UTC
    assert local_day("2026-09-27", pk) == "2026-09-27"               # already a day
    assert local_day(None, pk) is None


def test_unknown_timezone_falls_back_to_pakistan():
    assert local_day("2026-09-27T21:30:00Z", zone("Not/AZone")) == "2026-09-28"


def test_client_day_must_be_close_to_now():
    assert valid_client_day("1999-01-01") is None
    assert valid_client_day("not a day") is None
    assert valid_client_day(None) is None
