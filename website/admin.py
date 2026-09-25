"""Admin API for PrepWithTee — everything the tutor needs behind one key.

Surfaces every form the site collects (demo bookings, feedback/issues, subject
requests, teacher applications), the Calendly booking calendar, per-student
progress logs, and teacher management (approve an applicant, then edit their
public card and assign the subjects they teach).

Auth is a single shared key, supplied as `?key=`, an `X-Admin-Key` header, or
an `admin_key` cookie. The key is compared in constant time. This is a
single-operator tool, so a shared secret is the right weight — but it means
ADMIN_KEY must be set in the environment on any public deployment.
"""

import json
import os
import random as _random
import re
import secrets
import smtplib
import string as _string
import time
import uuid as _uuid
from email.mime.text import MIMEText as _MIMEText
from pathlib import Path

import requests
from fastapi import (APIRouter, Cookie, Depends, File, Form, Header,
                     HTTPException, Query, UploadFile)
from jose import JWTError, jwt as _jwt
from pydantic import BaseModel

import users_db as _udb

router = APIRouter(prefix="/api/admin")

ROOT = Path(__file__).resolve().parent.parent
TAXONOMY_DIR = ROOT / "taxonomy"
RESOURCES_DIR = ROOT / "data" / "resources"
# Homework attachments land outside data/resources so they can never show up in
# the public Resources browser — they are one student's worksheet, not a note.
UPLOADS_DIR = ROOT / "data" / "uploads" / "homework"

STATUSES = {"not_started", "learning", "confident"}

ADMIN_KEY = (os.environ.get("ADMIN_ACCESS_KEY")
             or os.environ.get("ADMIN_KEY")
             or "prepwithtee-admin-2026")

_JWT_SECRET = os.environ.get("SECRET_KEY", "dev-only-change-me-in-production")
_JWT_ALG = "HS256"

SUBJECT_NAMES = {
    "4024": "O Level Mathematics D",
    "0580": "IGCSE Mathematics",
    "5054": "O Level Physics",
    "0625": "IGCSE Physics",
    "2210": "O Level Computer Science",
    "0478": "IGCSE Computer Science",
    "5070": "O Level Chemistry",
    "0620": "IGCSE Chemistry",
    "9709": "A Level Mathematics",
    "9702": "A Level Physics",
    "9618": "A Level Computer Science",
}


# ── Auth ─────────────────────────────────────────────────────────────────────

def require_admin(
    key: str | None = Query(None),
    x_admin_key: str | None = Header(None),
    admin_key: str | None = Cookie(None),
    session: str | None = Cookie(None),
) -> bool:
    # Preferred: JWT session cookie with role='admin'
    if session:
        try:
            payload = _jwt.decode(session, _JWT_SECRET, algorithms=[_JWT_ALG])
            u = payload.get("u", {})
            if u.get("role") == "admin":
                return True
        except (JWTError, Exception):
            pass
    # Legacy: shared admin key via query param, header, or cookie
    supplied = key or x_admin_key or admin_key or ""
    if supplied and secrets.compare_digest(supplied, ADMIN_KEY):
        return True
    raise HTTPException(401, "Invalid or missing admin credentials")


_Admin = Depends(require_admin)


# ── Teacher account helpers ───────────────────────────────────────────────────

def _generate_temp_password(length: int = 12) -> str:
    chars = _string.ascii_letters + _string.digits
    pwd = (
        _random.choice(_string.ascii_uppercase) +
        _random.choice(_string.digits) +
        ''.join(_random.choice(chars) for _ in range(length - 2))
    )
    return ''.join(_random.sample(pwd, len(pwd)))


def _send_teacher_welcome(to_email: str, name: str, temp_password: str) -> tuple[bool, str]:
    """Email the new teacher their login credentials. Returns (success, error_message)."""
    import logging
    log = logging.getLogger(__name__)

    base_url = os.environ.get("APP_BASE_URL", "https://prepwithtee.com")
    subject = "Welcome to PrepWithTee — your teacher account is ready"
    body = (
        f"Hi {name},\n\n"
        f"Your PrepWithTee teacher account has been approved!\n\n"
        f"Login page: {base_url}/login.html\n"
        f"Email: {to_email}\n"
        f"Temporary password: {temp_password}\n\n"
        f"You will be asked to set a new password on your first login.\n\n"
        f"If you have any questions, reply to this email.\n\n"
        f"PrepWithTee Team"
    )
    smtp_user = os.environ.get("SMTP_USER", "")

    resend_key = os.environ.get("RESEND_API_KEY")
    if resend_key:
        # Use SMTP_USER as from if it's a verified domain address; fallback to
        # the Resend test sender which works without domain verification.
        from_addr = (f"PrepWithTee <{smtp_user}>" if smtp_user else
                     "PrepWithTee <onboarding@resend.dev>")
        try:
            r = requests.post(
                "https://api.resend.com/emails",
                json={"from": from_addr, "to": [to_email],
                      "subject": subject, "text": body},
                headers={"Authorization": f"Bearer {resend_key}"},
                timeout=10,
            )
            if r.status_code < 300:
                return True, ""
            err = f"Resend {r.status_code}: {r.text[:200]}"
            log.warning("_send_teacher_welcome Resend failed: %s", err)
        except Exception as exc:
            err = str(exc)
            log.warning("_send_teacher_welcome Resend exception: %s", exc)
    else:
        err = "No RESEND_API_KEY"

    smtp_pass = os.environ.get("SMTP_PASS")
    if smtp_user and smtp_pass:
        try:
            msg = _MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = smtp_user
            msg["To"] = to_email
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=8) as srv:
                srv.starttls()
                srv.login(smtp_user, smtp_pass)
                srv.sendmail(smtp_user, to_email, msg.as_string())
            return True, ""
        except Exception as exc:
            err = str(exc)
            log.warning("_send_teacher_welcome SMTP exception: %s", exc)
    return False, err


# ── Helpers ──────────────────────────────────────────────────────────────────

def _subjects_of(teacher: dict) -> list[str]:
    """subjects_json is stored as a JSON string; tolerate it already being a list."""
    raw = teacher.get("subjects_json")
    if isinstance(raw, list):
        return raw
    try:
        val = json.loads(raw or "[]")
        return val if isinstance(val, list) else []
    except (TypeError, ValueError):
        return []


def _decorate_teacher(t: dict) -> dict:
    codes = _subjects_of(t)
    return {**t, "subjects": codes,
            "subject_names": [SUBJECT_NAMES.get(c, c) for c in codes]}


def _student_or_404(user_id: str) -> dict:
    user = _udb.get_user(user_id)
    if user is None:
        raise HTTPException(404, "No such student")
    return user


def _json_list(raw) -> list:
    """attachments_json / topics_json come back as text from SQLite and as a
    parsed list from Supabase's jsonb. Normalise both to a list."""
    if isinstance(raw, list):
        return raw
    try:
        val = json.loads(raw or "[]")
        return val if isinstance(val, list) else []
    except (TypeError, ValueError):
        return []


def _decorate_assignment(a: dict) -> dict:
    return {**a,
            "topics": _json_list(a.get("topics_json")),
            "attachments": _json_list(a.get("attachments_json")),
            "submissions": _json_list(a.get("student_submissions_json")),
            "subject_name": SUBJECT_NAMES.get(a.get("syllabus"), a.get("syllabus"))}


# ── Overview ─────────────────────────────────────────────────────────────────

@router.get("/overview")
def overview(_: bool = _Admin):
    """Cheap enough to double as the key-check the dashboard gate calls.

    Deliberately does no counting: the dashboard fetches every list anyway, so
    tallying here would double the queries against Supabase for no new data.
    """
    return {"subject_options": [{"code": c, "name": n}
                                for c, n in SUBJECT_NAMES.items()]}


# ── Form submissions ─────────────────────────────────────────────────────────

@router.get("/leads")
def leads(_: bool = _Admin):
    return {"leads": _udb.get_leads()}


@router.get("/feedback")
def feedback(_: bool = _Admin):
    return {"feedback": _udb.get_feedback()}


@router.get("/subject-requests")
def subject_requests(_: bool = _Admin):
    return {"subject_requests": _udb.get_subject_requests()}


# ── Students ─────────────────────────────────────────────────────────────────

@router.get("/students")
def students(_: bool = _Admin):
    rows = _udb.list_students()
    open_hw = _udb.count_open_assignments([r["id"] for r in rows])
    for r in rows:
        r["subject_names"] = [SUBJECT_NAMES.get(s, s) for s in r.get("subjects", [])]
        r["open_homework"] = open_hw.get(r["id"], 0)
        r["missing_fields"] = _missing_fields(r)
    return {"students": rows}


def _missing_fields(s: dict) -> list[str]:
    """Return the list of profile fields this student still needs to fill."""
    missing = []
    if not (s.get("name") or "").strip():
        missing.append("name")
    if not s.get("grade"):
        missing.append("qualification")
    if not s.get("phone"):
        missing.append("WhatsApp number")
    if not s.get("subjects"):
        missing.append("subjects")
    return missing


