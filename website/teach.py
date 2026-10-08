"""API for the teaching console (/teach): a teacher's own students, everything
about each one, and the shared folder.

    GET    /api/teach/me                          the teacher + counts
    GET    /api/teach/overview                    Today: live classes, to mark, overdue, quiet students
    GET    /api/teach/students                    my students (one row each, subjects I teach them)
    GET    /api/teach/students/{id}               profile, subjects, progress, papers, classes, homework
    GET    /api/teach/students/{id}/activity      timeline (no payments / emails / admin notes)
    POST   /api/teach/students/{id}/progress[/bulk], GET|POST .../papers, GET|POST .../classes
    PATCH|DELETE /api/teach/classes/{id}
    GET|POST /api/teach/students/{id}/assignments, PATCH|DELETE /api/teach/assignments/{id}
    POST   /api/teach/assignments/{id}/files, GET .../submission/{idx}, POST .../students/{id}/remind
    GET    /api/teach/homework, /syllabus/{s}/topics, /resources-flat
    POST   /api/teach/students/{id}/booklets      a booklet / mock test OWNED by the student, shared ink
    POST   /api/teach/students/{id}/boards        a whiteboard owned by the student, teacher can draw
    GET    /api/teach/students/{id}/folder        the shared folder (+ homework set elsewhere)
    POST   /api/teach/students/{id}/folder        a note or link for the student
    PATCH|DELETE /api/teach/folder/{item}
    GET|POST|DELETE /api/teach/students/{id}/notes   private notes (the student never sees them)

Paths and response shapes mirror /api/admin/... so the console's student page
(static/admin/sections/student-manage.js, homework.js) runs on either API.
The admin functions do the work; this module only checks, first, that the
student is the teacher's (teaching.teaches) - anything else is a 404.
The role is read from the database on every request (a newly promoted teacher
doesn't have to sign in again).
"""
from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

import admin as _admin
import auth as _auth
import teach_store as _ts
import teaching as _teaching
import users_db as _udb

router = APIRouter(prefix="/api/teach")

HIDDEN_EVENTS = {"payment", "email", "note"}          # admin-only parts of the timeline
FOLDER_KINDS = {"booklet", "test", "board", "homework", "class", "report", "file", "note", "link"}
STATUSES = ("todo", "in_progress", "done", "marked")


def require_teacher(user: dict = Depends(_auth.get_current_user)) -> dict:
    fresh = _udb.get_user(user["id"]) or {}
    if fresh.get("role") not in ("teacher", "admin"):
        raise HTTPException(403, "This is for PrepWithTee teachers.")
    return {**user, "role": fresh["role"], "name": fresh.get("name") or user.get("name"),
            "email": fresh.get("email") or user.get("email"), "picture_url": fresh.get("picture_url")}


Teacher = Depends(require_teacher)


def _mine(user: dict, student_id: str, syllabus: str | None = None) -> dict:
    if not _teaching.teaches(user, student_id, syllabus):
        raise HTTPException(404, "No such student")
    s = _udb.get_user(student_id)
    if not s:
        raise HTTPException(404, "No such student")
    return s


def _subjects_for(user: dict, sid: str) -> list[str]:
    if user.get("role") == "admin":
        return [e["syllabus"] for e in _safe(lambda: _udb.get_active_enrollments(sid), [])]
    return _teaching.subjects_taught(user, sid)


def _safe(fn, default=None):
    try:
        return fn()
    except Exception as exc:
        print(f"[teach] {exc}", flush=True)
        return default


# ── me + overview ────────────────────────────────────────────────────────────

@router.get("/me")
def me(user=Teacher):
    return {"teacher": {k: user.get(k) for k in ("id", "name", "email", "picture_url", "role")},
            "students": len(_teaching.students(user)), "folder": _ts.available()}


