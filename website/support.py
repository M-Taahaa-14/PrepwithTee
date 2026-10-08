"""Help centre: the PrepWithTee support assistant (static/support.js).

    GET  /api/support/context        what the help centre's Home tab shows: the
                                     student's plan, free allowance left, failed
                                     booklets, payment-proof status, office hours,
                                     status banner (guests get the public bits)
    POST /api/support/chat           one answer: {reply (markdown), links, actions,
                                     suggest_handoff, event_id}
    POST /api/support/vote           thumbs up / down on an answer
    POST /api/support/track          a one-tap fix was used (for the report)
    POST /api/support/handoff        "Send this to Tee": the chat + diagnostics +
                                     screenshots land in the admin Inbox
    GET  /api/support/threads        the student's own requests and Tee's replies
    admin: GET  /api/admin/support/report, GET/PUT /api/admin/support/status,
           POST /api/admin/support/{id}/draft

How an answer is made, cheapest first:
  1. intent() - word-boundary keywords, English + Roman Urdu. Problems (payment
     not showing, booklet failed, ran out, can't log in) are answered from the
     student's OWN account with buttons that fix them (retry the build, start
     the trial, reset the password) - never with a marketing blurb.
  2. navigate() - "2019 May/June paper 2 5054", "momentum notes" -> real pages
     from the site search index.
  3. Otherwise a free AI provider (content_ai.providers(): never the Groq vision
     budget, groq_text last) answers from facts() + the student's context. Every
     link it writes is checked against real pages; unknown ones are unlinked.

facts() is the ONE place prices, subjects, limits and class details come from
(billing.PERIODS, catalog.SUBJECTS, access quotas), so the bot can't drift from
the pricing page the way the old hard-coded FAQ did.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import access as _access
import auth as _auth
import billing as _billing
import catalog as _catalog
import support_store as _store
import users_db as _udb
from admin_auth import Admin

router = APIRouter()


def _app():
    """The running app module (helpers like _notify live there). It is 'app' on the
    server and 'website.app' under uvicorn website.app:app / pytest - reuse whichever
    is loaded instead of importing a second copy."""
    import sys
    mod = sys.modules.get("app") or sys.modules.get("website.app")
    if mod is None:
        import app as mod
    return mod

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
STATUS_FILE = Path(os.environ.get("SUPPORT_STATUS_FILE") or ROOT / "data" / "support" / "status.json")
PKT = timezone(timedelta(hours=5), "PKT")      # Pakistan has no daylight saving

WHATSAPP = "+92 320 488 4375"
WA_URL = "https://wa.me/923204884375"
COVERAGE = "2010 to 2026"

# Live classes (kept in step with static/promo-bar.js PROMO and the class pages).
CLASSES = {
    "start": date(2026, 10, 31),
    "olevel_price": 8499, "alevel_from": 12999,
    "pages": [("Maths classes", "/maths-classes.html"), ("Physics classes", "/physics-classes.html"),
              ("Computer Science classes", "/cs-classes.html")],
    "all": "/courses.html",
    "shape": "small groups of 4-6, 4 classes + 1 test a week; syllabus Nov-Jan, past papers Feb-Apr; "
             "money back if you're not happy after the first paid class",
    "a_level": "A Level: Maths 9709 (P1, P3, M1, S1), Physics 9702 (AS, A2), CS 9618 (P1-P4), "
               "each paper its own course",
}
TUTORING = {"group_from": 12000, "solo_from": 20000}       # pricing.html TUT_PRICES p1

DEFAULT_HOURS = {"start": 10, "end": 22, "days": [0, 1, 2, 3, 4, 5, 6]}   # PKT, Mon=0


# ── Facts: one live source ────────────────────────────────────────────────────

def _pkr(n: int) -> str:
    return f"PKR {n:,}"


def facts() -> dict:
    by_board: dict[str, list[str]] = {}
    for code, s in _catalog.SUBJECTS.items():
        by_board.setdefault(_catalog.BOARD_SHORT[s["board_slug"]], []).append(f"{s['plain']} {code}")
    periods = []
    for key, p in _billing.PERIODS.items():
        periods.append({"id": key, "label": p["label"],
                        "prices": {k: v for k, v in p["amount"].items()},
                        "until": p.get("until"), "days": p.get("days")})
    free = {ev: _access.MONTHLY_QUOTAS.get(ev, {}).get("free")
            for ev in ("topical_paper", "topic_test", "ai_quiz", "mcq_drill")}
    return {"subjects": by_board, "periods": periods, "free": free,
            "trial_days": _access.TRIAL_DAYS, "plan_labels": _billing.PLAN_LABELS,
            "classes": CLASSES, "tutoring": TUTORING, "whatsapp": WHATSAPP, "coverage": COVERAGE}


def facts_text() -> str:
    f = facts()
    subj = "\n".join(f"- {b}: {', '.join(v)}" for b, v in f["subjects"].items())
    lab = _billing.PLAN_LABELS
    prices = "\n".join(
        f"- {p['label']}: " + ", ".join(f"{lab[k]} {_pkr(v)}" for k, v in p["prices"].items())
        + (f" (valid until {p['until']})" if p.get("until") else "")
        for p in f["periods"])
    fr = f["free"]
    c = f["classes"]
    return f"""== SUBJECTS (Cambridge, papers {f['coverage']}, every session and variant) ==
{subj}

== PLATFORM PLANS ==
- Free: {fr['topical_paper']} topical booklets + {fr['topic_test']} mock tests a month, papers by year (no account needed), MCQ practice, tools, notes, progress tracking for every subject. One worked AI explanation per question.
- Solo = 1 subject, 3 Subjects = 3 chosen subjects, All Subjects = everything incl. MCQ live solver. Paid plans: unlimited booklets and mock tests, worked solutions, hints, follow-up questions, AI Tutor.
{prices}
- Free 7-day trial of All Subjects: once per account, starts instantly from the help centre or the limit card, no payment.
- How to pay: JazzCash, EasyPaisa or bank transfer, then upload the payment screenshot on /pricing.html (the plan picker). Tee checks the money arrived and the plan switches on, usually within 24 hours. Renewing early adds to the current end date.