@router.post("/students/nudge-incomplete")
def nudge_incomplete(key: str | None = None, _: bool = _Admin):
    """Email every student who has an incomplete profile."""
    from app import _notify

    rows = _udb.list_students()
    base = "https://prepwithtee.com"
    sent: list[str] = []
    skipped: list[str] = []

    for s in rows:
        missing = _missing_fields(s)
        if not missing:
            skipped.append(s["id"])
            continue

        email = (s.get("email") or "").strip()
        if not email:
            continue

        first = (s.get("name") or "there").split()[0]
        missing_str = ", ".join(missing)
        subject = "[PrepWithTee] Please complete your profile"
        body = (
            f"Hi {first},\n\n"
            f"We noticed your PrepWithTee profile is missing: {missing_str}.\n\n"
            f"Complete your profile so your tutor can reach you and so your "
            f"dashboard is fully personalised for your subjects:\n\n"
            f"  {base}/profile.html?setup=1\n\n"
            f"It only takes a minute!\n\n"
            f"Tee  ·  PrepWithTee\n"
            f"{base}"
        )

        missing_items_html = "".join(
            f'<li style="margin:4px 0;font-size:.88rem;color:#555">{m}</li>'
            for m in missing
        )
        html = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f4f0ea;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td style="padding:32px 16px">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;margin:0 auto">
  <tr><td style="background:#2E1B4A;border-radius:12px 12px 0 0;padding:22px 28px">
    <p style="color:#C9BDF0;font-size:.75rem;margin:0;letter-spacing:.06em;text-transform:uppercase">PrepWithTee</p>
    <h1 style="color:#fff;font-size:1.1rem;margin:6px 0 0;font-weight:700">Complete your profile, {first} 🦉</h1>
  </td></tr>
  <tr><td style="background:#fff;padding:24px 28px 28px;border-radius:0 0 12px 12px;box-shadow:0 2px 16px rgba(0,0,0,.08)">
    <p style="margin:0 0 14px;font-size:.9rem;color:#333;line-height:1.6">
      Hi {first}, your PrepWithTee account is set up but a few details are still missing:
    </p>
    <ul style="margin:0 0 18px;padding-left:20px;line-height:1.7">
      {missing_items_html}
    </ul>
    <p style="margin:0 0 20px;font-size:.88rem;color:#555;line-height:1.6">
      Filling these in lets your tutor reach you on WhatsApp and makes your dashboard
      fully personalised to your subjects and level.
    </p>
    <p style="margin:0 0 8px;text-align:center">
      <a href="{base}/profile.html?setup=1"
         style="display:inline-block;background:#E8913A;color:#fff;text-decoration:none;
                font-weight:700;font-size:.92rem;padding:12px 28px;border-radius:10px">
        Complete my profile →
      </a>
    </p>
    <p style="margin:20px 0 0;font-size:.78rem;color:#aaa;text-align:center">
      PrepWithTee &nbsp;·&nbsp; <a href="{base}" style="color:#aaa">{base}</a>
    </p>
  </td></tr>
