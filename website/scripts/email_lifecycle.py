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
from ..app import _notify, _esc
from ..reminders import _public_base

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

_LOGO_URL  = "https://prepwithtee.com/logo.png"
_SITE_URL  = "https://prepwithtee.com"

def _letter_html(body_html: str, cta_label: str, cta_url: str) -> str:
    """Branded letter-style HTML email: logo header, gold rule, white card, footer."""

    cta_block = f"""
    <table width="100%" cellpadding="0" cellspacing="0" role="presentation"
           style="margin-top:28px">
      <tr><td style="text-align:center">
        <a href="{_esc(cta_url)}"
           style="display:inline-block;background:#E8913A;color:#ffffff;
                  text-decoration:none;font-family:-apple-system,BlinkMacSystemFont,
                  'Segoe UI',Arial,sans-serif;font-weight:700;font-size:.9rem;
                  padding:13px 32px;border-radius:8px;letter-spacing:.02em;
                  mso-padding-alt:13px 32px">
          {_esc(cta_label)} &rarr;
        </a>
      </td></tr>
    </table>""" if cta_label else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="light">
  <meta name="supported-color-schemes" content="light">
</head>
<body style="margin:0;padding:0;background:#edeae5;
      font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;
      -webkit-text-size-adjust:100%;mso-line-height-rule:exactly">

<table width="100%" cellpadding="0" cellspacing="0" role="presentation">
<tr><td style="padding:32px 16px 48px">

  <!-- CARD WRAPPER ─────────────────────────────────────────── -->
  <table width="100%" cellpadding="0" cellspacing="0" role="presentation"
         style="max-width:520px;margin:0 auto">

    <!-- ① HEADER: logo on dark-purple -->
    <tr><td style="background:#2E1B4A;border-radius:16px 16px 0 0;
                   padding:28px 32px 22px;text-align:center">
      <a href="{_SITE_URL}" style="text-decoration:none;display:block">
        <img src="{_LOGO_URL}" alt="PrepWithTee" width="72" height="72"
             style="display:block;margin:0 auto 12px;border-radius:50%;
                    border:3px solid rgba(201,168,76,.45)">
        <p style="margin:0;color:#ffffff;font-size:1.05rem;font-weight:700;
                  letter-spacing:.01em">PrepWithTee</p>
        <p style="margin:4px 0 0;color:#C9BDF0;font-size:.72rem;
                  letter-spacing:.09em;text-transform:uppercase">
          Cambridge Exam Prep
        </p>
      </a>
    </td></tr>

    <!-- ② GOLD RULE -->
    <tr><td style="background:#C9A84C;height:3px;font-size:1px;line-height:1px">&nbsp;</td></tr>

    <!-- ③ BODY: white card -->
    <tr><td style="background:#ffffff;padding:34px 38px 38px;
                   border-radius:0 0 16px 16px;
                   box-shadow:0 6px 32px rgba(46,27,74,.12)">

      <!-- message text -->
      <div style="font-size:.93rem;color:#1e1b30;line-height:1.85;
                  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif">
        {body_html}
      </div>

      <!-- divider before CTA -->
      {f'<div style="border-top:1px solid #f0ece6;margin:26px 0 0"></div>' if cta_label else ''}

      {cta_block}
    </td></tr>

    <!-- ④ FOOTER -->
    <tr><td style="padding:22px 0 4px;text-align:center">
      <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
        <tr><td style="text-align:center;padding-bottom:10px">
          <img src="{_LOGO_URL}" alt="" width="28" height="28"
               style="display:inline-block;border-radius:50%;opacity:.4;
                      vertical-align:middle">
        </td></tr>
        <tr><td style="font-size:.7rem;color:#aaa;line-height:1.7;
                       font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;
                       text-align:center">
          <strong style="color:#888">PrepWithTee</strong>
          &nbsp;&middot;&nbsp; Lahore, Pakistan<br>
          You're getting this because you signed up at
          <a href="{_SITE_URL}" style="color:#aaa;text-decoration:none">prepwithtee.com</a>.<br>
          Questions or need tutoring?
          <a href="https://wa.me/923204884375"
             style="color:#aaa;text-decoration:underline">WhatsApp us</a><br>
          <a href="{_esc(_UNSUB_MAILTO)}"
             style="color:#aaa;text-decoration:underline">Unsubscribe</a>
        </td></tr>
      </table>
    </td></tr>

  </table>
  <!-- /CARD WRAPPER -->

