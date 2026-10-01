"""Plans, prices and payment-proof checks - one source of truth for the server.

The pricing page shows these same numbers (static/pricing.html PERIODS); a
test compares the two so they cannot drift.

What is automatic and what is not (tutor, 2026-10-01):
  automatic  - the expected amount for the plan + period, the new expiry
               (extends from the current expiry, never cuts paid days short),
               duplicate transaction ids / screenshots, amount mismatches,
               emails to the student, expiry reminders (scripts/email_lifecycle.py)
  manual     - confirming the money actually arrived in JazzCash / EasyPaisa /
               the bank, and judging a screenshot that looks edited. Approval
               requires the admin to tick "I've seen the money".
"""

from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = ROOT / "data" / "uploads"

PERIODS: dict[str, dict] = {
    "monthly": {"label": "Monthly", "days": 30,
                "amount": {"solo": 1000, "three": 2000, "all": 3000}},
    "octnov":  {"label": "Oct/Nov 2026 session", "until": "2026-11-30",
                "amount": {"solo": 3000, "three": 6000, "all": 9000}},
    "mayjun":  {"label": "May/June 2027 session", "until": "2027-06-15",
                "amount": {"solo": 8000, "three": 15000, "all": 22000}},
    "yearly":  {"label": "Yearly", "days": 365,
                "amount": {"solo": 9600, "three": 19200, "all": 28800}},
}
PLAN_LABELS = {"free": "Free", "solo": "Solo", "three": "3 Subjects", "all": "All Subjects",
               "tutoring": "1-on-1 Tutoring"}


def expected_amount(plan: str, period: str | None) -> int | None:
    p = PERIODS.get(period or "monthly")
    return p["amount"].get(plan) if p else None


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def new_expiry(period: str | None, current_expiry: str | None, current_plan: str | None,
               now: datetime | None = None) -> datetime:
    """When the plan bought with this period ends.

    Monthly / yearly add their days to whichever is later: today, or the
    current (still running, paid) expiry - renewing early never loses days.
    A session package runs to its fixed date, unless the student already has
    paid time beyond it.
    """
    now = now or datetime.now(timezone.utc)
    p = PERIODS.get(period or "monthly") or PERIODS["monthly"]
    cur = _parse(current_expiry) if (current_plan or "free") != "free" else None
    start = max(now, cur) if cur else now
    if "days" in p:
        return start + timedelta(days=p["days"])
    end = datetime.fromisoformat(p["until"]).replace(hour=23, minute=59, tzinfo=timezone.utc)
    return max(end, cur) if cur else end


def _digits(s: str | None) -> str:
    return re.sub(r"\W", "", s or "").lower()


def screenshot_path(url: str | None) -> Path | None:
    """/uploads/payments/<name> -> the file on disk (never outside the uploads dir)."""
    if not url or not url.startswith("/uploads/"):
        return None
    p = (UPLOADS / url[len("/uploads/"):]).resolve()
    try:
        p.relative_to(UPLOADS.resolve())
    except ValueError:
        return None
    return p if p.is_file() else None


def file_hash(url: str | None) -> str | None:
    p = screenshot_path(url)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p else None


def checks(proof: dict, others: list[dict]) -> list[dict]:
    """Automatic checks for one proof. Each: {code, ok, text}. `others` = every other proof."""
    out = []
    exp = expected_amount(proof.get("plan"), proof.get("period"))
    amt = proof.get("amount_pkr")
    if exp is None:
        out.append({"code": "amount", "ok": False, "text": "Unknown plan or period - check the amount by hand"})
    elif amt is None:
        out.append({"code": "amount", "ok": False, "text": f"No amount entered; expected PKR {exp:,}"})
    elif amt != exp:
        out.append({"code": "amount", "ok": False,
                    "text": f"Amount PKR {amt:,} does not match PKR {exp:,} for this plan and period"})
    else:
        out.append({"code": "amount", "ok": True, "text": f"Amount matches the plan (PKR {exp:,})"})

    tid = _digits(proof.get("transaction_id"))
    if not tid:
        out.append({"code": "tid", "ok": False, "text": "No transaction id given"})
    else:
        dup = [o for o in others if _digits(o.get("transaction_id")) == tid]
        out.append({"code": "tid", "ok": not dup,
                    "text": (f"Transaction id already used on proof #{dup[0]['id']} ({dup[0].get('status')})"
                             if dup else "Transaction id not used before")})

    h = proof.get("screenshot_sha256")
    if not proof.get("screenshot_url"):
        out.append({"code": "shot", "ok": False, "text": "No screenshot attached"})
    elif h:
        dup = [o for o in others if o.get("screenshot_sha256") == h]
        out.append({"code": "shot", "ok": not dup,
                    "text": (f"Same screenshot as proof #{dup[0]['id']}" if dup
                             else "Screenshot not seen before")})

    from access import PLAN_SUBJECT_LIMITS
    need = PLAN_SUBJECT_LIMITS.get(proof.get("plan") or "")
    if need:
        subs = proof.get("subjects") or []
        out.append({"code": "subjects", "ok": len(subs) == need,
                    "text": (f"Subjects chosen: {', '.join(subs)}" if len(subs) == need
                             else f"Plan needs {need} subject(s) - choose them when approving")})
    return out