</table></td></tr></table>
</body></html>"""

        ok = _notify(subject, body, to=email, html_override=html)
        if ok:
            sent.append(email)

    return {"sent": len(sent), "skipped": len(skipped), "emails": sent}


@router.get("/students/{user_id}")
def student_detail(user_id: str, _: bool = _Admin):
    detail = _udb.get_student_detail(user_id)
    if detail is None:
        raise HTTPException(404, "No such student")

    # Group topic progress by syllabus so the drill-down reads subject by subject.
    #
    # The percentage is confident CHAPTERS over the chapters in the syllabus.
    # It used to be confident rows over *touched* rows, which made a student who
    # had ticked 14 subtopics of a single chapter show "14 confident — 100%".
    # Two separate faults there: subtopics counted as chapters, and the
    # denominator was whatever happened to be in the table.
    by_syllabus: dict[str, dict] = {}
    for p in detail["progress"]:
        syl = p.get("syllabus") or "?"
        entry = by_syllabus.setdefault(syl, {
            "syllabus": syl, "name": SUBJECT_NAMES.get(syl, syl),
            "topics": [], "subtopics": [],
            "confident": 0, "learning": 0, "not_started": 0,
            "sub_confident": 0, "chapters_total": 0})
        status = p.get("status") or "not_started"
        if p.get("subtopic"):
            entry["subtopics"].append(p)
            if status == "confident":
                entry["sub_confident"] += 1
        else:
            entry["topics"].append(p)
            if status in entry:
                entry[status] += 1

    for syl, entry in by_syllabus.items():
        try:
            entry["chapters_total"] = len(_taxonomy(syl)["topics"])
        except HTTPException:
            entry["chapters_total"] = len(entry["topics"])   # unknown syllabus
        # Chapters the student has never opened are genuinely "not started";
        # only counting rows that exist understates the work left.
        entry["not_started"] = max(
            0, entry["chapters_total"] - entry["confident"] - entry["learning"])
        entry["pct"] = (round(entry["confident"] / entry["chapters_total"] * 100)
                        if entry["chapters_total"] else 0)

    quizzes = detail["quizzes"]
    scored = [q["score"] for q in quizzes if q.get("score") is not None]

    for e in detail["enrollments"]:
        e["name"] = SUBJECT_NAMES.get(e.get("syllabus"), e.get("syllabus"))

    assignments = [_decorate_assignment(a) for a in detail.get("assignments", [])]
    classes = detail.get("classes", [])
    held = [c for c in classes if (c.get("status") or "held") == "held"]

    return {
        **detail,
        "assignments": assignments,
        "by_syllabus": sorted(by_syllabus.values(), key=lambda s: s["syllabus"]),
        "stats": {
            "quiz_count": len(quizzes),
            "avg_score": round(sum(scored) / len(scored), 1) if scored else None,
            "topics_tracked": len(detail["progress"]),
            "papers_done": sum(1 for p in detail.get("papers", [])
                               if p.get("status") == "confident"),
            "classes_held": len(held),
            "last_class": max((c.get("class_date") or "" for c in held),
                              default=None) or None,
            "open_homework": sum(1 for a in assignments if a.get("status") != "done"),
            "last_active": max((q.get("created_at") or "" for q in quizzes),
                               default=None) or None,
        },
    }


# ── Syllabus taxonomy (the picker behind every topic control) ────────────────

_TAX_CACHE: dict[str, dict] = {}


def _taxonomy(syllabus: str) -> dict:
    """Topics + subtopics straight from taxonomy/<code>.json.

    The tutor must be able to set a status on a chapter the student has never
    opened, so the editor is driven by the syllabus, not by existing rows.
    """
    if syllabus in _TAX_CACHE:
        return _TAX_CACHE[syllabus]
    if not re.fullmatch(r"[0-9A-Za-z]{4,6}", syllabus):
        raise HTTPException(400, "Invalid syllabus code")
    path = TAXONOMY_DIR / f"{syllabus}.json"
    if not path.is_file():
        raise HTTPException(404, f"No taxonomy for {syllabus}")
    data = json.loads(path.read_text("utf-8"))
    out = {
        "syllabus": syllabus,
        "subject": data.get("subject", syllabus),
        "name": SUBJECT_NAMES.get(syllabus, data.get("subject", syllabus)),
        "topics": [{"name": t["name"],
                    "subtopics": [s["name"] for s in t.get("subtopics", [])]}
                   for t in data.get("topics", [])],
    }
    _TAX_CACHE[syllabus] = out
    return out


@router.get("/syllabus/{syllabus}/topics")
def syllabus_topics(syllabus: str, _: bool = _Admin):
    return _taxonomy(syllabus)


# ── Student topic progress (tutor-set) ───────────────────────────────────────

class ProgressWrite(BaseModel):
    syllabus: str
    topic: str
    subtopic: str | None = None
    status: str | None = None          # how well they know it
    papers_status: str | None = None   # whether they've drilled its past papers


class ProgressBulk(BaseModel):
    items: list[ProgressWrite]


def _apply_progress(user_id: str, item: ProgressWrite) -> dict:
    for field, value in (("status", item.status),
                         ("papers_status", item.papers_status)):
        if value is not None and value not in STATUSES:
            raise HTTPException(
                400, f"{field} must be one of: {', '.join(sorted(STATUSES))}")
    if item.status is None and item.papers_status is None:
        raise HTTPException(400, "Send status, papers_status, or both")
    _taxonomy(item.syllabus)          # 400/404 on a bogus syllabus code
    return _udb.upsert_progress(user_id, item.syllabus, item.topic,
                                item.subtopic, item.status, item.papers_status)


class PlanUpdate(BaseModel):
    plan: str                         # 'free' | 'solo' | 'three' | 'all'
    trial: bool = False               # Grant a 7-day trial instead of full term
    plan_expires_at: str | None = None  # Override: ISO-8601 or null (auto-computed if absent)


VALID_PLANS = {"free", "solo", "three", "all"}


@router.patch("/students/{user_id}/plan")
def set_student_plan(user_id: str, req: PlanUpdate, _: bool = _Admin):
    from datetime import datetime, timedelta, timezone
    from access import TRIAL_DAYS, BILLING_CYCLE_DAYS

    if req.plan not in VALID_PLANS:
        raise HTTPException(400, f"plan must be one of: {', '.join(sorted(VALID_PLANS))}")
    _student_or_404(user_id)

    now = datetime.now(timezone.utc)
    started_at = now.isoformat()

    if req.plan == "free":
        expires_at = None
        trial = False
    elif req.plan_expires_at:
        expires_at = req.plan_expires_at
        trial = req.trial
    elif req.trial:
        expires_at = (now + timedelta(days=TRIAL_DAYS)).isoformat()
        trial = True
    else:
        expires_at = (now + timedelta(days=BILLING_CYCLE_DAYS)).isoformat()
        trial = False

    updated = _udb.update_user_plan(
        user_id, req.plan, expires_at,
        started_at=started_at, trial=trial,
    )
    return {
        "ok": True,
        "plan": updated.get("plan"),
        "plan_expires_at": updated.get("plan_expires_at"),
        "plan_started_at": updated.get("plan_started_at"),
        "plan_trial": updated.get("plan_trial"),
    }


@router.post("/students/{user_id}/progress")
def set_student_progress(user_id: str, req: ProgressWrite, _: bool = _Admin):
    _student_or_404(user_id)
    return {"progress": _apply_progress(user_id, req)}


@router.post("/students/{user_id}/progress/bulk")
def set_student_progress_bulk(user_id: str, req: ProgressBulk, _: bool = _Admin):
    """Used by "mark the whole chapter" — one call instead of N round-trips."""
    _student_or_404(user_id)
    if not req.items:
        raise HTTPException(400, "Nothing to update")
    return {"updated": [_apply_progress(user_id, i) for i in req.items]}


# ── Student past-paper practice ──────────────────────────────────────────────

class PaperWrite(BaseModel):
    syllabus: str
    year: int
    session: str
    paper: int
    variant: str | None = ""
    status: str
    score: int | None = None
    max_score: int | None = None
    note: str | None = None


@router.get("/students/{user_id}/papers")
def student_papers(user_id: str, _: bool = _Admin):
    _student_or_404(user_id)
    return {"papers": _udb.get_paper_progress(user_id)}


@router.post("/students/{user_id}/papers")
def set_student_paper(user_id: str, req: PaperWrite, _: bool = _Admin):
    _student_or_404(user_id)
    if req.status not in STATUSES:
        raise HTTPException(400, f"status must be one of: {', '.join(sorted(STATUSES))}")
    row = _udb.upsert_paper_progress(
        user_id, req.syllabus, req.year, req.session, req.paper,
        req.variant or "", req.status, req.score, req.max_score, req.note,
        set_by="tutor")
    return {"paper": row}


# ── Class log (per-student attendance calendar) ──────────────────────────────

CLASS_STATUSES = {"held", "cancelled", "missed", "rescheduled"}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}$")


class ClassWrite(BaseModel):
    class_date: str | None = None
    start_time: str | None = None
    duration_min: int | None = None
    syllabus: str | None = None
    status: str | None = None
    topic: str | None = None
    note: str | None = None


def _class_fields(req: ClassWrite, *, creating: bool) -> dict:
    fields: dict = {}
    if req.class_date is not None:
        if not _DATE_RE.match(req.class_date):
            raise HTTPException(400, "class_date must be YYYY-MM-DD")
        fields["class_date"] = req.class_date
    elif creating:
        raise HTTPException(400, "class_date is required")

    if req.start_time is not None:
        t = req.start_time.strip()
        if t and not _TIME_RE.match(t):
            raise HTTPException(400, "start_time must be HH:MM")
        fields["start_time"] = t or None
    if req.status is not None:
        if req.status not in CLASS_STATUSES:
            raise HTTPException(
                400, f"status must be one of: {', '.join(sorted(CLASS_STATUSES))}")
        fields["status"] = req.status
    for name in ("duration_min", "syllabus", "topic", "note"):
        value = getattr(req, name)
        if value is not None:
            fields[name] = value
    return fields


@router.get("/students/{user_id}/classes")
def student_classes(user_id: str, _: bool = _Admin):
    _student_or_404(user_id)
    return {"classes": _udb.get_class_log(user_id)}


@router.post("/students/{user_id}/classes")
def add_class(user_id: str, req: ClassWrite, _: bool = _Admin):
    _student_or_404(user_id)
    fields = _class_fields(req, creating=True)
    fields.setdefault("status", "held")
    fields["user_id"] = user_id
    return {"class": _udb.create_class_entry(fields)}


@router.patch("/classes/{entry_id}")
def edit_class(entry_id: int, req: ClassWrite, _: bool = _Admin):
    if _udb.get_class_entry(entry_id) is None:
        raise HTTPException(404, "No such class entry")
    fields = _class_fields(req, creating=False)
    if not fields:
        raise HTTPException(400, "Nothing to update")
    return {"class": _udb.update_class_entry(entry_id, fields)}


@router.delete("/classes/{entry_id}")
def remove_class(entry_id: int, _: bool = _Admin):
    if _udb.get_class_entry(entry_id) is None:
        raise HTTPException(404, "No such class entry")
    _udb.delete_class_entry(entry_id)
    return {"status": "deleted"}


# ── Assignments (the student diary) ──────────────────────────────────────────

ASSIGN_KINDS = {"homework", "reading", "practice", "test"}


class AttachmentIn(BaseModel):
    """One item hanging off an assignment.

    type=resource → `rel` points into data/resources (a notes/formula PDF).
    type=booklet  → `params` is a /api/generate body the student can run.
    type=upload   → written by the upload endpoint, never accepted from a client.
    """
    type: str
    name: str | None = None
    rel: str | None = None
    params: dict | None = None


class AssignmentWrite(BaseModel):
    syllabus: str | None = None
    kind: str | None = None
    title: str | None = None
    instructions: str | None = None
    topics: list[str] | None = None
    attachments: list[AttachmentIn] | None = None
    due_date: str | None = None
    status: str | None = None


def _clean_attachments(items: list[AttachmentIn]) -> list[dict]:
    out = []
    for a in items:
        if a.type == "resource":
            if not a.rel:
                raise HTTPException(400, "A resource attachment needs `rel`")
            # Same resolve-and-check the public resource route uses: `rel` is
            # attacker-controlled text and must not escape data/resources.
            base = RESOURCES_DIR.resolve()
            path = (RESOURCES_DIR / a.rel).resolve()
            if not str(path).startswith(str(base)) or not path.is_file():
                raise HTTPException(400, f"No such resource: {a.rel}")
            out.append({"type": "resource", "rel": a.rel,
                        "name": a.name or path.name})
        elif a.type == "booklet":
            if not isinstance(a.params, dict) or not a.params.get("topics"):
                raise HTTPException(400, "A booklet attachment needs params.topics")
            out.append({"type": "booklet", "name": a.name or "Practice booklet",
                        "params": a.params})
        elif a.type == "upload":
            # Uploads are minted server-side; echoing one back keeps an edit
            # from dropping files the tutor already attached.
            if not a.rel:
                raise HTTPException(400, "An upload attachment needs `rel`")
            out.append({"type": "upload", "rel": a.rel, "name": a.name or a.rel})
        else:
            raise HTTPException(400, f"Unknown attachment type: {a.type}")
    return out


def _assignment_fields(req: AssignmentWrite, *, creating: bool) -> dict:
    fields: dict = {}
    if req.title is not None:
        if not req.title.strip():
            raise HTTPException(400, "Title cannot be blank")
        fields["title"] = req.title.strip()
    elif creating:
        raise HTTPException(400, "Title is required")

    if req.kind is not None:
        if req.kind not in ASSIGN_KINDS:
            raise HTTPException(
                400, f"kind must be one of: {', '.join(sorted(ASSIGN_KINDS))}")
        fields["kind"] = req.kind
    if req.due_date is not None:
        d = req.due_date.strip()
        if d and not _DATE_RE.match(d):
            raise HTTPException(400, "due_date must be YYYY-MM-DD")
        fields["due_date"] = d or None
    if req.status is not None:
        if req.status not in {"assigned", "done"}:
            raise HTTPException(400, "status must be 'assigned' or 'done'")
        fields["status"] = req.status
        fields["completed_at"] = _udb._now() if req.status == "done" else None
    if req.topics is not None:
        fields["topics_json"] = json.dumps(req.topics)
    if req.attachments is not None:
        fields["attachments_json"] = json.dumps(_clean_attachments(req.attachments))
    for name in ("syllabus", "instructions"):
        value = getattr(req, name)
        if value is not None:
            fields[name] = value
    return fields


@router.get("/students/{user_id}/assignments")
def student_assignments(user_id: str, _: bool = _Admin):
    _student_or_404(user_id)
    return {"assignments": [_decorate_assignment(a)
                            for a in _udb.get_assignments(user_id)]}


@router.get("/homework")
def homework_overview(_: bool = _Admin):
    """Every student's work in one payload, for the Homework page.

    Returns students already sorted by what needs attention — anything a
    student has submitted and the tutor has not marked done floats to the top,
    then overdue, then open. That ordering is the whole point of the page: the
    tutor opens it to answer "who is waiting on me?".
    """
    from datetime import date
    today = date.today().isoformat()

    students = {s["id"]: s for s in _udb.list_students()}

    def shape(a: dict) -> dict:
        d = _decorate_assignment(a)
        # Submissions are downloaded by index, so the stored `rel` (a server
        # path) has no reason to travel to the browser.
        d["submissions"] = [
            {"idx": i, "name": s.get("name"), "size": s.get("size"),
             "submitted_at": s.get("submitted_at")}
            for i, s in enumerate(d.get("submissions") or [])]
        return d

    rows = [shape(a) for a in _udb.get_all_assignments()]

    by_student: dict[str, list] = {}
    for a in rows:
        # An assignment whose student no longer exists is a leftover, not a row
        # worth rendering — the page is a per-student view.
        if a.get("user_id") in students:
            by_student.setdefault(a["user_id"], []).append(a)

    out = []
    for uid, items in by_student.items():
        s = students[uid]
        open_items = [a for a in items if a.get("status") != "done"]
        overdue = [a for a in open_items
                   if a.get("due_date") and str(a["due_date"]) < today]
        # "Waiting on you": the student has handed something in and it is still
        # sitting open.
        awaiting = [a for a in open_items if a.get("submissions")]
        out.append({
            "user_id": uid,
            "name": s.get("name") or s.get("email") or "Student",
            "email": s.get("email"),
            "picture_url": s.get("picture_url"),
            "total": len(items),
            "open": len(open_items),
            "overdue": len(overdue),
            "awaiting_review": len(awaiting),
            "submissions": sum(len(a.get("submissions") or []) for a in items),
            "assignments": items,
        })

    out.sort(key=lambda s: (-s["awaiting_review"], -s["overdue"], -s["open"],
                            s["name"].lower()))
    return {
        "students": out,
        "totals": {
            "students": len(out),
            "open": sum(s["open"] for s in out),
            "overdue": sum(s["overdue"] for s in out),
            "awaiting_review": sum(s["awaiting_review"] for s in out),
            "submissions": sum(s["submissions"] for s in out),
        },
    }


@router.post("/students/{user_id}/assignments")
def add_assignment(user_id: str, req: AssignmentWrite, notify: bool = True,
                   _: bool = _Admin):
    user = _student_or_404(user_id)
    fields = _assignment_fields(req, creating=True)
    fields["user_id"] = user_id
    fields.setdefault("kind", "homework")
    fields.setdefault("status", "assigned")
    fields.setdefault("topics_json", "[]")
    fields.setdefault("attachments_json", "[]")
    row = _decorate_assignment(_udb.create_assignment(fields))

    # Tell the student straight away. Attachments are usually added in the step
    # after this, so ?notify=false lets the console hold the email until the
    # tutor has finished putting the assignment together.
    emailed = False
    if notify:
        from app import _notify
        import reminders
        emailed = reminders.send_assigned_email(user, row, _notify)
    return {"assignment": row, "emailed": emailed}


@router.patch("/assignments/{assignment_id}")
def edit_assignment(assignment_id: int, req: AssignmentWrite, _: bool = _Admin):
    if _udb.get_assignment(assignment_id) is None:
        raise HTTPException(404, "No such assignment")
    fields = _assignment_fields(req, creating=False)
    if not fields:
        raise HTTPException(400, "Nothing to update")
    return {"assignment": _decorate_assignment(
        _udb.update_assignment(assignment_id, fields))}


@router.delete("/assignments/{assignment_id}")
def remove_assignment(assignment_id: int, _: bool = _Admin):
    row = _udb.get_assignment(assignment_id)
    if row is None:
        raise HTTPException(404, "No such assignment")
    # Take the uploaded files with it — nothing else references them.
    for att in _json_list(row.get("attachments_json")):
        if att.get("type") == "upload":
            try:
                (UPLOADS_DIR / att["rel"]).unlink(missing_ok=True)
            except (OSError, KeyError):
                pass
    _udb.delete_assignment(assignment_id)
    return {"status": "deleted"}


# ── Reminders ────────────────────────────────────────────────────────────────

@router.post("/students/{user_id}/remind")
def remind_student(user_id: str, _: bool = _Admin):
    """Nudge a student about everything still outstanding, on demand."""
    user = _student_or_404(user_id)
    from app import _notify
    import reminders

    items = reminders.open_homework(user_id)
    if not items:
        raise HTTPException(400, "Nothing outstanding to remind them about")
    for a in items:
        a.setdefault("subject_name", SUBJECT_NAMES.get(a.get("syllabus"),
                                                       a.get("syllabus")))
    sent = reminders.send_digest_email(user, items, _notify)
    return {
        "sent": sent, "count": len(items),
        "email": user.get("email"),
        # WhatsApp cannot be automated without the Business API, so hand the
        # tutor a prefilled link to send themselves.
        "whatsapp": _wa_reminder_link(user, items),
        "detail": None if sent else
                  "SMTP is not configured on this server, so no email was sent.",
    }


def _wa_reminder_link(user: dict, items: list[dict]) -> str | None:
    import urllib.parse
    import reminders
    digits = "".join(ch for ch in (user.get("phone") or "") if ch.isdigit())
    if not digits:
        return None
    if digits.startswith("0"):
        digits = "92" + digits[1:]
    elif not digits.startswith("92") and len(digits) <= 11:
        digits = "92" + digits
    first = (user.get("name") or "there").split(" ")[0]
    lines = "\n".join(
        f"- {a.get('title')} ({reminders.due_phrase(reminders.days_left(a.get('due_date')))})"
        for a in items[:6])
    text = (f"Hi {first}! Reminder about your PrepWithTee homework:\n{lines}\n\n"
            f"{reminders.APP_BASE_URL}/homework.html")
    return f"https://wa.me/{digits}?text={urllib.parse.quote(text)}"


@router.get("/students/{user_id}/calendar-url")
def student_calendar_url(user_id: str, _: bool = _Admin):
    """The subscribe-once feed URL to hand a student."""
    _student_or_404(user_id)
    import reminders
    return {"url": reminders.calendar_url(user_id)}


# ── Homework file uploads ────────────────────────────────────────────────────

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_UPLOAD_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".doc", ".docx",
                       ".txt", ".csv", ".xlsx", ".ppt", ".pptx", ".zip"}


@router.post("/assignments/{assignment_id}/files")
async def upload_assignment_file(assignment_id: int,
                                 file: UploadFile = File(...),
                                 label: str | None = Form(None),
                                 _: bool = _Admin):
    """Attach a worksheet to an assignment.

    The stored name is generated, never the client's: an uploaded filename is
    untrusted input and would otherwise be a path-traversal hole. The original
    is kept only as the display label.
    """
    row = _udb.get_assignment(assignment_id)
    if row is None:
        raise HTTPException(404, "No such assignment")

    original = os.path.basename(file.filename or "file")
    ext = Path(original).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTS:
        raise HTTPException(400, f"{ext or 'That file type'} is not allowed")

    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is larger than 25 MB")
    if not data:
        raise HTTPException(400, "That file is empty")

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    rel = f"{assignment_id}_{_uuid.uuid4().hex[:12]}{ext}"
    (UPLOADS_DIR / rel).write_bytes(data)

    attachments = _json_list(row.get("attachments_json"))
    attachments.append({"type": "upload", "rel": rel,
                        "name": (label or original).strip() or original,
                        "size": len(data)})
    updated = _udb.update_assignment(
        assignment_id, {"attachments_json": json.dumps(attachments)})
    return {"assignment": _decorate_assignment(updated)}


@router.get("/assignments/{assignment_id}/submission/{idx}")
def download_student_submission(assignment_id: int, idx: int, _: bool = _Admin):
    """Serve a student's submission to the administrator."""
    from fastapi.responses import FileResponse
    from admin import UPLOADS_DIR
    row = _udb.get_assignment(assignment_id)
    if row is None:
        raise HTTPException(404, "No such assignment")
    submissions = _json_list(row.get("student_submissions_json"))
    if not 0 <= idx < len(submissions):
        raise HTTPException(404, "No such submission")
    sub = submissions[idx]
    path = (UPLOADS_DIR / (sub.get("rel") or "")).resolve()
    if not path.is_file():
        raise HTTPException(404, "That file is no longer on the server")
    import mimetypes as _mt
    name = sub.get("name") or path.name
    ext = path.suffix.lower()
    if ext and not name.lower().endswith(ext):
        name = name + ext
    media_type = _mt.guess_type(str(path))[0] or "application/octet-stream"
    return FileResponse(path, filename=name, media_type=media_type)



