"""Who teaches whom - the one access rule for everything a teacher does with a
student (shared booklets, boards, folder, live classes, reports).

A teacher teaches a student when an admin has linked them in teacher_students
(status='active'), per subject. Admins pass every check. Lookups are cached
briefly; any change made through the admin console clears the cache.
"""
from __future__ import annotations

import time

import users_db as _udb

_TTL = 60
_CACHE: dict[str, tuple[float, list[dict]]] = {}


def clear() -> None:
    _CACHE.clear()


def roster(teacher_id: str) -> list[dict]:
    """teacher_students rows (one per student per subject) + the student's profile."""
    hit = _CACHE.get(teacher_id)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    try:
        rows = _udb.get_teacher_students(teacher_id)
    except Exception as exc:
        print(f"[teaching] roster failed: {exc}", flush=True)
        rows = []
    if len(_CACHE) > 500:
        _CACHE.clear()
    _CACHE[teacher_id] = (time.time(), rows)
    return rows


def is_admin(user: dict | None) -> bool:
    return bool(user) and user.get("role") == "admin"


def teaches(user: dict | None, student_id: str, syllabus: str | None = None) -> bool:
    """True if `user` is an admin, or a teacher linked to this student (for
    this subject, when one is given)."""
    if not user or not student_id:
        return False
    if is_admin(user):
        return True
    if user.get("role") != "teacher":
        return False
    return any(r.get("student_id") == student_id and (syllabus is None or r.get("syllabus") == syllabus)
               for r in roster(user["id"]))


def subjects_taught(user: dict, student_id: str) -> list[str]:
    return sorted({r["syllabus"] for r in roster(user["id"]) if r.get("student_id") == student_id
                   and r.get("syllabus")})


def students(user: dict) -> dict[str, dict]:
    """{student_id: {id, name, email, picture_url, subjects: [...]}} for a teacher."""
    out: dict[str, dict] = {}
    for r in roster(user["id"]):
        s = out.setdefault(r["student_id"], {"id": r["student_id"], "name": r.get("name"),
                                             "email": r.get("email"), "picture_url": r.get("picture_url"),
                                             "grade": r.get("grade"), "phone": r.get("phone"),
                                             "subjects": []})
        if r.get("syllabus") and r["syllabus"] not in s["subjects"]:
            s["subjects"].append(r["syllabus"])
    return out


def teachers_of(student_id: str) -> list[dict]:
    try:
        return _udb.get_student_teachers(student_id)
    except Exception:
        return []


def linked(a: dict, b_id: str) -> bool:
    """May user `a` message user `b_id`? Teacher<->their student, parent<->their
    child, anyone<->admin."""
    if not a or not b_id or a["id"] == b_id:
        return False
    if is_admin(a):
        return True
    other = _udb.get_user(b_id) or {}
    if other.get("role") == "admin":
        return True
    role = a.get("role") or "student"
    if role == "teacher":
        return teaches(a, b_id)
    if role == "student":
        if other.get("role") == "teacher":
            return any(t["id"] == b_id for t in teachers_of(a["id"]))
        if other.get("role") == "parent":
            return _parent_of(b_id, a["id"])
        return False
    if role == "parent":
        if other.get("role") == "teacher":     # a child's teacher
            return any(_teaches_id(b_id, c) for c in _children(a["id"]))
        return _parent_of(a["id"], b_id)
    return False


def _children(parent_id: str) -> list[str]:
    try:
        return [r.get("student_id") for r in _udb.get_parent_links(parent_id) if r.get("student_id")]
    except Exception:
        return []


def _parent_of(parent_id: str, student_id: str) -> bool:
    return student_id in _children(parent_id)


def _teaches_id(teacher_id: str, student_id: str) -> bool:
    return any(r.get("student_id") == student_id for r in roster(teacher_id))