def _student_rows(user: dict) -> list[dict]:
    studs = _teaching.students(user)
    rows = []
    today = date.today().isoformat()

    def one(s):
        sid = s["id"]
        prof = _udb.get_user(sid) or {}
        hw = _safe(lambda: _udb.get_assignments(sid), []) or []
        items = _safe(lambda: _ts.folder(sid), []) or []
        open_hw = [a for a in hw if a.get("status") != "done"]
        return {**s, "name": prof.get("name") or s.get("name"), "email": prof.get("email") or s.get("email"),
                "picture_url": prof.get("picture_url") or s.get("picture_url"),
                "last_active": prof.get("last_seen_at"),
                "open_homework": len(open_hw),
                "overdue": sum(1 for a in open_hw if a.get("due_date") and str(a["due_date"]) < today),
                "handed_in": sum(1 for a in open_hw if (a.get("student_submissions_json") not in (None, "", "[]"))),
                "to_mark": sum(1 for i in items if i["status"] == "done" and i["kind"] in ("booklet", "test", "homework")),
                "items": len(items), "live": False}
    out = _udb.gather(**{s["id"]: (lambda s=s: one(s)) for s in studs.values()}) if studs else {}
    rows = list(out.values())
    live = {r["student_id"] for r in _safe(lambda: _ts.live_for_teacher(user["id"]), []) or []}
    for r in rows:
        r["live"] = r["id"] in live
    rows.sort(key=lambda r: (r["name"] or "").lower())
    return rows


@router.get("/students")
def students(user=Teacher):
    return {"students": _student_rows(user)}


@router.get("/students/table")
def students_table(q: str = "", per: int = 8, user=Teacher):
    """For homework.js's student picker - only my students."""
    q = q.strip().lower()
    rows = [r for r in _student_rows(user) if not q or q in (r["name"] or "").lower() or q in (r["email"] or "").lower()]
    return {"rows": rows[:per], "total": len(rows)}


@router.get("/overview")
def overview(user=Teacher):
    rows = _student_rows(user)
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    to_mark = []
    for r in rows:
        for i in _safe(lambda: _ts.folder(r["id"]), []) or []:
            if i["status"] == "done" and i["kind"] in ("booklet", "test", "homework"):
                to_mark.append({**_item_out(i), "student": r["name"], "student_id": r["id"]})
    to_mark.sort(key=lambda i: i.get("student_done_at") or i["updated_at"] or "", reverse=True)
    return {
        "students": rows,
        "live": [r for r in rows if r["live"]],
        "to_mark": to_mark[:30],
        "overdue": [r for r in rows if r["overdue"]],
        "handed_in": [r for r in rows if r["handed_in"]],
        "quiet": [r for r in rows if not r["last_active"] or r["last_active"] < week_ago],
        "totals": {"students": len(rows), "to_mark": len(to_mark),
                   "overdue": sum(r["overdue"] for r in rows), "open": sum(r["open_homework"] for r in rows)},
    }


# ── one student ──────────────────────────────────────────────────────────────

@router.get("/students/{sid}")
def student(sid: str, user=Teacher):
    _mine(user, sid)
    d = _admin.student_detail(sid, True)
    taught = _subjects_for(user, sid)
    d["taught"] = taught
    d["teachers"] = _teaching.teachers_of(sid)
    try:
        d["parents"] = [{"id": p.get("parent_id"), "name": (p.get("profiles") or {}).get("name") or p.get("name"),
                         "email": (p.get("profiles") or {}).get("email") or p.get("email")}
                        for p in _udb.get_linked_parents(sid)]
    except Exception:
        d["parents"] = []
    return d


@router.get("/students/{sid}/activity")
def activity(sid: str, limit: int = Query(400, ge=1, le=2000), user=Teacher):
    _mine(user, sid)
    import admin_students
    a = admin_students.student_activity(sid, None, 2000, True)
    a["events"] = [e for e in a["events"] if e["type"] not in HIDDEN_EVENTS][:limit]
    a["counts"] = {k: v for k, v in a["counts"].items() if k not in HIDDEN_EVENTS}
    a.pop("plan", None)
    return a


@router.post("/students/{sid}/progress")
def progress(sid: str, req: _admin.ProgressWrite, user=Teacher):
    _mine(user, sid)
    return _admin.set_student_progress(sid, req, True)