# ── Resource picker ──────────────────────────────────────────────────────────

@router.get("/resources-flat")
def resources_flat(_: bool = _Admin):
    """Every resource file as one flat list, for the "assign notes" dropdown."""
    if not RESOURCES_DIR.is_dir():
        return {"files": []}
    base = RESOURCES_DIR.resolve()
    files = []
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.name.startswith((".", "_")):
            continue
        rel = path.relative_to(base)
        files.append({"rel": rel.as_posix(), "name": path.name,
                      "category": rel.parts[0] if len(rel.parts) > 1 else "",
                      "size": path.stat().st_size})
    return {"files": files}


# ── Teacher applications ─────────────────────────────────────────────────────

@router.get("/teacher-applications")
def teacher_applications(_: bool = _Admin):
    return {"applications": _udb.get_teacher_applications()}


class ApproveReq(BaseModel):
    """Fields the admin fills in for the public teacher card.

    Everything is optional: blank values fall back to what the applicant wrote,
    so approving with an empty body still produces a usable card.
    """
    name: str | None = None
    role: str | None = None
    bio: str | None = None
    subjects: list[str] | None = None
    qualifications: str | None = None
    experience_years: int | None = None
    picture_url: str | None = None
    display_order: int | None = None
    admin_note: str | None = None


