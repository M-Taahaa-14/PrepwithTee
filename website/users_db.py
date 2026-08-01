"""Supabase data access for user/student tables.

All functions use the Supabase Python SDK (REST API) so no direct Postgres
connection string is needed.  Falls back to a local SQLite file
(data/users.db) when SUPABASE_URL is not set (pure local dev).
"""

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_USERS_DB = ROOT / "data" / "users.db"

_USE_SUPABASE = bool(os.environ.get("SUPABASE_URL"))

if _USE_SUPABASE:
    from supabase import create_client as _create_client
    _sb = None  # lazy init
    def _client():
        global _sb
        if _sb is None:
            _sb = _create_client(
                os.environ["SUPABASE_URL"],
                os.environ.get("SUPABASE_SERVICE_KEY")
                or os.environ["SUPABASE_SERVICE_ROLE_KEY"],
            )
        return _sb
else:
    # ── Local SQLite fallback ─────────────────────────────────────────────
    _LOCAL_SCHEMA = """
    CREATE TABLE IF NOT EXISTS profiles (
        id               TEXT PRIMARY KEY,
        email            TEXT UNIQUE NOT NULL,
        name             TEXT NOT NULL,
        picture_url      TEXT,
        google_id        TEXT UNIQUE,
        password_hash    TEXT,
        birthday         TEXT,
        gender           TEXT,
        grade            TEXT,
        phone            TEXT,
        profile_complete INTEGER DEFAULT 0,
        created_at       TEXT DEFAULT (datetime('now')),
        updated_at       TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS enrollments (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     TEXT REFERENCES profiles(id) ON DELETE CASCADE,
        syllabus    TEXT NOT NULL,
        enrolled_at TEXT DEFAULT (datetime('now')),
        status      TEXT DEFAULT 'active',
        UNIQUE(user_id, syllabus)
    );
    CREATE TABLE IF NOT EXISTS topic_progress (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id       TEXT REFERENCES profiles(id) ON DELETE CASCADE,
        syllabus      TEXT NOT NULL,
        topic         TEXT NOT NULL,
        subtopic      TEXT,
        status        TEXT DEFAULT 'not_started',
        last_reviewed TEXT,
        updated_at    TEXT DEFAULT (datetime('now')),
        UNIQUE(user_id, syllabus, topic, subtopic)
    );
    CREATE TABLE IF NOT EXISTS quiz_sessions (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id        TEXT REFERENCES profiles(id) ON DELETE CASCADE,
        syllabus       TEXT NOT NULL,
        topic          TEXT NOT NULL,
        subtopic       TEXT,
        question_text  TEXT NOT NULL,
        student_answer TEXT,
        score          INTEGER,
        ideal_answer   TEXT,
        feedback       TEXT,
        created_at     TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS teachers (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        name             TEXT NOT NULL,
        role             TEXT,
        subjects_json    TEXT NOT NULL DEFAULT '[]',
        bio              TEXT,
        picture_url      TEXT,
        qualifications   TEXT,
        experience_years INTEGER,
        display_order    INTEGER DEFAULT 0,
        active           INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS teacher_applications (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        name           TEXT,
        email          TEXT,
        phone          TEXT,
        subjects       TEXT,
        qualifications TEXT,
        experience     TEXT,
        message        TEXT,
        status         TEXT DEFAULT 'pending',
        created_at     TEXT DEFAULT (datetime('now'))
    );
    """

    def _local():
        _USERS_DB.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(_USERS_DB)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        c.executescript(_LOCAL_SCHEMA)
        return c


# ── Internal helpers ──────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_or_none(result) -> dict | None:
    if _USE_SUPABASE:
        data = result.data
        return data[0] if data else None
    return dict(result) if result else None


# ── Profile CRUD ──────────────────────────────────────────────────────────────