@router.post("/students/{sid}/progress/bulk")
def progress_bulk(sid: str, req: _admin.ProgressBulk, user=Teacher):
    _mine(user, sid)
    return _admin.set_student_progress_bulk(sid, req, True)


@router.get("/students/{sid}/papers")
def papers(sid: str, user=Teacher):
    _mine(user, sid)
    return _admin.student_papers(sid, True)


@router.post("/students/{sid}/papers")
def paper_write(sid: str, req: _admin.PaperWrite, user=Teacher):
    _mine(user, sid)
    return _admin.set_student_paper(sid, req, True)


@router.get("/students/{sid}/classes")
def classes(sid: str, user=Teacher):
    _mine(user, sid)
    return _admin.student_classes(sid, True)


@router.post("/students/{sid}/classes")
def class_add(sid: str, req: _admin.ClassWrite, user=Teacher):
    _mine(user, sid)
    out = _admin.add_class(sid, req, True)
    c = out.get("class") or {}
    if c.get("id") and (c.get("syllabus") or req.syllabus):
        _safe(lambda: _ts.add_item({"student_id": sid, "teacher_id": user["id"], "syllabus": c.get("syllabus") or req.syllabus,
                                    "kind": "class", "ref_id": str(c["id"]),
                                    "title": c.get("topic") or "Class", "status": "done",
                                    "created_by": user["id"], "meta_json": {"date": c.get("class_date")}}))
    return out


def _class_mine(user: dict, entry_id: int) -> dict:
    c = _udb.get_class_entry(entry_id)
    if not c or not _teaching.teaches(user, c.get("user_id")):
        raise HTTPException(404, "No such class entry")
    return c


@router.patch("/classes/{entry_id}")
def class_edit(entry_id: int, req: _admin.ClassWrite, user=Teacher):
    _class_mine(user, entry_id)
    return _admin.edit_class(entry_id, req, True)


@router.delete("/classes/{entry_id}")
def class_delete(entry_id: int, user=Teacher):
    _class_mine(user, entry_id)
    it = _safe(lambda: _ts.item_for("class", str(entry_id)))
    if it:
        _ts.delete_item(it["id"])
    return _admin.remove_class(entry_id, True)


# ── homework ─────────────────────────────────────────────────────────────────

@router.get("/students/{sid}/assignments")
def assignments(sid: str, user=Teacher):
    _mine(user, sid)
    return _admin.student_assignments(sid, True)


@router.post("/students/{sid}/assignments")
def assignment_add(sid: str, req: _admin.AssignmentWrite, notify: bool = True, user=Teacher):
    _mine(user, sid)
    out = _admin.add_assignment(sid, req, notify, True)
    a = out["assignment"]
    _udb.update_assignment(a["id"], {"assigned_by": user["id"]})
    booklet = next((x.get("booklet_id") for x in a.get("attachments") or [] if x.get("type") == "paper"), None)
    if booklet:                                    # the paper built for this homework: one folder row, due date on it
        it = _safe(lambda: _ts.item_for("booklet", booklet)) or _safe(lambda: _ts.item_for("test", booklet))
        if it:
            _ts.update_item(it["id"], {"due_at": a.get("due_date"), "meta_json": {**(it.get("meta_json") or {}),
                                                                                  "assignment_id": a["id"]}})
            return out
    if a.get("syllabus"):
        _safe(lambda: _ts.add_item({"student_id": sid, "teacher_id": user["id"], "syllabus": a["syllabus"],
                                    "kind": "homework", "ref_id": str(a["id"]), "title": a["title"],
                                    "due_at": a.get("due_date"), "chapters_json": a.get("topics") or [],
                                    "created_by": user["id"]}))
    return out


def _assignment_mine(user: dict, aid: int) -> dict:
    a = _udb.get_assignment(aid)
    if not a or not _teaching.teaches(user, a.get("user_id")):
        raise HTTPException(404, "No such assignment")
    return a


@router.patch("/assignments/{aid}")
def assignment_edit(aid: int, req: _admin.AssignmentWrite, user=Teacher):
    _assignment_mine(user, aid)
    out = _admin.edit_assignment(aid, req, True)
    it = _safe(lambda: _ts.item_for("homework", str(aid)))
    if it and req.status:
        _ts.update_item(it["id"], {"status": "marked" if req.status == "done" else "todo"})
    return out


