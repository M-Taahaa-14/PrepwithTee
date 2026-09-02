"""Daily email lifecycle cron runner.

Runs at 07:45 PKT (02:45 UTC) via /etc/cron.d/prepwithtee.

Sequences handled here (all use the `email_log` table to avoid duplicates):

  Onboarding  W1 Welcome          — day users sign up
              W2 Your First Step  — 1 day after signup
              W3 Meet the AI      — 3 days after signup

  Re-engage   R1 We Miss You      — 3 days inactive
              R2 Still Procras?   — 7 days inactive
              R3 One Last Nudge   — 14 days inactive

  Weekly      F1 Study Tip        — every Sunday (once per week per user)

Milestone emails (M1/M2/M3) are triggered inline from route handlers,
not from this cron, because they depend on a specific user action.

Execution:
    .venv/Scripts/python -m website.scripts.email_lifecycle
"""

import sys
from datetime import datetime, timedelta, timezone, date as _date

from .. import users_db as _udb
from ..app import _notify, _public_base, _esc

APP_URL = _public_base()
_UNSUB_MAILTO = "mailto:nexgentutors6@gmail.com?subject=Unsubscribe%20from%20PrepWithTee%20emails"


# ── Email log ─────────────────────────────────────────────────────────────────

def _recent_sends(days: int = 60) -> set[tuple[str, str]]:
    """Return set of (user_id, template_id) sent within the last `days` days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    if _udb._USE_SUPABASE:
        res = (_udb._client().table("email_log")
               .select("user_id,template_id")
               .gte("sent_at", cutoff)
               .execute())
        return {(r["user_id"], r["template_id"]) for r in (res.data or [])}
    with _udb._local() as c:
        rows = c.execute(
            "SELECT user_id, template_id FROM email_log WHERE sent_at >= ?",
            (cutoff,)
        ).fetchall()
        return {(r[0], r[1]) for r in rows}


def _log_sent(user_id: str, template_id: str):
    """Record a sent email so we never send the same sequence twice."""
    now = datetime.now(timezone.utc).isoformat()
    if _udb._USE_SUPABASE:
        _udb._client().table("email_log").insert(
            {"user_id": user_id, "template_id": template_id, "sent_at": now}
        ).execute()
    else:
        with _udb._local() as c:
            c.execute(
                "INSERT INTO email_log (user_id, template_id, sent_at) VALUES (?, ?, ?)",
                (user_id, template_id, now)
            )
            c.commit()


def _already_sent(sent_set: set, user_id: str, template_id: str) -> bool:
    return (user_id, template_id) in sent_set


# ── Last-active lookup ────────────────────────────────────────────────────────

def _last_active_map() -> dict[str, _date]:
    """Per-user last date they actually used the site (from daily_time_spent).

    Falls back to the profile's updated_at date for users with no time-spent
    rows (new signups who haven't triggered the timer yet).
    """
    result: dict[str, _date] = {}
    if _udb._USE_SUPABASE:
        res = (_udb._client().table("daily_time_spent")
               .select("user_id,date")
               .execute())
        for r in (res.data or []):
            uid = r["user_id"]
            try:
                d = _date.fromisoformat(r["date"])
                if uid not in result or d > result[uid]:
                    result[uid] = d
            except (ValueError, TypeError):
                pass
    else:
        with _udb._local() as c:
            for row in c.execute(
                "SELECT user_id, MAX(date) FROM daily_time_spent GROUP BY user_id"
            ):
                try:
                    result[row[0]] = _date.fromisoformat(row[1])
                except (ValueError, TypeError):
                    pass
    return result


# ── HTML email builder ────────────────────────────────────────────────────────

def _letter_html(body_html: str, cta_label: str, cta_url: str) -> str:
    """Render a personal letter-style HTML email in PrepWithTee brand colours."""
    cta_block = f"""
    <p style="margin:28px 0 0;text-align:center">
      <a href="{_esc(cta_url)}"
         style="display:inline-block;background:#E8913A;color:#fff;
                text-decoration:none;font-weight:700;font-size:.9rem;
                padding:12px 28px;border-radius:10px;letter-spacing:.01em">
        {_esc(cta_label)}
      </a>
    </p>""" if cta_label else ""

    return f"""<!DOCTYPE html>
<html lang="en"><body style="margin:0;padding:0;background:#f4f0ea;
      font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Georgia,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td style="padding:32px 16px">
<table width="100%" cellpadding="0" cellspacing="0"
       style="max-width:500px;margin:0 auto">

  <tr><td style="background:#2E1B4A;border-radius:12px 12px 0 0;
                 padding:16px 28px 14px">
    <p style="color:#C9BDF0;font-size:.72rem;margin:0;
              letter-spacing:.07em;text-transform:uppercase">PrepWithTee</p>
  </td></tr>

  <tr><td style="background:#fff;padding:28px 32px 32px;
                 border-radius:0 0 12px 12px;
                 box-shadow:0 2px 16px rgba(0,0,0,.08)">
    <div style="font-size:.92rem;color:#1a1a2e;line-height:1.75">
      {body_html}
    </div>
    {cta_block}
  </td></tr>

  <tr><td style="padding:18px 0 8px;text-align:center;
                 color:#bbb;font-size:.72rem;line-height:1.6">
    PrepWithTee &nbsp;&middot;&nbsp; Lahore, Pakistan<br>
    You're getting this because you signed up at prepwithtee.com.<br>
    <a href="{_esc(_UNSUB_MAILTO)}"
       style="color:#bbb;text-decoration:underline">Unsubscribe</a>
  </td></tr>

</table></td></tr></table>
</body></html>"""


# ── Email templates ───────────────────────────────────────────────────────────

def _send(user: dict, template_id: str, subject: str,
          body_plain: str, body_html: str,
          cta_label: str = "", cta_url: str = "") -> bool:
    email = (user.get("email") or "").strip()
    if not email:
        return False
    html = _letter_html(body_html, cta_label, cta_url)
    ok = _notify(subject, body_plain, to=email, html_override=html)
    if ok:
        _log_sent(user["id"], template_id)
    return ok


def _p(text: str) -> str:
    return f'<p style="margin:0 0 14px">{text}</p>'


def send_W1(user: dict) -> bool:
    """Welcome — sent day of signup."""
    first = (user.get("name") or "there").split()[0]
    lib = f"{APP_URL}/library.html"
    return _send(
        user, "W1",
        subject="You're in. Let's make sure every mark counts.",
        body_plain=(
            f"Hi {first},\n\n"
            "Welcome to PrepWithTee.\n\n"
            "Every question in this library is a real Cambridge exam question, "
            "sorted by topic, with the mark scheme right next to it. "
            "No hunting through PDFs.\n\n"
            "Pick your subject → pick a topic → download a question set. "
            "It takes 30 seconds.\n\n"
            f"See you inside: {lib}\n\n"
            "— Tee"
        ),
        body_html=(
            _p(f"Hi {_esc(first)},")
            + _p("Welcome to PrepWithTee.")
            + _p(
                "Every question in this library is a real Cambridge exam question, "
                "sorted by topic, with the mark scheme right next to it. "
                "No hunting through PDFs, no guessing which papers to use."
            )
            + _p("<strong>Pick your subject &rarr; pick a topic &rarr; "
                 "download a question set.</strong> It takes 30 seconds.")
            + _p("The first time you sit with a topical booklet and work through "
                 "it question by question, you'll feel the difference.")
            + _p("See you inside,<br><strong>Tee</strong>")
            + f'<p style="margin:18px 0 0;font-size:.82rem;color:#777">'
              f'P.S. If you\'re not sure where to start, just reply to this email '
              f'and tell me which subject is giving you trouble. I read every reply.</p>'
        ),
        cta_label="Open the Library",
        cta_url=lib,
    )


def send_W2(user: dict) -> bool:
    """Your First Step — 1 day after signup."""
    first = (user.get("name") or "there").split()[0]
    lib = f"{APP_URL}/library.html"
    return _send(
        user, "W2",
        subject="The single best thing you can do today (takes 10 minutes)",
        body_plain=(
            f"Hi {first},\n\n"
            "Most students revise by reading their notes.\n\n"
            "The problem? Reading feels like progress but it isn't. "
            "Your brain needs to retrieve information under pressure — "
            "that's what the exam actually tests.\n\n"
            "The fix: practice questions, by topic, from day one.\n\n"
            "Choose one topic you covered this week. Open the Library, "
            "filter by that topic, and download the question set. "
            "Work through it with a pen and paper, then check the mark scheme.\n\n"
            "Ten minutes of active recall beats an hour of passive reading every time.\n\n"
            f"Go try it: {lib}\n\n"
            "— Tee"
        ),
        body_html=(
            _p(f"Hi {_esc(first)},")
            + _p("Most students revise by reading their notes.")
            + _p(
                "The problem? Reading <em>feels</em> like progress but it isn't. "
                "Your brain needs to <em>retrieve</em> information under pressure "
                "&mdash; that's what the exam actually tests."
            )
            + _p("The fix is simple: <strong>practice questions, by topic, from day one.</strong>")
            + _p(
                "Choose one topic you covered this week. Open the Library, "
                "filter by that topic, and download the question set. "
                "Work through it with a pen and paper, then check the mark scheme."
            )
            + _p("Ten minutes of active recall beats an hour of passive reading every time.")
            + _p("— <strong>Tee</strong>")
        ),
        cta_label="Open the Library",
        cta_url=lib,
    )


def send_W3(user: dict) -> bool:
    """Meet the AI Tutor — 3 days after signup."""
    first = (user.get("name") or "there").split()[0]
    ask = f"{APP_URL}/ask.html"
    return _send(
        user, "W3",
        subject="Stuck on a question at midnight? There's someone here.",
        body_plain=(
            f"Hi {first},\n\n"
            "Ever been working through a past paper at 11 PM and hit a question "
            "you just can't crack — with no one to ask?\n\n"
            "That's exactly why we built the AI Tutor.\n\n"
            "It knows the Cambridge syllabus inside out. Ask it to explain a concept, "
            "walk you through a worked example, or tell you why your answer missed the marks. "
            "It won't just give you the answer — it'll help you understand it.\n\n"
            f"Click 'Ask AI' and give it a go: {ask}\n\n"
            "— Tee"
        ),
        body_html=(
            _p(f"Hi {_esc(first)},")
            + _p(
                "Ever been working through a past paper at 11&nbsp;PM and hit a question "
                "you just can't crack &mdash; with no one to ask?"
            )
            + _p("That's exactly why we built the <strong>AI Tutor</strong>.")
            + _p(
                "It's not a search engine. It knows the Cambridge syllabus inside out. "
                "Ask it to explain a concept, walk you through a worked example, "
                "or tell you why your answer missed the marks. "
                "It won't just give you the answer &mdash; it'll help you "
                "<em>understand</em> it."
            )
            + _p('Click <strong>Ask AI</strong> on any question page and give it a go.')
            + _p("— <strong>Tee</strong>")
        ),
        cta_label="Try the AI Tutor",
        cta_url=ask,
    )


def send_R1(user: dict) -> bool:
    """We Miss You — 3 days inactive."""
    first = (user.get("name") or "there").split()[0]
    lib = f"{APP_URL}/library.html"
    return _send(
        user, "R1",
        subject="Everything okay?",
        body_plain=(
            f"Hi {first},\n\n"
            "I noticed you haven't been on in a few days. That's completely fine — life gets busy.\n\n"
            "But I also know how easy it is for revision to quietly slip off the list. "
            "Before you know it, three days turns into three weeks.\n\n"
            "You don't need a big session today. Just open one topic set, "
            "do three questions, check the mark schemes. Literally ten minutes.\n\n"
            "Small consistent sessions beat a panic cram every single time.\n\n"
            f"Come back when you're ready: {lib}\n\n"
            "— Tee"
        ),
        body_html=(
            _p(f"Hi {_esc(first)},")
            + _p(
                "I noticed you haven't been on in a few days. "
                "That's completely fine &mdash; life gets busy."
            )
            + _p(
                "But I also know how easy it is for revision to quietly slip off the list. "
                "Before you know it, three days turns into three weeks."
            )
            + _p(
                "You don't need a big session today. Just open one topic set, "
                "do three questions, check the mark schemes. Literally ten minutes."
            )
            + _p(
                "Small consistent sessions beat a panic cram every single time &mdash; "
                "and you already have everything you need, right here."
            )
            + _p("Come back when you're ready.")
            + _p("&mdash; <strong>Tee</strong>")
        ),
        cta_label="Continue where you left off",
        cta_url=lib,
    )


def send_R2(user: dict) -> bool:
    """Still Procrastinating? — 7 days inactive."""
    first = (user.get("name") or "there").split()[0]
    lib = f"{APP_URL}/library.html"
    return _send(
        user, "R2",
        subject="I'll be honest with you.",
        body_plain=(
            f"Hi {first},\n\n"
            "A week away from revision. I get it — sometimes the hardest part is just starting again.\n\n"
            "Here's what works for students who get stuck: don't try to 'catch up'. "
            "Forget the time you've missed. Just open one topic set — any topic — "
            "and do the first question. That's the only goal.\n\n"
            "You'll feel the gears start turning. Then do the second question. "
            "Then check your answers against the mark scheme.\n\n"
            "By the time you've done five questions you'll have forgotten you were even putting it off.\n\n"
            f"The library is right where you left it: {lib}\n\n"
            "— Tee\n\n"
            "P.S. If something specific is blocking you — a topic you don't understand, "
            "a question type that keeps tripping you up — reply to this email. I mean that."
        ),
        body_html=(
            _p(f"Hi {_esc(first)},")
            + _p(
                "A week away from revision. I get it &mdash; "
                "sometimes the hardest part is just starting again."
            )
            + _p(
                "Here's what works for students who get stuck: "
                "<strong>don't try to &ldquo;catch up&rdquo;</strong>. "
                "Forget the time you've missed. Just open one topic set &mdash; "
                "any topic &mdash; and do the first question. That's the only goal."
            )
            + _p(
                "You'll feel the gears start turning. Then do the second question. "
                "Then check your answers against the mark scheme."
            )
            + _p(
                "By the time you've done five questions you'll have forgotten "
                "you were even putting it off."
            )
            + _p("The library is right where you left it.")
            + _p("&mdash; <strong>Tee</strong>")
            + f'<p style="margin:18px 0 0;font-size:.82rem;color:#777">'
              f'P.S. If something specific is blocking you &mdash; a topic you don\'t '
              f'understand, a question type that keeps tripping you up &mdash; just '
              f'reply to this email. I mean that.</p>'
        ),
        cta_label="Pick up where you left off",
        cta_url=lib,
    )


def send_R3(user: dict) -> bool:
    """One Last Nudge — 14 days inactive."""
    first = (user.get("name") or "there").split()[0]
    lib = f"{APP_URL}/library.html"
    return _send(
        user, "R3",
        subject="One thing before I leave you alone",
        body_plain=(
            f"Hi {first},\n\n"
            "I'm not going to keep sending you emails you're not finding useful. "
            "This one's the last one for a while.\n\n"
            "But before I go quiet, I want to leave you with this:\n\n"
            "Cambridge O-Level and IGCSE exams reward students who have seen lots of "
            "questions on a topic, not students who memorised a textbook. "
            "Every session on PrepWithTee builds that pattern recognition — "
            "the kind that gets you from a C to a B, or a B to an A.\n\n"
            "When you're ready to come back — whether that's tomorrow or in a month — "
            "everything will be here waiting.\n\n"
            f"{lib}\n\n"
            "Rooting for you,\n"
            "Tee"
        ),
        body_html=(
            _p(f"Hi {_esc(first)},")
            + _p(
                "I'm not going to keep sending you emails you're not finding useful. "
                "This one's the last one for a while."
            )
            + _p(
                "But before I go quiet, I want to leave you with this:"
            )
            + _p(
                "Cambridge O-Level and IGCSE exams reward students who have "
                "<em>seen lots of questions</em> on a topic, not students who "
                "memorised a textbook. Every session on PrepWithTee builds that "
                "pattern recognition &mdash; the kind that gets you from a C to a B, "
                "or a B to an A."
            )
            + _p(
                "When you're ready to come back &mdash; whether that's tomorrow "
                "or in a month &mdash; everything will be here waiting."
            )
            + _p("Rooting for you,<br><strong>Tee</strong>")
        ),
        cta_label="I'm ready — take me back",
        cta_url=lib,
    )


def send_F1(user: dict) -> bool:
    """Weekly Study Tip — every Sunday."""
    first = (user.get("name") or "there").split()[0]
    lib = f"{APP_URL}/library.html"
    return _send(
        user, "F1",
        subject="One thing worth trying this week",
        body_plain=(
            f"Hi {first},\n\n"
            "Quick one this week.\n\n"
            "Try 'mark scheme first' on one question.\n\n"
            "Pick a question you're unsure about. Before you attempt it, "
            "read the mark scheme. See exactly what Cambridge is looking for. "
            "Then close the mark scheme, answer the question, and compare.\n\n"
            "Most students treat mark schemes as answer keys. They're not — "
            "they're blueprints for how to think about the question. "
            "Reading them before answering teaches you the examiner's logic, "
            "which is half of what the exam actually tests.\n\n"
            "Give it a go this week.\n\n"
            f"{lib}\n\n"
            "Have a good week,\n"
            "Tee"
        ),
        body_html=(
            _p(f"Hi {_esc(first)},")
            + _p("Quick one this week.")
            + _p("<strong>Try &ldquo;mark scheme first&rdquo; on one question.</strong>")
            + _p(
                "Pick a question you're unsure about. Before you attempt it, "
                "read the mark scheme. See exactly what Cambridge is looking for. "
                "Then close the mark scheme, answer the question, and compare."
            )
            + _p(
                "Most students treat mark schemes as answer keys. They're not &mdash; "
                "they're blueprints for how to think about the question. "
                "Reading them <em>before</em> answering teaches you the examiner's logic, "
                "which is half of what the exam actually tests."
            )
            + _p("Give it a go this week in whatever topic you're revising.")
            + _p("Have a good week,<br><strong>Tee</strong>")
        ),
        cta_label="Open the Library",
        cta_url=lib,
    )


# ── Helpers you can call from route handlers for milestone emails ─────────────

def send_M1(user: dict, notify_fn) -> bool:
    """First topic completed. Call from the route handler; pass app._notify."""
    first = (user.get("name") or "there").split()[0]
    lib = f"{APP_URL}/library.html"
    body_html = (
        _p(f"Hi {_esc(first)},")
        + _p(
            "You just worked through a complete topic set. That might not sound like much, "
            "but it's more than most students do in a month."
        )
        + _p(
            "You've seen how the questions are structured, where the marks sit, "
            "what the mark scheme expects. That knowledge compounds &mdash; "
            "every topic you do next will feel a little faster, a little more familiar."
        )
        + _p(
            "What's next? Pick the topic you're <em>least</em> comfortable with. "
            "That's where the marks are hiding."
        )
        + _p("Keep going,<br><strong>Tee</strong>")
    )
    html = _letter_html(body_html, "Open the Library", lib)
    ok = notify_fn(
        "You just finished your first topic set ✓",
        f"Hi {first},\n\nYou just worked through a complete topic set.\n\n"
        "What's next? Pick the topic you're least comfortable with. "
        "That's where the marks are hiding.\n\n— Tee",
        to=(user.get("email") or "").strip(),
        html_override=html,
    )
    if ok:
        _log_sent(user["id"], "M1")
    return ok


def send_M2(user: dict, notify_fn) -> bool:
    """First mock test generated."""
    first = (user.get("name") or "there").split()[0]
    body_html = (
        _p(f"Hi {_esc(first)},")
        + _p("You've just generated your first mock test. Good move.")
        + _p(
            "A few tips to get the most out of it:"
        )
        + _p(
            "Find a quiet 45 minutes. Put your phone in another room. "
            "Work through it like it's the real thing &mdash; no peeking at the "
            "mark scheme until you're done."
        )
        + _p(
            "When you check your answers, don't just mark right&nbsp;/&nbsp;wrong. "
            "For every question you got wrong, read the mark scheme carefully and ask: "
            "<em>exactly where did my answer miss the mark?</em> "
            "That gap is your revision target."
        )
        + _p("Repeat the same test in a week. You'll be surprised how much sticks.")
        + _p("&mdash; <strong>Tee</strong>")
    )
    html = _letter_html(body_html, "", "")
    ok = notify_fn(
        "Your mock test is ready — here's how to use it.",
        f"Hi {first},\n\nYou've just generated your first mock test.\n\n"
        "Sit it timed, no mark scheme. Then review every wrong answer carefully.\n\n"
        "Repeat in a week. You'll be surprised how much sticks.\n\n— Tee",
        to=(user.get("email") or "").strip(),
        html_override=html,
    )
    if ok:
        _log_sent(user["id"], "M2")
    return ok


# ── Main loop ─────────────────────────────────────────────────────────────────

def _get_students() -> list[dict]:
    if _udb._USE_SUPABASE:
        res = (_udb._client().table("profiles")
               .select("*")
               .eq("role", "student")
               .execute())
        return res.data or []
    with _udb._local() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM profiles WHERE role = 'student' OR role IS NULL"
        )]


def _parse_date(s: str | None) -> _date | None:
    if not s:
        return None
    try:
        return _date.fromisoformat(s.replace("Z", "").split("T")[0])
    except (ValueError, TypeError):
        return None


def main() -> int:
    print("[email_lifecycle] Starting...", flush=True)
    today = _date.today()
    is_sunday = today.weekday() == 6

    users = _get_students()
    print(f"[email_lifecycle] {len(users)} student profiles loaded.", flush=True)

    # Fetch all email_log rows from the last 60 days once — avoids N queries.
    sent_60d = _recent_sends(days=60)
    # Separate 7-day window for weekly tip dedup.
    sent_7d = _recent_sends(days=7)

    last_active = _last_active_map()

    w1 = w2 = w3 = r1 = r2 = r3 = f1 = 0

    for u in users:
        uid = u.get("id", "")
        created = _parse_date(u.get("created_at"))
        if created is None:
            continue

        age_days = (today - created).days

        # best estimate of last activity — daily_time_spent first, else profile updated_at
        active_date = last_active.get(uid) or _parse_date(u.get("updated_at")) or created
        inactive_days = (today - active_date).days

        # ── Onboarding sequence ───────────────────────────────────────────────
        # W1 — sent same day as signup (age 0 or 1 to catch yesterday's signups if
        #       the cron missed them, but not older).
        if age_days <= 1 and not _already_sent(sent_60d, uid, "W1"):
            if send_W1(u):
                w1 += 1
                sent_60d.add((uid, "W1"))

        # W2 — 1 day after signup
        elif age_days == 1 and not _already_sent(sent_60d, uid, "W2"):
            if send_W2(u):
                w2 += 1
                sent_60d.add((uid, "W2"))

        # W3 — 3 days after signup
        elif age_days == 3 and not _already_sent(sent_60d, uid, "W3"):
            if send_W3(u):
                w3 += 1
                sent_60d.add((uid, "W3"))

        # ── Re-engagement sequence ────────────────────────────────────────────
        # Only trigger if the onboarding sequence is done (user is > 3 days old).
        if age_days > 3:
            if inactive_days == 3 and not _already_sent(sent_60d, uid, "R1"):
                if send_R1(u):
                    r1 += 1
                    sent_60d.add((uid, "R1"))

            elif inactive_days == 7 and not _already_sent(sent_60d, uid, "R2"):
                if send_R2(u):
                    r2 += 1
                    sent_60d.add((uid, "R2"))

            elif inactive_days == 14 and not _already_sent(sent_60d, uid, "R3"):
                if send_R3(u):
                    r3 += 1
                    sent_60d.add((uid, "R3"))

        # ── Weekly tip (Sundays only) ─────────────────────────────────────────
        if is_sunday and not _already_sent(sent_7d, uid, "F1"):
            if send_F1(u):
                f1 += 1
                sent_7d.add((uid, "F1"))

    print(
        f"[email_lifecycle] Done. "
        f"W1={w1} W2={w2} W3={w3} | R1={r1} R2={r2} R3={r3} | F1={f1}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