@router.post("/teacher-applications/{app_id}/approve")
def approve_application(app_id: int, req: ApproveReq, _: bool = _Admin):
    from auth import hash_password as _hash_pw
    application = _udb.get_teacher_application(app_id)
    if application is None:
        raise HTTPException(404, "No such application")
    if application.get("teacher_id"):
        raise HTTPException(409, "This application has already been approved")

    codes = req.subjects
    if codes is None:
        raw = application.get("subject_codes") or ""
        codes = [c.strip() for c in raw.split(",") if c.strip()]

    teacher = _udb.create_teacher({
        "name": (req.name or application.get("name") or "").strip(),
        "role": (req.role or "Teacher").strip(),
        "bio": req.bio,
        "subjects_json": json.dumps(codes),
        "qualifications": req.qualifications or application.get("qualifications"),
        "experience_years": req.experience_years,
        "picture_url": req.picture_url,
        "display_order": req.display_order if req.display_order is not None else 0,
        "email": application.get("email"),
        "phone": application.get("phone"),
        "application_id": app_id,
    })

    updated = _udb.update_teacher_application(app_id, {
        "status": "approved",
        "reviewed_at": _udb._now(),
        "teacher_id": teacher.get("id"),
        "admin_note": req.admin_note,
    })

    # Create a login account for the teacher (if one doesn't exist already)
    app_email = (application.get("email") or "").strip().lower()
    app_name  = (req.name or application.get("name") or "").strip()
    temp_password = None
    email_sent = False
    profile_id = None

    if app_email:
        existing = _udb.get_user_by_email(app_email)
        if existing:
            # Promote to teacher if needed
            if existing.get("role") not in ("teacher", "admin"):
                _udb.update_profile(existing["id"], {"role": "teacher"})
            profile_id = existing["id"]
        else:
            temp_password = _generate_temp_password()
            profile = _udb.create_teacher_profile(app_email, app_name, _hash_pw(temp_password))
            profile_id = profile["id"]
            email_sent, email_error = _send_teacher_welcome(app_email, app_name, temp_password)
    else:
        email_error = ""

    return {"status": "approved", "application": updated,
            "teacher": _decorate_teacher(teacher),
            "profile_id": profile_id,
            "email_sent": email_sent,
            "email_error": email_error,
            "temp_password": temp_password}


class RejectReq(BaseModel):
    admin_note: str | None = None


@router.post("/teacher-applications/{app_id}/reject")
def reject_application(app_id: int, req: RejectReq, _: bool = _Admin):
    if _udb.get_teacher_application(app_id) is None:
        raise HTTPException(404, "No such application")
    updated = _udb.update_teacher_application(app_id, {
        "status": "rejected",
        "reviewed_at": _udb._now(),
        "admin_note": req.admin_note,
    })
    return {"status": "rejected", "application": updated}


# ── Teacher management ───────────────────────────────────────────────────────

@router.get("/teachers")
def all_teachers(_: bool = _Admin):
    return {"teachers": [_decorate_teacher(t) for t in _udb.get_all_teachers()],
            "subject_options": [{"code": c, "name": n}
                                for c, n in SUBJECT_NAMES.items()]}


class TeacherWrite(BaseModel):
    name: str | None = None
    role: str | None = None
    bio: str | None = None
    subjects: list[str] | None = None
    qualifications: str | None = None
    experience_years: int | None = None
    picture_url: str | None = None
    display_order: int | None = None
    active: bool | None = None
    email: str | None = None
    phone: str | None = None


def _teacher_fields(req: TeacherWrite) -> dict:
    fields: dict = {}
    for name in ("role", "bio", "qualifications", "picture_url",
                 "email", "phone", "experience_years", "display_order"):
        value = getattr(req, name)
        if value is not None:
            fields[name] = value
    if req.name is not None:
        fields["name"] = req.name.strip()
    if req.subjects is not None:
        fields["subjects_json"] = json.dumps(req.subjects)
    if req.active is not None:
        # Postgres wants a real boolean, the SQLite fallback wants 0/1.
        fields["active"] = req.active if _udb._USE_SUPABASE else int(req.active)
    return fields


@router.post("/teachers")
def add_teacher(req: TeacherWrite, _: bool = _Admin):
    if not (req.name or "").strip():
        raise HTTPException(400, "Name is required")
    teacher = _udb.create_teacher(_teacher_fields(req))
    return {"teacher": _decorate_teacher(teacher)}


@router.patch("/teachers/{teacher_id}")
def edit_teacher(teacher_id: int, req: TeacherWrite, _: bool = _Admin):
    if _udb.get_teacher(teacher_id) is None:
        raise HTTPException(404, "No such teacher")
    fields = _teacher_fields(req)
    if not fields:
        raise HTTPException(400, "Nothing to update")
    return {"teacher": _decorate_teacher(_udb.update_teacher(teacher_id, fields))}


@router.delete("/teachers/{teacher_id}")
def remove_teacher(teacher_id: int, _: bool = _Admin):
    if _udb.get_teacher(teacher_id) is None:
        raise HTTPException(404, "No such teacher")
    _udb.delete_teacher(teacher_id)
    return {"status": "deleted"}


# ── Teacher ↔ student assignment ─────────────────────────────────────────────


def _teacher_profile_id(teacher_id: int) -> str:
    """Resolve a teachers.id integer to the teacher's profiles.id UUID via email."""
    t = _udb.get_teacher(teacher_id)
    if not t:
        raise HTTPException(404, "No such teacher")
    profile = _udb.get_user_by_email(t.get("email", ""))
    if not profile:
        raise HTTPException(404, "Teacher has no login account (email not found in profiles)")
    return profile["id"]


class TeacherStudentIn(BaseModel):
    student_id: str
    syllabus: str


@router.get("/teachers/{teacher_id}/students")
def teacher_student_list(teacher_id: int, _: bool = _Admin):
    """Return all active student links for a teacher."""
    pid = _teacher_profile_id(teacher_id)
    rows = _udb.get_teacher_students(pid)
    return {"assignments": rows}


@router.post("/teachers/{teacher_id}/students")
def assign_student(teacher_id: int, req: TeacherStudentIn, _: bool = _Admin):
    """Link a student to a teacher for a given syllabus."""
    pid = _teacher_profile_id(teacher_id)
    if not _udb.get_user(req.student_id):
        raise HTTPException(404, "Student not found")
    _udb.assign_teacher_student(pid, req.student_id, req.syllabus)
    return {"status": "assigned"}


@router.delete("/teachers/{teacher_id}/students/{student_id}")
def unassign_student(teacher_id: int, student_id: str,
                     syllabus: str = Query(...), _: bool = _Admin):
    """Remove a teacher-student link for a specific syllabus."""
    pid = _teacher_profile_id(teacher_id)
    _udb.remove_teacher_student(pid, student_id, syllabus)
    return {"status": "removed"}


# ── Calendly ─────────────────────────────────────────────────────────────────
#
# Calendly has no webhook set up for this site, so the admin reads the calendar
# live over API v2. Listing events is one request, but invitee names/emails are
# a separate request per event, so results are cached briefly — opening the tab
# repeatedly must not burn through the rate limit.
# ---------------------------------------------------------------------------
CALENDLY_API = "https://api.calendly.com"
_CAL_CACHE: dict = {"at": 0.0, "data": None}
_CAL_TTL_S = 120
_CAL_INVITEE_LIMIT = 40


def _calendly_get(path: str, token: str, params: dict | None = None) -> dict:
    r = requests.get(f"{CALENDLY_API}{path}", timeout=20,
                     headers={"Authorization": f"Bearer {token}"}, params=params)
    if r.status_code != 200:
        raise HTTPException(
            502, f"Calendly API returned {r.status_code}: {r.text[:200]}")
    return r.json()


@router.get("/calendly")
def calendly(_: bool = _Admin, refresh: bool = False):
    """Scheduled meetings with their invitees, newest first."""
    token = (os.environ.get("CALENDLY_ACCESS_TOKEN")
             or os.environ.get("CALENDLY_TOKEN"))
    if not token:
        return {"configured": False, "events": [],
                "message": "Set CALENDLY_ACCESS_TOKEN on the server to show bookings "
                           "here. Create a personal access token at "
                           "calendly.com/integrations/api_webhooks."}

    now = time.time()
    if not refresh and _CAL_CACHE["data"] and now - _CAL_CACHE["at"] < _CAL_TTL_S:
        return _CAL_CACHE["data"]

    me = _calendly_get("/users/me", token)["resource"]
    raw = _calendly_get("/scheduled_events", token, {
        "user": me["uri"], "count": 100, "sort": "start_time:desc"})

    events = []
    for i, ev in enumerate(raw.get("collection", [])):
        uuid = (ev.get("uri") or "").rsplit("/", 1)[-1]
        invitees = []
        # Only the most recent events get the extra round-trip for invitees.
        if i < _CAL_INVITEE_LIMIT and uuid:
            try:
                inv = _calendly_get(f"/scheduled_events/{uuid}/invitees", token,
                                    {"count": 10})
                invitees = [{
                    "name": x.get("name"),
                    "email": x.get("email"),
                    "timezone": x.get("timezone"),
                    "status": x.get("status"),
                    "questions": [
                        {"question": q.get("question"), "answer": q.get("answer")}
                        for q in (x.get("questions_and_answers") or [])
                    ],
                } for x in inv.get("collection", [])]
            except HTTPException:
                invitees = []           # one bad event must not blank the tab

        events.append({
            "uuid": uuid,
            "name": ev.get("name"),
            "status": ev.get("status"),
            "start_time": ev.get("start_time"),
            "end_time": ev.get("end_time"),
            "location": (ev.get("location") or {}).get("location")
                        or (ev.get("location") or {}).get("type"),
            "join_url": (ev.get("location") or {}).get("join_url"),
            "invitees_counter": ev.get("invitees_counter"),
            "invitees": invitees,
        })

    data = {"configured": True, "scheduling_url": me.get("scheduling_url"),
            "events": events}
    _CAL_CACHE.update(at=now, data=data)
    return data