== LIVE CLASSES WITH TEE ==
- New batches from {c['start']:%d %B %Y}: Maths, Physics, Computer Science. {c['shape']}.
- O Level & IGCSE: {_pkr(c['olevel_price'])}/month. {c['a_level']}, from {_pkr(c['alevel_from'])}/month.
- Pages: /maths-classes.html, /physics-classes.html, /cs-classes.html, /courses.html. Free demo class: WhatsApp Tee.
- Other tutoring: group lessons from {_pkr(f['tutoring']['group_from'])}/month, 1-on-1 from {_pkr(f['tutoring']['solo_from'])}/month (/pricing.html#tutoring-section).

== WHERE THINGS ARE ==
- /papers/topical: topical booklets (pick board, subject, chapters, subtopics; mark scheme after each question)
- /papers/mock-tests: timed mock tests (review and customise the questions; scheme unlocks when you finish)
- /yearly: every past paper by year with mark scheme and insert, side by side
- /mcq: MCQ practice, full papers or by topic, marked instantly
- /my-papers: every booklet and test you built (open for 30 days after last opened, then kept as a record you can rebuild)
- /notes: revision notes per chapter; /resources: PDFs, books, worksheets, syllabuses
- /solver: Photo Solver (solve a question / check my working); /tutor.html: AI Tutor
- /whiteboard: PrepWithTee Board; pens, ruler, protractor and compass are on every paper (left toolbar)
- /tools.html: calculator, graph plotter, formula sheets, periodic table, pseudocode
- /dashboard.html: progress, streaks; /profile.html: account, boards, subjects
- /features: every feature with tips; /explore: every page
- Parents: /parent-dashboard.html, linked with the student's code from their profile
- Contact: WhatsApp Tee {f['whatsapp']} ({WA_URL}) or /contact.html"""


# ── Office hours + status banner (data/support/status.json) ──────────────────

def load_status() -> dict:
    try:
        d = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_status(d: dict) -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATUS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
    os.replace(tmp, STATUS_FILE)


def hours(now: datetime | None = None, status: dict | None = None) -> dict:
    """Is Tee around? {open, text}. Hours are Pakistan time."""
    st = status if status is not None else load_status()
    h = {**DEFAULT_HOURS, **(st.get("hours") or {})}
    now = (now or datetime.now(timezone.utc)).astimezone(PKT)
    start, end = int(h["start"]), int(h["end"])

    def fmt(x: int) -> str:
        return f"{(x - 1) % 12 + 1}{'am' if x < 12 or x == 24 else 'pm'}"

    open_now = now.weekday() in h["days"] and start <= now.hour < end and not st.get("away")
    if open_now:
        text = "Tee usually replies within a few hours."
    elif st.get("away"):
        text = str(st["away"])[:200]
    else:
        nxt = now if now.hour < start else now + timedelta(days=1)
        for _ in range(7):
            if nxt.weekday() in h["days"]:
                break
            nxt += timedelta(days=1)
        day = "today" if nxt.date() == now.date() else "tomorrow" if nxt.date() == now.date() + timedelta(days=1) \
            else nxt.strftime("%A")
        text = f"Tee is offline now - your message will be answered from {fmt(start)} {day} (Pakistan time)."
    return {"open": open_now, "text": text, "start": start, "end": end}


def banner(status: dict | None = None) -> dict | None:
    st = status if status is not None else load_status()
    b = st.get("banner") or {}
    if not b.get("text"):
        return None
    if b.get("until"):
        try:
            if datetime.fromisoformat(b["until"]).date() < date.today():
                return None
        except ValueError:
            pass
    return {"text": str(b["text"])[:300], "tone": b.get("tone") if b.get("tone") in ("info", "warn", "ok") else "info"}


# ── Intent: what is the person asking about? ─────────────────────────────────

_ROMAN_URDU = {"hai", "hain", "nahi", "nahin", "nai", "kya", "kaise", "kaisay", "kitni", "kitna", "kitne",
               "mera", "meri", "mere", "mujhe", "muje", "karna", "karni", "chahiye", "chahye", "kahan",
               "kyun", "kyu", "bhai", "aap", "ap", "hoga", "raha", "rahi", "gaya", "gayi", "kar", "ki", "ko",
               "se", "bhi", "abhi", "tak", "batao", "bataen", "masla", "theek", "kab", "wala", "wali"}


def language(text: str) -> str:
    if re.search(r"[؀-ۿ]", text or ""):
        return "ur"
    words = set(re.findall(r"[a-z]+", (text or "").lower()))
    return "ur-Latn" if len(words & _ROMAN_URDU) >= 2 else "en"


def _has(text: str, *phrases: str) -> bool:
    return any(re.search(rf"(?<![a-z]){p}(?![a-z])", text) for p in phrases)


_PROBLEM = ("not working", "doesn't work", "doesnt work", "isn't working", "won't", "wont", "can't", "cant",
            "cannot", "couldn't", "couldnt", "unable", "fail", "failed", "failing", "error", "errors", "stuck",
            "broken", "bug", "issue", "problem", "wrong", "blank", "missing", "not showing", "not opening",
            "not loading", "slow", "loading", "nahi", "nahin", "nai", "masla", "kharab", "still", "abhi tak",
            "why", "kyun", "kyu", "not")


def intent(text: str) -> str | None:
    t = " " + re.sub(r"\s+", " ", (text or "").lower()) + " "
    problem = _has(t, *_PROBLEM)
    paperish = _has(t, "booklet", "booklets", "topical", "mock test", "mock", "test paper", "paper", "papers",
                    "pdf", "build", "built", "building", "generate", "generating")
    if _has(t, "forgot", "forget", "reset", "bhool", "bhul") and _has(t, "password", "pass"):
        return "password"
    if _has(t, "log in", "login", "logged in", "sign in", "signin", "signed in", "account") and problem \
            and not _has(t, "pay", "paid", "payment"):
        return "login"
    paying = _has(t, "paid", "pay", "payment", "payments", "jazzcash", "jazz cash", "easypaisa", "easy paisa",
                  "bank transfer", "transaction", "receipt", "proof", "paise", "paisay", "bheje", "bhej",
                  "transfer", "upgrade", "upgraded")
    if paying and (problem or _has(t, "status", "pending", "approved", "approve", "activate", "activated",
                                   "when", "kab", "sent", "screenshot", "still free", "plan")):
        if _has(t, "paid", "payment", "proof", "transaction", "receipt", "sent", "bheje", "bhej", "screenshot",
                "transfer", "pending", "approved", "activate", "activated", "upgraded"):
            return "payment_status"
    if _has(t, "limit", "limits", "ran out", "run out", "used up", "used all", "no more", "quota", "allowance",
            "khatam", "remaining", "left this month", "how many"):
        if paperish or _has(t, "free", "limit", "quota", "allowance", "khatam", "remaining", "left"):
            return "quota"
    if paperish and problem:
        return "booklet_problem"
    if _has(t, "trial"):
        return "trial"
    if _has(t, "which plan", "what plan", "best plan", "recommend", "konsa plan", "kaunsa plan",
            "should i buy", "should i get", "which package", "worth it"):
        return "plan_advice"
    if _has(t, "parent", "parents", "my son", "my daughter", "my child", "my kid", "beta", "beti", "bacha",
            "bachay", "bache", "ammi", "abbu"):
        return "parent"
    if _has(t, "class", "classes", "batch", "batches", "tuition", "tuitions", "tutoring", "tutor me", "demo",
            "1-on-1", "one on one", "one-on-one", "group lesson", "lessons", "academy", "enrol", "enroll"):
        return "classes"
    if _has(t, "human", "real person", "talk to", "speak to", "call", "whatsapp", "contact", "number",
            "email tee", "message tee", "reach tee", "baat"):
        return "contact"
    if _has(t, "price", "prices", "pricing", "cost", "costs", "fee", "fees", "how much", "kitni", "kitne",
            "kitna", "subscription", "subscribe", "plans", "plan", "package", "packages", "pkr", "rupees",
            "monthly", "yearly", "discount"):
        return "pricing"
    if _has(t, "subjects", "which subject", "do you have", "do you cover", "cover", "syllabus", "syllabuses"):
        if not _subject_codes(t):
            return "subjects"
    if problem and _has(t, "bug", "error", "broken", "not working", "doesn't work", "masla", "kharab",
                        "issue", "problem", "crash", "crashes"):
        return "problem"
    return None


# ── Navigation: "where do I find ..." -> real pages ──────────────────────────

_BOARD_WORDS = {"o-level": ("o level", "olevel", "o-level", "ol", "gce"),
                "igcse": ("igcse", "gcse"),
                "a-level": ("a level", "alevel", "a-level", "as level", "as", "a2", "al")}
_SESSIONS = {"s": ("may", "june", "may/june", "may june", "summer", "mj"),
             "w": ("oct", "october", "nov", "november", "oct/nov", "winter", "on"),
             "m": ("feb", "february", "march", "feb/march", "fm")}
_NAMES = {"maths": "mathematics", "math": "mathematics", "mathematics": "mathematics", "physics": "physics",
          "chemistry": "chemistry", "chem": "chemistry", "cs": "computer science",
          "computer": "computer science", "computing": "computer science", "islamiyat": "islamiyat",
          "islamiat": "islamiyat", "pak studies": "pakistan studies", "pakistan studies": "pakistan studies",
          "biology": "biology", "economics": "economics", "accounting": "accounting", "english": "english"}
_STOP = {"the", "a", "an", "of", "for", "to", "in", "on", "and", "or", "is", "are", "where", "can", "i", "do",
         "find", "how", "me", "my", "show", "open", "get", "want", "need", "please", "questions", "question",
         "paper", "papers", "past", "with", "what", "which", "there", "any", "kahan", "hai", "hain", "chahiye",
         "mujhe", "link", "page", "level", "o", "igcse", "as", "from", "by", "it", "this", "that", "you", "have"}


def _subject_codes(t: str) -> list[str]:
    codes = [c for c in _catalog.SUBJECTS if re.search(rf"(?<!\d){c}(?!\d)", t)]
    if codes:
        return codes
    board = next((b for b, ws in _BOARD_WORDS.items() if _has(t, *(re.escape(w) for w in ws))), None)
    name = next((n for k, n in _NAMES.items() if _has(t, re.escape(k))), None)
    if not name:
        return []
    out = [c for c, s in _catalog.SUBJECTS.items()
           if name in s["name"].lower() and (board is None or s["board_slug"] == board)]
    return out


def _sitting(t: str) -> dict:
    out: dict = {}
    m = re.search(r"(?<!\d)(20[012]\d)(?!\d)", t)
    if m:
        out["year"] = int(m.group(1))
    for code, words in _SESSIONS.items():
        if _has(t, *(re.escape(w) for w in words)):
            out["session"] = code
            break
    m = re.search(r"(?:paper|p)\s*([1-6])\s*([1-3])?(?!\d)", t)
    if m:
        out["paper"] = int(m.group(1))
        if m.group(2):
            out["variant"] = m.group(2)
    m = re.search(r"variant\s*([1-3])", t)
    if m:
        out["variant"] = m.group(1)
    return out


def _search(query: str, codes: list[str], limit: int = 4) -> list[dict]:
    try:
        import search
        rows = search.index_rows()
    except Exception:
        return []
    words = [w for w in re.findall(r"[a-z0-9']+", query.lower()) if w not in _STOP and len(w) > 1
             and not re.fullmatch(r"20\d\d", w)]
    if not words:
        return []
    scored = []
    for r in rows:
        title = r["t"].lower()
        hay = f"{title} {r.get('s', '').lower()} {r.get('q', '').lower()}"
        if codes and not any(c in hay for c in codes):
            continue
        score = 0
        for w in words:
            if re.search(rf"\b{re.escape(w)}", title):
                score += 3
            elif re.search(rf"\b{re.escape(w)}", hay):
                score += 1
        if score:
            kind_bonus = {"chapter": 1, "note": 0.5}.get(r.get("k"), 0)
            scored.append((score + kind_bonus, r))
    scored.sort(key=lambda x: -x[0])
    top = scored[0][0] if scored else 0
    out, seen = [], set()
    for s, r in scored:
        if s < max(2, top * 0.6) or r["u"] in seen:
            continue
        seen.add(r["u"])
        out.append({"t": r["t"], "s": r.get("s", ""), "u": r["u"]})
        if len(out) >= limit:
            break
    return out


def navigate(text: str) -> dict | None:
    """Real pages for a 'where is ...' question: {reply, links} or None."""
    t = " " + re.sub(r"\s+", " ", (text or "").lower()) + " "
    codes = _subject_codes(t)
    sit = _sitting(t)
    links: list[dict] = []
    reply = ""
    if len(codes) == 1:
        code = codes[0]
        s = _catalog.SUBJECTS[code]
        name = f"{s['plain']} {code}"
        if sit.get("year"):
            q = f"syllabus={code}&year={sit['year']}"
            label = f"{name} - {sit['year']}"
            if sit.get("session"):
                q += f"&session={sit['session']}"
                label += {"s": " May/June", "w": " Oct/Nov", "m": " Feb/March"}[sit["session"]]
            exact = bool(sit.get("paper") and sit.get("session"))
            if sit.get("paper"):
                variant = sit.get("variant") or "1"          # "paper 2" = the first variant, 21
                q += f"&paper={sit['paper']}&variant={variant}"
                label += f" Paper {sit['paper']}{variant}"
            links.append({"t": label, "s": "Question paper + mark scheme" if exact else "Every sitting that year",
                          "u": f"/yearly/open?{q}"})
            if exact:
                year_url = _catalog_yearly(code, sit["year"])
                if year_url:
                    links.append({"t": f"{name} - every {sit['year']} paper", "s": "Other variants and sessions",
                                  "u": year_url})
            reply = ((f"Here's **{label}**. It opens with the mark scheme beside it - no account needed."
                      + ("" if sit.get("variant") else " Other variants are on the year page."))
                     if exact else f"Here are the **{name}** papers from {sit['year']} - pick the session and paper.")
        else:
            import ui
            want = {"mcq": ("mcq", "multiple choice"), "notes": ("notes", "note", "revision"),
                    "mock": ("mock", "test"), "yearly": ("yearly", "by year", "past paper"),
                    "resources": ("resources", "books", "pdf", "worksheets")}
            pick = next((k for k, ws in want.items() if _has(t, *(re.escape(w) for w in ws))), None)
            for key, label, url, _ic in ui.subject_links(code):
                if pick is None or pick in key or key == "topical":
                    links.append({"t": f"{name} · {label}", "s": s["board"], "u": url})
            reply = f"Here's where to find **{name}**:"
    elif len(codes) > 1:
        for c in codes[:4]:
            s = _catalog.SUBJECTS[c]
            links.append({"t": f"{s['plain']} {c}", "s": s["board"], "u": _catalog.subject_url(c)})
        reply = "Which one do you mean?"
    hits = _search(text, codes[:1] if len(codes) == 1 else [])
    for h in hits:
        if h["u"] not in {l["u"] for l in links}:
            links.append(h)
    if not links:
        return None
    if not reply:
        reply = "These pages look like what you're after:"
    return {"reply": reply, "links": links[:5]}


def _catalog_yearly(code: str, year: int) -> str | None:
    try:
        import yearly
        return yearly.yearly_url(code, year)
    except Exception:
        return None


def wants_navigation(text: str) -> bool:
    t = " " + (text or "").lower() + " "
    return bool(_has(t, "where", "find", "show me", "open", "link", "kahan", "kidhar", "chahiye", "looking for",
                     "go to", "take me", "notes for", "notes on", "questions on", "questions for", "paper")
                or _subject_codes(t) or _sitting(t).get("year"))


# ── Links the AI wrote: keep only real pages ─────────────────────────────────

_ROUTE_PREFIXES = ("/papers", "/yearly", "/mcq", "/notes", "/resources", "/my-papers", "/whiteboard",
                   "/features", "/explore", "/solver", "/blog", "/admin", "/teach")
_LINK_MD = re.compile(r"\[([^\]\n]{1,120})\]\(([^)\s]{1,300})\)")


def known_url(u: str) -> bool:
    u = (u or "").strip()
    if u.startswith(("https://wa.me/923204884375", "https://prepwithtee.com", "mailto:")):
        return True
    if not u.startswith("/") or u.startswith("//"):
        return False
    path = u.split("#")[0].split("?")[0]
    if path in ("/",) or path.startswith(_ROUTE_PREFIXES):
        return True
    f = (STATIC / path.lstrip("/")).resolve()
    return str(f).startswith(str(STATIC.resolve())) and f.is_file()


def clean_links(text: str) -> str:
    def fix(m):
        return m.group(0) if known_url(m.group(2)) else m.group(1)
    return _LINK_MD.sub(fix, text or "")


# ── The student's own account ────────────────────────────────────────────────

_QUOTA_EVENTS = (("topical_paper", "topical booklets"), ("topic_test", "mock tests"))


def _allowance(user: dict, info: dict) -> list[dict]:
    out = []
    resets = None
    try:
        start = datetime.fromisoformat(str(info["period_start"]).replace("Z", "+00:00"))
        resets = (start + timedelta(days=_access.BILLING_CYCLE_DAYS)).date().isoformat()
    except (KeyError, TypeError, ValueError):
        pass
    for ev, label in _QUOTA_EVENTS:
        limit = (_access.TRIAL_QUOTAS.get(ev) if info.get("trial")
                 else _access.MONTHLY_QUOTAS.get(ev, {}).get(info["plan"]))
        used = _udb.count_usage_this_month(user["id"], ev, info.get("period_start"))
        out.append({"event": ev, "label": label, "used": used, "limit": limit, "resets_on": resets})
    return out


def _recent_booklets(user: dict, days: int = 14) -> list[dict]:
    import booklets as _bk
    out = []
    for b in _udb.list_booklets(user["id"], limit=20):
        age = _hours_since(b.get("created_at"))
        if age is not None and age > days * 24 and b.get("status") != "failed":
            continue
        if b.get("status") in ("failed", "queued", "building"):
            b = _udb.get_booklet(b["id"]) or b       # the list query leaves out error / updated_at
        row = {"id": b["id"], "title": b.get("title") or "Your paper", "status": b.get("status"),
               "kind": _bk._kind(b), "url": f"/papers/view/{b['id']}", "created_at": b.get("created_at")}
        if b.get("status") == "failed":
            f = _bk.failure(b)
            row.update(code=f["code"], why=f["title"], message=f["message"], retryable=f["retryable"],
                       rebuild_url=_bk._rebuild_url(b))
        elif b.get("status") in ("queued", "building"):
            stuck = _bk._fail_if_stuck(b)
            if stuck.get("status") == "failed":
                f = _bk.failure(stuck)
                row.update(status="failed", code=f["code"], why=f["title"], message=f["message"],
                           retryable=f["retryable"], rebuild_url=_bk._rebuild_url(b))
        elif _bk.expired(b):
            row.update(status="expired", rebuild_url=_bk._rebuild_url(b))
        out.append(row)
    return out


def _payment(user: dict) -> dict | None:
    try:
        rows = _udb.fetch_all("payment_proofs", eq={"user_id": user["id"]}, order="created_at", desc=True)
    except Exception:
        return None
    if not rows:
        return None
    p = rows[0]
    period = _billing.PERIODS.get(p.get("period") or "monthly", {}).get("label")
    return {"id": p.get("id"), "status": p.get("status") or "pending", "plan": p.get("plan"),
            "plan_label": _billing.PLAN_LABELS.get(p.get("plan"), p.get("plan")), "period": period,
            "amount": p.get("amount_pkr"), "created_at": p.get("created_at"),
            "note": p.get("reviewer_note") if p.get("status") == "rejected" else None}


def account(user: dict | None) -> dict:
    """Everything the help centre knows about this person (nothing for guests)."""
    if not user:
        return {"signed_in": False}
    info = _access.plan_info(user)
    out = {"signed_in": True, "name": (user.get("name") or "").split(" ")[0] or None,
           "full_name": user.get("name"), "email": user.get("email"),
           "role": user.get("role") or "student", "plan": info["plan"],
           "plan_label": _access.PLAN_LABELS.get(info["plan"], info["plan"]),
           "trial": bool(info.get("trial")), "trial_days_left": info.get("trial_days_left"),
           "expires_at": info.get("expires_at") if info["plan"] != "free" else None}
    got = _udb.gather(
        allowance=lambda: _safe(lambda: _allowance(user, info), []),
        booklets=lambda: _safe(lambda: _recent_booklets(user), []),
        payment=lambda: _safe(lambda: _payment(user), None),
        eligible=lambda: _safe(lambda: _trial_eligible(user), False),
    )
    out.update(allowance=got["allowance"], booklets=got["booklets"], payment=got["payment"],
               trial_eligible=got["eligible"])
    return out


def _trial_eligible(user: dict) -> bool:
    import upgrade
    return upgrade.trial_eligible(user)


def _safe(fn, default):
    try:
        return fn()
    except Exception as exc:
        print(f"[support] context part skipped: {exc}", flush=True)
        return default


def _date(ts) -> str:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).strftime("%d %b")
    except (TypeError, ValueError):
        return str(ts or "")[:10]


def _hours_since(ts) -> float | None:
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - d).total_seconds() / 3600
    except (TypeError, ValueError):
        return None


# ── Answers for each intent ──────────────────────────────────────────────────

def _act(kind: str, label: str, **kw) -> dict:
    return {"kind": kind, "label": label, **kw}


SIGN_IN = _act("link", "Sign in", url="/login.html")
HANDOFF = _act("handoff", "Send this to Tee")


def answer_intent(name: str, text: str, acct: dict) -> dict | None:
    """Deterministic answer {reply, actions, links, suggest_handoff} or None (= ask the AI)."""
    f = facts()
    signed = acct.get("signed_in")
    fr = f["free"]
    if name == "payment_status":
        if not signed:
            return {"reply": "Sign in and ask again - I can then see whether your payment proof has "
                             "arrived and where it is in the queue.",
                    "actions": [SIGN_IN, _act("link", "How to pay", url="/pricing.html#plans")]}
        p = acct.get("payment")
        if not p:
            return {"reply": "I can't see a payment proof from this account yet. After paying by JazzCash, "
                             "EasyPaisa or bank transfer, pick your plan on the pricing page and **upload the "
                             "payment screenshot** there - that's what tells Tee to switch your plan on.",
                    "actions": [_act("link", "Upload my payment proof", url="/pricing.html#plans"), HANDOFF],
                    "suggest_handoff": True}
        when = _date(p["created_at"])
        what = f"**{p['plan_label']}**" + (f" ({p['period']})" if p.get("period") else "")
        if p["status"] == "approved":
            exp = acct.get("expires_at")
            return {"reply": f"Your payment for {what} was **approved** - you're on the "
                             f"**{acct.get('plan_label')}** plan"
                             + (f" until **{_date(exp)}**." if exp else ".")
                             + " If a page still shows the free limits, sign out and back in once.",
                    "actions": [_act("link", "Go to my dashboard", url="/dashboard.html")]}
        if p["status"] == "rejected":
            why = f" Tee's note: “{p['note']}”" if p.get("note") else ""
            return {"reply": f"Your payment proof for {what} from {when} was **not approved**.{why} "
                             "You can upload a corrected screenshot, or send this to Tee if you think it's a mistake.",
                    "actions": [_act("link", "Upload again", url="/pricing.html#plans"), HANDOFF],
                    "suggest_handoff": True}
        hrs = _hours_since(p["created_at"]) or 0
        late = hrs > 24
        return {"reply": f"Tee has your payment proof for {what}, sent on **{when}** - it's **waiting to be "
                         "checked**. Tee confirms the money arrived and then your plan switches on, usually "
                         "within 24 hours." + (" It's been longer than that, so I'd send this to Tee now." if late else
                                               " You'll get an email the moment it's done."),
                "actions": [HANDOFF] if late else [],
                "suggest_handoff": late}

    if name == "booklet_problem":
        if not signed:
            return {"reply": "Sign in and ask again so I can look at your papers. Most build problems are "
                             "fixed by **Try again**; a very big selection (over ~30 questions) can time out.",
                    "actions": [SIGN_IN, HANDOFF]}
        bad = [b for b in acct.get("booklets") or [] if b["status"] in ("failed", "expired")]
        building = [b for b in acct.get("booklets") or [] if b["status"] in ("queued", "building")]
        if bad:
            b = bad[0]
            if b["status"] == "expired":
                return {"reply": f"**{b['title']}** hasn't been opened for 30 days, so its PDF was cleared. "
                                 "The record is kept - build it again with the same chapters in one tap.",
                        "actions": [_act("link", "Build it again", url=b["rebuild_url"]),
                                    _act("link", "My papers", url="/my-papers")]}
            actions = []
            if b.get("retryable"):
                actions.append(_act("retry", "Try again", booklet_id=b["id"]))
            actions.append(_act("link", "Change my selection", url=b["rebuild_url"]))
            actions.append(HANDOFF)
            return {"reply": f"**{b['title']}** didn't build: **{b['why']}.** {b['message']}",
                    "actions": actions, "suggest_handoff": b.get("code") in ("missing_source", "internal")}
        if building:
            b = building[0]
            return {"reply": f"**{b['title']}** is still being built. Big booklets take a minute or two - "
                             "keep the page open and it appears by itself.",
                    "actions": [_act("link", "Open it", url=b["url"])]}
        return {"reply": "All your recent papers built fine, so this sounds like a viewing problem. Try: "
                         "reload the page; if pages stay blank, switch **Dark paper** off in the viewer; on a "
                         "slow connection the first page takes a few seconds. Still stuck? Send this to Tee "
                         "and your browser details go with it.",
                "actions": [_act("link", "My papers", url="/my-papers"), HANDOFF], "suggest_handoff": True}

    if name == "quota":
        if not signed:
            return {"reply": f"Free accounts get **{fr['topical_paper']} topical booklets and "
                             f"{fr['topic_test']} mock tests a month**, plus every past paper by year with no "
                             "limit. Sign in to see how many you have left.",
                    "actions": [SIGN_IN, _act("link", "See plans", url="/pricing.html#plans")]}
        lines = []
        for a in acct.get("allowance") or []:
            if a["limit"] is None:
                lines.append(f"- {a['label'].capitalize()}: **unlimited**")
            else:
                lines.append(f"- {a['label'].capitalize()}: **{max(0, a['limit'] - a['used'])} of {a['limit']} left**")
        resets = next((a["resets_on"] for a in acct.get("allowance") or [] if a.get("resets_on")), None)
        reply = f"You're on the **{acct['plan_label']}** plan" + (" (trial)" if acct.get("trial") else "") + ":\n" \
                + "\n".join(lines)
        if resets and acct["plan"] == "free":
            reply += f"\n\nYour free allowance resets on **{_date(resets)}**. Papers by year never count."
        actions = []
        if acct.get("trial_eligible"):
            actions.append(_act("trial", f"Start my free {f['trial_days']}-day trial"))
        if acct["plan"] in ("free", "solo", "three") and not acct.get("trial"):
            actions.append(_act("link", "See plans", url="/pricing.html#plans"))
        return {"reply": reply, "actions": actions}

    if name == "trial":
        if not signed:
            return {"reply": f"Every account can have **one free {f['trial_days']}-day trial** of All "
                             "Subjects - it starts instantly, no payment. Sign in (or sign up free) first.",
                    "actions": [SIGN_IN]}
        if acct.get("trial"):
            return {"reply": f"Your trial is running - **{acct.get('trial_days_left', 0)} days left**. "
                             "After it ends you go back to the free plan unless you pick one.",
                    "actions": [_act("link", "See plans", url="/pricing.html#plans")]}
        if acct.get("trial_eligible"):
            return {"reply": f"You can start a **free {f['trial_days']}-day trial of All Subjects** right now - "
                             "no payment, it switches on instantly and ends by itself.",
                    "actions": [_act("trial", f"Start my free {f['trial_days']}-day trial")]}
        return {"reply": "The free trial is once per account and this account has already had it (or has a "
                         "paid plan). The plans start from **" + _pkr(_billing.PERIODS['monthly']['amount']['solo'])
                         + "/month**.",
                "actions": [_act("link", "See plans", url="/pricing.html#plans")]}

    if name == "password":
        return {"reply": "Use **Forgot password** - we email you a reset link (check spam too). If you "
                         "signed up with **Google**, there's no password: use *Continue with Google* instead.",
                "actions": [_act("link", "Reset my password", url="/forgot-password.html"),
                            _act("link", "Sign in", url="/login.html")]}

    if name == "login":
        if signed:
            return {"reply": f"You're signed in right now as **{acct.get('email')}**. If another device won't "
                             "sign in, use the same method you signed up with (Google or email + password).",
                    "actions": [_act("link", "My profile", url="/profile.html")]}
        return {"reply": "Most sign-in problems are one of these:\n- You signed up with **Google** - use "
                         "*Continue with Google*, there's no password.\n- Forgotten password - reset it by email.\n"
                         "- Wrong email - try the other address you use.\nStill stuck? Send this to Tee.",
                "actions": [_act("link", "Reset my password", url="/forgot-password.html"),
                            _act("link", "Sign in", url="/login.html"), HANDOFF]}

    if name == "pricing":
        m = _billing.PERIODS["monthly"]["amount"]
        lab = _billing.PLAN_LABELS
        others = [p for k, p in _billing.PERIODS.items() if k != "monthly"]
        reply = (f"**Free**: {fr['topical_paper']} topical booklets + {fr['topic_test']} mock tests a month, "
                 "every paper by year, MCQs and tools.\n"
                 + "\n".join(f"- **{lab[k]}**: {_pkr(v)}/month" for k, v in m.items())
                 + "\n\nSession packages: " + "; ".join(
                     f"{p['label']} - " + ", ".join(f"{lab[k]} {_pkr(v)}" for k, v in p["amount"].items())
                     for p in others)
                 + f".\n\nPay by JazzCash, EasyPaisa or bank transfer and upload the screenshot. "
                 f"Live classes are separate: O Level/IGCSE {_pkr(CLASSES['olevel_price'])}/month.")
        actions = [_act("link", "See plans", url="/pricing.html#plans"),
                   _act("say", "Which plan fits me?", text="Which plan should I get?")]
        if acct.get("trial_eligible"):
            actions.insert(0, _act("trial", f"Try everything free for {f['trial_days']} days"))
        return {"reply": reply, "actions": actions}

    if name == "plan_advice":
        return plan_advice(text, acct)

    if name == "classes":
        c = CLASSES
        started = date.today() >= c["start"]
        reply = (f"**Live classes with Tee** - Maths, Physics and Computer Science "
                 f"{'started' if started else 'start'} **{c['start']:%d %B}**"
                 f"{' (late joiners welcome)' if started else ''}: {c['shape']}.\n"
                 f"- O Level & IGCSE: **{_pkr(c['olevel_price'])}/month**\n"
                 f"- {c['a_level']}: from **{_pkr(c['alevel_from'])}/month**\n"
                 f"- Private 1-on-1: from {_pkr(TUTORING['solo_from'])}/month\n\nThe first demo class is free.")
        demo = WA_URL + "?text=" + _quote("Hi Tee! I'd like to book a FREE DEMO class.\n\nSubject + level: \n"
                                           "Exam session: \nStudent's name: ")
        return {"reply": reply,
                "actions": [_act("link", "Book a free demo", url=demo, external=True),
                            _act("link", "All courses", url=c["all"])],
                "links": [{"t": t, "s": "Week-by-week plan, fees, timings", "u": u} for t, u in c["pages"]]}

    if name == "parent":
        return {"reply": "Parents get their own dashboard: link it with your child's **student code** "
                         "(on their Profile page) and you'll see their papers, marks, streaks and homework. "
                         f"For classes with Tee, O Level/IGCSE batches are {_pkr(CLASSES['olevel_price'])}/month "
                         "and the first demo is free.",
                "actions": [_act("link", "Parent dashboard", url="/parent-dashboard.html"),
                            _act("say", "Tell me about the classes", text="Tell me about the live classes"),
                            _act("link", "WhatsApp Tee", url=WA_URL, external=True)]}

    if name == "contact":
        h = hours()
        return {"reply": f"You can reach Tee two ways:\n- **Send this chat to Tee** from here - it goes "
                         "straight to Tee's inbox with your account details, and the reply comes back here "
                         f"and by email.\n- **WhatsApp**: {WHATSAPP}\n\n{h['text']}",
                "actions": [HANDOFF, _act("link", "WhatsApp Tee", url=WA_URL, external=True)]}

    if name == "subjects":
        reply = f"All Cambridge, papers from {COVERAGE}:\n" + "\n".join(
            f"- **{b}**: {', '.join(v)}" for b, v in f["subjects"].items())
        return {"reply": reply, "actions": [_act("link", "Browse subjects", url="/papers")]}

    if name == "problem":
        return {"reply": "Sorry about that. Tell me what you were doing and what happened - or send it straight "
                         "to Tee: your page, browser and any errors are attached automatically, and you can add "
                         "a screenshot.",
                "actions": [HANDOFF], "suggest_handoff": True}
    return None


def _quote(s: str) -> str:
    from urllib.parse import quote
    return quote(s)


def _months_until(d: date) -> int:
    today = date.today()
    return max(1, (d.year - today.year) * 12 + d.month - today.month + (1 if d.day >= today.day else 0))


def plan_advice(text: str, acct: dict) -> dict:
    """Two quick questions -> a recommendation with the real saving."""
    t = (text or "").lower()
    m = re.search(r"(\d+)\s*(?:subjects?|subject)", t)
    n = int(m.group(1)) if m else (1 if _has(" " + t + " ", "one subject", "1 subject", "single") else
                                   3 if _has(" " + t + " ", "three", "2 subjects", "two subjects") else
                                   4 if _has(" " + t + " ", "all subjects", "4 subjects", "many", "every") else None)
    if n is None:
        return {"reply": "Two quick questions. **How many subjects** do you want help with?",
                "actions": [_act("say", "1 subject", text="Which plan for 1 subject?"),
                            _act("say", "2-3 subjects", text="Which plan for 3 subjects?"),
                            _act("say", "4 or more", text="Which plan for 4 subjects?")]}
    plan = "solo" if n <= 1 else "three" if n <= 3 else "all"
    lab = _billing.PLAN_LABELS[plan]
    P = _billing.PERIODS
    monthly = P["monthly"]["amount"][plan]
    lines = [f"For {n} subject{'s' if n != 1 else ''}, **{lab}** fits: {_pkr(monthly)}/month."]
    session = "mayjun" if _has(" " + t + " ", "may", "june", "2027", "summer") else \
        "octnov" if _has(" " + t + " ", "oct", "nov", "october", "november") else None
    if session and session in P and P[session].get("until"):
        until = date.fromisoformat(P[session]["until"])
        if until > date.today():
            months = _months_until(until)
            pkg = P[session]["amount"][plan]
            save = monthly * months - pkg
            lines.append(f"Your exams are in **{P[session]['label']}** - about {months} months of monthly payments "
                         f"({_pkr(monthly * months)}). The session package is **{_pkr(pkg)}**"
                         + (f", saving **{_pkr(save)}**." if save > 0 else "."))
    elif not session:
        return {"reply": lines[0] + " And **when are your exams?** Session packages are cheaper than paying monthly.",
                "actions": [_act("say", "Oct/Nov 2026", text=f"Which plan for {n} subjects, exams in Oct/Nov?"),
                            _act("say", "May/June 2027", text=f"Which plan for {n} subjects, exams in May/June 2027?"),
                            _act("link", "See all plans", url="/pricing.html#plans")]}
    yearly = P["yearly"]["amount"][plan]
    lines.append(f"Yearly is {_pkr(yearly)} ({_pkr(round(yearly / 12))}/month).")
    actions = [_act("link", f"Choose {lab}", url=f"/pricing.html?plan={plan}#plans")]
    if acct.get("trial_eligible"):
        actions.append(_act("trial", "Try it free for 7 days first"))
    return {"reply": "\n".join(lines), "actions": actions}


# ── AI answer ────────────────────────────────────────────────────────────────

RULES = """You are the PrepWithTee help assistant on prepwithtee.com (Cambridge O Level, IGCSE and A Level past papers, revision and live classes, run by Tee from Lahore, Pakistan).

RULES
1. 2-5 short sentences, or a short list. Markdown: **bold**, "- " lists, [label](/path) links.
2. Only state prices, limits, dates and features that appear in the FACTS. If you don't know, say so and suggest "Send this to Tee".
3. Only link to pages listed in the FACTS or in RELEVANT PAGES. Never invent a URL.
4. Answer in the language the student wrote in: English, Urdu, or Roman Urdu (Urdu in Latin letters).
5. You are support, not a subject tutor: for a maths/physics/CS question, send them to the Photo Solver (/solver) or AI Tutor (/tutor.html).
6. Never ask for passwords or card/account numbers. You can't change plans or approve payments - Tee does that.
7. Warm, direct, no filler ("Great question!")."""


def _ai_messages(text: str, history: list[dict], acct: dict, page: str, links: list[dict], lang: str) -> list[dict]:
    ctx = ["== THE STUDENT =="]
    if acct.get("signed_in"):
        ctx.append(f"Signed in as {acct.get('name') or 'a student'} ({acct.get('role')}), plan "
                   f"{acct.get('plan_label')}{' (trial)' if acct.get('trial') else ''}.")
        for a in acct.get("allowance") or []:
            if a["limit"] is not None:
                ctx.append(f"{a['label']}: {a['used']} of {a['limit']} used this month.")
        if acct.get("trial_eligible"):
            ctx.append("Can still start the free 7-day trial.")
    else:
        ctx.append("Not signed in.")
    ctx.append(f"Current page: {page or 'unknown'}")
    if links:
        ctx.append("\n== RELEVANT PAGES ==\n" + "\n".join(f"- {l['t']}: {l['u']}" for l in links))
    if lang != "en":
        ctx.append("\nThe student is writing in " + ("Urdu script" if lang == "ur" else "Roman Urdu")
                   + " - reply the same way.")
    msgs = [{"role": "system", "content": f"{RULES}\n\n== FACTS ==\n{facts_text()}\n\n" + "\n".join(ctx)}]
    for h in (history or [])[-6:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            msgs.append({"role": h["role"], "content": str(h["content"])[:600]})
    msgs.append({"role": "user", "content": text[:1000]})
    return msgs


def _ai(messages: list[dict], max_tokens: int = 450) -> str | None:
    """First free provider that answers. Tests set AI_CALL."""
    if AI_CALL is not None:
        return AI_CALL(messages)
    try:
        import content_ai
        from pipeline import ai_providers
        for name in content_ai.providers():
            try:
                text, _u, _m, _h = ai_providers.call(name, messages, max_tokens=max_tokens, temperature=0.3)
                text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
                if text:
                    return text
            except Exception as exc:
                print(f"[support] {name} failed: {str(exc)[:120]}", flush=True)
    except Exception as exc:
        print(f"[support] providers unavailable: {exc}", flush=True)
    try:
        text, _p = _app()._chat_complete(messages, max_tokens=max_tokens)
        return text
    except Exception:
        return None


AI_CALL = None          # tests: a function(messages) -> str


def translate(reply: str, lang: str) -> str:
    if lang == "en" or not reply:
        return reply
    out = _ai([{"role": "system", "content": "Rewrite the message in " + ("Urdu" if lang == "ur" else
                "Roman Urdu (Urdu written in Latin letters, the way Pakistani students text)")
                + ". Keep every markdown link, number, price and **bold** exactly. Reply with the message only."},
               {"role": "user", "content": reply}], max_tokens=500)
    return clean_links(out) if out else reply


# ── Rate limit ───────────────────────────────────────────────────────────────

_hits: dict[str, list[float]] = {}
_hits_lock = threading.Lock()
LIMIT_USER, LIMIT_GUEST, WINDOW = 60, 25, 3600


def _rate(key: str, limit: int) -> bool:
    now = time.time()
    with _hits_lock:
        h = [t for t in _hits.get(key, []) if now - t < WINDOW]
        if len(h) >= limit:
            _hits[key] = h
            return False
        h.append(now)
        _hits[key] = h
        if len(_hits) > 5000:
            for k in [k for k, v in _hits.items() if not v or now - v[-1] > WINDOW]:
                _hits.pop(k, None)
    return True


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/api/support/context")
def context(user: dict | None = Depends(_auth.maybe_user)):
    st = load_status()
    return {**account(user), "hours": hours(status=st), "banner": banner(st),
            "whatsapp": WHATSAPP, "whatsapp_url": WA_URL}


class ChatReq(BaseModel):
    message: str
    history: list[dict] | None = None
    page: str | None = None


@router.post("/api/support/chat")
def chat(req: ChatReq, request: Request, user: dict | None = Depends(_auth.maybe_user)):
    text = (req.message or "").strip()
    if not text:
        raise HTTPException(400, "Type your question.")
    text = text[:1000]
    key, limit = (f"u:{user['id']}", LIMIT_USER) if user else (f"ip:{_app()._client_ip(request)}", LIMIT_GUEST)
    if not _rate(key, limit):
        raise HTTPException(429, {"code": "support_rate", "message":
                                  "That's a lot of questions in one hour - send this chat to Tee, or "
                                  f"WhatsApp {WHATSAPP}."})
    page = (req.page or "")[:200]
    lang = language(text)
    name = intent(text)
    acct = account(user) if user and name in ("payment_status", "booklet_problem", "quota", "trial", "login",
                                              "pricing", "plan_advice") else \
        (account(user) if user else {"signed_in": False})
    out = answer_intent(name, text, acct) if name else None
    source = "intent"
    if out is None and wants_navigation(text):
        out = navigate(text)
        source, name = "navigate", name or "navigate"
    if out is not None:
        out = {"reply": out["reply"], "actions": out.get("actions") or [], "links": out.get("links") or [],
               "suggest_handoff": bool(out.get("suggest_handoff"))}
        out["reply"] = translate(out["reply"], lang)
    else:
        source = "ai"
        hits = _search(text, [], limit=5)
        reply = _ai(_ai_messages(text, req.history or [], acct, page, hits, lang))
        if not reply:
            source = "fallback"
            reply = ("I can't reach my AI helper right now. You can still **send this to Tee** - the reply "
                     f"comes back here and by email - or WhatsApp {WHATSAPP}.")
            out = {"reply": reply, "actions": [HANDOFF], "links": hits[:3], "suggest_handoff": True}
        else:
            reply = clean_links(reply.strip())
            unsure = bool(re.search(r"send this to tee|not sure|don't know|do not know|can't help|cannot help",
                                    reply.lower()))
            out = {"reply": reply, "actions": [HANDOFF] if unsure else [], "links": hits[:3],
                   "suggest_handoff": unsure}
    out["intent"] = name
    out["source"] = source
    out["event_id"] = _store.log_event("ask", user_id=(user or {}).get("id"), intent=name or source,
                                       question=text, answer=out["reply"], page=page, lang=lang)
    return out


class VoteReq(BaseModel):
    event_id: int
    vote: int


@router.post("/api/support/vote")
def vote(req: VoteReq, user: dict | None = Depends(_auth.maybe_user)):
    if req.vote not in (-1, 1):
        raise HTTPException(400, "vote must be 1 or -1")
    ev = _store.get_event(req.event_id)
    if not ev or ev.get("kind") != "ask":
        raise HTTPException(404, "Answer not found")
    if ev.get("user_id") and ev["user_id"] != (user or {}).get("id"):
        raise HTTPException(403, "Not your answer")
    _store.set_vote(req.event_id, req.vote)
    return {"ok": True}


class TrackReq(BaseModel):
    action: str
    page: str | None = None


@router.post("/api/support/track")
def track(req: TrackReq, user: dict | None = Depends(_auth.maybe_user)):
    act = re.sub(r"[^a-z_-]", "", (req.action or "").lower())[:30]
    if act:
        _store.log_event("action", user_id=(user or {}).get("id"), intent=act, page=(req.page or "")[:200])
    return {"ok": True}


_DIAG_KEYS = {"url", "ua", "screen", "viewport", "theme", "lang", "tz", "errors", "failed", "online", "memory",
              "connection", "dpr"}


def clean_diag(d: dict | None) -> dict:
    out = {}
    for k, v in (d or {}).items():
        if k not in _DIAG_KEYS:
            continue
        if isinstance(v, list):
            v = [str(x)[:300] for x in v[:10]]
        elif isinstance(v, (dict,)):
            v = {str(a)[:40]: str(b)[:120] for a, b in list(v.items())[:10]}
        else:
            v = str(v)[:400]
        out[k] = v
    return out


class HandoffReq(BaseModel):
    name: str | None = None
    email: str | None = None
    message: str | None = None
    transcript: list[dict] | None = None
    page: str | None = None
    diag: dict | None = None
    snips: list[str] | None = None


@router.post("/api/support/handoff")
def handoff(req: HandoffReq, user: dict | None = Depends(_auth.maybe_user)):
    a = _app()
    _notify, _save_snips, _valid_email = a._notify, a._save_snips, a._valid_email
    name = (req.name or "").strip()[:120]
    if len(name) < 2:
        raise HTTPException(400, "Please enter your name.")
    email = _valid_email(req.email, (user or {}).get("email"))
    msg = (req.message or "").strip()[:2000]
    transcript = [{"role": "student" if m.get("role") == "user" else "assistant",
                   "text": str(m.get("content") or m.get("text") or "")[:1500]}
                  for m in (req.transcript or [])[-30:]
                  if m.get("role") in ("user", "assistant", "student") and (m.get("content") or m.get("text"))]
    if not msg and not transcript:
        raise HTTPException(400, "Tell Tee what you need help with.")
    if not msg:
        msg = next((m["text"] for m in reversed(transcript) if m["role"] == "student"), "")[:2000]
    diag = clean_diag(req.diag)
    snips = _save_snips(req.snips)
    page = (req.page or "")[:300]
    tid = _store.add_thread({"user_id": (user or {}).get("id"), "name": name, "email": email, "page": page,
                             "message": msg, "transcript_json": transcript, "diag_json": diag,
                             "snips_json": snips})
    if tid is None:                      # migration 030 not run yet: still reach Tee
        convo = "\n".join(f"{m['role']}: {m['text']}" for m in transcript)
        _udb.save_feedback({"message": (msg + "\n\n--- chat ---\n" + convo)[:6000], "name": name, "email": email,
                            "page": page, "type": "support",
                            "attachments": json.dumps(snips) if snips else None})
    _store.log_event("handoff", user_id=(user or {}).get("id"), intent="handoff", question=msg, page=page,
                     ref_id=tid)
    acct = account(user) if user else {"signed_in": False}
    plan = acct.get("plan_label") or "guest"
    convo = "\n".join(f"{'Student' if m['role'] == 'student' else 'Assistant'}: {m['text']}" for m in transcript)
    _notify(f"[PrepWithTee] Help request from {name} - {page or 'site'}",
            f"Name: {name}\nEmail: {email}\nPlan: {plan}\nPage: {page}\n\n{msg}\n\n--- chat ---\n{convo}\n\n"
            f"--- device ---\n{json.dumps(diag, indent=1)}",
            rows=[("Name", name), ("Email", email), ("Plan", plan), ("Page", page or "-"), ("Message", msg),
                  *([("Screenshots", f"{len(snips)} attached - see the admin Inbox")] if snips else [])],
            cta=("Open the Inbox", os.environ.get("APP_BASE_URL", "https://prepwithtee.com").rstrip("/")
                 + "/admin#inbox"))
    return {"ok": True, "id": tid, "hours": hours()}


@router.get("/api/support/threads")
def threads(user: dict = Depends(_auth.get_current_user)):
    rows = _store.list_threads(user["id"], limit=30)
    st = _safe(_udb.list_inbox_status, {})
    out = []
    for r in rows:
        s = st.get(("support", str(r["id"])), {})
        replies = s.get("replies_json") or []
        if isinstance(replies, str):
            try:
                replies = json.loads(replies)
            except ValueError:
                replies = []
        out.append({"id": r["id"], "at": r["created_at"], "message": r["message"], "page": r.get("page"),
                    "status": s.get("status") or "new",
                    "replies": [{"at": x.get("at"), "body": x.get("body"), "subject": x.get("subject")}
                                for x in replies]})
    return {"threads": out}


# ── Admin ────────────────────────────────────────────────────────────────────

def report(days: int = 7) -> dict:
    evs = _store.events_since(days)
    asks = [e for e in evs if e["kind"] == "ask"]
    by_intent: dict[str, int] = {}
    for e in asks:
        by_intent[e.get("intent") or "other"] = by_intent.get(e.get("intent") or "other", 0) + 1
    unanswered = [e for e in asks if e.get("intent") in ("fallback",) or
                  re.search(r"send this to tee|not sure|don't know", (e.get("answer") or "").lower())]
    down = [e for e in asks if (e.get("vote") or 0) < 0]
    up = sum(1 for e in asks if (e.get("vote") or 0) > 0)
    actions: dict[str, int] = {}
    for e in evs:
        if e["kind"] == "action":
            actions[e.get("intent") or "?"] = actions.get(e.get("intent") or "?", 0) + 1
    # most-asked questions, grouped by a normalised form
    groups: dict[str, dict] = {}
    for e in asks:
        k = re.sub(r"[^a-z0-9 ]", "", (e.get("question") or "").lower()).strip()[:80]
        if k:
            g = groups.setdefault(k, {"question": e.get("question"), "count": 0, "intent": e.get("intent")})
            g["count"] += 1

    def slim(e):
        return {"id": e["id"], "ts": e["ts"], "question": e.get("question"), "answer": e.get("answer"),
                "intent": e.get("intent"), "page": e.get("page"), "signed_in": bool(e.get("user_id"))}
    return {"days": days, "asked": len(asks), "people": len({e.get("user_id") or f"g{e['id']}" for e in asks}),
            "handoffs": sum(1 for e in evs if e["kind"] == "handoff"), "up": up, "down": len(down),
            "by_intent": sorted(by_intent.items(), key=lambda x: -x[1]), "actions": actions,
            "top": sorted(groups.values(), key=lambda g: -g["count"])[:15],
            "unanswered": [slim(e) for e in unanswered[:30]], "downvoted": [slim(e) for e in down[:30]]}


@router.get("/api/admin/support/report")
def admin_report(days: int = 7, _=Admin):
    _store.prune_guest_events()
    return report(max(1, min(days, 90)))


class StatusReq(BaseModel):
    banner_text: str | None = None
    banner_tone: str | None = None
    banner_until: str | None = None
    hours_start: int | None = None
    hours_end: int | None = None
    hours_days: list[int] | None = None
    away: str | None = None


@router.get("/api/admin/support/status")
def admin_status(_=Admin):
    st = load_status()
    return {"status": st, "hours": hours(status=st), "banner": banner(st)}


@router.put("/api/admin/support/status")
def admin_set_status(req: StatusReq, _=Admin):
    st = load_status()
    b = st.get("banner") or {}
    if req.banner_text is not None:
        b["text"] = req.banner_text.strip()[:300]
    if req.banner_tone is not None:
        b["tone"] = req.banner_tone if req.banner_tone in ("info", "warn", "ok") else "info"
    if req.banner_until is not None:
        b["until"] = req.banner_until.strip()[:10] or None
    st["banner"] = b if b.get("text") else {}
    h = {**DEFAULT_HOURS, **(st.get("hours") or {})}
    if req.hours_start is not None:
        h["start"] = max(0, min(23, req.hours_start))
    if req.hours_end is not None:
        h["end"] = max(1, min(24, req.hours_end))
    if req.hours_days is not None:
        h["days"] = sorted({d for d in req.hours_days if 0 <= d <= 6})
    if h["end"] <= h["start"]:
        raise HTTPException(400, "Office hours must end after they start.")
    st["hours"] = h
    if req.away is not None:
        st["away"] = req.away.strip()[:200] or None
    save_status(st)
    return {"status": st, "hours": hours(status=st), "banner": banner(st)}


def account_summary(r: dict) -> dict | None:
    """What Tee needs to see beside a help request: plan, expiry, failed builds, payment."""
    acct = None
    if r.get("user_id"):
        u = _safe(lambda: _udb.get_user(r["user_id"]), None)
        if u:
            info = _safe(lambda: _access.plan_info(u), {"plan": u.get("plan") or "free"})
            bks = _safe(lambda: _recent_booklets(u), [])
            acct = {"id": u["id"], "plan": _access.PLAN_LABELS.get(info.get("plan"), info.get("plan")),
                    "expires_at": info.get("expires_at"), "trial": bool(info.get("trial")),
                    "failed": [{"title": b["title"], "why": b.get("why")} for b in bks if b["status"] == "failed"][:3],
                    "payment": _safe(lambda: _payment(u), None),
                    "last_seen": u.get("last_seen_at")}
    return acct


@router.get("/api/admin/support/{thread_id}/account")
def admin_thread_account(thread_id: int, _=Admin):
    r = _store.get_thread(thread_id)
    if not r:
        raise HTTPException(404, "Request not found")
    return {"account": account_summary(r)}


@router.post("/api/admin/support/{thread_id}/draft")
def admin_draft(thread_id: int, _=Admin):
    r = _store.get_thread(thread_id)
    if not r:
        raise HTTPException(404, "Request not found")
    convo = "\n".join(f"{m['role']}: {m['text']}" for m in r.get("transcript_json") or [])
    acct = json.dumps(account_summary(r) or {"signed_in": False}, default=str)
    import content_ai
    try:
        out, model = content_ai.generate(
            content_ai.VOICE + "\n\nYou draft Tee's email reply to a student's help request. Be specific, "
            "solve the problem if the facts allow, keep it under 150 words, sign off as Tee. Use only these "
            "facts:\n" + facts_text(),
            f"Student: {r['name']}\nPage: {r.get('page')}\nAccount: {acct}\nMessage: {r['message']}\n\nChat:\n{convo}",
            {"subject": ("str", True), "body": ("str", True)}, max_tokens=900, temperature=0.4)
    except content_ai.AIUnavailable as exc:
        raise HTTPException(503, str(exc))
    return {"subject": out["subject"][:150], "body": out["body"][:3000], "model": model}