@router.delete("/assignments/{aid}")
def assignment_delete(aid: int, user=Teacher):
    _assignment_mine(user, aid)
    it = _safe(lambda: _ts.item_for("homework", str(aid)))
    if it:
        _ts.delete_item(it["id"])
    return _admin.remove_assignment(aid, True)


@router.post("/assignments/{aid}/files")
async def assignment_file(aid: int, file: UploadFile = File(...), label: str | None = Form(None), user=Teacher):
    _assignment_mine(user, aid)
    return await _admin.upload_assignment_file(aid, file, label, True)


@router.get("/assignments/{aid}/submission/{idx}")
def assignment_submission(aid: int, idx: int, user=Teacher):
    _assignment_mine(user, aid)
    return _admin.download_student_submission(aid, idx, True)


@router.post("/students/{sid}/remind")
def remind(sid: str, user=Teacher):
    _mine(user, sid)
    return _admin.remind_student(sid, True)


@router.get("/homework")
def homework(user=Teacher):
    mine = set(_teaching.students(user)) if user.get("role") != "admin" else None
    d = _admin.homework_overview(True)
    if mine is not None:
        d["students"] = [s for s in d["students"] if s["user_id"] in mine]
        d["totals"] = {k: (len(d["students"]) if k == "students" else sum(s.get(k, 0) for s in d["students"]))
                       for k in d["totals"]}
    return d


@router.get("/subjects")
def subjects(user=Teacher):
    """The subjects I teach (any subject for an admin) - homework.js's subject list."""
    mine = {r.get("syllabus") for r in _teaching.roster(user["id"])} if user.get("role") != "admin" else None
    return {"subject_options": [{"code": c, "name": n} for c, n in _admin.SUBJECT_NAMES.items()
                                if mine is None or c in mine]}


@router.get("/syllabus/{syllabus}/topics")
def topics(syllabus: str, user=Teacher):
    return _admin.syllabus_topics(syllabus, True)


@router.get("/resources-flat")
def resources(user=Teacher):
    return _admin.resources_flat(True)


# ── building for the student ─────────────────────────────────────────────────

@router.post("/students/{sid}/booklets")
def booklet_for(sid: str, req: dict, user=Teacher):
    """A topical booklet or mock test OWNED by the student, built from my
    selection: no quota, no enrolment needed, and both of us ink on it
    (collab). It goes in their folder."""
    syl = (req or {}).get("syllabus")
    _mine(user, sid, syl if user.get("role") != "admin" else None)
    import admin_ops
    sel = {k: v for k, v in (req or {}).items() if k not in ("ms_policy", "due_date")}
    out = admin_ops.booklet_for_student(sid, sel, {"email": user.get("email"), "id": user["id"]})
    b = _udb.get_booklet(out["id"])
    pj = {**(b.get("params_json") or {}), "collab": True, "set_by_id": user["id"]}
    if req.get("ms_policy") in ("after_finish", "now", "teacher_only"):
        pj["ms_policy"] = req["ms_policy"]
    _udb.update_booklet(out["id"], {"params_json": pj})
    kind = "test" if pj.get("kind") == "test" else "booklet"
    chapters = [p.get("chapter") for p in (req.get("picks") or []) if p.get("chapter")]
    item = _safe(lambda: _ts.add_item({"student_id": sid, "teacher_id": user["id"], "syllabus": syl, "kind": kind,
                                       "ref_id": out["id"], "title": out["title"], "chapters_json": chapters,
                                       "due_at": req.get("due_date"), "created_by": user["id"]}))
    return {**out, "item": _item_out(item) if item else None}


class BoardFor(BaseModel):
    syllabus: str
    title: str = ""
    template: str = "squared"
    chapters: list[str] = []


