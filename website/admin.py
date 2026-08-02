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
import secrets
import time

import requests
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query
from pydantic import BaseModel

from . import users_db as _udb

router = APIRouter(prefix="/api/admin")

ADMIN_KEY = (os.environ.get("ADMIN_ACCESS_KEY")
             or os.environ.get("ADMIN_KEY")
             or "prepwithtee-admin-2026")

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
) -> bool:
    supplied = key or x_admin_key or admin_key or ""
    if not secrets.compare_digest(supplied, ADMIN_KEY):
        raise HTTPException(401, "Invalid or missing admin key")
    return True


_Admin = Depends(require_admin)


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
    for r in rows:
        r["subject_names"] = [SUBJECT_NAMES.get(s, s) for s in r.get("subjects", [])]
    return {"students": rows}


@router.get("/students/{user_id}")
def student_detail(user_id: str, _: bool = _Admin):
    detail = _udb.get_student_detail(user_id)
    if detail is None:
        raise HTTPException(404, "No such student")

    # Group topic progress by syllabus so the drill-down reads subject by subject.
    by_syllabus: dict[str, dict] = {}
    for p in detail["progress"]:
        syl = p.get("syllabus") or "?"
        entry = by_syllabus.setdefault(syl, {
            "syllabus": syl, "name": SUBJECT_NAMES.get(syl, syl),
            "topics": [], "confident": 0, "learning": 0, "not_started": 0})
        entry["topics"].append(p)
        status = p.get("status") or "not_started"
        if status in entry:
            entry[status] += 1

    quizzes = detail["quizzes"]
    scored = [q["score"] for q in quizzes if q.get("score") is not None]

    for e in detail["enrollments"]:
        e["name"] = SUBJECT_NAMES.get(e.get("syllabus"), e.get("syllabus"))

    return {
        **detail,
        "by_syllabus": sorted(by_syllabus.values(), key=lambda s: s["syllabus"]),
        "stats": {
            "quiz_count": len(quizzes),
            "avg_score": round(sum(scored) / len(scored), 1) if scored else None,
            "topics_tracked": len(detail["progress"]),
            "last_active": max((q.get("created_at") or "" for q in quizzes),
                               default=None) or None,
        },
    }


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
    return {"status": "approved", "application": updated,
            "teacher": _decorate_teacher(teacher)}


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