# ── Course catalog (admin CRUD) ───────────────────────────────────────────────


class CourseWrite(BaseModel):
    syllabus_code: str
    slug: str
    title: str
    level: str
    subject: str
    tagline: str | None = None
    overview_html: str | None = None
    approach_html: str | None = None
    what_you_get_json: str | None = "[]"
    teacher_id: int | None = None
    meta_title: str | None = None
    meta_description: str | None = None
    published: bool = False
    sort_order: int = 0


@router.get("/courses")
def admin_list_courses(_: bool = _Admin):
    """All courses including unpublished."""
    return {"courses": _udb.get_all_courses(published_only=False)}


@router.post("/courses")
def admin_create_course(req: CourseWrite, _: bool = _Admin):
    import json as _json
    payload = req.model_dump()
    payload["published"] = payload["published"] if _udb._USE_SUPABASE else int(payload["published"])
    course = _udb.create_course(payload)
    return {"course": course}


@router.put("/courses/{course_id}")
def admin_update_course(course_id: int, req: CourseWrite, _: bool = _Admin):
    if _udb.get_course(course_id) is None:
        raise HTTPException(404, "Course not found")
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    if "published" in fields and not _udb._USE_SUPABASE:
        fields["published"] = int(fields["published"])
    updated = _udb.update_course(course_id, fields)
    return {"course": updated}


@router.patch("/courses/{course_id}")
def admin_patch_course(course_id: int, body: dict, _: bool = _Admin):
    """Partial update — pass only the fields to change (e.g. {published: true})."""
    if _udb.get_course(course_id) is None:
        raise HTTPException(404, "Course not found")
    if "published" in body and not _udb._USE_SUPABASE:
        body["published"] = int(body["published"])
    updated = _udb.update_course(course_id, body)
    return {"course": updated}


@router.delete("/courses/{course_id}")
def admin_delete_course(course_id: int, _: bool = _Admin):
    if _udb.get_course(course_id) is None:
        raise HTTPException(404, "Course not found")
    _udb.delete_course(course_id)
    return {"ok": True}


# ── Groups (admin) ────────────────────────────────────────────────────────────

class GroupStatusUpdate(BaseModel):
    status: str   # draft|active|closed


@router.get("/groups")
def admin_list_groups(_: bool = _Admin):
    groups = _udb.get_all_groups()
    for g in groups:
        g["member_count"] = _udb.get_group_member_count(g["id"])
    return {"groups": groups}


@router.get("/groups/{group_id}")
def admin_get_group(group_id: int, _: bool = _Admin):
    g = _udb.get_group(group_id)
    if not g:
        raise HTTPException(404, "Group not found")
    return {"group": g, "members": _udb.get_group_members(group_id),
            "sessions": _udb.get_group_sessions(group_id)}


@router.patch("/groups/{group_id}/status")
def admin_set_group_status(group_id: int, req: GroupStatusUpdate, _: bool = _Admin):
    if req.status not in {"draft", "active", "closed"}:
        raise HTTPException(400, "status must be draft|active|closed")
    if not _udb.get_group(group_id):
        raise HTTPException(404, "Group not found")
    updated = _udb.update_group(group_id, {"status": req.status})
    return {"ok": True, "group": updated}


# ── Payment proofs (admin) ────────────────────────────────────────────────────

class ProofReview(BaseModel):
    status: str          # approved|rejected
    reviewer_note: str | None = None


@router.get("/payment-proofs")
def admin_list_proofs(status: str | None = None, _: bool = _Admin):
    return {"proofs": _udb.get_payment_proofs(status=status)}


@router.get("/payment-proofs/{proof_id}")
def admin_get_proof(proof_id: int, _: bool = _Admin):
    p = _udb.get_payment_proof(proof_id)
    if not p:
        raise HTTPException(404, "Proof not found")
    return {"proof": p}


@router.post("/payment-proofs/{proof_id}/review")
def admin_review_proof(proof_id: int, req: ProofReview, _: bool = _Admin):
    from datetime import datetime, timezone
    if req.status not in {"approved", "rejected"}:
        raise HTTPException(400, "status must be approved or rejected")
    proof = _udb.get_payment_proof(proof_id)
    if not proof:
        raise HTTPException(404, "Proof not found")
    if proof.get("status") != "pending":
        raise HTTPException(409, "This proof has already been reviewed")

    update_fields = {
        "status": req.status,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    if req.reviewer_note:
        update_fields["note"] = req.reviewer_note
    _udb.update_payment_proof(proof_id, update_fields)

    if req.status == "approved":
        from datetime import datetime, timedelta, timezone
        from access import BILLING_CYCLE_DAYS
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(days=BILLING_CYCLE_DAYS)).isoformat()
        _udb.update_user_plan(
            proof["user_id"], proof["plan"], expires,
            started_at=now.isoformat(), trial=False,
        )

    return {"ok": True, "proof": _udb.get_payment_proof(proof_id)}


# ── Teacher-student allocations ───────────────────────────────────────────────

class AllocationReq(BaseModel):
    teacher_id: str
    student_id: str
    syllabus: str


@router.get("/teacher-profiles")
def list_teacher_profiles(_: bool = _Admin):
    """Profiles with role=teacher — used for allocation dropdowns."""
    return {"teachers": _udb.list_teacher_profiles()}


@router.get("/allocations")
def admin_list_allocations(_: bool = _Admin):
    return {"allocations": _udb.get_allocations()}


@router.post("/allocations")
def admin_create_allocation(req: AllocationReq, _: bool = _Admin):
    # Verify both IDs are actual profiles before inserting
    if not _udb.get_user(req.teacher_id):
        raise HTTPException(404, f"Teacher profile not found: {req.teacher_id}")
    if not _udb.get_user(req.student_id):
        raise HTTPException(404, f"Student profile not found: {req.student_id}")
    alloc = _udb.create_allocation(req.teacher_id, req.student_id, req.syllabus)
    return {"ok": True, "allocation": alloc}


@router.delete("/allocations/{alloc_id}")
def admin_delete_allocation(alloc_id: int, _: bool = _Admin):
    _udb.delete_allocation(alloc_id)
    return {"ok": True}


# ── Contacts ──────────────────────────────────────────────────────────────────

@router.get("/contacts")
def admin_list_contacts(_: bool = _Admin):
    return {"contacts": _udb.get_contacts()}


# ── Newsletter ────────────────────────────────────────────────────────────────

@router.get("/newsletter")
def admin_list_newsletter(_: bool = _Admin):
    return {"subscribers": _udb.get_newsletter_subscribers()}


# ── Blog ──────────────────────────────────────────────────────────────────────

class _BlogPostIn(BaseModel):
    title: str
    slug: str
    excerpt: str | None = None
    body_markdown: str = ""
    cover_url: str | None = None
    author: str = "Muhammad Taahaa"
    meta_title: str | None = None
    meta_desc: str | None = None


class _BlogPostPatch(BaseModel):
    title: str | None = None
    slug: str | None = None
    excerpt: str | None = None
    body_markdown: str | None = None
    cover_url: str | None = None
    author: str | None = None
    meta_title: str | None = None
    meta_desc: str | None = None
    published: bool | None = None


@router.get("/blog")
def admin_blog_list(_: bool = _Admin):
    import blog as _blog
    return {"posts": _blog.get_all_posts_admin()}


@router.post("/blog")
def admin_blog_create(post: _BlogPostIn, _: bool = _Admin):
    import blog as _blog
    if not re.match(r"^[a-z0-9-]+$", post.slug):
        raise HTTPException(400, "Slug must contain only lowercase letters, numbers and hyphens")
    _blog.ensure_table()
    con = _blog._con()
    try:
        con.execute(
            """INSERT INTO blog_posts
               (title, slug, excerpt, body_markdown, cover_url, author, meta_title, meta_desc)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (post.title, post.slug, post.excerpt, post.body_markdown,
             post.cover_url, post.author, post.meta_title, post.meta_desc))
        con.commit()
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(409, "A post with that slug already exists")
        raise HTTPException(500, str(exc))
    finally:
        con.close()
    return {"ok": True}


@router.patch("/blog/{post_id}")
def admin_blog_update(post_id: int, data: _BlogPostPatch, _: bool = _Admin):
    import blog as _blog
    fields = data.model_dump(exclude_unset=True)
    if not fields:
        return {"ok": True}
    if "slug" in fields and fields["slug"] is not None:
        if not re.match(r"^[a-z0-9-]+$", fields["slug"]):
            raise HTTPException(400, "Slug must contain only lowercase letters, numbers and hyphens")
    if fields.get("published") is True:
        fields.setdefault("published_at", _blog._now_iso())
    fields["updated_at"] = _blog._now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [post_id]
    _blog.ensure_table()
    con = _blog._con()
    try:
        con.execute(f"UPDATE blog_posts SET {set_clause} WHERE id = ?", values)
        con.commit()
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(409, "A post with that slug already exists")
        raise HTTPException(500, str(exc))
    finally:
        con.close()
    return {"ok": True}


@router.delete("/blog/{post_id}")
def admin_blog_delete(post_id: int, _: bool = _Admin):
    import blog as _blog
    _blog.ensure_table()
    con = _blog._con()
    try:
        con.execute("DELETE FROM blog_posts WHERE id = ?", (post_id,))
        con.commit()
    finally:
        con.close()
    return {"ok": True}


# Blog images (covers + inline) are stored under data/uploads/blog, which the
# app serves at /uploads/blog/<name> via the persistent /uploads static mount.
BLOG_UPLOADS_DIR = ROOT / "data" / "uploads" / "blog"
ALLOWED_BLOG_IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_BLOG_IMG_BYTES = 8 * 1024 * 1024


@router.post("/blog/upload")
async def admin_blog_upload_image(file: UploadFile = File(...), _: bool = _Admin):
    """Store an uploaded blog image and return its stable public URL.

    The stored name is generated server-side, never the client's, so an
    uploaded filename can't be used to traverse or clobber anything.
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_BLOG_IMG_EXTS:
        raise HTTPException(400, "Please upload a PNG, JPG, WEBP or GIF image.")
    data = await file.read(MAX_BLOG_IMG_BYTES + 1)
    if len(data) > MAX_BLOG_IMG_BYTES:
        raise HTTPException(413, "Image is too large (max 8 MB).")
    BLOG_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    rel = f"{_uuid.uuid4().hex}{ext}"
    (BLOG_UPLOADS_DIR / rel).write_bytes(data)
    return {"url": f"/uploads/blog/{rel}"}


# ── Newsletter Admin ──────────────────────────────────────────────────────────

class NewsletterBroadcastReq(BaseModel):
    subject: str
    body: str


@router.get("/newsletter/subscribers")
def admin_list_newsletter(_: bool = _Admin):
    subs = _udb.get_newsletter_subscribers(limit=2000)
    return {"subscribers": subs}


@router.get("/newsletter/export")
def admin_export_newsletter(_: bool = _Admin):
    import csv
    import io
    subs = _udb.get_newsletter_subscribers(limit=10000, active_only=True)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["email", "subscribed_at", "status"])
    for s in subs:
        writer.writerow([s.get("email"), s.get("subscribed_at"), s.get("status", "subscribed")])
    return Response(
        content=out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="newsletter_subscribers.csv"'}
    )