</td></tr>
</table>
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
    lib = f"{APP_URL}/yearly"
    return _send(
        user, "W1",
        subject="You're in, {first} — here's your first move.".format(first=first),
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
    lib = f"{APP_URL}/yearly"
    return _send(
        user, "W2",
        subject="The revision habit that actually works (10 min today)",
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
        subject="Stuck at midnight on a question? This helps.",
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
    lib = f"{APP_URL}/yearly"
    return _send(
        user, "R1",
        subject="{first}, is everything okay?".format(first=first),
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
    lib = f"{APP_URL}/yearly"
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
    lib = f"{APP_URL}/yearly"
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


# ── Weekly tip bank ──────────────────────────────────────────────────────────
# Cycles by ISO week number. Add more tips freely — the modulo keeps it working.
# Each entry: (subject, plain_intro, html_tip_paragraph, plain_tip_paragraph)

_WEEKLY_TIPS = [
    (
        "Your study tip this week: mark scheme first",
        "Try 'mark scheme first' on one question this week.\n\n"
        "Pick a question you're unsure about. Before you attempt it, read the mark scheme — "
        "see exactly what Cambridge is looking for. Then close it, answer the question, and compare.\n\n"
        "Most students treat mark schemes as answer keys. They're not. They're blueprints for "
        "how to think about the question. Reading them before answering teaches you the examiner's "
        "logic, which is half of what the exam tests.",
        "<strong>Try &ldquo;mark scheme first&rdquo; on one question this week.</strong>"
        "<br><br>"
        "Pick a question you're unsure about. Before you attempt it, read the mark scheme &mdash; "
        "see exactly what Cambridge is looking for. Then close it, answer the question, and compare."
        "<br><br>"
        "Most students treat mark schemes as answer keys. They're not &mdash; they're blueprints "
        "for how to think about the question. Reading them <em>before</em> answering teaches you "
        "the examiner's logic, which is half of what the exam tests.",
    ),
    (
        "Your study tip this week: test yourself, don't re-read",
        "This week, replace one re-reading session with a blank-page test.\n\n"
        "Close your notes. Pick a topic. Write down everything you can remember about it — "
        "definitions, formulas, worked examples, anything. Then open your notes and check.\n\n"
        "The gaps you find are your actual revision list. Re-reading hides them. "
        "This surfaces them in 10 minutes.",
        "<strong>This week: replace one re-reading session with a blank-page test.</strong>"
        "<br><br>"
        "Close your notes. Pick a topic. Write down everything you can remember about it &mdash; "
        "definitions, formulas, worked examples, anything. Then open your notes and check."
        "<br><br>"
        "The gaps you find are your actual revision list. Re-reading hides them. "
        "This surfaces them in 10 minutes.",
    ),
    (
        "Your study tip this week: count the answer lines",
        "Cambridge answer boxes have a specific number of lines for a reason. Use them.\n\n"
        "A 2-line box wants 2 distinct points. A 6-line box wants a structured explanation "
        "with multiple steps. Before you write a word, count the lines and plan your answer to fill them.\n\n"
        "Most marks lost on 'describe' and 'explain' questions are from students who gave one point "
        "when the box clearly expected three.",
        "<strong>Cambridge answer boxes have a specific number of lines for a reason. Use them.</strong>"
        "<br><br>"
        "A 2-line box wants 2 distinct points. A 6-line box wants a structured explanation "
        "with multiple steps. Before you write a word, count the lines and plan your answer to fill them."
        "<br><br>"
        "Most marks lost on &lsquo;describe&rsquo; and &lsquo;explain&rsquo; questions are from "
        "students who gave one point when the box clearly expected three.",
    ),
    (
        "Your study tip this week: time pressure from day one",
        "This week, try one question under timed conditions.\n\n"
        "Pick a structured question worth 6 marks. Set a timer for 7 minutes. "
        "Attempt it with no pausing, no peeking. Then check the mark scheme.\n\n"
        "Exam panic is almost always about pace, not knowledge. Students who practise timed "
        "from early on don't freeze in the hall — they've already felt the pressure and worked through it.",
        "<strong>This week: attempt one question under real timed conditions.</strong>"
        "<br><br>"
        "Pick a structured question worth 6 marks. Set a timer for 7 minutes. "
        "Attempt it with no pausing, no peeking. Then check the mark scheme."
        "<br><br>"
        "Exam panic is almost always about pace, not knowledge. Students who practise timed "
        "from early on don't freeze in the hall &mdash; they've already felt that pressure "
        "and worked through it.",
    ),
    (
        "Your study tip this week: learn the command words",
        "Cambridge uses the same command words across every paper, and each one has a specific meaning.\n\n"
        "'State' means one fact, no explanation. 'Describe' means what happens. "
        "'Explain' means why it happens — mechanism required. 'Suggest' means apply your knowledge "
        "to an unfamiliar situation.\n\n"
        "Read the command word before anything else. Half the marks lost on long-answer questions "
        "come from answering the wrong thing — explaining when they only asked you to describe.",
        "<strong>Cambridge uses the same command words on every paper. Each one has a specific meaning.</strong>"
        "<br><br>"
        "&lsquo;State&rsquo; = one fact, no explanation. &lsquo;Describe&rsquo; = what happens. "
        "&lsquo;Explain&rsquo; = why it happens &mdash; mechanism required. "
        "&lsquo;Suggest&rsquo; = apply knowledge to an unfamiliar situation."
        "<br><br>"
        "Read the command word before anything else. Half the marks lost on long-answer questions "
        "come from answering the wrong thing &mdash; explaining when they only asked you to describe.",
    ),
    (
        "Your study tip this week: work backwards from the marks",
        "In Maths and Physics, the mark allocation tells you how much working to show.\n\n"
        "A 1-mark question: just the answer. A 3-mark question: method, substitution, answer — "
        "three distinct steps on three lines. A 5-mark question: set up, working, intermediate "
        "result, final answer, units.\n\n"
        "Cambridge often awards marks for correct method even if the final answer is wrong. "
        "A student who shows full working and gets the arithmetic wrong can still score 4/5. "
        "A student who writes only the wrong answer scores 0.",
        "<strong>In Maths and Physics, the mark allocation tells you how much working to show.</strong>"
        "<br><br>"
        "A 1-mark question: just the answer. A 3-mark question: method, substitution, answer &mdash; "
        "three steps on three lines. A 5-mark question: set-up, working, intermediate result, "
        "final answer, units."
        "<br><br>"
        "Cambridge often awards marks for correct method even if the final answer is wrong. "
        "A student who shows full working and gets the arithmetic wrong can still score 4/5. "
        "A student who writes only the wrong answer scores 0.",
    ),
    (
        "Your study tip this week: keep a wrong-answers log",
        "This week, start a wrong-answers log. It takes 2 minutes per question.\n\n"
        "Every question you get wrong, write down: the topic, what you wrote, "
        "what the mark scheme wanted, and why you missed it.\n\n"
        "After a week you'll see a pattern. Not 'I'm bad at Physics' — something specific, "
        "like 'I keep forgetting to include units' or 'I miss the second mark on explain questions'. "
        "Specific problems have specific fixes. Vague ones don't.",
        "<strong>This week: start a wrong-answers log.</strong> It takes 2 minutes per question."
        "<br><br>"
        "Every question you get wrong, write: the topic, what you wrote, "
        "what the mark scheme wanted, and why you missed it."
        "<br><br>"
        "After a week you'll see a pattern &mdash; not &lsquo;I'm bad at Physics&rsquo; but "
        "something specific: <em>&lsquo;I keep forgetting units&rsquo;</em> or "
        "<em>&lsquo;I miss the second mark on explain questions.&rsquo;</em> "
        "Specific problems have specific fixes. Vague ones don't.",
    ),
    (
        "Your study tip this week: draw before you write",
        "For Physics and Maths, draw a diagram before you start any calculation.\n\n"
        "Even a rough sketch — a circuit, a force diagram, a triangle — "
        "locks in what the question is actually asking. It stops you substituting into "
        "the wrong formula and gives you something to check your answer against.\n\n"
        "Diagrams don't cost marks. In fact, examiners often give credit for a correct "
        "diagram even when the algebra that follows has an error.",
        "<strong>For Physics and Maths: draw a diagram before you start any calculation.</strong>"
        "<br><br>"
        "Even a rough sketch &mdash; a circuit, a force diagram, a triangle &mdash; "
        "locks in what the question is actually asking. It stops you substituting into "
        "the wrong formula and gives you something to check your answer against."
        "<br><br>"
        "Diagrams don't cost marks. In fact, examiners often award credit for a correct "
        "diagram even when the algebra that follows has an error.",
    ),
    (
        "Your study tip this week: spot the repeating questions",
        "Cambridge reuses question patterns more than students realise.\n\n"
        "Open five past papers for one topic. Look at how the question is phrased each time. "
        "You'll find 2 or 3 recurring structures — the same setup, different numbers or context.\n\n"
        "Once you know the pattern, you're not 'doing a question' — you're recognising a type. "
        "That's the difference between students who find exams familiar and students who find them unpredictable.",
        "<strong>Cambridge reuses question patterns more than students realise.</strong>"
        "<br><br>"
        "Open five past papers for one topic. Look at how each question is phrased. "
        "You'll find 2 or 3 recurring structures &mdash; the same setup with different numbers or context."
        "<br><br>"
        "Once you know the pattern, you're not &lsquo;doing a question&rsquo; &mdash; "
        "you're recognising a type. That's the difference between students who find exams "
        "familiar and students who find them unpredictable.",
    ),
    (
        "Your study tip this week: the Feynman check",
        "After you revise a topic, close your notes and explain it out loud as if you're teaching a 12-year-old.\n\n"
        "Where you hesitate or use vague words like 'somehow' or 'it just does' — "
        "that's exactly where your understanding has a hole.\n\n"
        "Go back to that specific point, re-read it, then explain it again. "
        "If you can say it clearly in simple language, you understand it well enough to answer any exam question about it.",
        "<strong>After revising a topic, explain it out loud as if you're teaching a 12-year-old.</strong>"
        "<br><br>"
        "Where you hesitate or use vague words like &lsquo;somehow&rsquo; or &lsquo;it just does&rsquo; &mdash; "
        "that's exactly where your understanding has a hole."
        "<br><br>"
        "Go back to that specific point, re-read it, then explain it again. "
        "If you can say it clearly in simple language, you can answer any exam question about it.",
    ),
    (
        "Your study tip this week: one mark per minute",
        "Cambridge papers are designed for one mark per minute. Use that.\n\n"
        "A 2-mark question gets 2 minutes. A 6-mark question gets 6 minutes. "
        "If you're spending 12 minutes on a 4-mark question, you're already behind — "
        "move on, come back to it at the end.\n\n"
        "Practise timing yourself this week. Set a phone timer for each question. "
        "You don't need to get faster — you need to get comfortable stopping when the time is up.",
        "<strong>Cambridge papers are designed for one mark per minute. Use that rule.</strong>"
        "<br><br>"
        "A 2-mark question gets 2 minutes. A 6-mark question gets 6 minutes. "
        "If you're spending 12 minutes on a 4-mark question, you're already behind &mdash; "
        "move on and come back."
        "<br><br>"
        "Practise timing yourself this week. Set a timer for each question. "
        "You don't need to get faster &mdash; you need to get comfortable stopping when time is up.",
    ),
    (
        "Your study tip this week: read the question twice",
        "The most common exam mistake isn't not knowing the answer. It's misreading the question.\n\n"
        "This week, practise reading every question twice before you write anything. "
        "First read: understand the context. Second read: identify exactly what is being asked "
        "and circle the command word.\n\n"
        "A student who knows the topic but answers the wrong question scores zero. "
        "A student who reads carefully and answers precisely scores full marks — "
        "even with imperfect knowledge.",
        "<strong>The most common exam mistake isn't not knowing the answer. It's misreading the question.</strong>"
        "<br><br>"
        "This week: read every question twice before writing anything. "
        "First read: understand the context. Second read: identify exactly what's being asked "
        "and note the command word."
        "<br><br>"
        "A student who knows the topic but answers the wrong question scores zero. "
        "A student who reads carefully and answers precisely scores full marks &mdash; "
        "even with imperfect knowledge.",
    ),
]


def send_F1(user: dict, week_number: int) -> bool:
    """Weekly Study Tip — rotates through _WEEKLY_TIPS by ISO week number."""
    first = (user.get("name") or "there").split()[0]
    lib = f"{APP_URL}/yearly"
    subject, plain_tip, html_tip = _WEEKLY_TIPS[week_number % len(_WEEKLY_TIPS)]

    return _send(
        user, "F1",
        subject=subject,
        body_plain=(
            f"Hi {first},\n\n"
            "Quick one this week.\n\n"
            f"{plain_tip}\n\n"
            "Give it a go this week.\n\n"
            f"{lib}\n\n"
            "Have a good week,\n"
            "Tee"
        ),
        body_html=(
            _p(f"Hi {_esc(first)},")
            + _p("Quick one this week.")
            + f'<p style="margin:0 0 14px;padding:16px 18px;background:#faf8f5;'
              f'border-left:3px solid #C9A84C;border-radius:0 6px 6px 0;'
              f'font-size:.9rem;color:#1e1b30;line-height:1.8">{html_tip}</p>'
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
    lib = f"{APP_URL}/yearly"
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
        f"Your mock test is ready, {first} — here's how to nail it.",
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
            if send_F1(u, today.isocalendar()[1]):
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
