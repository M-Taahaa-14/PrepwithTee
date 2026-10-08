"""Teacher-facing API routes for PrepWithTee.

Teachers can see only their own assigned students. All write operations
(homework, class log) reuse the same underlying _udb functions as the
admin, but scoped to the requesting teacher's students.
"""

import json
import os
import re
import uuid as _uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from auth import get_current_user
import users_db as _udb
import reminders

# ── Paths & constants ──────────────────────────────────────────────────────────

_ROOT = Path(__file__).resolve().parent.parent
_TAXONOMY_DIR = _ROOT / "taxonomy"
_RESOURCES_DIR = _ROOT / "data" / "resources"
_UPLOADS_DIR = _ROOT / "data" / "uploads" / "homework"

STATUSES = {"not_started", "learning", "confident"}
CLASS_STATUSES = {"held", "cancelled", "missed", "rescheduled"}
ASSIGN_KINDS = {"homework", "reading", "practice", "test"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}$")
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_UPLOAD_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".doc",
                       ".docx", ".txt", ".csv", ".xlsx", ".ppt", ".pptx", ".zip"}

# ── Taxonomy ───────────────────────────────────────────────────────────────────

_TAX_CACHE: dict[str, dict] = {}


def _taxonomy(syllabus: str) -> dict:
    if syllabus in _TAX_CACHE:
        return _TAX_CACHE[syllabus]
    if not re.fullmatch(r"[0-9A-Za-z]{4,6}", syllabus):
        raise HTTPException(400, "Invalid syllabus code")
    path = _TAXONOMY_DIR / f"{syllabus}.json"
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

# ── Helpers ────────────────────────────────────────────────────────────────────


def _json_list(raw) -> list:
    if isinstance(raw, list):
        return raw
    try:
        val = json.loads(raw or "[]")
        return val if isinstance(val, list) else []
    except (TypeError, ValueError):
        return []


def _decorate(a: dict) -> dict:
    return {**a,
            "topics": _json_list(a.get("topics_json")),
            "attachments": _json_list(a.get("attachments_json")),
            "submissions": _json_list(a.get("student_submissions_json")),
            "subject_name": SUBJECT_NAMES.get(a.get("syllabus"), a.get("syllabus"))}

router = APIRouter(prefix="/api/teacher")

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