@router.post("/students/{sid}/boards")
def board_for(sid: str, req: BoardFor, user=Teacher):
    """A whiteboard owned by the student, that I can draw on too (shared,
    near-live). Not counted against the student's free board limit."""
    student = _mine(user, sid, req.syllabus if user.get("role") != "admin" else None)
    import whiteboard as _wb
    tpl = req.template if req.template in _wb.TEMPLATES else "squared"
    b = _wb._make_board(student, req.title.strip()[:120] or f"Lesson {date.today().strftime('%d %b')}", tpl)
    _ts.set_board_member(b["id"], user["id"], "edit", user["id"])
    _wb.S.update_board(b["id"], {"shared_with_teacher": True})
    item = _ts.add_item({"student_id": sid, "teacher_id": user["id"], "syllabus": req.syllabus, "kind": "board",
                         "ref_id": b["id"], "title": b["title"], "chapters_json": req.chapters,
                         "created_by": user["id"]})
    return {"board": {"id": b["id"], "title": b["title"], "url": f"/whiteboard/{b['id']}"}, "item": _item_out(item)}


# ── the folder ───────────────────────────────────────────────────────────────

def _url(i: dict) -> str | None:
    k, ref = i["kind"], i.get("ref_id")
    if k in ("booklet", "test") and ref:
        return f"/papers/view/{ref}"
    if k == "board" and ref:
        return f"/whiteboard/{ref}"
    if k == "link":
        return (i.get("meta_json") or {}).get("url")
    if k == "report" and ref:
        return f"/classroom/report/{ref}"
    return None


def _item_out(i: dict) -> dict:
    return {**{k: i.get(k) for k in ("id", "student_id", "teacher_id", "syllabus", "kind", "ref_id", "title",
                                     "status", "due_at", "created_at", "updated_at", "student_opened_at",
                                     "student_done_at", "marked_at")},
            "chapters": i.get("chapters_json") or [], "meta": i.get("meta_json") or {}, "url": _url(i)}


def folder_for(sid: str, syllabus: str | None, private: bool) -> list[dict]:
    """The folder as both sides see it: folder rows, plus homework set without
    one (older homework, or set by the admin), newest first. `private` adds
    the teacher's own notes."""
    items = [_item_out(i) for i in (_safe(lambda: _ts.folder(sid, syllabus), []) or [])
             if private or i["kind"] != "tnote"]
    if not private:
        items = [i for i in items if not (i["meta"] or {}).get("private")]
    have = {i["ref_id"] for i in items if i["kind"] == "homework"}
    have |= {str((i["meta"] or {}).get("assignment_id")) for i in items if (i["meta"] or {}).get("assignment_id")}
    for a in _safe(lambda: _udb.get_assignments(sid), []) or []:
        if str(a["id"]) in have or (syllabus and a.get("syllabus") != syllabus):
            continue
        subs = a.get("student_submissions_json")
        handed = bool(subs and subs not in ("[]", []))
        items.append({"id": f"hw-{a['id']}", "student_id": sid, "teacher_id": a.get("assigned_by"),
                      "syllabus": a.get("syllabus"), "kind": "homework", "ref_id": str(a["id"]), "title": a["title"],
                      "status": "marked" if a.get("status") == "done" else "done" if handed else "todo",
                      "due_at": a.get("due_date"), "created_at": a.get("created_at"), "updated_at": a.get("updated_at"),
                      "student_opened_at": a.get("seen_at"), "student_done_at": None, "marked_at": a.get("completed_at"),
                      "chapters": [], "meta": {"virtual": True}, "url": "/homework.html"})
    items.sort(key=lambda i: i.get("updated_at") or i.get("created_at") or "", reverse=True)
    return items


@router.get("/students/{sid}/folder")
def folder(sid: str, syllabus: str | None = None, user=Teacher):
    _mine(user, sid)
    items = folder_for(sid, syllabus, private=False)
    for i in items:
        if i["kind"] in ("booklet", "test", "board"):
            i["fb"] = [f for f in _safe(lambda: _ts.feedback(i["id"]), []) or []] if not i["meta"].get("virtual") else []
    return {"items": items, "counts": {s: sum(1 for i in items if i["status"] == s) for s in STATUSES}}