# ── emails to the student ────────────────────────────────────────────────────

SITE = "https://prepwithtee.com"


def _p(text: str) -> str:
    return f'<p style="margin:0 0 14px">{text}</p>'


def _fmt(d: datetime | str | None) -> str:
    if isinstance(d, str):
        d = _parse(d)
    return f"{d.day} {d:%B %Y}" if d else ""


def approved_email(name: str | None, plan: str, period: str | None, expires: datetime,
                   subjects: list[str] | None, note: str | None) -> tuple[str, str, str]:
    from admin import _mail_html
    first = html.escape((name or "there").split()[0])
    what = PLAN_LABELS.get(plan, plan)
    subj_line = f" for {html.escape(', '.join(subjects))}" if subjects else ""
    body = (_p(f"Hi {first},")
            + _p(f"Your payment is confirmed and your <strong>{what}</strong> plan{subj_line} "
                 f"is active until <strong>{_fmt(expires)}</strong>.")
            + (_p(html.escape(note)) if note else "")
            + _p("Thank you - and good luck with your preparation.<br><strong>Tee</strong>"))
    subject = f"Payment confirmed - {what} is active"
    text = (f"Hi {(name or 'there').split()[0]},\n\nYour payment is confirmed: {what}{', '.join(subjects or [])} "
            f"is active until {_fmt(expires)}.\n\n{note or ''}\n\nTee - PrepWithTee")
    return subject, text, _mail_html(body, "Open your dashboard", f"{SITE}/dashboard.html")


def rejected_email(name: str | None, plan: str, reason: str) -> tuple[str, str, str]:
    from admin import _mail_html
    first = html.escape((name or "there").split()[0])
    what = PLAN_LABELS.get(plan, plan)
    body = (_p(f"Hi {first},")
            + _p(f"We couldn't confirm your payment for the <strong>{what}</strong> plan.")
            + _p(f"<strong>Reason:</strong> {html.escape(reason)}")
            + _p("If you think this is a mistake, reply to this email or message us on WhatsApp "
                 "with your transaction id and we'll sort it out.<br><strong>Tee</strong>"))
    return (f"About your {what} payment", f"We couldn't confirm your {what} payment: {reason}",
            _mail_html(body, "Pricing and payment details", f"{SITE}/pricing.html"))


def reminder_email(name: str | None, plan: str, expires: str, days_left: int) -> tuple[str, str, str]:
    from admin import _mail_html
    first = html.escape((name or "there").split()[0])
    what = PLAN_LABELS.get(plan, plan)
    if days_left <= 0:
        lead = f"Your <strong>{what}</strong> plan ended on {_fmt(expires)}, so your account is back on the free plan."
        subject = f"Your {what} plan has ended"
    else:
        lead = (f"Your <strong>{what}</strong> plan ends on <strong>{_fmt(expires)}</strong> "
                f"({days_left} day{'s' if days_left != 1 else ''} left).")
        subject = f"Your {what} plan ends in {days_left} day{'s' if days_left != 1 else ''}"
    body = (_p(f"Hi {first},") + _p(lead)
            + _p("Renew from the pricing page to keep unlimited booklets, mock tests and AI help. "
                 "Renewing early never loses days - the new period starts when the current one ends.")
            + _p("<strong>Tee</strong>"))
    return subject, f"{subject}. Renew at {SITE}/pricing.html", _mail_html(body, "Renew my plan", f"{SITE}/pricing.html")


# ── expiry reminders (run daily by scripts/email_lifecycle.py) ───────────────

REMINDER_STEPS = ((7, "EXP7"), (3, "EXP3"), (1, "EXP1"))


def reminder_due(user: dict, now: datetime, already: set[str]) -> tuple[str, int] | None:
    """(template_id, days_left) to send today, or None.

    Ids carry the expiry date ("EXP3:2026-10-21"), so a renewed plan gets its
    own reminders and a missed cron day still sends the next step once.
    Expired plans get one "EXPIRED" email within 3 days of ending.
    """
    if (user.get("plan") or "free") == "free":
        return None
    exp = _parse(user.get("plan_expires_at"))
    if not exp:
        return None
    left = (exp - now).total_seconds() / 86400
    tag = exp.date().isoformat()
    if left <= 0:
        tid = f"EXPIRED:{tag}"
        return (tid, 0) if -3 <= left and tid not in already else None
    if left > REMINDER_STEPS[0][0]:
        return None
    due = next(code for days, code in reversed(REMINDER_STEPS) if left <= days)
    tid = f"{due}:{tag}"
    return (tid, max(1, int(left + 0.999))) if tid not in already else None