@router.post("/newsletter/broadcast")
def admin_broadcast_newsletter(req: NewsletterBroadcastReq, _: bool = _Admin):
    if not (req.subject or "").strip():
        raise HTTPException(400, "Subject required")
    if not (req.body or "").strip():
        raise HTTPException(400, "Body required")

    subs = _udb.get_newsletter_subscribers(limit=5000, active_only=True)
    if not subs:
        return {"ok": True, "sent": 0, "total": 0}

    from app import _notify
    sent_count = 0
    # Batch processing in chunks of 100
    batch_size = 100
    for i in range(0, len(subs), batch_size):
        chunk = subs[i:i + batch_size]
        for sub in chunk:
            email = sub["email"]
            tok = sub.get("unsubscribe_token") or "legacy"
            unsub_link = f"https://prepwithtee.com/unsubscribe?token={tok}"
            full_body = (
                f"{req.body}\n\n"
                f"---\n"
                f"To unsubscribe, visit: {unsub_link}\n"
            )
            ok = _notify(req.subject, full_body, to=email, cta=("PrepWithTee", "https://prepwithtee.com/"))
            if ok:
                sent_count += 1

    return {"ok": True, "sent": sent_count, "total": len(subs)}


# ── Email Admin ───────────────────────────────────────────────────────────────

import html as _html_mod

_MAIL_LOGO  = "https://prepwithtee.com/logo.png"
_MAIL_SITE  = "https://prepwithtee.com"
_MAIL_WA    = "https://wa.me/923204884375"
_MAIL_UNSUB = "mailto:nexgentutors6@gmail.com?subject=Unsubscribe%20PrepWithTee"


def _mail_p(text: str) -> str:
    return f'<p style="margin:0 0 14px">{text}</p>'


def _mail_html(body_html: str, cta_label: str = "", cta_url: str = "") -> str:
    """Branded PrepWithTee email card — matches email_lifecycle._letter_html."""
    cta_block = (
        f'<table width="100%" cellpadding="0" cellspacing="0" role="presentation"'
        f' style="margin-top:28px"><tr><td style="text-align:center">'
        f'<a href="{_html_mod.escape(cta_url)}"'
        f' style="display:inline-block;background:#E8913A;color:#fff;text-decoration:none;'
        f'font-weight:700;font-size:.9rem;padding:13px 32px;border-radius:8px;letter-spacing:.02em">'
        f'{_html_mod.escape(cta_label)} &rarr;</a></td></tr></table>'
        if cta_label else ""
    )
    cta_divider = '<div style="border-top:1px solid #f0ece6;margin:26px 0 0"></div>' if cta_label else ""
    return (
        f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
        f'<body style="margin:0;padding:0;background:#edeae5;'
        f'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Arial,sans-serif">'
        f'<table width="100%" cellpadding="0" cellspacing="0" role="presentation">'
        f'<tr><td style="padding:32px 16px 48px">'
        f'<table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="max-width:520px;margin:0 auto">'
        f'<tr><td style="background:#2E1B4A;border-radius:16px 16px 0 0;padding:28px 32px 22px;text-align:center">'
        f'<a href="{_MAIL_SITE}" style="text-decoration:none;display:block">'
        f'<img src="{_MAIL_LOGO}" width="72" height="72"'
        f' style="display:block;margin:0 auto 12px;border-radius:50%;border:3px solid rgba(201,168,76,.45)" alt="">'
        f'<p style="margin:0;color:#fff;font-size:1.05rem;font-weight:700">PrepWithTee</p>'
        f'<p style="margin:4px 0 0;color:#C9BDF0;font-size:.72rem;letter-spacing:.09em;text-transform:uppercase">'
        f'Cambridge Exam Prep</p></a></td></tr>'
        f'<tr><td style="background:#C9A84C;height:3px;font-size:1px;line-height:1px">&nbsp;</td></tr>'
        f'<tr><td style="background:#fff;padding:34px 38px 38px;border-radius:0 0 16px 16px;'
        f'box-shadow:0 6px 32px rgba(46,27,74,.12)">'
        f'<div style="font-size:.93rem;color:#1e1b30;line-height:1.85">{body_html}</div>'
        f'{cta_divider}'
        f'{cta_block}</td></tr>'
        f'<tr><td style="padding:22px 0 4px;text-align:center">'
        f'<table width="100%" cellpadding="0" cellspacing="0" role="presentation">'
        f'<tr><td style="text-align:center;padding-bottom:8px">'
        f'<img src="{_MAIL_LOGO}" alt="" width="26" height="26" style="border-radius:50%;opacity:.4;vertical-align:middle">'
        f'</td></tr>'
        f'<tr><td style="font-size:.7rem;color:#aaa;line-height:1.7;text-align:center">'
        f'<strong style="color:#888">PrepWithTee</strong> &middot; Lahore, Pakistan<br>'
        f'Questions or need tutoring? <a href="{_MAIL_WA}" style="color:#aaa;text-decoration:underline">WhatsApp us</a><br>'
        f'<a href="{_MAIL_UNSUB}" style="color:#aaa;text-decoration:underline">Unsubscribe</a>'
        f'</td></tr></table></td></tr>'
        f'</table></td></tr></table></body></html>'
    )