def _require_teacher(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in ("teacher", "admin"):
        raise HTTPException(403, "Teacher access required")
    return user


_Teacher = Annotated[dict, Depends(_require_teacher)]


def _assert_owns_student(teacher_id: str, student_id: str):
    students = _udb.get_teacher_students(teacher_id)
    if not any(s["student_id"] == student_id for s in students):
        raise HTTPException(403, "This student is not assigned to you")


# ── Student list ──────────────────────────────────────────────────────────────

@router.get("/students")
def teacher_students(user: _Teacher):
    rows = _udb.get_teacher_students(user["id"])
    for r in rows:
        syllabus = r.get("syllabus", "")
        r["subject_name"] = SUBJECT_NAMES.get(syllabus, syllabus)
    return {"students": rows, "teacher": {k: v for k, v in user.items()
                                          if k != "password_hash"}}


@router.get("/student/{student_id}")
def teacher_student_detail(student_id: str, user: _Teacher):
    _assert_owns_student(user["id"], student_id)
    detail = _udb.get_student_detail(student_id)
    if not detail:
        raise HTTPException(404, "Student not found")
    return detail


@router.delete("/student/{student_id}/allocation")
def drop_student(student_id: str, user: _Teacher):
    """Remove a student from this teacher's roster (soft drop: every subject's link)."""
    _assert_owns_student(user["id"], student_id)
    _udb.remove_teacher_student(user["id"], student_id)
    return {"ok": True}


# ── Homework ──────────────────────────────────────────────────────────────────

class AssignReq(BaseModel):
    syllabus: str | None = None
    kind: str = "homework"
    title: str
    instructions: str | None = None
    topics_json: str = "[]"
    attachments_json: str = "[]"
    due_date: str | None = None


@router.post("/student/{student_id}/homework")
def assign_homework(student_id: str, req: AssignReq, user: _Teacher):
    _assert_owns_student(user["id"], student_id)
    assignment = _udb.create_assignment({
        "user_id": student_id,
        "syllabus": req.syllabus,
        "kind": req.kind,
        "title": req.title.strip(),
        "instructions": req.instructions,
        "topics_json": req.topics_json,
        "attachments_json": req.attachments_json,
        "due_date": req.due_date,
        "assigned_by": user["id"],
    })
    return {"ok": True, "assignment": assignment}


@router.get("/student/{student_id}/homework")
def get_student_homework(student_id: str, user: _Teacher):
    _assert_owns_student(user["id"], student_id)
    assignments = _udb.get_assignments(student_id)
    return {"assignments": assignments}


# ── Class log ─────────────────────────────────────────────────────────────────

class ClassReq(BaseModel):
    class_date: str
    start_time: str | None = None
    duration_min: int | None = None
    syllabus: str | None = None
    status: str = "held"
    topic: str | None = None
    note: str | None = None


@router.post("/student/{student_id}/class")
def log_class(student_id: str, req: ClassReq, user: _Teacher):
    _assert_owns_student(user["id"], student_id)
    entry = _udb.create_class_entry({
        "user_id": student_id,
        "class_date": req.class_date,
        "start_time": req.start_time,
        "duration_min": req.duration_min,
        "syllabus": req.syllabus,
        "status": req.status,
        "topic": req.topic,
        "note": req.note,
    })
    return {"ok": True, "entry": entry}


@router.get("/student/{student_id}/classes")
def get_student_classes(student_id: str, user: _Teacher):
    _assert_owns_student(user["id"], student_id)
    return {"classes": _udb.get_class_log(student_id)}


# ── Teacher self-edit ─────────────────────────────────────────────────────────

class TeacherProfileUpdate(BaseModel):
    bio: str | None = None
    subjects_json: str | None = None   # JSON array e.g. '["0625","5054"]'
    qualifications: str | None = None
    experience_years: int | None = None
    phone: str | None = None


@router.get("/profile")
def get_teacher_profile(user: _Teacher):
    row = _udb.get_teacher_by_profile_id(user["id"])
    return {"profile": row}


@router.put("/profile")
def update_teacher_profile(req: TeacherProfileUpdate, user: _Teacher):
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    updated = _udb.update_teacher_by_profile_id(user["id"], fields)
    return {"ok": True, "profile": updated}


# ── Groups ────────────────────────────────────────────────────────────────────

class GroupCreate(BaseModel):
    name: str
    description: str | None = None
    syllabus: str | None = None
    max_students: int = 6
    schedule_json: str = "{}"


class GroupUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    syllabus: str | None = None
    max_students: int | None = None
    schedule_json: str | None = None


class GroupSessionReq(BaseModel):
    session_date: str
    duration_min: int | None = None
    topic: str | None = None
    notes: str | None = None
    status: str = "held"


def _assert_owns_group(teacher_id: str, group_id: int):
    g = _udb.get_group(group_id)
    if not g or g["teacher_id"] != teacher_id:
        raise HTTPException(403, "This group does not belong to you")
    return g


@router.post("/groups")
def create_group(req: GroupCreate, user: _Teacher):
    g = _udb.create_group({
        "name": req.name.strip(),
        "description": req.description,
        "teacher_id": user["id"],
        "syllabus": req.syllabus,
        "max_students": req.max_students,
        "schedule_json": req.schedule_json,
    })
    return {"ok": True, "group": g}


@router.get("/groups")
def list_teacher_groups(user: _Teacher):
    groups = _udb.get_teacher_groups(user["id"])
    for g in groups:
        g["member_count"] = _udb.get_group_member_count(g["id"])
    return {"groups": groups}


@router.get("/group/{group_id}")
def get_group_detail(group_id: int, user: _Teacher):
    g = _assert_owns_group(user["id"], group_id)
    members = _udb.get_group_members(group_id)
    sessions = _udb.get_group_sessions(group_id)
    return {"group": g, "members": members, "sessions": sessions}


@router.patch("/group/{group_id}")
def update_group(group_id: int, req: GroupUpdate, user: _Teacher):
    _assert_owns_group(user["id"], group_id)
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    updated = _udb.update_group(group_id, fields)
    return {"ok": True, "group": updated}


@router.post("/group/{group_id}/session")
def log_group_session(group_id: int, req: GroupSessionReq, user: _Teacher):
    _assert_owns_group(user["id"], group_id)
    session = _udb.create_group_session({
        "group_id": group_id,
        "session_date": req.session_date,
        "duration_min": req.duration_min,
        "topic": req.topic,
        "notes": req.notes,
        "status": req.status,
    })
    return {"ok": True, "session": session}


@router.get("/group/{group_id}/sessions")
def list_group_sessions(group_id: int, user: _Teacher):
    _assert_owns_group(user["id"], group_id)
    return {"sessions": _udb.get_group_sessions(group_id)}


# ── Syllabus taxonomy ─────────────────────────────────────────────────────────

@router.get("/syllabus/{syllabus}/topics")
def teacher_syllabus_topics(syllabus: str, user: _Teacher):
    return _taxonomy(syllabus)


# ── Chapter progress ──────────────────────────────────────────────────────────

class ProgressWrite(BaseModel):
    syllabus: str
    topic: str
    subtopic: str | None = None
    status: str | None = None
    papers_status: str | None = None


class ProgressBulk(BaseModel):
    items: list[ProgressWrite]


def _apply_progress(student_id: str, item: ProgressWrite) -> dict:
    for field, value in (("status", item.status), ("papers_status", item.papers_status)):
        if value is not None and value not in STATUSES:
            raise HTTPException(400, f"{field} must be one of: {', '.join(sorted(STATUSES))}")
    if item.status is None and item.papers_status is None:
        raise HTTPException(400, "Send status, papers_status, or both")
    _taxonomy(item.syllabus)
    return _udb.upsert_progress(student_id, item.syllabus, item.topic,
                                item.subtopic, item.status, item.papers_status)


@router.post("/student/{student_id}/progress")
def set_progress(student_id: str, req: ProgressWrite, user: _Teacher):
    _assert_owns_student(user["id"], student_id)
    return {"progress": _apply_progress(student_id, req)}


@router.post("/student/{student_id}/progress/bulk")
def set_progress_bulk(student_id: str, req: ProgressBulk, user: _Teacher):
    _assert_owns_student(user["id"], student_id)
    if not req.items:
        raise HTTPException(400, "Nothing to update")
    return {"updated": [_apply_progress(student_id, i) for i in req.items]}


# ── Past-paper tracking ───────────────────────────────────────────────────────

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


@router.post("/student/{student_id}/papers")
def set_paper(student_id: str, req: PaperWrite, user: _Teacher):
    _assert_owns_student(user["id"], student_id)
    if req.status not in STATUSES:
        raise HTTPException(400, f"status must be one of: {', '.join(sorted(STATUSES))}")
    row = _udb.upsert_paper_progress(
        student_id, req.syllabus, req.year, req.session, req.paper,
        req.variant or "", req.status, req.score, req.max_score, req.note,
        set_by="tutor")
    return {"paper": row}


# ── Class log: edit & delete ──────────────────────────────────────────────────

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
            raise HTTPException(400, f"status must be one of: {', '.join(sorted(CLASS_STATUSES))}")
        fields["status"] = req.status
    for name in ("duration_min", "syllabus", "topic", "note"):
        value = getattr(req, name)
        if value is not None:
            fields[name] = value
    return fields


def _owned_class(teacher_id: str, entry_id: int) -> dict:
    entry = _udb.get_class_entry(entry_id)
    if entry is None:
        raise HTTPException(404, "No such class entry")
    _assert_owns_student(teacher_id, entry["user_id"])
    return entry


@router.patch("/class/{entry_id}")
def edit_class(entry_id: int, req: ClassWrite, user: _Teacher):
    _owned_class(user["id"], entry_id)
    fields = _class_fields(req, creating=False)
    if not fields:
        raise HTTPException(400, "Nothing to update")
    return {"class": _udb.update_class_entry(entry_id, fields)}


@router.delete("/class/{entry_id}")
def delete_class(entry_id: int, user: _Teacher):
    _owned_class(user["id"], entry_id)
    _udb.delete_class_entry(entry_id)
    return {"status": "deleted"}


# ── Assignments: edit, delete, file upload, submission download ───────────────

class AttachmentIn(BaseModel):
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
            base = _RESOURCES_DIR.resolve()
            path = (_RESOURCES_DIR / a.rel).resolve()
            if not str(path).startswith(str(base)) or not path.is_file():
                raise HTTPException(400, f"No such resource: {a.rel}")
            out.append({"type": "resource", "rel": a.rel, "name": a.name or path.name})
        elif a.type == "booklet":
            if not isinstance(a.params, dict) or not a.params.get("topics"):
                raise HTTPException(400, "A booklet attachment needs params.topics")
            out.append({"type": "booklet", "name": a.name or "Practice booklet",
                        "params": a.params})
        elif a.type == "upload":
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
            raise HTTPException(400, f"kind must be one of: {', '.join(sorted(ASSIGN_KINDS))}")
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


def _owned_assignment(teacher_id: str, assignment_id: int) -> dict:
    row = _udb.get_assignment(assignment_id)
    if row is None:
        raise HTTPException(404, "No such assignment")
    _assert_owns_student(teacher_id, row["user_id"])
    return row


@router.patch("/homework/{assignment_id}")
def edit_homework(assignment_id: int, req: AssignmentWrite, user: _Teacher):
    _owned_assignment(user["id"], assignment_id)
    fields = _assignment_fields(req, creating=False)
    if not fields:
        raise HTTPException(400, "Nothing to update")
    return {"assignment": _decorate(_udb.update_assignment(assignment_id, fields))}


@router.delete("/homework/{assignment_id}")
def delete_homework(assignment_id: int, user: _Teacher):
    row = _owned_assignment(user["id"], assignment_id)
    for att in _json_list(row.get("attachments_json")):
        if att.get("type") == "upload":
            try:
                (_UPLOADS_DIR / att["rel"]).unlink(missing_ok=True)
            except (OSError, KeyError):
                pass
    _udb.delete_assignment(assignment_id)
    return {"status": "deleted"}


@router.post("/homework/{assignment_id}/files")
async def upload_homework_file(
    assignment_id: int,
    file: UploadFile = File(...),
    label: str | None = Form(None),
    user: dict = Depends(_require_teacher),
):
    row = _owned_assignment(user["id"], assignment_id)
    original = os.path.basename(file.filename or "file")
    ext = Path(original).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTS:
        raise HTTPException(400, f"{ext or 'That file type'} is not allowed")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is larger than 25 MB")
    if not data:
        raise HTTPException(400, "That file is empty")
    _UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    rel = f"{assignment_id}_{_uuid.uuid4().hex[:12]}{ext}"
    (_UPLOADS_DIR / rel).write_bytes(data)
    attachments = _json_list(row.get("attachments_json"))
    attachments.append({"type": "upload", "rel": rel,
                        "name": (label or original).strip() or original,
                        "size": len(data)})
    updated = _udb.update_assignment(assignment_id, {"attachments_json": json.dumps(attachments)})
    return {"assignment": _decorate(updated)}


@router.get("/homework/{assignment_id}/submission/{idx}")
def download_submission(assignment_id: int, idx: int, user: _Teacher):
    from fastapi.responses import FileResponse
    row = _owned_assignment(user["id"], assignment_id)
    submissions = _json_list(row.get("student_submissions_json"))
    if not 0 <= idx < len(submissions):
        raise HTTPException(404, "No such submission")
    sub = submissions[idx]
    path = (_UPLOADS_DIR / (sub.get("rel") or "")).resolve()
    if not path.is_file():
        raise HTTPException(404, "That file is no longer on the server")
    import mimetypes as _mt
    name = sub.get("name") or path.name
    ext = path.suffix.lower()
    if ext and not name.lower().endswith(ext):
        name = name + ext
    media_type = _mt.guess_type(str(path))[0] or "application/octet-stream"
    return FileResponse(path, filename=name, media_type=media_type)


# ── Remind student ────────────────────────────────────────────────────────────

@router.post("/student/{student_id}/remind")
def remind_student(student_id: str, user: _Teacher):
    _assert_owns_student(user["id"], student_id)
    student = _udb.get_user(student_id)
    if not student:
        raise HTTPException(404, "Student not found")
    from app import _notify
    import reminders
    items = reminders.open_homework(student_id)
    if not items:
        raise HTTPException(400, "Nothing outstanding to remind them about")
    for a in items:
        a.setdefault("subject_name", SUBJECT_NAMES.get(a.get("syllabus"), a.get("syllabus")))
    sent = reminders.send_digest_email(student, items, _notify)
    digits = "".join(ch for ch in (student.get("phone") or "") if ch.isdigit())
    whatsapp = None
    if digits:
        if digits.startswith("0"):
            digits = "92" + digits[1:]
        elif not digits.startswith("92") and len(digits) <= 11:
            digits = "92" + digits
        import urllib.parse
        first = (student.get("name") or "there").split(" ")[0]
        lines = "\n".join(
            f"- {a.get('title')} ({reminders.due_phrase(reminders.days_left(a.get('due_date')))})"
            for a in items[:6])
        text = (f"Hi {first}! Reminder about your PrepWithTee homework:\n{lines}\n\n"
                f"{reminders.APP_BASE_URL}/homework.html")
        whatsapp = f"https://wa.me/{digits}?text={urllib.parse.quote(text)}"
    return {
        "sent": sent, "count": len(items),
        "email": student.get("email"),
        "whatsapp": whatsapp,
        "detail": None if sent else "SMTP is not configured on this server.",
    }

# ── Teacher ↔ Parent Connectivity ─────────────────────────────────────────────

class ParentMessageReq(BaseModel):
    message: str


@router.get("/student/{student_id}/parent")
def get_student_parent(student_id: str, user: _Teacher):
    _assert_owns_student(user["id"], student_id)
    parents = _udb.get_linked_parents(student_id)
    return {"parent": parents[0] if parents else None, "parents": parents}


@router.post("/student/{student_id}/parent-message")
def send_parent_message(student_id: str, req: ParentMessageReq, user: _Teacher):
    _assert_owns_student(user["id"], student_id)
    msg_text = (req.message or "").strip()
    if not msg_text:
        raise HTTPException(400, "Message body required")
    parents = _udb.get_linked_parents(student_id)
    if not parents:
        raise HTTPException(404, "No parent linked to this student")

    parent_id = parents[0].get("parent_id") or parents[0].get("id")
    msg = _udb.create_message(user["id"], parent_id, msg_text)
    
    # Notify parent via email if enabled
    parent_email = parents[0].get("email")
    if parent_email:
        try:
            from app import _notify
            student_name = (_udb.get_user(student_id) or {}).get("name", "your child")
            _notify(
                f"[PrepWithTee] Message from Tutor ({user.get('name', 'Tutor')}) regarding {student_name}",
                f"Hi,\n\n{user.get('name', 'Tutor')} sent you a message regarding {student_name}:\n\n{msg_text}\n\n"
                f"Log in to reply: {reminders.APP_BASE_URL}/parent-dashboard.html",
                to=parent_email,
                cta=("Open Parent Portal", f"{reminders.APP_BASE_URL}/parent-dashboard.html")
            )
        except Exception as exc:
            print(f"[parent_message] notify failed: {exc}", flush=True)

    return {"ok": True, "message": msg}


# ── Resources flat list ───────────────────────────────────────────────────────

@router.get("/resources-flat")
def teacher_resources_flat(user: _Teacher):
    if not _RESOURCES_DIR.is_dir():
        return {"files": []}
    base = _RESOURCES_DIR.resolve()
    files = []
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.name.startswith((".", "_")):
            continue
        rel = path.relative_to(base)
        files.append({"rel": rel.as_posix(), "name": path.name,
                      "category": rel.parts[0] if len(rel.parts) > 1 else "",
                      "size": path.stat().st_size})
    return {"files": files}


# ── Teacher Groups Workflow ───────────────────────────────────────────────────

class GroupMembersReq(BaseModel):
    student_ids: list[str]


class GroupSessionReq(BaseModel):
    session_date: str
    duration_min: int | None = 60
    topic: str | None = None
    notes: str | None = None


@router.get("/groups/{group_id}")
def get_teacher_group_detail(group_id: int, user: _Teacher):
    group = _udb.get_group(group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    if group.get("teacher_id") != user["id"] and user.get("role") != "admin":
        raise HTTPException(403, "Access denied")
    members = _udb.get_group_members(group_id)
    sessions = _udb.get_group_sessions(group_id)
    return {"group": group, "members": members, "sessions": sessions}


@router.post("/groups/{group_id}/members")
def add_group_members(group_id: int, req: GroupMembersReq, user: _Teacher):
    group = _udb.get_group(group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    if group.get("teacher_id") != user["id"] and user.get("role") != "admin":
        raise HTTPException(403, "Access denied")

    added = []
    for sid in req.student_ids:
        mem = _udb.join_group(group_id, sid)
        if mem:
            added.append(mem)
    return {"status": "success", "added": len(added), "members": _udb.get_group_members(group_id)}


@router.delete("/groups/{group_id}/members/{student_id}")
def remove_group_member(group_id: int, student_id: str, user: _Teacher):
    group = _udb.get_group(group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    if group.get("teacher_id") != user["id"] and user.get("role") != "admin":
        raise HTTPException(403, "Access denied")

    _udb.leave_group(group_id, student_id)
    return {"status": "removed", "members": _udb.get_group_members(group_id)}


@router.post("/groups/{group_id}/sessions")
def create_teacher_group_session(group_id: int, req: GroupSessionReq, user: _Teacher):
    group = _udb.get_group(group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    if group.get("teacher_id") != user["id"] and user.get("role") != "admin":
        raise HTTPException(403, "Access denied")

    sess = _udb.create_group_session({
        "group_id": group_id,
        "session_date": req.session_date,
        "duration_min": req.duration_min,
        "topic": req.topic,
        "notes": req.notes,
        "status": "held",
    })
    return {"session": sess}
