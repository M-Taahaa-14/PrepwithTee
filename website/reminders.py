"""Homework reminders for students.

Three channels, deliberately chosen for what this deployment can actually do:

  * **Email** — SMTP is already configured for the tutor's form notifications,
    so reaching students costs nothing extra. Sent when work is assigned and by
    a daily digest for anything due or overdue.
  * **Calendar (.ics)** — a subscribable feed the student adds once; their own
    phone then alarms them. No push infrastructure, works offline, and survives
    the student never opening the site.
  * **In-app** — the dashboard banner and nav badge (see dashboard.js).

Browser push was considered and rejected: it needs a service worker, VAPID keys
and a subscription table, only fires while the browser is running, and most
students dismiss the permission prompt. Email plus a calendar feed reaches them
on the device they actually use.

WhatsApp is the tutor's real channel but automated sending needs the Business
API (paid, approval-gated), so the admin console offers a prefilled click-to-send
link instead — the tutor presses it, which is honest about who is sending.
"""

import hashlib
import hmac
import json
import os
from datetime import date, datetime, timedelta

import users_db as _udb

def _public_base() -> str:
    """Base URL for links that leave the server — emails, calendar feeds.

    APP_BASE_URL is localhost during development, and a localhost link in an
    email or a phone's calendar subscription is simply broken: the recipient's
    device cannot reach it. Outbound links therefore always fall back to the
    real domain, and PUBLIC_BASE_URL can override both.
    """
    explicit = os.environ.get("PUBLIC_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    base = (os.environ.get("APP_BASE_URL") or "").rstrip("/")
    if not base or "localhost" in base or "127.0.0.1" in base or "0.0.0.0" in base:
        return "https://prepwithtee.com"
    return base


APP_BASE_URL = _public_base()
_SECRET = os.environ.get("SECRET_KEY", "dev-only-change-me-in-production")


# ── Calendar feed token ──────────────────────────────────────────────────────
# The .ics feed is fetched by a phone's calendar app, which cannot carry a
# session cookie, so the URL itself has to authenticate. A keyed digest of the
# user id is unguessable, stable (the student subscribes once) and revocable by
# rotating SECRET_KEY. It grants read-only access to homework titles and dates —
# no marks, no contact details — which is the right blast radius for a URL that
# will sit in a calendar app forever.

def calendar_token(user_id: str) -> str:
    return hmac.new(_SECRET.encode(), f"cal:{user_id}".encode(),
                    hashlib.sha256).hexdigest()[:32]


def verify_calendar_token(user_id: str, token: str) -> bool:
    return hmac.compare_digest(calendar_token(user_id), token or "")


def calendar_url(user_id: str) -> str:
    return f"{APP_BASE_URL}/api/calendar/{user_id}/{calendar_token(user_id)}.ics"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _json_list(raw):
    if isinstance(raw, list):
        return raw
    try:
        val = json.loads(raw or "[]")
        return val if isinstance(val, list) else []
    except (TypeError, ValueError):
        return []


def days_left(due: str | None) -> int | None:
    if not due:
        return None
    try:
        return (date.fromisoformat(due) - date.today()).days
    except ValueError:
        return None


def open_homework(user_id: str) -> list[dict]:
    return [a for a in _udb.get_assignments(user_id)
            if a.get("status") != "done"]


def due_phrase(d: int | None) -> str:
    if d is None:
        return "no deadline"
    if d < 0:
        return f"{abs(d)} day{'' if abs(d) == 1 else 's'} overdue"
    if d == 0:
        return "due today"
    if d == 1:
        return "due tomorrow"
    return f"due in {d} days"


# ── Email ────────────────────────────────────────────────────────────────────

def send_assigned_email(user: dict, assignment: dict, notify) -> bool:
    """Told-you-have-work email, fired when the tutor assigns something."""
    email = (user.get("email") or "").strip()
    if not email:
        return False
    first = (user.get("name") or "there").split(" ")[0]
    due = assignment.get("due_date")
    rows = [
        ("Task", assignment.get("title")),
        ("Subject", assignment.get("subject_name") or assignment.get("syllabus") or "—"),
        ("Type", (assignment.get("kind") or "homework").title()),
        ("Due", f"{due} ({due_phrase(days_left(due))})" if due else "No deadline set"),
    ]
    if assignment.get("instructions"):
        rows.append(("What to do", assignment["instructions"]))
    atts = _json_list(assignment.get("attachments_json"))
    if atts:
        rows.append(("Attached", ", ".join(
            a.get("name") or a.get("rel") or "file" for a in atts)))

    body = (f"Hi {first},\n\nTee has set you new work: {assignment.get('title')}\n"
            f"{'Due ' + due if due else 'No deadline set'}\n\n"
            f"Open it here: {APP_BASE_URL}/homework.html\n")
    return notify(f"New homework from Tee: {assignment.get('title')}",
                  body, rows, to=email,
                  cta=("Open your homework", f"{APP_BASE_URL}/homework.html"))


def send_digest_email(user: dict, items: list[dict], notify) -> bool:
    """Daily nudge covering everything due soon or already late."""
    email = (user.get("email") or "").strip()
    if not email or not items:
        return False
    first = (user.get("name") or "there").split(" ")[0]
    overdue = [a for a in items if (days_left(a.get("due_date")) or 0) < 0
               and a.get("due_date")]

    rows = [(due_phrase(days_left(a.get("due_date"))).title(), a.get("title"))
            for a in items]
    headline = (f"{len(overdue)} overdue" if overdue
                else f"{len(items)} due soon")
    body = (f"Hi {first},\n\nHomework reminder — {headline}.\n\n"
            + "\n".join(f"- {a.get('title')} ({due_phrase(days_left(a.get('due_date')))})"
                        for a in items)
            + f"\n\nOpen: {APP_BASE_URL}/homework.html\n")
    return notify(f"Homework reminder — {headline}",
                  body, rows, to=email,
                  cta=("Open your homework", f"{APP_BASE_URL}/homework.html"))


# ── iCalendar feed ───────────────────────────────────────────────────────────

def _ics_escape(s: str) -> str:
    return (str(s or "").replace("\\", "\\\\").replace(";", r"\;")
            .replace(",", r"\,").replace("\n", r"\n"))


def _fold(line: str) -> str:
    """RFC 5545 caps a content line at 75 octets; longer lines continue with a
    leading space. Calendar apps reject the file outright if this is skipped."""
    out, cur = [], line
    while len(cur.encode("utf-8")) > 73:
        cut = 73
        while len(cur[:cut].encode("utf-8")) > 73:
            cut -= 1
        out.append(cur[:cut])
        cur = " " + cur[cut:]
    out.append(cur)
    return "\r\n".join(out)


def build_ics(user: dict, assignments: list[dict]) -> str:
    """An all-day VEVENT per dated assignment, with an alarm the night before.

    VALARM is what actually makes the phone buzz — without it the entry is just
    a silent row in the calendar.
    """
    now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//PrepWithTee//Homework//EN",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "X-WR-CALNAME:PrepWithTee homework",
        "X-WR-CALDESC:Homework set by your tutor",
        # Tells subscribing clients how often to re-poll for new work.
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]
    for a in assignments:
        due = (a.get("due_date") or "").strip()
        if not due:
            continue                    # an undated task has nothing to alarm on
        try:
            d = date.fromisoformat(due)
        except ValueError:
            continue
        stamp = d.strftime("%Y%m%d")
        end = (d + timedelta(days=1)).strftime("%Y%m%d")
        done = a.get("status") == "done"
        title = ("✓ " if done else "") + (a.get("title") or "Homework")
        desc = a.get("instructions") or ""
        lines += [
            "BEGIN:VEVENT",
            _fold(f"UID:hw-{a.get('id')}-{user.get('id')}@prepwithtee"),
            f"DTSTAMP:{now}",
            f"DTSTART;VALUE=DATE:{stamp}",
            f"DTEND;VALUE=DATE:{end}",
            _fold(f"SUMMARY:{_ics_escape(title)}"),
            _fold(f"DESCRIPTION:{_ics_escape(desc)}"),
            _fold(f"URL:{APP_BASE_URL}/homework.html"),
            f"STATUS:{'COMPLETED' if done else 'CONFIRMED'}",
        ]
        if not done:
            lines += [
                "BEGIN:VALARM", "ACTION:DISPLAY",
                _fold(f"DESCRIPTION:{_ics_escape('Homework due: ' + (a.get('title') or ''))}"),
                "TRIGGER:-PT15H",       # ~6pm the evening before a midnight due date
                "END:VALARM",
            ]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