def _build_template(template_id: str, name: str) -> tuple[str, str]:
    """Return (subject, html) for the given template id and recipient name."""
    first = _html_mod.escape((name or "there").split()[0])
    p = _mail_p
    lib = "https://prepwithtee.com/yearly"
    ask = "https://prepwithtee.com/ask.html"

    if template_id == "W1":
        return (
            f"You're in, {first} — here's your first move.",
            _mail_html(
                p(f"Hi {first},")
                + p("Welcome to PrepWithTee.")
                + p("Every question in this library is a real Cambridge exam question, sorted by topic, "
                    "with the mark scheme right next to it. No hunting through PDFs.")
                + p("<strong>Pick your subject &rarr; pick a topic &rarr; download a question set.</strong> "
                    "It takes 30 seconds.")
                + p("See you inside,<br><strong>Tee</strong>")
                + '<p style="margin:16px 0 0;font-size:.8rem;color:#999">P.S. If you\'re not sure where '
                  'to start, just reply to this email &mdash; I read every reply.</p>',
                "Open the Library", lib,
            ),
        )

    if template_id == "W2":
        return (
            "The revision habit that actually works (10 min today)",
            _mail_html(
                p(f"Hi {first},")
                + p("Most students revise by reading their notes.")
                + p("The problem? Reading <em>feels</em> like progress but it isn't. Your brain needs to "
                    "<em>retrieve</em> information under pressure &mdash; that's what the exam tests.")
                + p("<strong>Practice questions, by topic, from day one.</strong>")
                + p("Open the Library, pick any topic you covered this week, work through the question set "
                    "with pen and paper, then check the mark scheme.")
                + p("Ten minutes of active recall beats an hour of passive reading every time.")
                + p("&mdash; <strong>Tee</strong>"),
                "Open the Library", lib,
            ),
        )

    if template_id == "W3":
        return (
            "Stuck at midnight on a question? This helps.",
            _mail_html(
                p(f"Hi {first},")
                + p("Ever been working through a past paper at 11&nbsp;PM and hit a question you just "
                    "can't crack &mdash; with no one to ask?")
                + p("That's exactly why we built the <strong>AI Tutor</strong>.")
                + p("It knows the Cambridge syllabus inside out. Ask it to explain a concept, walk you "
                    "through a worked example, or tell you why your answer missed the marks.")
                + p("Click <strong>Ask AI</strong> on any question page and give it a go.")
                + p("&mdash; <strong>Tee</strong>"),
                "Try the AI Tutor", ask,
            ),
        )

    if template_id == "R1":
        return (
            f"{first}, is everything okay?",
            _mail_html(
                p(f"Hi {first},")
                + p("I noticed you haven't been on in a few days. That's completely fine &mdash; life gets busy.")
                + p("But I also know how easy it is for revision to quietly slip off the list. "
                    "Before you know it, three days turns into three weeks.")
                + p("You don't need a big session today. Just open one topic set, do three questions, "
                    "check the mark schemes. Literally ten minutes.")
                + p("Small consistent sessions beat a panic cram every single time.")
                + p("Come back when you're ready.")
                + p("&mdash; <strong>Tee</strong>"),
                "Continue where you left off", lib,
            ),
        )

    if template_id == "R2":
        return (
            "I'll be honest with you.",
            _mail_html(
                p(f"Hi {first},")
                + p("A week away from revision. I get it &mdash; sometimes the hardest part is just "
                    "starting again.")
                + p("Here's what works: <strong>don't try to catch up.</strong> Forget the time you've "
                    "missed. Just open one topic set &mdash; any topic &mdash; and do the first question.")
                + p("By the time you've done five questions you'll have forgotten you were even putting it off.")
                + p("The library is right where you left it.")
                + p("&mdash; <strong>Tee</strong>")
                + '<p style="margin:16px 0 0;font-size:.8rem;color:#999">P.S. If something specific is '
                  'blocking you &mdash; just reply. I mean that.</p>',
                "Pick up where you left off", lib,
            ),
        )

    if template_id == "R3":
        return (
            "One thing before I leave you alone",
            _mail_html(
                p(f"Hi {first},")
                + p("I'm not going to keep sending you emails you're not finding useful. "
                    "This one's the last one for a while.")
                + p("Cambridge exams reward students who have <em>seen lots of questions</em> on a topic "
                    "&mdash; not students who memorised a textbook. Every session on PrepWithTee builds "
                    "that pattern recognition.")
                + p("When you're ready to come back &mdash; whether that's tomorrow or in a month &mdash; "
                    "everything will be here waiting.")
                + p("Rooting for you,<br><strong>Tee</strong>"),
                "I'm ready — take me back", lib,
            ),
        )

    if template_id == "F1":
        from datetime import date as _d
        week = _d.today().isocalendar()[1]
        tips = [
            ("mark scheme first",
             "<strong>Try &ldquo;mark scheme first&rdquo; on one question this week.</strong><br><br>"
             "Before you attempt a question, read the mark scheme. See what Cambridge is looking for. "
             "Then close it, answer, and compare."),
            ("blank-page recall",
             "<strong>This week: replace one re-reading session with a blank-page test.</strong><br><br>"
             "Close your notes. Pick a topic. Write down everything you remember. "
             "Then check the gaps &mdash; those are your actual revision list."),
        ]
        tip_label, tip_body = tips[week % len(tips)]
        return (
            f"Your study tip this week: {tip_label}",
            _mail_html(
                p(f"Hi {first},")
                + p("Quick one this week.")
                + f'<p style="margin:0 0 14px;padding:16px 18px;background:#faf8f5;'
                  f'border-left:3px solid #C9A84C;border-radius:0 6px 6px 0;'
                  f'font-size:.9rem;color:#1e1b30;line-height:1.8">{tip_body}</p>'
                + p("Give it a go this week.")
                + p("Have a good week,<br><strong>Tee</strong>"),
                "Open the Library", lib,
            ),
        )

    return "Message from PrepWithTee", _mail_html(p(f"Hi {first},") + p("&mdash; <strong>Tee</strong>"))


class AdminSendEmailReq(BaseModel):
    user_ids: list[str]
    template: str
    subject: str = ""
    body: str = ""
    log_send: bool = False


@router.get("/email-activity")
def admin_email_activity(_: bool = _Admin):
    """All students with last-active date and full email_log history."""
    from datetime import date
    today = date.today()

    if _udb._USE_SUPABASE:
        cl = _udb._client()
        students = cl.table("profiles").select("*").eq("role", "student").execute().data or []
        log_rows  = cl.table("email_log").select("user_id,template_id,sent_at").execute().data or []
        ts_rows   = cl.table("daily_time_spent").select("user_id,date").execute().data or []
    else:
        with _udb._local() as c:
            students = [dict(r) for r in c.execute(
                "SELECT * FROM profiles WHERE role='student' OR role IS NULL")]
            log_rows = [dict(r) for r in c.execute(
                "SELECT user_id,template_id,sent_at FROM email_log")]
            ts_rows  = [{"user_id": r[0], "date": r[1]} for r in c.execute(
                "SELECT user_id,MAX(date) FROM daily_time_spent GROUP BY user_id")]

    from collections import defaultdict
    log_by_user: dict[str, list] = defaultdict(list)
    for row in log_rows:
        log_by_user[row["user_id"]].append({
            "template_id": row["template_id"],
            "sent_at": (row.get("sent_at") or "")[:16],
        })

    last_active: dict[str, str] = {}
    for r in ts_rows:
        uid, d = r["user_id"], (r.get("date") or "")[:10]
        if d and (uid not in last_active or d > last_active[uid]):
            last_active[uid] = d

    result = []
    for s in students:
        uid     = s.get("id", "")
        created = (s.get("created_at") or "")[:10]
        la      = last_active.get(uid) or (s.get("updated_at") or created)[:10]
        inactive_days = 0
        if la:
            try:
                inactive_days = max(0, (today - date.fromisoformat(la[:10])).days)
            except (ValueError, TypeError):
                pass
        result.append({
            "id":            uid,
            "name":          s.get("name") or "",
            "email":         s.get("email") or "",
            "picture_url":   s.get("picture_url") or "",
            "created_at":    created,
            "last_active":   la[:10] if la else "",
            "inactive_days": inactive_days,
            "emails_sent":   sorted(log_by_user.get(uid, []), key=lambda x: x["sent_at"]),
        })

    result.sort(key=lambda x: x["inactive_days"], reverse=True)
    return {"students": result}


@router.get("/email-preview")
def admin_email_preview(
    template: str = Query("R1"),
    name: str = Query("Ahmed"),
    subject: str = Query(""),
    body: str = Query(""),
    _: bool = _Admin,
):
    if template == "custom":
        if not subject:
            raise HTTPException(400, "subject required")
        first = _html_mod.escape((name or "Student").split()[0])
        p = _mail_p
        body_html = (
            p(f"Hi {first},")
            + "".join(
                p(_html_mod.escape(line)) if line.strip() else "<br>"
                for line in (body or "").split("\n")
            )
            + p("&mdash; <strong>Tee</strong>")
        )
        return {"subject": subject, "html": _mail_html(body_html)}
    subj, html = _build_template(template, name)
    return {"subject": subj, "html": html}


@router.post("/send-email")
def admin_send_email(req: AdminSendEmailReq, _: bool = _Admin):
    from app import _notify
    from datetime import datetime, timezone

    if not req.user_ids:
        raise HTTPException(400, "No users selected")
    if not req.template:
        raise HTTPException(400, "Template required")
    if req.template == "custom" and not (req.subject or "").strip():
        raise HTTPException(400, "Subject required for custom emails")

    if _udb._USE_SUPABASE:
        profs = _udb._client().table("profiles").select("*").in_("id", req.user_ids).execute().data or []
        profiles = {p["id"]: p for p in profs}
    else:
        profiles = {}
        with _udb._local() as c:
            ph = ",".join("?" * len(req.user_ids))
            for row in c.execute(f"SELECT * FROM profiles WHERE id IN ({ph})", req.user_ids):
                d = dict(row); profiles[d["id"]] = d

    now     = datetime.now(timezone.utc).isoformat()
    results = []

    for uid in req.user_ids:
        user  = profiles.get(uid)
        if not user:
            results.append({"user_id": uid, "ok": False, "error": "not found"}); continue
        email = (user.get("email") or "").strip()
        name  = user.get("name") or "there"
        if not email:
            results.append({"user_id": uid, "ok": False, "error": "no email"}); continue

        if req.template == "custom":
            first = _html_mod.escape(name.split()[0])
            body_html = (
                _mail_p(f"Hi {first},")
                + "".join(
                    _mail_p(_html_mod.escape(line)) if line.strip() else "<br>"
                    for line in (req.body or "").split("\n")
                )
                + _mail_p("&mdash; <strong>Tee</strong>")
            )
            html  = _mail_html(body_html)
            subj  = req.subject
            plain = req.body or req.subject
        else:
            subj, html = _build_template(req.template, name)
            plain = subj

        ok = _notify(subj, plain, to=email, html_override=html)

        if ok and req.log_send:
            tpl_id = req.template if req.template != "custom" else "MANUAL"
            try:
                if _udb._USE_SUPABASE:
                    _udb._client().table("email_log").insert(
                        {"user_id": uid, "template_id": tpl_id, "sent_at": now}
                    ).execute()
                else:
                    with _udb._local() as c:
                        c.execute(
                            "INSERT INTO email_log (user_id,template_id,sent_at) VALUES (?,?,?)",
                            (uid, tpl_id, now),
                        )
                        c.commit()
            except Exception:
                pass

        results.append({"user_id": uid, "email": email, "ok": ok})

    sent = sum(1 for r in results if r["ok"])
    return {"sent": sent, "total": len(req.user_ids), "results": results}
