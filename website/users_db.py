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
    import threading
    from supabase import create_client as _create_client

    # One client per thread. The SDK wraps a single sync httpx client, and
    # FastAPI runs these sync endpoints in a threadpool — sharing one client
    # across threads corrupts its HTTP/2 connection state and surfaces as
    # `httpx.ReadError: [WinError 10035]` whenever two requests overlap.
    _local_client = threading.local()

    def _client():
        sb = getattr(_local_client, "sb", None)
        if sb is None:
            sb = _create_client(
                os.environ["SUPABASE_URL"],
                os.environ.get("SUPABASE_SERVICE_KEY")
                or os.environ["SUPABASE_SERVICE_ROLE_KEY"],
            )
            _local_client.sb = sb
        return sb
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
        max_marks      INTEGER,
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
        active           INTEGER DEFAULT 1,
        email            TEXT,
        phone            TEXT,
        application_id   INTEGER,
        created_at       TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS teacher_applications (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        name           TEXT,
        email          TEXT,
        phone          TEXT,
        subjects       TEXT,
        subject_codes  TEXT,
        qualifications TEXT,
        experience     TEXT,
        message        TEXT,
        status         TEXT DEFAULT 'pending',
        admin_note     TEXT,
        reviewed_at    TEXT,
        teacher_id     INTEGER,
        created_at     TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS leads (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_name  TEXT,
        student_name TEXT,
        contact      TEXT,
        grade        TEXT,
        subjects     TEXT,
        message      TEXT,
        timestamp    TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS feedback (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        rating  INTEGER,
        message TEXT,
        name    TEXT,
        page    TEXT,
        type    TEXT,
        ts      TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS subject_requests (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        subject TEXT,
        board   TEXT,
        message TEXT,
        ts      TEXT DEFAULT (datetime('now'))
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
              feedback: str | None, max_marks: int | None = None) -> dict:
    payload = {
        "user_id": user_id, "syllabus": syllabus, "topic": topic,
        "subtopic": subtopic, "question_text": question_text,
        "student_answer": student_answer, "score": score,
        "max_marks": max_marks,
        "ideal_answer": ideal_answer, "feedback": feedback,
        "created_at": _now(),
    }
    if _USE_SUPABASE:
        r = _client().table("quiz_sessions").insert(payload).execute()
        return r.data[0] if r.data else payload
    with _local() as c:
        c.execute("""INSERT INTO quiz_sessions
            (user_id,syllabus,topic,subtopic,question_text,student_answer,
             score,max_marks,ideal_answer,feedback,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (user_id, syllabus, topic, subtopic, question_text,
             student_answer, score, max_marks, ideal_answer, feedback, _now()))
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
    payload.setdefault("status", "pending")
    if _USE_SUPABASE:
        r = _client().table("teacher_applications").insert(payload).execute()
        return r.data[0] if r.data else payload
    with _local() as c:
        c.execute("""INSERT INTO teacher_applications
            (name,email,phone,subjects,subject_codes,qualifications,experience,
             message,status,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (payload.get("name"), payload.get("email"), payload.get("phone"),
             payload.get("subjects"), payload.get("subject_codes"),
             payload.get("qualifications"), payload.get("experience"),
             payload.get("message"), payload["status"], payload["created_at"]))
        c.commit()
    return payload


# ── Generic helpers so the admin reads/writes look the same in both modes ─────

def _insert(table: str, payload: dict, columns: list[str]) -> dict:
    if _USE_SUPABASE:
        r = _client().table(table).insert(payload).execute()
        return r.data[0] if r.data else payload
    cols = [c for c in columns if c in payload]
    with _local() as c:
        cur = c.execute(
            f"INSERT INTO {table} ({','.join(cols)}) "
            f"VALUES ({','.join('?' for _ in cols)})",
            [payload[k] for k in cols])
        payload["id"] = cur.lastrowid
        c.commit()
    return payload


def _select_all(table: str, order_col: str, limit: int = 1000) -> list[dict]:
    if _USE_SUPABASE:
        r = (_client().table(table).select("*")
             .order(order_col, desc=True).limit(limit).execute())
        return r.data or []
    with _local() as c:
        rows = c.execute(
            f"SELECT * FROM {table} ORDER BY {order_col} DESC LIMIT ?",
            (limit,)).fetchall()
        return [dict(r) for r in rows]


# ── Leads / feedback / subject requests ──────────────────────────────────────

def save_lead(payload: dict) -> dict:
    payload["timestamp"] = _now()
    return _insert("leads", payload,
                   ["parent_name", "student_name", "contact", "grade",
                    "subjects", "message", "timestamp"])


def get_leads(limit: int = 1000) -> list[dict]:
    return _select_all("leads", "timestamp", limit)


def save_feedback(payload: dict) -> dict:
    payload["ts"] = _now()
    return _insert("feedback", payload,
                   ["rating", "message", "name", "page", "type", "ts"])


def get_feedback(limit: int = 1000) -> list[dict]:
    return _select_all("feedback", "ts", limit)


def save_subject_request(payload: dict) -> dict:
    payload["ts"] = _now()
    return _insert("subject_requests", payload, ["subject", "board", "message", "ts"])


def get_subject_requests(limit: int = 1000) -> list[dict]:
    return _select_all("subject_requests", "ts", limit)


# ── Teacher applications (admin) ─────────────────────────────────────────────

def get_teacher_applications(limit: int = 500) -> list[dict]:
    return _select_all("teacher_applications", "created_at", limit)


def get_teacher_application(app_id: int) -> dict | None:
    if _USE_SUPABASE:
        r = (_client().table("teacher_applications").select("*")
             .eq("id", app_id).limit(1).execute())
        return r.data[0] if r.data else None
    with _local() as c:
        row = c.execute("SELECT * FROM teacher_applications WHERE id=?",
                        (app_id,)).fetchone()
        return dict(row) if row else None


def update_teacher_application(app_id: int, fields: dict) -> dict | None:
    if _USE_SUPABASE:
        _client().table("teacher_applications").update(fields).eq("id", app_id).execute()
    else:
        with _local() as c:
            c.execute(
                f"UPDATE teacher_applications SET {', '.join(f'{k}=?' for k in fields)} "
                f"WHERE id=?", (*fields.values(), app_id))
            c.commit()
    return get_teacher_application(app_id)


# ── Teacher CRUD (admin) ─────────────────────────────────────────────────────

_TEACHER_COLS = ["name", "role", "subjects_json", "bio", "picture_url",
                 "qualifications", "experience_years", "display_order",
                 "active", "email", "phone", "application_id", "created_at"]


def get_all_teachers() -> list[dict]:
    """Every teacher including deactivated ones — the public route hides those."""
    if _USE_SUPABASE:
        r = _client().table("teachers").select("*").order("display_order").execute()
        return r.data or []
    with _local() as c:
        rows = c.execute("SELECT * FROM teachers ORDER BY display_order").fetchall()
        return [dict(r) for r in rows]


def get_teacher(teacher_id: int) -> dict | None:
    if _USE_SUPABASE:
        r = _client().table("teachers").select("*").eq("id", teacher_id).limit(1).execute()
        return r.data[0] if r.data else None
    with _local() as c:
        row = c.execute("SELECT * FROM teachers WHERE id=?", (teacher_id,)).fetchone()
        return dict(row) if row else None


def create_teacher(payload: dict) -> dict:
    payload.setdefault("created_at", _now())
    payload.setdefault("subjects_json", "[]")
    payload.setdefault("active", True if _USE_SUPABASE else 1)
    return _insert("teachers", payload, _TEACHER_COLS)


def update_teacher(teacher_id: int, fields: dict) -> dict | None:
    if _USE_SUPABASE:
        _client().table("teachers").update(fields).eq("id", teacher_id).execute()
    else:
        with _local() as c:
            c.execute(f"UPDATE teachers SET {', '.join(f'{k}=?' for k in fields)} "
                      f"WHERE id=?", (*fields.values(), teacher_id))
            c.commit()
    return get_teacher(teacher_id)


def delete_teacher(teacher_id: int) -> None:
    if _USE_SUPABASE:
        _client().table("teachers").delete().eq("id", teacher_id).execute()
    else:
        with _local() as c:
            c.execute("DELETE FROM teachers WHERE id=?", (teacher_id,))
            c.commit()


# ── Students (admin) ─────────────────────────────────────────────────────────

def list_students() -> list[dict]:
    """Every student profile with the counts the admin list needs.

    Enrollments, progress and quizzes are fetched in three bulk reads rather
    than per student, so the list stays one round-trip per table however many
    students there are.
    """
    if _USE_SUPABASE:
        cl = _client()
        profiles = (cl.table("profiles").select(
            "id,email,name,picture_url,grade,phone,gender,birthday,"
            "profile_complete,created_at").order("created_at", desc=True)
            .execute().data or [])
        enrolls = cl.table("enrollments").select("user_id,syllabus,status").execute().data or []
        progress = cl.table("topic_progress").select("user_id,status").execute().data or []
        quizzes = (cl.table("quiz_sessions")
                   .select("user_id,score,created_at").execute().data or [])
    else:
        with _local() as c:
            profiles = [dict(r) for r in c.execute(
                "SELECT id,email,name,picture_url,grade,phone,gender,birthday,"
                "profile_complete,created_at FROM profiles ORDER BY created_at DESC")]
            enrolls = [dict(r) for r in c.execute(
                "SELECT user_id,syllabus,status FROM enrollments")]
            progress = [dict(r) for r in c.execute(
                "SELECT user_id,status FROM topic_progress")]
            quizzes = [dict(r) for r in c.execute(
                "SELECT user_id,score,created_at FROM quiz_sessions")]

    by_user: dict[str, dict] = {
        p["id"]: {**p, "subjects": [], "topics_tracked": 0, "topics_confident": 0,
                  "quiz_count": 0, "avg_score": None, "last_active": None}
        for p in profiles}

    for e in enrolls:
        u = by_user.get(e["user_id"])
        if u is not None and e.get("status") == "active":
            u["subjects"].append(e["syllabus"])
    for p in progress:
        u = by_user.get(p["user_id"])
        if u is not None:
            u["topics_tracked"] += 1
            if p.get("status") == "confident":
                u["topics_confident"] += 1

    scores: dict[str, list[int]] = {}
    for q in quizzes:
        u = by_user.get(q["user_id"])
        if u is None:
            continue
        u["quiz_count"] += 1
        if q.get("score") is not None:
            scores.setdefault(q["user_id"], []).append(q["score"])
        created = q.get("created_at")
        if created and (u["last_active"] is None or created > u["last_active"]):
            u["last_active"] = created
    for uid, vals in scores.items():
        by_user[uid]["avg_score"] = round(sum(vals) / len(vals), 1)

    return list(by_user.values())


def get_student_detail(user_id: str) -> dict | None:
    """One student's full record: profile, enrollments, every topic, every quiz."""
    user = get_user(user_id)
    if not user:
        return None
    if _USE_SUPABASE:
        cl = _client()
        enrollments = (cl.table("enrollments").select("*")
                       .eq("user_id", user_id).execute().data or [])
        progress = (cl.table("topic_progress").select("*")
                    .eq("user_id", user_id).execute().data or [])
        quizzes = (cl.table("quiz_sessions").select("*").eq("user_id", user_id)
                   .order("created_at", desc=True).limit(200).execute().data or [])
    else:
        with _local() as c:
            enrollments = [dict(r) for r in c.execute(
                "SELECT * FROM enrollments WHERE user_id=?", (user_id,))]
            progress = [dict(r) for r in c.execute(
                "SELECT * FROM topic_progress WHERE user_id=?", (user_id,))]
            quizzes = [dict(r) for r in c.execute(
                "SELECT * FROM quiz_sessions WHERE user_id=? "
                "ORDER BY created_at DESC LIMIT 200", (user_id,))]

    return {
        "profile": {k: v for k, v in user.items() if k != "password_hash"},
        "enrollments": enrollments,
        "progress": progress,
        "quizzes": quizzes,
    }