def get_user(user_id: str) -> dict | None:
    if _USE_SUPABASE:
        r = (_client().table("profiles")
             .select("*")
             .eq("id", user_id)
             .single()
             .execute())
        return r.data if r.data else None
    with _local() as c:
        row = c.execute("SELECT * FROM profiles WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None


def get_user_by_email(email: str) -> dict | None:
    if _USE_SUPABASE:
        r = (_client().table("profiles")
             .select("*")
             .eq("email", email)
             .limit(1)
             .execute())
        return r.data[0] if r.data else None
    with _local() as c:
        row = c.execute("SELECT * FROM profiles WHERE email=?", (email,)).fetchone()
        return dict(row) if row else None


def get_user_by_google(google_id: str) -> dict | None:
    if _USE_SUPABASE:
        r = (_client().table("profiles")
             .select("*")
             .eq("google_id", google_id)
             .limit(1)
             .execute())
        return r.data[0] if r.data else None
    with _local() as c:
        row = c.execute("SELECT * FROM profiles WHERE google_id=?",
                        (google_id,)).fetchone()
        return dict(row) if row else None


def create_user(email: str, name: str, password_hash: str | None = None,
                google_id: str | None = None, picture_url: str | None = None) -> dict:
    uid = str(uuid.uuid4())
    payload = {
        "id": uid, "email": email, "name": name,
        "password_hash": password_hash, "google_id": google_id,
        "picture_url": picture_url, "profile_complete": 0,
        "created_at": _now(), "updated_at": _now(),
    }
    if _USE_SUPABASE:
        r = _client().table("profiles").insert(payload).execute()
        return r.data[0]
    with _local() as c:
        c.execute("""INSERT INTO profiles
            (id,email,name,password_hash,google_id,picture_url,profile_complete,created_at,updated_at)
            VALUES (?,?,?,?,?,?,0,?,?)""",
            (uid, email, name, password_hash, google_id, picture_url, _now(), _now()))
        c.commit()
    return get_user(uid)


def upsert_google_user(google_id: str, email: str, name: str,
                       picture_url: str | None = None) -> dict:
    existing = get_user_by_google(google_id) or get_user_by_email(email)
    if existing:
        # Update picture/name in case they changed
        updates = {"picture_url": picture_url, "updated_at": _now()}
        if not existing.get("google_id"):
            updates["google_id"] = google_id
        if _USE_SUPABASE:
            _client().table("profiles").update(updates).eq("id", existing["id"]).execute()
        else:
            with _local() as c:
                c.execute("UPDATE profiles SET picture_url=?,updated_at=?,google_id=COALESCE(google_id,?) WHERE id=?",
                          (picture_url, _now(), google_id, existing["id"]))
                c.commit()
        return get_user(existing["id"])
    return create_user(email=email, name=name, google_id=google_id, picture_url=picture_url)


def update_profile(user_id: str, fields: dict) -> dict:
    fields["updated_at"] = _now()
    if _USE_SUPABASE:
        _client().table("profiles").update(fields).eq("id", user_id).execute()
    else:
        set_clause = ", ".join(f"{k}=?" for k in fields)
        with _local() as c:
            c.execute(f"UPDATE profiles SET {set_clause} WHERE id=?",
                      (*fields.values(), user_id))
            c.commit()
    return get_user(user_id)


# ── Enrollments ───────────────────────────────────────────────────────────────

def get_enrollments(user_id: str) -> list[str]:
    if _USE_SUPABASE:
        r = (_client().table("enrollments")
             .select("syllabus")
             .eq("user_id", user_id)
             .eq("status", "active")
             .execute())
        return [row["syllabus"] for row in (r.data or [])]
    with _local() as c:
        rows = c.execute(
            "SELECT syllabus FROM enrollments WHERE user_id=? AND status='active'",
            (user_id,)).fetchall()
        return [r["syllabus"] for r in rows]


def enroll(user_id: str, syllabus: str):
    if _USE_SUPABASE:
        (_client().table("enrollments")
         .upsert({"user_id": user_id, "syllabus": syllabus, "status": "active"},
                 on_conflict="user_id,syllabus")
         .execute())
    else:
        with _local() as c:
            c.execute("""INSERT INTO enrollments (user_id, syllabus, status)
                VALUES (?,?,'active')
                ON CONFLICT(user_id, syllabus) DO UPDATE SET status='active'""",
                (user_id, syllabus))
            c.commit()


def unenroll(user_id: str, syllabus: str):
    if _USE_SUPABASE:
        (_client().table("enrollments")
         .update({"status": "paused"})
         .eq("user_id", user_id)
         .eq("syllabus", syllabus)
         .execute())
    else:
        with _local() as c:
            c.execute("UPDATE enrollments SET status='paused' WHERE user_id=? AND syllabus=?",
                      (user_id, syllabus))
            c.commit()


# ── Topic progress ────────────────────────────────────────────────────────────

def get_progress(user_id: str, syllabus: str) -> list[dict]:
    if _USE_SUPABASE:
        r = (_client().table("topic_progress")
             .select("*")
             .eq("user_id", user_id)
             .eq("syllabus", syllabus)
             .execute())
        return r.data or []
    with _local() as c:
        rows = c.execute(
            "SELECT * FROM topic_progress WHERE user_id=? AND syllabus=?",
            (user_id, syllabus)).fetchall()
        return [dict(r) for r in rows]


def upsert_progress(user_id: str, syllabus: str, topic: str,
                    subtopic: str | None, status: str) -> dict:
    now = _now()
    payload = {
        "user_id": user_id, "syllabus": syllabus, "topic": topic,
        "subtopic": subtopic, "status": status,
        "last_reviewed": now, "updated_at": now,
    }
    if _USE_SUPABASE:
        r = (_client().table("topic_progress")
             .upsert(payload, on_conflict="user_id,syllabus,topic,subtopic")
             .execute())
        return r.data[0] if r.data else payload
    with _local() as c:
        c.execute("""INSERT INTO topic_progress
            (user_id,syllabus,topic,subtopic,status,last_reviewed,updated_at)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(user_id,syllabus,topic,subtopic)
            DO UPDATE SET status=excluded.status,
                          last_reviewed=excluded.last_reviewed,
                          updated_at=excluded.updated_at""",
            (user_id, syllabus, topic, subtopic, status, now, now))
        c.commit()
    return payload


# ── Quiz sessions ─────────────────────────────────────────────────────────────

def save_quiz(user_id: str, syllabus: str, topic: str, subtopic: str | None,
              question_text: str, student_answer: str | None,
              score: int | None, ideal_answer: str | None,
              feedback: str | None) -> dict:
    payload = {
        "user_id": user_id, "syllabus": syllabus, "topic": topic,
        "subtopic": subtopic, "question_text": question_text,
        "student_answer": student_answer, "score": score,
        "ideal_answer": ideal_answer, "feedback": feedback,
        "created_at": _now(),
    }
    if _USE_SUPABASE:
        r = _client().table("quiz_sessions").insert(payload).execute()
        return r.data[0] if r.data else payload
    with _local() as c:
        c.execute("""INSERT INTO quiz_sessions
            (user_id,syllabus,topic,subtopic,question_text,student_answer,
             score,ideal_answer,feedback,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (user_id, syllabus, topic, subtopic, question_text,
             student_answer, score, ideal_answer, feedback, _now()))
        c.commit()
    return payload


def get_quiz_history(user_id: str, syllabus: str | None, limit: int = 10) -> list[dict]:
    if _USE_SUPABASE:
        q = (_client().table("quiz_sessions")
             .select("*")
             .eq("user_id", user_id)
             .order("created_at", desc=True)
             .limit(limit))
        if syllabus:
            q = q.eq("syllabus", syllabus)
        r = q.execute()
        return r.data or []
    with _local() as c:
        if syllabus:
            rows = c.execute(
                "SELECT * FROM quiz_sessions WHERE user_id=? AND syllabus=? "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, syllabus, limit)).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM quiz_sessions WHERE user_id=? "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, limit)).fetchall()
        return [dict(r) for r in rows]


# ── Dashboard summary ─────────────────────────────────────────────────────────

def get_progress_summary(user_id: str) -> dict:
    """Returns { syllabus: {total, confident, learning, not_started} }."""
    if _USE_SUPABASE:
        r = (_client().table("topic_progress")
             .select("syllabus,status")
             .eq("user_id", user_id)
             .execute())
        rows = r.data or []
    else:
        with _local() as c:
            rows = [dict(r) for r in c.execute(
                "SELECT syllabus,status FROM topic_progress WHERE user_id=?",
                (user_id,)).fetchall()]

    summary: dict = {}
    for row in rows:
        syl = row["syllabus"]
        s = row["status"]
        if syl not in summary:
            summary[syl] = {"total": 0, "confident": 0, "learning": 0, "not_started": 0}
        summary[syl]["total"] += 1
        if s in summary[syl]:
            summary[syl][s] += 1
    return summary


# ── Teachers ──────────────────────────────────────────────────────────────────

def get_teachers() -> list[dict]:
    if _USE_SUPABASE:
        r = (_client().table("teachers")
             .select("*")
             .eq("active", True)
             .order("display_order")
             .execute())
        return r.data or []
    with _local() as c:
        rows = c.execute(
            "SELECT * FROM teachers WHERE active=1 ORDER BY display_order").fetchall()
        return [dict(r) for r in rows]


def save_teacher_application(payload: dict) -> dict:
    payload["created_at"] = _now()
    if _USE_SUPABASE:
        r = _client().table("teacher_applications").insert(payload).execute()
        return r.data[0] if r.data else payload
    with _local() as c:
        c.execute("""INSERT INTO teacher_applications
            (name,email,phone,subjects,qualifications,experience,message,created_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (payload.get("name"), payload.get("email"), payload.get("phone"),
             payload.get("subjects"), payload.get("qualifications"),
             payload.get("experience"), payload.get("message"),
             payload["created_at"]))
        c.commit()
    return payload