class FolderNew(BaseModel):
    syllabus: str
    kind: str = "note"                 # note | link
    title: str
    body: str | None = None
    url: str | None = None
    chapters: list[str] = []
    due_at: str | None = None


@router.post("/students/{sid}/folder")
def folder_add(sid: str, req: FolderNew, user=Teacher):
    _mine(user, sid)
    if req.kind not in ("note", "link"):
        raise HTTPException(400, "Add a note or a link here - papers and boards have their own buttons.")
    if not req.title.strip():
        raise HTTPException(400, "Give it a title")
    if req.kind == "link" and not (req.url or "").startswith(("https://", "http://", "/")):
        raise HTTPException(400, "Links start with https://")
    item = _ts.add_item({"student_id": sid, "teacher_id": user["id"], "syllabus": req.syllabus, "kind": req.kind,
                         "title": req.title.strip()[:200], "chapters_json": req.chapters, "due_at": req.due_at,
                         "created_by": user["id"],
                         "meta_json": {"body": (req.body or "")[:5000], "url": req.url} if req.kind == "link"
                         else {"body": (req.body or "")[:5000]}})
    return {"item": _item_out(item)}


class FolderPatch(BaseModel):
    status: str | None = None
    title: str | None = None
    due_at: str | None = None
    chapters: list[str] | None = None


def _item_mine(user: dict, item_id: str) -> dict:
    it = _ts.get_item(item_id)
    if not it or not _teaching.teaches(user, it["student_id"]):
        raise HTTPException(404, "Not found")
    return it


@router.patch("/folder/{item_id}")
def folder_patch(item_id: str, req: FolderPatch, user=Teacher):
    it = _item_mine(user, item_id)
    f: dict = {}
    if req.status is not None:
        if req.status not in STATUSES:
            raise HTTPException(400, "Unknown status")
        f["status"] = req.status
        if req.status == "marked":
            f["marked_at"] = _ts.now()
    if req.title is not None and req.title.strip():
        f["title"] = req.title.strip()[:200]
    if req.due_at is not None:
        f["due_at"] = req.due_at or None
    if req.chapters is not None:
        f["chapters_json"] = req.chapters
    if f:
        _ts.update_item(it["id"], f)
    return {"item": _item_out(_ts.get_item(it["id"]))}


@router.delete("/folder/{item_id}")
def folder_delete(item_id: str, user=Teacher):
    """Takes the row out of the folder. The paper / board itself stays with the
    student (it is theirs)."""
    it = _item_mine(user, item_id)
    _ts.delete_item(it["id"])
    return {"ok": True}


# ── private notes ────────────────────────────────────────────────────────────

class NoteIn(BaseModel):
    body: str
    syllabus: str | None = None


@router.get("/students/{sid}/notes")
def notes(sid: str, user=Teacher):
    _mine(user, sid)
    rows = [i for i in (_safe(lambda: _ts.folder(sid), []) or []) if i["kind"] == "tnote"
            and (i["teacher_id"] == user["id"] or user.get("role") == "admin")]
    return {"notes": [{"id": i["id"], "body": (i.get("meta_json") or {}).get("body", ""), "syllabus": i["syllabus"],
                       "at": i["created_at"]} for i in rows]}


@router.post("/students/{sid}/notes")
def note_add(sid: str, req: NoteIn, user=Teacher):
    _mine(user, sid)
    if not req.body.strip():
        raise HTTPException(400, "Write the note first")
    i = _ts.add_item({"student_id": sid, "teacher_id": user["id"], "syllabus": req.syllabus or "-", "kind": "tnote",
                      "title": "Note", "status": "done", "created_by": user["id"],
                      "meta_json": {"body": req.body.strip()[:5000], "private": True}})
    return {"id": i["id"]}


@router.delete("/students/{sid}/notes/{note_id}")
def note_delete(sid: str, note_id: str, user=Teacher):
    _mine(user, sid)
    it = _ts.get_item(note_id)
    if not it or it["kind"] != "tnote" or it["student_id"] != sid or (
            it["teacher_id"] != user["id"] and user.get("role") != "admin"):
        raise HTTPException(404, "Not found")
    _ts.delete_item(note_id)
    return {"ok": True}
