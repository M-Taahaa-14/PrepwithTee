"""Study streaks, computed on the server from everything a student does.

The old streak counted only quizzes and tracked time, keyed by the SERVER's
UTC date, and the "best streak" lived in the browser (and was overwritten by
the server's 0 on every visit) - so nobody on production had a streak above 0
(2026-09-28). Now:

  * a day counts if the student did ANYTHING that day: active time on the
    site, a quiz, a topical booklet / mock test built, an MCQ session, a paper
    marked, flashcard reviews;
  * days are the student's own calendar days (their timezone, from the
    browser; Asia/Karachi when unknown), not UTC;
  * current streak = consecutive days ending today (or yesterday - today is
    not over yet); best = the longest run ever.

Pure functions only; users.py gathers the timestamps.
"""

from datetime import date, datetime, timedelta, timezone

DEFAULT_TZ = "Asia/Karachi"


def zone(name: str | None):
    """A tzinfo for an IANA name from the browser, or the default."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name or DEFAULT_TZ)
    except Exception:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(DEFAULT_TZ)
        except Exception:                        # no tz database at all (bare Windows)
            return timezone(timedelta(hours=5))


def local_today(tz) -> date:
    return datetime.now(tz).date()


def local_day(ts, tz) -> str | None:
    """'2026-09-27T20:15:00+00:00' (or a naive UTC timestamp, or a bare
    'YYYY-MM-DD') -> the student's local 'YYYY-MM-DD'."""
    if not ts:
        return None
    s = str(ts).strip()
    if len(s) == 10:                             # already a calendar day
        return s
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T", 1))
    except ValueError:
        return s[:10] if len(s) >= 10 else None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).date().isoformat()


def streaks(days: set[str], today: date) -> tuple[int, int]:
    """(current, best) runs of consecutive active days."""
    got = set()
    for d in days:
        try:
            got.add(date.fromisoformat(d[:10]))
        except (TypeError, ValueError):
            continue
    if not got:
        return 0, 0
    # current: from today, or from yesterday while today has no activity yet
    start = today if today in got else today - timedelta(days=1)
    cur = 0
    while start - timedelta(days=cur) in got:
        cur += 1
    best, run, prev = 0, 0, None
    for d in sorted(got):
        run = run + 1 if prev is not None and d - prev == timedelta(days=1) else 1
        best = max(best, run)
        prev = d
    return cur, max(best, cur)


def valid_client_day(day: str | None) -> str | None:
    """A 'YYYY-MM-DD' from the browser, accepted only within a day of UTC now
    (every real timezone is) - otherwise None."""
    if not day:
        return None
    try:
        d = date.fromisoformat(day)
    except ValueError:
        return None
    utc = datetime.now(timezone.utc).date()
    return day if abs((d - utc).days) <= 1 else None
