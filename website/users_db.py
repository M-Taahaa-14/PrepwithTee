"""Supabase data access for user/student tables.

All functions use the Supabase Python SDK (REST API) so no direct Postgres
connection string is needed.  Falls back to a local SQLite file
(data/users.db) when SUPABASE_URL is not set (pure local dev).
"""

import json
import os
import re
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import env_guard as _env_guard

ROOT = Path(__file__).resolve().parent.parent
# Overridable so the test suite gets a throwaway file instead of the dev one.
_USERS_DB = Path(os.environ.get("USERS_DB_PATH") or ROOT / "data" / "users.db")

_env_guard.check()
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
        plan             TEXT NOT NULL DEFAULT 'free',
        plan_expires_at  TEXT,
        plan_started_at  TEXT,
        plan_trial       INTEGER NOT NULL DEFAULT 0,
        role             TEXT NOT NULL DEFAULT 'student',
        flags_json       TEXT NOT NULL DEFAULT '{}',
        created_at       TEXT DEFAULT (datetime('now')),
        updated_at       TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS enrollments (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     TEXT REFERENCES profiles(id) ON DELETE CASCADE,
        syllabus    TEXT NOT NULL,
        enrolled_at TEXT DEFAULT (datetime('now')),
        status      TEXT DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
        UNIQUE(user_id, syllabus)
    );
    -- Which Cambridge boards a student studies (migrations/019_student_boards.sql)
    CREATE TABLE IF NOT EXISTS student_boards (
        user_id    TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        board      TEXT NOT NULL CHECK (board IN ('o-level', 'igcse', 'a-level')),
        is_primary INTEGER NOT NULL DEFAULT 0,
        added_at   TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (user_id, board)
    );
    -- AI help on questions (migrations/021_ai_help.sql)
    CREATE TABLE IF NOT EXISTS explanation_unlocks (
        user_id     TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        question_id INTEGER NOT NULL,
        unlocked_at TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (user_id, question_id)
    );
    CREATE TABLE IF NOT EXISTS explanation_messages (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        question_id INTEGER NOT NULL,
        role        TEXT NOT NULL,
        quoted_text TEXT,
        content     TEXT NOT NULL,
        created_at  TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS explanation_reports (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     TEXT,
        question_id INTEGER NOT NULL,
        reason      TEXT,
        created_at  TEXT DEFAULT (datetime('now'))
    );
    -- Web-builder topical booklets (migrations/020_booklets.sql)
    CREATE TABLE IF NOT EXISTS booklets (
        id            TEXT PRIMARY KEY,
        user_id       TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        syllabus      TEXT NOT NULL,
        title         TEXT,
        params_json   TEXT NOT NULL DEFAULT '{}',
        question_ids  TEXT NOT NULL DEFAULT '[]',
        seed          INTEGER,
        status        TEXT NOT NULL DEFAULT 'queued',
        progress      INTEGER NOT NULL DEFAULT 0,
        stage         TEXT,
        page_map_json TEXT,
        error         TEXT,
        created_at    TEXT DEFAULT (datetime('now')),
        updated_at    TEXT DEFAULT (datetime('now'))
    );
    -- MCQ practice sessions + page annotations (migrations/022_mcq_sessions_annotations.sql)
    CREATE TABLE IF NOT EXISTS mcq_sessions (
        id            TEXT PRIMARY KEY,
        user_id       TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        syllabus      TEXT NOT NULL,
        kind          TEXT NOT NULL,
        paper_id      INTEGER,
        title         TEXT,
        question_ids  TEXT NOT NULL DEFAULT '[]',
        settings      TEXT NOT NULL DEFAULT '{}',
        answers       TEXT NOT NULL DEFAULT '{}',
        status        TEXT NOT NULL DEFAULT 'active',
        elapsed_s     INTEGER NOT NULL DEFAULT 0,
        score         INTEGER,
        total         INTEGER,
        created_at    TEXT DEFAULT (datetime('now')),
        updated_at    TEXT DEFAULT (datetime('now')),
        submitted_at  TEXT
    );
    CREATE TABLE IF NOT EXISTS page_annotations (
        user_id     TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        doc_key     TEXT NOT NULL,
        page        INTEGER NOT NULL,
        strokes     TEXT NOT NULL DEFAULT '[]',
        updated_at  TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (user_id, doc_key, page)
    );
    CREATE TABLE IF NOT EXISTS calc_state (
        user_id     TEXT PRIMARY KEY REFERENCES profiles(id) ON DELETE CASCADE,
        mem         REAL NOT NULL DEFAULT 0,
        ans         REAL NOT NULL DEFAULT 0,
        vars        TEXT NOT NULL DEFAULT '{}',
        deg         INTEGER NOT NULL DEFAULT 1,
        history     TEXT NOT NULL DEFAULT '[]',
        updated_at  TEXT DEFAULT (datetime('now'))
    );
    -- subtopic is NOT NULL DEFAULT '' on purpose: a chapter-level row used to
    -- store NULL, and neither SQLite nor Postgres treats two NULLs as equal in
    -- a UNIQUE key, so every chapter save inserted a duplicate instead of
    -- updating. '' is stored on write and mapped back to None on read (see
    -- _chapter / _out_subtopic below), so callers still speak in None.
    CREATE TABLE IF NOT EXISTS topic_progress (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id       TEXT REFERENCES profiles(id) ON DELETE CASCADE,
        syllabus      TEXT NOT NULL,
        topic         TEXT NOT NULL,
        subtopic      TEXT NOT NULL DEFAULT '',
        status        TEXT DEFAULT 'not_started',
        -- Second, independent axis: have they drilled this chapter's
        -- past-paper questions? Exam-ready = both are 'confident'.
        papers_status TEXT NOT NULL DEFAULT 'not_started',
        papers_updated_at TEXT,
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
        email   TEXT,
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

    -- ── Teaching side ────────────────────────────────────────────────────
    -- Which whole past papers a student has worked through. Same three-state
    -- vocabulary as topic_progress so the two read alike on the dashboard.
    CREATE TABLE IF NOT EXISTS paper_progress (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    TEXT REFERENCES profiles(id) ON DELETE CASCADE,
        syllabus   TEXT NOT NULL,
        year       INTEGER NOT NULL,
        session    TEXT NOT NULL,
        paper      INTEGER NOT NULL,
        variant    TEXT NOT NULL DEFAULT '',
        status     TEXT DEFAULT 'not_started',
        score      INTEGER,
        max_score  INTEGER,
        note       TEXT,
        set_by     TEXT DEFAULT 'student',   -- student | tutor
        updated_at TEXT DEFAULT (datetime('now')),
        UNIQUE(user_id, syllabus, year, session, paper, variant)
    );

    -- One row per lesson. The tutor owns it; the student sees it read-only.
    CREATE TABLE IF NOT EXISTS class_log (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      TEXT REFERENCES profiles(id) ON DELETE CASCADE,
        class_date   TEXT NOT NULL,            -- YYYY-MM-DD
        start_time   TEXT,                     -- HH:MM, optional
        duration_min INTEGER,
        syllabus     TEXT,
        status       TEXT DEFAULT 'held',      -- held|cancelled|missed|rescheduled
        topic        TEXT,
        note         TEXT,
        created_at   TEXT DEFAULT (datetime('now')),
        updated_at   TEXT DEFAULT (datetime('now'))
    );

    -- The student diary. attachments_json is a list of
    --   {"type":"upload"|"resource"|"booklet", ...}
    -- so one row carries an uploaded worksheet, a notes file from
    -- data/resources, and a generated topical booklet all at once.
    CREATE TABLE IF NOT EXISTS assignments (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id          TEXT REFERENCES profiles(id) ON DELETE CASCADE,
        syllabus         TEXT,
        kind             TEXT DEFAULT 'homework',  -- homework|reading|practice|test
        title            TEXT NOT NULL,
        instructions     TEXT,
        topics_json      TEXT DEFAULT '[]',
        attachments_json TEXT DEFAULT '[]',
        due_date         TEXT,                     -- YYYY-MM-DD
        status           TEXT DEFAULT 'assigned',  -- assigned|done
        student_note     TEXT,
        seen_at          TEXT,
        completed_at     TEXT,
        student_submissions_json TEXT DEFAULT '[]',
        assigned_by      TEXT,
        created_at       TEXT DEFAULT (datetime('now')),
        updated_at       TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS usage_events (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     TEXT REFERENCES profiles(id) ON DELETE CASCADE,
        event_type  TEXT NOT NULL,
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS usage_events_user_month
        ON usage_events(user_id, event_type, created_at);

    CREATE TABLE IF NOT EXISTS daily_time_spent (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        date        TEXT NOT NULL DEFAULT (date('now')),
        seconds     INTEGER NOT NULL DEFAULT 0,
        UNIQUE(user_id, date)
    );
    CREATE INDEX IF NOT EXISTS daily_time_spent_user_date
        ON daily_time_spent(user_id, date);

    CREATE TABLE IF NOT EXISTS grade_thresholds (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        syllabus    TEXT NOT NULL,
        subject     TEXT NOT NULL,
        level       TEXT NOT NULL,
        year        INTEGER NOT NULL,
        session     TEXT NOT NULL,
        paper       INTEGER NOT NULL,
        variant     TEXT NOT NULL DEFAULT '',
        max_mark    INTEGER NOT NULL,
        grade_astar INTEGER,
        grade_a     INTEGER NOT NULL,
        grade_b     INTEGER NOT NULL,
        grade_c     INTEGER NOT NULL,
        grade_d     INTEGER NOT NULL,
        grade_e     INTEGER NOT NULL,
        status      TEXT NOT NULL DEFAULT 'official',
        UNIQUE(syllabus, year, session, paper, variant)
    );
    CREATE INDEX IF NOT EXISTS idx_grade_thresholds_lookup
        ON grade_thresholds(syllabus, year, session, paper, variant);

    CREATE TABLE IF NOT EXISTS pdf_annotations (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id       TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        paper_id      INTEGER NOT NULL,
        assignment_id INTEGER,
        data          TEXT NOT NULL DEFAULT '{}',
        created_at    TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(user_id, paper_id, assignment_id)
    );

    CREATE TABLE IF NOT EXISTS teacher_students (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        teacher_id   TEXT NOT NULL,
        student_id   TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        syllabus     TEXT NOT NULL,
        allocated_at TEXT NOT NULL DEFAULT (datetime('now')),
        status       TEXT NOT NULL DEFAULT 'active',
        UNIQUE(teacher_id, student_id, syllabus)
    );
    CREATE TABLE IF NOT EXISTS courses (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        syllabus_code    TEXT NOT NULL,
        slug             TEXT UNIQUE NOT NULL,
        title            TEXT NOT NULL,
        level            TEXT NOT NULL,
        subject          TEXT NOT NULL,
        tagline          TEXT,
        overview_html    TEXT,
        approach_html    TEXT,
        what_you_get_json TEXT DEFAULT '[]',
        teacher_id       INTEGER,
        meta_title       TEXT,
        meta_description TEXT,
        published        INTEGER NOT NULL DEFAULT 0,
        sort_order       INTEGER NOT NULL DEFAULT 0,
        created_at       TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
    );

    -- ── Groups (small-group tutoring) ────────────────────────────────────
    CREATE TABLE IF NOT EXISTS groups (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        name         TEXT NOT NULL,
        description  TEXT,
        teacher_id   TEXT NOT NULL,          -- profiles.id of the teacher
        syllabus     TEXT,
        max_students INTEGER NOT NULL DEFAULT 6,
        schedule_json TEXT NOT NULL DEFAULT '{}',
        status       TEXT NOT NULL DEFAULT 'draft',  -- draft|active|closed
        created_at   TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS group_memberships (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id   INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
        student_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        joined_at  TEXT NOT NULL DEFAULT (datetime('now')),
        status     TEXT NOT NULL DEFAULT 'active',  -- active|left
        UNIQUE(group_id, student_id)
    );
    CREATE TABLE IF NOT EXISTS group_sessions (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id     INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
        session_date TEXT NOT NULL,
        duration_min INTEGER,
        topic        TEXT,
        notes        TEXT,
        status       TEXT NOT NULL DEFAULT 'held',  -- held|cancelled
        created_at   TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS parent_student_links (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_id   TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        student_id  TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        created_at  TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(parent_id, student_id)
    );
    CREATE TABLE IF NOT EXISTS messages (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id    TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        recipient_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        body         TEXT NOT NULL,
        read_at      TEXT,
        created_at   TEXT NOT NULL DEFAULT (datetime('now'))
    );
    -- Admin console v2 (migrations/025_admin_v2.sql)
    CREATE TABLE IF NOT EXISTS admin_audit (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id     TEXT,
        admin_email  TEXT,
        via          TEXT,
        action       TEXT NOT NULL,
        target       TEXT,
        details_json TEXT NOT NULL DEFAULT '{}',
        ok           INTEGER NOT NULL DEFAULT 1,
        created_at   TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS admin_audit_created ON admin_audit (created_at);
    CREATE TABLE IF NOT EXISTS admin_views (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id    TEXT,
        section     TEXT NOT NULL,
        name        TEXT NOT NULL,
        params_json TEXT NOT NULL DEFAULT '{}',
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS admin_notes (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id  TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        admin_id    TEXT,
        admin_name  TEXT,
        body        TEXT NOT NULL,
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS admin_notes_student ON admin_notes (student_id, created_at);
    CREATE TABLE IF NOT EXISTS inbox_status (
        source       TEXT NOT NULL,
        item_id      TEXT NOT NULL,
        status       TEXT NOT NULL DEFAULT 'new',
        handled_by   TEXT,
        note         TEXT,
        replies_json TEXT NOT NULL DEFAULT '[]',
        updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (source, item_id)
    );
    CREATE TABLE IF NOT EXISTS newsletter_broadcasts (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        subject       TEXT NOT NULL,
        body_markdown TEXT NOT NULL,
        cta_label     TEXT,
        cta_url       TEXT,
        status        TEXT NOT NULL DEFAULT 'queued',
        scheduled_at  TEXT,
        total         INTEGER NOT NULL DEFAULT 0,
        sent          INTEGER NOT NULL DEFAULT 0,
        failed        INTEGER NOT NULL DEFAULT 0,
        created_by    TEXT,
        created_at    TEXT NOT NULL DEFAULT (datetime('now')),
        started_at    TEXT,
        finished_at   TEXT,
        error         TEXT,
        worker        TEXT,
        heartbeat_at  TEXT
    );
    CREATE TABLE IF NOT EXISTS newsletter_sends (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        broadcast_id INTEGER NOT NULL REFERENCES newsletter_broadcasts(id) ON DELETE CASCADE,
        email        TEXT NOT NULL,
        ok           INTEGER NOT NULL DEFAULT 0,
        error        TEXT,
        sent_at      TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE (broadcast_id, email)
    );
    CREATE TABLE IF NOT EXISTS email_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        template_id TEXT NOT NULL,
        sent_at     TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS email_log_user_template
        ON email_log (user_id, template_id, sent_at);
    CREATE TABLE IF NOT EXISTS contacts (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT,
        email      TEXT NOT NULL,
        subject    TEXT,
        message    TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS newsletter_subscribers (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        email         TEXT UNIQUE NOT NULL,
        subscribed_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS payment_proofs (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id        TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        plan           TEXT NOT NULL,
        amount_pkr     INTEGER,
        method         TEXT,          -- jazzcash|easypaisa|bank|other
        transaction_id TEXT,
        screenshot_url TEXT,
        note           TEXT,
        status         TEXT NOT NULL DEFAULT 'pending',  -- pending|approved|rejected
        reviewed_by    TEXT,
        reviewed_at    TEXT,
        created_at     TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS grade_options (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        syllabus      TEXT    NOT NULL,
        subject       TEXT    NOT NULL,
        level         TEXT    NOT NULL,
        board         TEXT    NOT NULL DEFAULT 'CAIE',
        year          INTEGER NOT NULL,
        session       TEXT    NOT NULL,
        option_code   TEXT    NOT NULL,
        components    TEXT    NOT NULL,
        max_mark      INTEGER NOT NULL,
        is_as_level   INTEGER NOT NULL DEFAULT 0,
        grade_astar   INTEGER,
        grade_a       INTEGER NOT NULL,
        grade_b       INTEGER NOT NULL,
        grade_c       INTEGER NOT NULL,
        grade_d       INTEGER NOT NULL,
        grade_e       INTEGER NOT NULL,
        grade_f       INTEGER,
        grade_g       INTEGER,
        status        TEXT    NOT NULL DEFAULT 'official',
        UNIQUE (syllabus, year, session, option_code)
    );
    CREATE INDEX IF NOT EXISTS idx_grade_options_lookup
        ON grade_options (syllabus, year, session);

    CREATE TABLE IF NOT EXISTS student_scores (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id          TEXT    NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        syllabus         TEXT    NOT NULL,
        year             INTEGER NOT NULL,
        session          TEXT    NOT NULL,
        paper            INTEGER NOT NULL,
        variant          TEXT    NOT NULL,
        raw_mark         INTEGER NOT NULL,
        max_mark         INTEGER NOT NULL,
        component_grade  TEXT,
        option_code      TEXT,
        notes            TEXT,
        recorded_at      TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at       TEXT    NOT NULL DEFAULT (datetime('now')),
        UNIQUE (user_id, syllabus, year, session, paper, variant)
    );
    CREATE INDEX IF NOT EXISTS idx_student_scores_user
        ON student_scores (user_id, syllabus, year, session);

    CREATE TABLE IF NOT EXISTS tutor_sessions (
        id            TEXT PRIMARY KEY,
        user_id       TEXT REFERENCES profiles(id) ON DELETE CASCADE,
        title         TEXT,
        subject       TEXT,
        topic         TEXT,
        pinned        INTEGER DEFAULT 0,
        mode          TEXT DEFAULT 'normal',
        summary       TEXT,
        created_at    TEXT DEFAULT (datetime('now')),
        updated_at    TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_tutor_sessions_user ON tutor_sessions(user_id, updated_at DESC);

    CREATE TABLE IF NOT EXISTS tutor_messages (
        id            TEXT PRIMARY KEY,
        session_id    TEXT REFERENCES tutor_sessions(id) ON DELETE CASCADE,
        role          TEXT NOT NULL,
        content       TEXT NOT NULL,
        attachments   TEXT DEFAULT '[]',
        provider      TEXT,
        feedback      TEXT,
        created_at    TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_tutor_messages_session ON tutor_messages(session_id, created_at);

    CREATE TABLE IF NOT EXISTS notes (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id             TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        type                TEXT NOT NULL DEFAULT 'text',
        title               TEXT,
        content             TEXT,
        color               TEXT,
        linked_type         TEXT,
        linked_id           TEXT,
        linked_label        TEXT,
        syllabus            TEXT,
        tags_json           TEXT NOT NULL DEFAULT '[]',
        pinned_to_dashboard INTEGER NOT NULL DEFAULT 0,
        location_json       TEXT,
        is_mistake          INTEGER NOT NULL DEFAULT 0,
        is_exam_revision    INTEGER NOT NULL DEFAULT 0,
        created_at          TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_notes_user   ON notes(user_id, updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_notes_linked ON notes(linked_type, linked_id);

    CREATE TABLE IF NOT EXISTS user_stats (
        user_id    TEXT PRIMARY KEY REFERENCES profiles(id) ON DELETE CASCADE,
        xp_total   INTEGER NOT NULL DEFAULT 0,
        xp_log     TEXT NOT NULL DEFAULT '[]',
        streak     INTEGER NOT NULL DEFAULT 0,
        streak_max INTEGER NOT NULL DEFAULT 0,
        badges     TEXT NOT NULL DEFAULT '[]',
        focus      TEXT NOT NULL DEFAULT '{}',
        missions   TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS password_reset_tokens (
        token      TEXT PRIMARY KEY,
        user_id    TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        expires_at TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """

    def _local():
        _USERS_DB.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(_USERS_DB)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        c.executescript(_LOCAL_SCHEMA)
        # Safe migrations for existing databases
        _safe_alters = [
            "ALTER TABLE assignments ADD COLUMN student_submissions_json TEXT DEFAULT '[]'",
            "ALTER TABLE feedback ADD COLUMN email TEXT",
            "ALTER TABLE assignments ADD COLUMN assigned_by TEXT",
            "ALTER TABLE profiles ADD COLUMN plan TEXT NOT NULL DEFAULT 'free'",
            "ALTER TABLE profiles ADD COLUMN plan_expires_at TEXT",
            "ALTER TABLE profiles ADD COLUMN role TEXT NOT NULL DEFAULT 'student'",
            "ALTER TABLE profiles ADD COLUMN flags_json TEXT NOT NULL DEFAULT '{}'",
            "ALTER TABLE profiles ADD COLUMN persona TEXT",
            "ALTER TABLE profiles ADD COLUMN student_code TEXT",
            "ALTER TABLE teachers ADD COLUMN profile_id TEXT",
            "ALTER TABLE paper_progress ADD COLUMN grade TEXT",
            "ALTER TABLE paper_progress ADD COLUMN confidence TEXT",
            "ALTER TABLE paper_progress ADD COLUMN attempts_json TEXT DEFAULT '[]'",
            "ALTER TABLE paper_progress ADD COLUMN synced INTEGER DEFAULT 0",
            "ALTER TABLE profiles ADD COLUMN referral_code TEXT",
            "ALTER TABLE newsletter_subscribers ADD COLUMN unsubscribe_token TEXT",
            "ALTER TABLE newsletter_subscribers ADD COLUMN unsubscribed_at TEXT",
            "ALTER TABLE newsletter_subscribers ADD COLUMN status TEXT DEFAULT 'subscribed'",
            "ALTER TABLE student_scores ADD COLUMN set_by TEXT DEFAULT 'student'",
            "ALTER TABLE tutor_sessions ADD COLUMN mode TEXT DEFAULT 'normal'",
            "ALTER TABLE profiles ADD COLUMN plan_started_at TEXT",
            "ALTER TABLE profiles ADD COLUMN plan_trial INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE payment_proofs ADD COLUMN reviewer_note TEXT",
            "ALTER TABLE payment_proofs ADD COLUMN subjects_json TEXT",
            "ALTER TABLE usage_events ADD COLUMN syllabus TEXT",
            "ALTER TABLE profiles ADD COLUMN last_seen_at TEXT",
            "ALTER TABLE payment_proofs ADD COLUMN period TEXT",
            "ALTER TABLE payment_proofs ADD COLUMN expected_pkr INTEGER",
            "ALTER TABLE payment_proofs ADD COLUMN screenshot_sha256 TEXT",
            "ALTER TABLE courses ADD COLUMN faq_json TEXT",
            "ALTER TABLE profiles ADD COLUMN plan_subjects_json TEXT NOT NULL DEFAULT '[]'",
        ]
        for stmt in _safe_alters:
            try:
                c.execute(stmt)
                c.commit()
            except sqlite3.OperationalError:
                pass

        try:
            c.execute("UPDATE enrollments SET status='inactive' WHERE status='paused'")
            c.commit()
        except sqlite3.OperationalError:
            pass

        # Seed grade_thresholds from JSON file if empty
        try:
            row = c.execute("SELECT COUNT(*) FROM grade_thresholds").fetchone()
            if row and row[0] == 0:
                seed_file = Path(__file__).parent.parent / "supabase" / "grade_thresholds_seed.json"
                if seed_file.exists():
                    import json
                    with open(seed_file, "r", encoding="utf-8") as f:
                        records = json.load(f)
                    for r in records:
                        t = r.get("thresholds", {})
                        c.execute(
                            "INSERT OR IGNORE INTO grade_thresholds "
                            "(syllabus, subject, level, year, session, paper, variant, max_mark, "
                            "grade_astar, grade_a, grade_b, grade_c, grade_d, grade_e, status) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (r["syllabus"], r["subject"], r["level"], int(r["year"]), r["session"],
                             int(r["paper"]), r.get("variant", ""), int(r["max_mark"]),
                             t.get("A*"), t.get("A", 0), t.get("B", 0), t.get("C", 0),
                             t.get("D", 0), t.get("E", 0), r.get("status", "official"))
                        )
                    c.commit()
        except Exception:
            pass

        # Seed grade_options from JSON file if empty
        try:
            row = c.execute("SELECT COUNT(*) FROM grade_options").fetchone()
            if row and row[0] == 0:
                seed_file = Path(__file__).parent.parent / "supabase" / "grade_options_seed.json"
                if seed_file.exists():
                    import json
                    with open(seed_file, "r", encoding="utf-8") as f:
                        records = json.load(f)
                    for r in records:
                        t = r.get("thresholds", {})
                        c.execute(
                            "INSERT OR IGNORE INTO grade_options "
                            "(syllabus, subject, level, board, year, session, option_code, "
                            "components, max_mark, grade_astar, grade_a, grade_b, grade_c, "
                            "grade_d, grade_e, grade_f, grade_g, status) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (r["syllabus"], r.get("subject", ""), r.get("level", ""),
                             r.get("board", "CAIE"), int(r["year"]), r["session"],
                             r["option_code"], r["components"], int(r["max_mark"]),
                             t.get("A*"), t.get("A", 0), t.get("B", 0), t.get("C", 0),
                             t.get("D", 0), t.get("E", 0), t.get("F"), t.get("G"),
                             r.get("status", "official"))
                        )
                    c.commit()
        except Exception:
            pass

        return c


# ── Internal helpers ──────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# One pool for the process, NOT one per call.
#
# The Supabase client is thread-local (see the note at the top of this file), so
# a throwaway ThreadPoolExecutor would build a brand-new client — and pay a
# fresh TLS handshake — on every worker of every request. Measured: per-call
# pools made the dashboard *slower* than running the reads in sequence
# (1.6 s -> 2-5 s). A long-lived pool keeps the same threads, so their clients
# and their warm HTTP connections are reused.
_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="pwt-db")


def gather(**jobs) -> dict:
    """Run independent reads at the same time and return {name: result}.

    Every Supabase call is a REST round-trip — about 0.6 s from Lahore to the
    ap-northeast-2 region — so a page needing six of them spent nearly four
    seconds doing nothing but waiting. They do not depend on each other, so
    they run concurrently instead.

    The SQLite fallback runs them in sequence: local reads are microseconds and
    a single connection is not safe to share across threads.

    A failing job raises, the same as if it had been called directly.
    """
    if not _USE_SUPABASE or len(jobs) < 2:
        return {name: fn() for name, fn in jobs.items()}
    futures = {name: _POOL.submit(fn) for name, fn in jobs.items()}
    return {name: f.result() for name, f in futures.items()}


def warm_pool() -> None:
    """Pre-build a client on every pool thread so the first real request does
    not pay the TLS handshake. Called off-thread at startup."""
    if not _USE_SUPABASE:
        return
    import time as _t

    def touch():
        _client()
        _t.sleep(0.05)      # hold the thread so the next submit picks a new one
    for f in [_POOL.submit(touch) for _ in range(8)]:
        try:
            f.result(timeout=30)
        except Exception:
            pass


def _row_or_none(result) -> dict | None:
    if _USE_SUPABASE:
        data = result.data
        return data[0] if data else None
    return dict(result) if result else None


# ── Profile CRUD ──────────────────────────────────────────────────────────────

def get_user(user_id: str) -> dict | None:
    if _USE_SUPABASE:
        # .limit(1), not .single(): postgrest-py raises on zero rows with .single(),
        # which turned "no such user" into a 500 instead of None.
        r = (_client().table("profiles")
             .select("*")
             .eq("id", user_id)
             .limit(1)
             .execute())
        return r.data[0] if r.data else None
    with _local() as c:
        row = c.execute("SELECT * FROM profiles WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None


def get_user_by_email(email: str) -> dict | None:
    """Case-insensitive: accounts were saved with whatever case the form had."""
    email = (email or "").strip()
    if not email:
        return None
    if _USE_SUPABASE:
        r = (_client().table("profiles")
             .select("*")
             .eq("email", email.lower())
             .limit(1)
             .execute())
        if r.data:
            return r.data[0]
        # ilike wildcards (% _) are escaped so they only match themselves.
        pat = email.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        r = (_client().table("profiles")
             .select("*")
             .ilike("email", pat)
             .limit(1)
             .execute())
        return r.data[0] if r.data else None
    with _local() as c:
        row = c.execute("SELECT * FROM profiles WHERE lower(email)=lower(?)",
                        (email,)).fetchone()
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
                google_id: str | None = None, picture_url: str | None = None,
                role: str = "student") -> dict:
    uid = str(uuid.uuid4())
    payload = {
        "id": uid, "email": email, "name": name,
        "password_hash": password_hash, "google_id": google_id,
        "picture_url": picture_url, "profile_complete": 0,
        "role": role,
        "created_at": _now(), "updated_at": _now(),
    }
    if _USE_SUPABASE:
        r = _client().table("profiles").insert(payload).execute()
        return r.data[0]
    with _local() as c:
        c.execute("""INSERT INTO profiles
            (id,email,name,password_hash,google_id,picture_url,profile_complete,role,created_at,updated_at)
            VALUES (?,?,?,?,?,?,0,?,?,?)""",
            (uid, email, name, password_hash, google_id, picture_url, role, _now(), _now()))
        c.commit()
    return get_user(uid)


def upsert_google_user(google_id: str, email: str, name: str,
                       picture_url: str | None = None,
                       role: str = "student") -> dict:
    existing = get_user_by_google(google_id) or get_user_by_email(email)
    if existing:
        # Existing account: update picture/name only; never override an
        # admin/teacher role that was assigned by the admin panel.
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
    # New account: use the role chosen on the sign-up page.
    return create_user(email=email, name=name, google_id=google_id,
                       picture_url=picture_url, role=role)


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


def merge_flags(user_id: str, key: str, value) -> dict:
    """Merge one key into flags_json and return the updated flags dict."""
    import json as _json
    user = get_user(user_id)
    if not user:
        return {}
    try:
        flags = _json.loads(user.get("flags_json") or "{}")
    except (ValueError, TypeError):
        flags = {}
    flags[key] = value
    flags_str = _json.dumps(flags)
    if _USE_SUPABASE:
        (_client().table("profiles")
         .update({"flags_json": flags_str, "updated_at": _now()})
         .eq("id", user_id)
         .execute())
    else:
        with _local() as c:
            c.execute("UPDATE profiles SET flags_json=?, updated_at=? WHERE id=?",
                      (flags_str, _now(), user_id))
            c.commit()
    return flags


# ── Teacher accounts ──────────────────────────────────────────────────────────

def create_teacher_profile(email: str, name: str, temp_password_hash: str) -> dict:
    """Create a profiles row for an approved teacher with a temporary password."""
    import json as _json
    uid = str(uuid.uuid4())
    flags = _json.dumps({"must_change_password": True})
    payload = {
        "id": uid, "email": email, "name": name,
        "password_hash": temp_password_hash,
        "role": "teacher",
        "flags_json": flags,
        "profile_complete": 1,
        "created_at": _now(), "updated_at": _now(),
    }
    if _USE_SUPABASE:
        r = _client().table("profiles").insert(payload).execute()
        return r.data[0]
    with _local() as c:
        c.execute(
            "INSERT INTO profiles "
            "(id,email,name,password_hash,role,flags_json,profile_complete,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,1,?,?)",
            (uid, email, name, temp_password_hash, "teacher", flags, _now(), _now()))
        c.commit()
    return get_user(uid)


def get_teacher_students(teacher_id: str) -> list[dict]:
    """Students assigned to a specific teacher via teacher_students table."""
    if _USE_SUPABASE:
        # Explicit FK hint (student_id → profiles) avoids ambiguity with teacher_id → profiles
        r = (_client().table("teacher_students")
             .select("id,teacher_id,student_id,syllabus,allocated_at,status,"
                     "profiles!teacher_students_student_id_fkey(id,name,email,grade,picture_url,phone)")
             .eq("teacher_id", teacher_id)
             .eq("status", "active")
             .execute())
        rows = r.data or []
        # Flatten nested profiles dict onto the row
        out = []
        for row in rows:
            p = row.pop("profiles", {}) or {}
            out.append({**row, **p})
        return out
    with _local() as c:
        rows = c.execute(
            "SELECT ts.id, ts.teacher_id, ts.student_id, ts.syllabus, ts.allocated_at, "
            "p.name, p.email, p.grade, p.picture_url, p.phone "
            "FROM teacher_students ts "
            "JOIN profiles p ON p.id = ts.student_id "
            "WHERE ts.teacher_id=? AND ts.status='active'",
            (teacher_id,)).fetchall()
        return [dict(r) for r in rows]


def get_student_teachers(student_id: str) -> list[dict]:
    """Teachers assigned to a specific student (unique by teacher_id)."""
    if _USE_SUPABASE:
        r = (_client().table("teacher_students")
             .select("teacher_id,syllabus,"
                     "profiles!teacher_students_teacher_id_fkey(id,name,email,picture_url)")
             .eq("student_id", student_id)
             .eq("status", "active")
             .execute())
        seen: set[str] = set()
        out = []
        for row in (r.data or []):
            p = row.pop("profiles", {}) or {}
            tid = p.get("id") or row.get("teacher_id")
            if tid and tid not in seen:
                seen.add(tid)
                out.append({"id": tid, "name": p.get("name"), "email": p.get("email"),
                            "picture_url": p.get("picture_url")})
        return out
    with _local() as c:
        rows = c.execute(
            "SELECT DISTINCT ts.teacher_id AS id, p.name, p.email, p.picture_url "
            "FROM teacher_students ts "
            "JOIN profiles p ON p.id = ts.teacher_id "
            "WHERE ts.student_id=? AND ts.status='active'",
            (student_id,)).fetchall()
        return [dict(r) for r in rows]


def assign_teacher_student(teacher_id: str, student_id: str, syllabus: str) -> None:
    """Link (or re-activate) a student to a teacher for a given syllabus."""
    if _USE_SUPABASE:
        (_client().table("teacher_students")
         .upsert({"teacher_id": teacher_id, "student_id": student_id,
                  "syllabus": syllabus, "status": "active"},
                 on_conflict="teacher_id,student_id,syllabus")
         .execute())
        return
    with _local() as c:
        c.execute(
            "INSERT INTO teacher_students (teacher_id, student_id, syllabus, status) "
            "VALUES (?, ?, ?, 'active') "
            "ON CONFLICT(teacher_id, student_id, syllabus) DO UPDATE SET status='active'",
            (teacher_id, student_id, syllabus))
        c.commit()


def remove_teacher_student(teacher_id: str, student_id: str,
                           syllabus: str | None = None) -> int:
    """Soft-remove teacher-student links (status='removed'); returns rows changed.

    syllabus=None drops every subject the pair shares (a teacher dropping a
    student from their roster). Soft removal is the one style used everywhere,
    so re-assigning re-activates the same row instead of hitting the unique key.
    """
    if _USE_SUPABASE:
        q = (_client().table("teacher_students")
             .update({"status": "removed"})
             .eq("teacher_id", teacher_id)
             .eq("student_id", student_id)
             .eq("status", "active"))
        if syllabus:
            q = q.eq("syllabus", syllabus)
        return len(q.execute().data or [])
    with _local() as c:
        sql = ("UPDATE teacher_students SET status='removed' "
               "WHERE teacher_id=? AND student_id=? AND status='active'")
        vals: list = [teacher_id, student_id]
        if syllabus:
            sql += " AND syllabus=?"
            vals.append(syllabus)
        n = c.execute(sql, vals).rowcount
        c.commit()
        return n


# ── Usage quota ──────────────────────────────────────────────────────────────

def count_usage_this_month(user_id: str, event_type: str, period_start: str | None = None,
                           exclude_syllabi: list[str] | None = None) -> int:
    """Count events of this type since period_start (ISO string).

    If period_start is None, falls back to the start of the current calendar month.
    Pass the billing-cycle start from access.billing_period_start() for accurate per-plan resets.
    exclude_syllabi skips events recorded against those subjects (a subject-limited
    plan's own subjects, when counting the free allowance for the other subjects);
    events with no subject recorded are always counted.
    """
    if not period_start:
        period_start = datetime.now(timezone.utc).strftime("%Y-%m-01")
    excl = [x for x in (exclude_syllabi or []) if re.fullmatch(r"[0-9A-Za-z]+", x or "")]
    if _USE_SUPABASE:
        q = (_client().table("usage_events")
             .select("id", count="exact")
             .eq("user_id", user_id)
             .eq("event_type", event_type)
             .gte("created_at", period_start))
        if excl:
            q = q.or_(f"syllabus.is.null,syllabus.not.in.({','.join(excl)})")
        return q.execute().count or 0
    with _local() as c:
        sql = ("SELECT COUNT(*) FROM usage_events WHERE user_id=? AND event_type=?"
               " AND created_at >= ?")
        vals: list = [user_id, event_type, period_start]
        if excl:
            marks = ",".join("?" for _ in excl)
            sql += f" AND (syllabus IS NULL OR syllabus NOT IN ({marks}))"
            vals += excl
        row = c.execute(sql, vals).fetchone()
        return row[0] if row else 0


def record_usage(user_id: str, event_type: str, syllabus: str | None = None):
    payload = {"user_id": user_id, "event_type": event_type, "created_at": _now()}
    if syllabus:
        payload["syllabus"] = syllabus
    if _USE_SUPABASE:
        _client().table("usage_events").insert(payload).execute()
    else:
        with _local() as c:
            c.execute("INSERT INTO usage_events (user_id, event_type, created_at, syllabus)"
                      " VALUES (?,?,?,?)",
                      (user_id, event_type, payload["created_at"], syllabus))
            c.commit()


def get_monthly_usage(user_id: str, period_start: str | None = None) -> dict:
    """Return {event_type: count} since period_start (billing cycle or calendar month)."""
    if not period_start:
        period_start = datetime.now(timezone.utc).strftime("%Y-%m-01")
    event_types = ("topical_paper", "yearly_paper", "ai_tutor", "ai_quiz", "topic_test")
    if _USE_SUPABASE:
        r = (_client().table("usage_events")
             .select("event_type")
             .eq("user_id", user_id)
             .gte("created_at", period_start)
             .execute())
        counts: dict = {t: 0 for t in event_types}
        for row in (r.data or []):
            t = row["event_type"]
            if t in counts:
                counts[t] += 1
        return counts
    with _local() as c:
        rows = c.execute(
            "SELECT event_type, COUNT(*) AS n FROM usage_events"
            " WHERE user_id=? AND created_at>=? GROUP BY event_type",
            (user_id, period_start)).fetchall()
        counts = {t: 0 for t in event_types}
        for row in rows:
            if row["event_type"] in counts:
                counts[row["event_type"]] = row["n"]
        return counts


def add_time_spent(user_id: str, seconds: int, day: str | None = None) -> None:
    """Add active seconds to the student's LOCAL calendar day (`day`, sent by
    the browser), falling back to the server's date."""
    from datetime import date
    today = day or date.today().isoformat()
    if _USE_SUPABASE:
        try:
            r = (_client().table("daily_time_spent")
                 .select("seconds")
                 .eq("user_id", user_id)
                 .eq("date", today)
                 .execute())
            if r.data:
                new_sec = r.data[0]["seconds"] + seconds
                (_client().table("daily_time_spent")
                 .update({"seconds": new_sec})
                 .eq("user_id", user_id)
                 .eq("date", today)
                 .execute())
            else:
                (_client().table("daily_time_spent")
                 .insert({"user_id": user_id, "date": today, "seconds": seconds})
                 .execute())
        except Exception:
            pass
    else:
        with _local() as c:
            row = c.execute("SELECT seconds FROM daily_time_spent WHERE user_id=? AND date=?", (user_id, today)).fetchone()
            if row:
                c.execute("UPDATE daily_time_spent SET seconds = seconds + ? WHERE user_id=? AND date=?", (seconds, user_id, today))
            else:
                c.execute("INSERT INTO daily_time_spent (user_id, date, seconds) VALUES (?, ?, ?)", (user_id, today, seconds))
            c.commit()


def get_today_time_spent(user_id: str, day: str | None = None) -> int:
    from datetime import date
    today = day or date.today().isoformat()
    if _USE_SUPABASE:
        try:
            r = (_client().table("daily_time_spent")
                 .select("seconds")
                 .eq("user_id", user_id)
                 .eq("date", today)
                 .execute())
            return r.data[0]["seconds"] if r.data else 0
        except Exception:
            return 0
    else:
        with _local() as c:
            row = c.execute("SELECT seconds FROM daily_time_spent WHERE user_id=? AND date=?", (user_id, today)).fetchone()
            return row[0] if row else 0


def get_time_spent_range(user_id: str, start_date: str, end_date: str) -> list[dict]:
    """[{date, seconds}] for every day in [start_date, end_date] with tracked
    time. (The dashboard's streak called this for months before it existed -
    the AttributeError was swallowed, so tracked time never counted.)"""
    if _USE_SUPABASE:
        r = (_client().table("daily_time_spent")
             .select("date, seconds")
             .eq("user_id", user_id)
             .gte("date", start_date)
             .lte("date", end_date)
             .order("date")
             .execute())
        return r.data or []
    with _local() as c:
        rows = c.execute(
            "SELECT date, seconds FROM daily_time_spent "
            "WHERE user_id=? AND date>=? AND date<=? ORDER BY date",
            (user_id, start_date, end_date)).fetchall()
        return [{"date": r[0], "seconds": r[1]} for r in rows]


def get_weekly_time_spent(user_id: str) -> list[dict]:
    from datetime import date, timedelta
    today = date.today()
    start_date = (today - timedelta(days=6)).isoformat()
    end_date = today.isoformat()
    if _USE_SUPABASE:
        try:
            r = (_client().table("daily_time_spent")
                 .select("date, seconds")
                 .eq("user_id", user_id)
                 .gte("date", start_date)
                 .lte("date", end_date)
                 .order("date")
                 .execute())
            return r.data or []
        except Exception:
            return []
    else:
        with _local() as c:
            rows = c.execute(
                "SELECT date, seconds FROM daily_time_spent "
                "WHERE user_id=? AND date>=? AND date<=? ORDER BY date",
                (user_id, start_date, end_date)).fetchall()
            return [{"date": r[0], "seconds": r[1]} for r in rows]


def update_user_plan(
    user_id: str,
    plan: str,
    expires_at: str | None,
    started_at: str | None = None,
    trial: bool = False,
    subjects: list[str] | None = None,
) -> dict:
    """subjects=None leaves plan_subjects_json alone; a list replaces it."""
    now = _now()
    fields: dict = {
        "plan": plan,
        "plan_expires_at": expires_at,
        "plan_started_at": started_at or now,
        "plan_trial": 1 if trial else 0,
        "updated_at": now,
    }
    if subjects is not None:
        fields["plan_subjects_json"] = json.dumps(list(subjects))
    if _USE_SUPABASE:
        _client().table("profiles").update(fields).eq("id", user_id).execute()
        # Record in subscriptions table (history log + current plan)
        try:
            sub = (_client().table("subscriptions").select("id")
                   .eq("user_id", user_id).limit(1).execute())
            sub_fields = {"user_id": user_id, "plan": plan,
                          "expires_at": expires_at, "started_at": started_at or now}
            if sub.data:
                _client().table("subscriptions").update(
                    {"plan": plan, "expires_at": expires_at}
                ).eq("user_id", user_id).execute()
            else:
                _client().table("subscriptions").insert(sub_fields).execute()
        except Exception:
            pass
    else:
        with _local() as c:
            c.execute(
                f"UPDATE profiles SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?",
                (*fields.values(), user_id),
            )
            c.commit()
    return get_user(user_id)


def set_plan_subjects(user_id: str, subjects: list[str]) -> None:
    fields = {"plan_subjects_json": json.dumps(list(subjects))}
    if _USE_SUPABASE:
        _client().table("profiles").update(fields).eq("id", user_id).execute()
        return
    with _local() as c:
        c.execute("UPDATE profiles SET plan_subjects_json=? WHERE id=?",
                  (fields["plan_subjects_json"], user_id))
        c.commit()


def delete_user(user_id: str) -> None:
    """Permanently delete a user and all their data (CASCADE handles child rows)."""
    if _USE_SUPABASE:
        _client().table("profiles").delete().eq("id", user_id).execute()
    else:
        with _local() as c:
            c.execute("DELETE FROM profiles WHERE id=?", (user_id,))
            c.commit()


# ── Enrollments ───────────────────────────────────────────────────────────────

def get_enrollments(user_id: str) -> list[str]:
    if _USE_SUPABASE:
        r = (_client().table("enrollments")
             .select("syllabus")
             .eq("user_id", user_id)
             .eq("status", "active")
             .order("enrolled_at")
             .execute())
        return [row["syllabus"] for row in (r.data or [])]
    with _local() as c:
        rows = c.execute(
            "SELECT syllabus FROM enrollments WHERE user_id=? AND status='active' "
            "ORDER BY enrolled_at, rowid",
            (user_id,)).fetchall()
        return [r["syllabus"] for r in rows]


BOARDS_MAP = {
    "4024": ("Cambridge O Level", "Mathematics"),
    "5054": ("Cambridge O Level", "Physics"),
    "5070": ("Cambridge O Level", "Chemistry"),
    "2210": ("Cambridge O Level", "Computer Science"),
    "2058": ("Cambridge O Level", "Islamiyat"),
    "2059": ("Cambridge O Level", "Pakistan Studies"),
    "0580": ("Cambridge IGCSE", "Mathematics"),
    "0625": ("Cambridge IGCSE", "Physics"),
    "0620": ("Cambridge IGCSE", "Chemistry"),
    "0478": ("Cambridge IGCSE", "Computer Science"),
    "9709": ("Cambridge A Level", "Mathematics"),
    "9702": ("Cambridge A Level", "Physics"),
    "9618": ("Cambridge A Level", "Computer Science"),
}


def get_active_enrollments(user_id: str) -> list[dict]:
    syllabuses = get_enrollments(user_id)
    out = []
    for s in syllabuses:
        board, subject = BOARDS_MAP.get(s, ("Other", f"Subject {s}"))
        out.append({
            "syllabus": s,
            "board": board,
            "subject": subject
        })
    return out


def get_archived_enrollments(user_id: str) -> list[str]:
    if _USE_SUPABASE:
        r = (_client().table("enrollments")
             .select("syllabus")
             .eq("user_id", user_id)
             .eq("status", "inactive")
             .execute())
        return [row["syllabus"] for row in (r.data or [])]
    with _local() as c:
        rows = c.execute(
            "SELECT syllabus FROM enrollments WHERE user_id=? AND status='inactive'",
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
         .update({"status": "inactive"})
         .eq("user_id", user_id)
         .eq("syllabus", syllabus)
         .execute())
    else:
        with _local() as c:
            c.execute("UPDATE enrollments SET status='inactive' WHERE user_id=? AND syllabus=?",
                      (user_id, syllabus))
            c.commit()


def archive_all_enrollments(user_id: str):
    """Mark all active enrollments as inactive/archived."""
    if _USE_SUPABASE:
        (_client().table("enrollments")
         .update({"status": "inactive"})
         .eq("user_id", user_id)
         .eq("status", "active")
         .execute())
    else:
        with _local() as c:
            c.execute("UPDATE enrollments SET status='inactive' WHERE user_id=? AND status='active'",
                      (user_id,))
            c.commit()


# ── Boards ────────────────────────────────────────────────────────────────────

def get_boards(user_id: str) -> tuple[list[str], str | None]:
    """(boards, primary) for a student; ([], None) until they have chosen."""
    if _USE_SUPABASE:
        r = (_client().table("student_boards").select("board,is_primary")
             .eq("user_id", user_id).execute())
        rows = r.data or []
    else:
        with _local() as c:
            rows = [dict(x) for x in c.execute(
                "SELECT board, is_primary FROM student_boards WHERE user_id=?",
                (user_id,)).fetchall()]
    order = ["o-level", "igcse", "a-level"]
    boards = sorted((x["board"] for x in rows), key=order.index)
    primary = next((x["board"] for x in rows if x["is_primary"]), None)
    return boards, primary


def set_boards(user_id: str, boards: list[str], primary: str) -> None:
    """Replace the student's boards (the set is small, so delete + insert)."""
    rows = [{"user_id": user_id, "board": b, "is_primary": b == primary} for b in boards]
    if _USE_SUPABASE:
        (_client().table("student_boards").delete().eq("user_id", user_id).execute())
        _client().table("student_boards").insert(rows).execute()
    else:
        with _local() as c:
            c.execute("DELETE FROM student_boards WHERE user_id=?", (user_id,))
            c.executemany(
                "INSERT INTO student_boards (user_id, board, is_primary) VALUES (?,?,?)",
                [(r["user_id"], r["board"], int(r["is_primary"])) for r in rows])
            c.commit()


# ── AI help: explanation unlocks, follow-up threads, reports ─────────────────

def unlocked_explanations(user_id: str) -> set[int]:
    if _USE_SUPABASE:
        r = (_client().table("explanation_unlocks").select("question_id")
             .eq("user_id", user_id).execute())
        return {int(x["question_id"]) for x in (r.data or [])}
    with _local() as c:
        return {r[0] for r in c.execute(
            "SELECT question_id FROM explanation_unlocks WHERE user_id=?", (user_id,))}


def unlock_explanation(user_id: str, question_id: int) -> None:
    if _USE_SUPABASE:
        (_client().table("explanation_unlocks")
         .upsert({"user_id": user_id, "question_id": question_id},
                 on_conflict="user_id,question_id").execute())
        return
    with _local() as c:
        c.execute("INSERT OR IGNORE INTO explanation_unlocks (user_id, question_id) VALUES (?,?)",
                  (user_id, question_id))
        c.commit()


def thread_messages(user_id: str, question_id: int, limit: int = 40) -> list[dict]:
    cols = "id,role,quoted_text,content,created_at"
    if _USE_SUPABASE:
        r = (_client().table("explanation_messages").select(cols)
             .eq("user_id", user_id).eq("question_id", question_id)
             .order("id", desc=False).limit(limit).execute())
        return r.data or []
    with _local() as c:
        return [dict(x) for x in c.execute(
            f"SELECT {cols} FROM explanation_messages WHERE user_id=? AND question_id=? "
            "ORDER BY id LIMIT ?", (user_id, question_id, limit)).fetchall()]


def add_thread_message(user_id: str, question_id: int, role: str, content: str,
                       quoted_text: str | None = None) -> None:
    row = {"user_id": user_id, "question_id": question_id, "role": role,
           "content": content, "quoted_text": quoted_text}
    if _USE_SUPABASE:
        _client().table("explanation_messages").insert(row).execute()
        return
    with _local() as c:
        c.execute("INSERT INTO explanation_messages (user_id, question_id, role, content, quoted_text) "
                  "VALUES (?,?,?,?,?)", (user_id, question_id, role, content, quoted_text))
        c.commit()


def report_explanation(user_id: str | None, question_id: int, reason: str | None) -> None:
    row = {"user_id": user_id, "question_id": question_id, "reason": (reason or "")[:1000]}
    if _USE_SUPABASE:
        _client().table("explanation_reports").insert(row).execute()
        return
    with _local() as c:
        c.execute("INSERT INTO explanation_reports (user_id, question_id, reason) VALUES (?,?,?)",
                  (user_id, question_id, row["reason"]))
        c.commit()


# ── Booklets (web topical builder) ────────────────────────────────────────────
# JSON columns are JSONB on Supabase and TEXT locally; callers always get
# Python lists/dicts back.
_BOOKLET_JSON = ("params_json", "question_ids", "page_map_json")


def _booklet_out(row: dict | None) -> dict | None:
    if not row:
        return None
    row = dict(row)
    for k in _BOOKLET_JSON:
        if isinstance(row.get(k), str):
            try:
                row[k] = json.loads(row[k])
            except ValueError:
                pass
    return row


def create_booklet(row: dict) -> dict:
    if _USE_SUPABASE:
        r = _client().table("booklets").insert(row).execute()
        return _booklet_out(r.data[0])
    local = {k: (json.dumps(v) if k in _BOOKLET_JSON and v is not None else v)
             for k, v in row.items()}
    cols = ", ".join(local)
    with _local() as c:
        c.execute(f"INSERT INTO booklets ({cols}) VALUES ({', '.join('?' for _ in local)})",
                  list(local.values()))
        c.commit()
    return get_booklet(row["id"])


def update_booklet(booklet_id: str, fields: dict) -> None:
    fields = {**fields, "updated_at": datetime.now(timezone.utc).isoformat()}
    if _USE_SUPABASE:
        _client().table("booklets").update(fields).eq("id", booklet_id).execute()
        return
    local = {k: (json.dumps(v) if k in _BOOKLET_JSON and v is not None else v)
             for k, v in fields.items()}
    with _local() as c:
        c.execute(f"UPDATE booklets SET {', '.join(f'{k}=?' for k in local)} WHERE id=?",
                  [*local.values(), booklet_id])
        c.commit()


def get_booklet(booklet_id: str) -> dict | None:
    if _USE_SUPABASE:
        r = _client().table("booklets").select("*").eq("id", booklet_id).limit(1).execute()
        return _booklet_out((r.data or [None])[0])
    with _local() as c:
        row = c.execute("SELECT * FROM booklets WHERE id=?", (booklet_id,)).fetchone()
        return _booklet_out(dict(row) if row else None)


def list_booklets(user_id: str, limit: int = 30) -> list[dict]:
    cols = "id,syllabus,title,status,created_at,question_ids,params_json"
    if _USE_SUPABASE:
        r = (_client().table("booklets").select(cols).eq("user_id", user_id)
             .order("created_at", desc=True).limit(limit).execute())
        rows = r.data or []
    else:
        with _local() as c:
            rows = [dict(x) for x in c.execute(
                f"SELECT {cols} FROM booklets WHERE user_id=? "
                "ORDER BY created_at DESC LIMIT ?", (user_id, limit)).fetchall()]
    return [_booklet_out(r) for r in rows]


# ── MCQ practice sessions ─────────────────────────────────────────────────────

_MCQ_JSON = ("question_ids", "settings", "answers")


def _mcq_out(row: dict | None) -> dict | None:
    if not row:
        return None
    row = dict(row)
    for k in _MCQ_JSON:
        if isinstance(row.get(k), str):
            try:
                row[k] = json.loads(row[k])
            except ValueError:
                pass
    return row


def _mcq_local(row: dict) -> dict:
    return {k: (json.dumps(v) if k in _MCQ_JSON and v is not None else v) for k, v in row.items()}


def create_mcq_session(row: dict) -> dict:
    if _USE_SUPABASE:
        r = _client().table("mcq_sessions").insert(row).execute()
        return _mcq_out(r.data[0])
    local = _mcq_local(row)
    with _local() as c:
        c.execute(f"INSERT INTO mcq_sessions ({', '.join(local)}) "
                  f"VALUES ({', '.join('?' for _ in local)})", list(local.values()))
        c.commit()
    return get_mcq_session(row["id"])


def update_mcq_session(session_id: str, fields: dict) -> None:
    fields = {**fields, "updated_at": datetime.now(timezone.utc).isoformat()}
    if _USE_SUPABASE:
        _client().table("mcq_sessions").update(fields).eq("id", session_id).execute()
        return
    local = _mcq_local(fields)
    with _local() as c:
        c.execute(f"UPDATE mcq_sessions SET {', '.join(f'{k}=?' for k in local)} WHERE id=?",
                  [*local.values(), session_id])
        c.commit()


def get_mcq_session(session_id: str) -> dict | None:
    if _USE_SUPABASE:
        r = _client().table("mcq_sessions").select("*").eq("id", session_id).limit(1).execute()
        return _mcq_out((r.data or [None])[0])
    with _local() as c:
        row = c.execute("SELECT * FROM mcq_sessions WHERE id=?", (session_id,)).fetchone()
        return _mcq_out(dict(row) if row else None)


def list_mcq_sessions(user_id: str, syllabus: str | None = None, limit: int = 20) -> list[dict]:
    cols = ("id,syllabus,kind,paper_id,title,status,score,total,elapsed_s,settings,"
            "question_ids,answers,created_at,updated_at,submitted_at")
    if _USE_SUPABASE:
        q = _client().table("mcq_sessions").select(cols).eq("user_id", user_id)
        if syllabus:
            q = q.eq("syllabus", syllabus)
        rows = q.order("updated_at", desc=True).limit(limit).execute().data or []
    else:
        sql = f"SELECT {cols} FROM mcq_sessions WHERE user_id=?"
        args: list = [user_id]
        if syllabus:
            sql += " AND syllabus=?"
            args.append(syllabus)
        with _local() as c:
            rows = [dict(x) for x in c.execute(sql + " ORDER BY updated_at DESC LIMIT ?",
                                               [*args, limit]).fetchall()]
    return [_mcq_out(r) for r in rows]


# ── Page annotations (pen / highlighter / shapes / text over a page) ─────────

def get_annotations(user_id: str, doc_key: str) -> dict[int, list]:
    if _USE_SUPABASE:
        rows = (_client().table("page_annotations").select("page,strokes")
                .eq("user_id", user_id).eq("doc_key", doc_key).execute().data or [])
    else:
        with _local() as c:
            rows = [dict(x) for x in c.execute(
                "SELECT page, strokes FROM page_annotations WHERE user_id=? AND doc_key=?",
                (user_id, doc_key)).fetchall()]
    out = {}
    for r in rows:
        s = r["strokes"]
        out[int(r["page"])] = json.loads(s) if isinstance(s, str) else (s or [])
    return out


def annotated_docs(user_id: str, prefix: str) -> set[str]:
    """Doc keys starting with `prefix` on which this user has any ink (My papers)."""
    if _USE_SUPABASE:
        rows = (_client().table("page_annotations").select("doc_key")
                .eq("user_id", user_id).like("doc_key", f"{prefix}%").execute().data or [])
    else:
        with _local() as c:
            rows = [dict(x) for x in c.execute(
                "SELECT DISTINCT doc_key FROM page_annotations WHERE user_id=? AND doc_key LIKE ?",
                (user_id, f"{prefix}%")).fetchall()]
    return {r["doc_key"] for r in rows}


def set_annotations(user_id: str, doc_key: str, page: int, strokes: list) -> None:
    now = datetime.now(timezone.utc).isoformat()
    if _USE_SUPABASE:
        if strokes:
            _client().table("page_annotations").upsert(
                {"user_id": user_id, "doc_key": doc_key, "page": page,
                 "strokes": strokes, "updated_at": now},
                on_conflict="user_id,doc_key,page").execute()
        else:
            (_client().table("page_annotations").delete().eq("user_id", user_id)
             .eq("doc_key", doc_key).eq("page", page).execute())
        return
    with _local() as c:
        if strokes:
            c.execute("INSERT INTO page_annotations (user_id, doc_key, page, strokes, updated_at) "
                      "VALUES (?,?,?,?,?) ON CONFLICT(user_id, doc_key, page) DO UPDATE SET "
                      "strokes=excluded.strokes, updated_at=excluded.updated_at",
                      (user_id, doc_key, page, json.dumps(strokes), now))
        else:
            c.execute("DELETE FROM page_annotations WHERE user_id=? AND doc_key=? AND page=?",
                      (user_id, doc_key, page))
        c.commit()


# ── Calculator memory + history (P2-c) ───────────────────────────────────────

CALC_HISTORY_MAX = 200
_CALC_DEFAULT = {"mem": 0.0, "ans": 0.0, "vars": {}, "deg": True, "history": []}


def get_calc(user_id: str) -> dict:
    if _USE_SUPABASE:
        rows = (_client().table("calc_state").select("mem,ans,vars,deg,history")
                .eq("user_id", user_id).execute().data or [])
    else:
        with _local() as c:
            rows = [dict(x) for x in c.execute(
                "SELECT mem, ans, vars, deg, history FROM calc_state WHERE user_id=?",
                (user_id,)).fetchall()]
    if not rows:
        return {**_CALC_DEFAULT, "vars": {}, "history": []}
    r = rows[0]
    load = lambda v, d: (json.loads(v) if isinstance(v, str) else v) or d   # noqa: E731
    return {"mem": float(r["mem"] or 0), "ans": float(r["ans"] or 0), "vars": load(r["vars"], {}),
            "deg": bool(r["deg"]), "history": load(r["history"], [])[:CALC_HISTORY_MAX]}


def set_calc(user_id: str, state: dict) -> dict:
    """Write the whole calculator state (history already trimmed by the caller)."""
    now = datetime.now(timezone.utc).isoformat()
    row = {"mem": float(state["mem"]), "ans": float(state["ans"]), "vars": state["vars"],
           "deg": bool(state["deg"]), "history": state["history"][:CALC_HISTORY_MAX]}
    if _USE_SUPABASE:
        _client().table("calc_state").upsert({"user_id": user_id, **row, "updated_at": now},
                                             on_conflict="user_id").execute()
    else:
        with _local() as c:
            c.execute("INSERT INTO calc_state (user_id, mem, ans, vars, deg, history, updated_at) "
                      "VALUES (?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET mem=excluded.mem, "
                      "ans=excluded.ans, vars=excluded.vars, deg=excluded.deg, "
                      "history=excluded.history, updated_at=excluded.updated_at",
                      (user_id, row["mem"], row["ans"], json.dumps(row["vars"]), int(row["deg"]),
                       json.dumps(row["history"]), now))
            c.commit()
    return row


def restore_enrollment(user_id: str, syllabus: str):
    """Restore an archived enrollment back to active status."""
    enroll(user_id, syllabus)


# ── Topic progress ────────────────────────────────────────────────────────────

# A chapter-level row is stored with subtopic = '' rather than NULL, because a
# UNIQUE key containing NULL never matches itself — see
# migrations/003_fix_topic_progress_null_subtopic.sql. Everything above this
# layer still speaks in None, so the conversion lives here and nowhere else.
def _in_subtopic(subtopic: str | None) -> str:
    return subtopic or ""


def _out_subtopic(row: dict) -> dict:
    if row.get("subtopic") == "":
        row = {**row, "subtopic": None}
    return row


def get_progress(user_id: str, syllabus: str) -> list[dict]:
    if _USE_SUPABASE:
        r = (_client().table("topic_progress")
             .select("*")
             .eq("user_id", user_id)
             .eq("syllabus", syllabus)
             .execute())
        rows = r.data or []
    else:
        with _local() as c:
            rows = [dict(r) for r in c.execute(
                "SELECT * FROM topic_progress WHERE user_id=? AND syllabus=?",
                (user_id, syllabus)).fetchall()]
    return [_out_subtopic(r) for r in rows]


def get_all_progress_for_user(user_id: str) -> list[dict]:
    """Return all topic_progress rows for a user across every syllabus."""
    if _USE_SUPABASE:
        r = (_client().table("topic_progress")
             .select("*")
             .eq("user_id", user_id)
             .execute())
        rows = r.data or []
    else:
        with _local() as c:
            rows = [dict(r) for r in c.execute(
                "SELECT * FROM topic_progress WHERE user_id=?",
                (user_id,)).fetchall()]
    return [_out_subtopic(r) for r in rows]


def upsert_progress(user_id: str, syllabus: str, topic: str,
                    subtopic: str | None, status: str | None = None,
                    papers_status: str | None = None) -> dict:
    """Set either axis of a chapter's progress, or both.

    `status` is how well they know it; `papers_status` is whether they have
    worked its past-paper questions. Passing only one leaves the other alone —
    the two controls in the UI write independently.
    """
    now = _now()
    stored = _in_subtopic(subtopic)
    payload = {
        "user_id": user_id, "syllabus": syllabus, "topic": topic,
        "subtopic": stored, "updated_at": now,
    }
    if status is not None:
        payload["status"] = status
        payload["last_reviewed"] = now
    if papers_status is not None:
        payload["papers_status"] = papers_status
        payload["papers_updated_at"] = now

    if _USE_SUPABASE:
        # A partial upsert would reset the untouched column to its default, so
        # merge onto the existing row first.
        existing = None
        r0 = (_client().table("topic_progress").select("*")
              .eq("user_id", user_id).eq("syllabus", syllabus)
              .eq("topic", topic).eq("subtopic", stored).limit(1).execute())
        if r0.data:
            existing = r0.data[0]
        merged = {**{k: v for k, v in (existing or {}).items() if k != "id"},
                  **payload}
        merged.setdefault("status", "not_started")
        merged.setdefault("papers_status", "not_started")
        r = (_client().table("topic_progress")
             .upsert(merged, on_conflict="user_id,syllabus,topic,subtopic")
             .execute())
        return _out_subtopic(r.data[0] if r.data else merged)

    lr, pu = payload.get("last_reviewed"), payload.get("papers_updated_at")
    with _local() as c:
        # The UPDATE arm re-binds the raw parameters rather than reading
        # `excluded`: excluded already carries the COALESCEd insert value, so
        # `excluded.status` would be 'not_started' rather than NULL and would
        # wipe the column the caller meant to leave alone.
        c.execute("""INSERT INTO topic_progress
            (user_id,syllabus,topic,subtopic,status,papers_status,
             last_reviewed,papers_updated_at,updated_at)
            VALUES (?,?,?,?,
                    COALESCE(?, 'not_started'), COALESCE(?, 'not_started'),
                    ?,?,?)
            ON CONFLICT(user_id,syllabus,topic,subtopic)
            DO UPDATE SET
                status            = COALESCE(?, topic_progress.status),
                papers_status     = COALESCE(?, topic_progress.papers_status),
                last_reviewed     = COALESCE(?, topic_progress.last_reviewed),
                papers_updated_at = COALESCE(?, topic_progress.papers_updated_at),
                updated_at        = ?""",
            (user_id, syllabus, topic, stored, status, papers_status, lr, pu, now,
             status, papers_status, lr, pu, now))
        c.commit()
        row = c.execute(
            "SELECT * FROM topic_progress WHERE user_id=? AND syllabus=? "
            "AND topic=? AND subtopic=?",
            (user_id, syllabus, topic, stored)).fetchone()
    return _out_subtopic(dict(row) if row else payload)


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
    """Per-syllabus progress, counted in CHAPTERS.

    Returns { syllabus: {total, confident, learning, not_started,
                         papers_confident, sub: {...}} }

    The counters deliberately cover chapter-level rows only (subtopic = '').
    Subtopics are a drill-down inside a chapter, not extra units of progress —
    counting them here is what made a student who ticked 14 subtopics of one
    chapter read as "14 confident", and the dashboard then divided that by the
    syllabus's chapter count to produce a nonsense percentage. Subtopic totals
    are still returned, under `sub`, for anything that wants the detail.
    """
    if _USE_SUPABASE:
        r = (_client().table("topic_progress")
             .select("syllabus,status,subtopic,papers_status")
             .eq("user_id", user_id)
             .execute())
        rows = r.data or []
    else:
        with _local() as c:
            rows = [dict(r) for r in c.execute(
                "SELECT syllabus,status,subtopic,papers_status "
                "FROM topic_progress WHERE user_id=?",
                (user_id,)).fetchall()]

    def blank():
        return {"total": 0, "confident": 0, "learning": 0, "not_started": 0,
                "papers_confident": 0,
                "sub": {"total": 0, "confident": 0, "learning": 0,
                        "not_started": 0}}

    summary: dict = {}
    for row in rows:
        entry = summary.setdefault(row["syllabus"], blank())
        status = row.get("status") or "not_started"
        is_chapter = not (row.get("subtopic") or "")
        bucket = entry if is_chapter else entry["sub"]
        bucket["total"] += 1
        if status in bucket:
            bucket[status] += 1
        if is_chapter and (row.get("papers_status") == "confident"):
            entry["papers_confident"] += 1
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
    try:
        return _insert("feedback", payload,
                       ["rating", "message", "name", "email", "page", "type", "ts"])
    except Exception:
        # Supabase without migration 024 (no email column): keep the address in
        # the message rather than lose the feedback.
        if not _USE_SUPABASE or "email" not in payload:
            raise
        rest = {k: v for k, v in payload.items() if k != "email"}
        rest["message"] = f"{rest.get('message') or ''}\n\n(email: {payload['email']})"
        return _insert("feedback", rest, ["rating", "message", "name", "page", "type", "ts"])


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
                 "active", "email", "phone", "application_id", "created_at",
                 "profile_id"]


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


def get_teacher_by_profile_id(profile_id: str) -> dict | None:
    """Return the teachers row linked to a profile (auth account)."""
    if _USE_SUPABASE:
        r = (_client().table("teachers").select("*")
             .eq("profile_id", profile_id).limit(1).execute())
        return r.data[0] if r.data else None
    with _local() as c:
        row = c.execute("SELECT * FROM teachers WHERE profile_id=?", (profile_id,)).fetchone()
        return dict(row) if row else None


_TEACHER_SELF_EDIT_COLS = {"bio", "subjects_json", "qualifications",
                           "experience_years", "phone"}


def update_teacher_by_profile_id(profile_id: str, fields: dict) -> dict | None:
    """Allow a teacher to update their own public profile (safe subset)."""
    safe = {k: v for k, v in fields.items() if k in _TEACHER_SELF_EDIT_COLS}
    if not safe:
        return get_teacher_by_profile_id(profile_id)
    if _USE_SUPABASE:
        _client().table("teachers").update(safe).eq("profile_id", profile_id).execute()
    else:
        with _local() as c:
            c.execute(f"UPDATE teachers SET {', '.join(f'{k}=?' for k in safe)} "
                      f"WHERE profile_id=?", (*safe.values(), profile_id))
            c.commit()
    return get_teacher_by_profile_id(profile_id)


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
            "profile_complete,created_at,updated_at")
            .eq("role", "student")
            .order("created_at", desc=True)
            .execute().data or [])
        enrolls = cl.table("enrollments").select("user_id,syllabus,status").execute().data or []
        progress = cl.table("topic_progress").select("user_id,status").execute().data or []
        quizzes = (cl.table("quiz_sessions")
                   .select("user_id,score,created_at").execute().data or [])
    else:
        with _local() as c:
            profiles = [dict(r) for r in c.execute(
                "SELECT id,email,name,picture_url,grade,phone,gender,birthday,"
                "profile_complete,created_at,updated_at FROM profiles"
                " WHERE role='student' ORDER BY created_at DESC")]
            enrolls = [dict(r) for r in c.execute(
                "SELECT user_id,syllabus,status FROM enrollments")]
            progress = [dict(r) for r in c.execute(
                "SELECT user_id,status FROM topic_progress")]
            quizzes = [dict(r) for r in c.execute(
                "SELECT user_id,score,created_at FROM quiz_sessions")]

    by_user: dict[str, dict] = {
        p["id"]: {**p, "subjects": [], "topics_tracked": 0, "topics_confident": 0,
                  "quiz_count": 0, "avg_score": None,
                  "last_active": p.get("updated_at") or p.get("created_at")}
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


# ── Past-paper practice tracker ──────────────────────────────────────────────
#
# Keyed on the same tuple the pipeline uses to identify a paper
# (syllabus, year, session, paper, variant). variant is '' rather than NULL so
# the UNIQUE constraint actually fires — in both SQLite and Postgres a NULL
# column never equals another NULL, which would let duplicates through.

_PAPER_KEY = ("syllabus", "year", "session", "paper", "variant")


def get_paper_progress(user_id: str, syllabus: str | None = None) -> list[dict]:
    if _USE_SUPABASE:
        q = _client().table("paper_progress").select("*").eq("user_id", user_id)
        if syllabus:
            q = q.eq("syllabus", syllabus)
        return q.execute().data or []
    with _local() as c:
        sql = "SELECT * FROM paper_progress WHERE user_id=?"
        args: list = [user_id]
        if syllabus:
            sql += " AND syllabus=?"
            args.append(syllabus)
        return [dict(r) for r in c.execute(sql + " ORDER BY year DESC, session, paper", args)]


def upsert_paper_progress(user_id: str, syllabus: str, year: int, session: str,
                          paper: int, variant: str, status: str,
                          score: int | None = None, max_score: int | None = None,
                          grade: str | None = None, confidence: str | None = None,
                          attempts_json: str = "[]", synced: int = 0,
                          note: str | None = None, set_by: str = "student") -> dict:
    payload = {
        "user_id": user_id, "syllabus": syllabus, "year": int(year),
        "session": session, "paper": int(paper), "variant": variant or "",
        "status": status, "score": score, "max_score": max_score,
        "grade": grade, "confidence": confidence, "attempts_json": attempts_json or "[]",
        "synced": synced or 0, "note": note, "set_by": set_by, "updated_at": _now(),
    }
    if _USE_SUPABASE:
        r = (_client().table("paper_progress")
             .upsert(payload, on_conflict="user_id,syllabus,year,session,paper,variant")
             .execute())
        return r.data[0] if r.data else payload
    with _local() as c:
        c.execute("""INSERT INTO paper_progress
            (user_id,syllabus,year,session,paper,variant,status,score,max_score,
             grade,confidence,attempts_json,synced,note,set_by,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(user_id,syllabus,year,session,paper,variant)
            DO UPDATE SET status=excluded.status, score=excluded.score,
                          max_score=excluded.max_score, grade=excluded.grade,
                          confidence=excluded.confidence, attempts_json=excluded.attempts_json,
                          synced=excluded.synced, note=excluded.note,
                          set_by=excluded.set_by, updated_at=excluded.updated_at""",
            (user_id, syllabus, int(year), session, int(paper), variant or "",
             status, score, max_score, grade, confidence, attempts_json or "[]",
             synced or 0, note, set_by, payload["updated_at"]))
        c.commit()
    return payload


def get_grade_thresholds(syllabus: str, year: int | None = None, session: str | None = None) -> list[dict]:
    if _USE_SUPABASE:
        q = _client().table("grade_thresholds").select("*").eq("syllabus", syllabus)
        if year is not None:
            q = q.eq("year", int(year))
        if session:
            q = q.eq("session", session)
        return q.execute().data or []
    with _local() as c:
        sql = "SELECT * FROM grade_thresholds WHERE syllabus=?"
        args: list = [syllabus]
        if year is not None:
            sql += " AND year=?"
            args.append(int(year))
        if session:
            sql += " AND session=?"
            args.append(session)
        return [dict(r) for r in c.execute(sql + " ORDER BY year DESC, session, paper, variant", args)]


# ── Class log (attendance calendar) ──────────────────────────────────────────

_CLASS_COLS = ["user_id", "class_date", "start_time", "duration_min", "syllabus",
               "status", "topic", "note", "created_at", "updated_at"]


def get_class_log(user_id: str, limit: int = 500) -> list[dict]:
    if _USE_SUPABASE:
        return (_client().table("class_log").select("*").eq("user_id", user_id)
                .order("class_date", desc=True).limit(limit).execute().data or [])
    with _local() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM class_log WHERE user_id=? "
            "ORDER BY class_date DESC, start_time DESC LIMIT ?", (user_id, limit))]


def create_class_entry(payload: dict) -> dict:
    payload.setdefault("created_at", _now())
    payload["updated_at"] = _now()
    return _insert("class_log", payload, _CLASS_COLS)


def get_class_entry(entry_id: int) -> dict | None:
    if _USE_SUPABASE:
        r = _client().table("class_log").select("*").eq("id", entry_id).limit(1).execute()
        return r.data[0] if r.data else None
    with _local() as c:
        row = c.execute("SELECT * FROM class_log WHERE id=?", (entry_id,)).fetchone()
        return dict(row) if row else None


def update_class_entry(entry_id: int, fields: dict) -> dict | None:
    fields["updated_at"] = _now()
    if _USE_SUPABASE:
        _client().table("class_log").update(fields).eq("id", entry_id).execute()
    else:
        with _local() as c:
            c.execute(f"UPDATE class_log SET {', '.join(f'{k}=?' for k in fields)} "
                      f"WHERE id=?", (*fields.values(), entry_id))
            c.commit()
    return get_class_entry(entry_id)


def delete_class_entry(entry_id: int) -> None:
    if _USE_SUPABASE:
        _client().table("class_log").delete().eq("id", entry_id).execute()
    else:
        with _local() as c:
            c.execute("DELETE FROM class_log WHERE id=?", (entry_id,))
            c.commit()


# ── Assignments (student diary / homework) ───────────────────────────────────

_ASSIGN_COLS = ["user_id", "syllabus", "kind", "title", "instructions",
                "topics_json", "attachments_json", "due_date", "status",
                "student_note", "seen_at", "completed_at",
                "student_submissions_json", "created_at", "updated_at"]


def get_assignments(user_id: str, limit: int = 300) -> list[dict]:
    if _USE_SUPABASE:
        return (_client().table("assignments").select("*").eq("user_id", user_id)
                .order("created_at", desc=True).limit(limit).execute().data or [])
    with _local() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM assignments WHERE user_id=? "
            "ORDER BY created_at DESC LIMIT ?", (user_id, limit))]


def get_all_assignments(limit: int = 1000) -> list[dict]:
    """Every student's assignments in one read, newest first.

    Backs the admin Homework page, which shows work across all students rather
    than one at a time. Fetching per student would be one round trip each —
    against Supabase that is the difference between one request and thirty.
    """
    if _USE_SUPABASE:
        return (_client().table("assignments").select("*")
                .order("created_at", desc=True).limit(limit).execute().data or [])
    with _local() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM assignments ORDER BY created_at DESC LIMIT ?", (limit,))]


def get_assignment(assignment_id: int) -> dict | None:
    if _USE_SUPABASE:
        r = _client().table("assignments").select("*").eq("id", assignment_id).limit(1).execute()
        return r.data[0] if r.data else None
    with _local() as c:
        row = c.execute("SELECT * FROM assignments WHERE id=?", (assignment_id,)).fetchone()
        return dict(row) if row else None


def create_assignment(payload: dict) -> dict:
    payload.setdefault("created_at", _now())
    payload["updated_at"] = _now()
    return _insert("assignments", payload, _ASSIGN_COLS)


def update_assignment(assignment_id: int, fields: dict) -> dict | None:
    fields["updated_at"] = _now()
    if _USE_SUPABASE:
        _client().table("assignments").update(fields).eq("id", assignment_id).execute()
    else:
        with _local() as c:
            c.execute(f"UPDATE assignments SET {', '.join(f'{k}=?' for k in fields)} "
                      f"WHERE id=?", (*fields.values(), assignment_id))
            c.commit()
    return get_assignment(assignment_id)


def delete_assignment(assignment_id: int) -> None:
    if _USE_SUPABASE:
        _client().table("assignments").delete().eq("id", assignment_id).execute()
    else:
        with _local() as c:
            c.execute("DELETE FROM assignments WHERE id=?", (assignment_id,))
            c.commit()


def count_open_assignments(user_ids: list[str]) -> dict[str, int]:
    """Open-homework counts for the admin student list, in one read."""
    if not user_ids:
        return {}
    if _USE_SUPABASE:
        rows = (_client().table("assignments").select("user_id,status")
                .in_("user_id", user_ids).execute().data or [])
    else:
        with _local() as c:
            rows = [dict(r) for r in c.execute("SELECT user_id,status FROM assignments")]
    out: dict[str, int] = {}
    for r in rows:
        if r.get("status") != "done" and r["user_id"] in user_ids:
            out[r["user_id"]] = out.get(r["user_id"], 0) + 1
    return out


def get_student_detail(user_id: str) -> dict | None:
    """One student's full record: profile, enrollments, every topic, every quiz."""
    user = get_user(user_id)
    if not user:
        return None
    if _USE_SUPABASE:
        # Six round-trips at ~0.6 s each; run them together so opening a
        # student is one wait, not six.
        got = gather(
            enrollments=lambda: (_client().table("enrollments").select("*")
                                 .eq("user_id", user_id).execute().data or []),
            progress=lambda: (_client().table("topic_progress").select("*")
                              .eq("user_id", user_id).execute().data or []),
            quizzes=lambda: (_client().table("quiz_sessions").select("*")
                             .eq("user_id", user_id).order("created_at", desc=True)
                             .limit(200).execute().data or []),
            papers=lambda: get_paper_progress(user_id),
            classes=lambda: get_class_log(user_id),
            assignments=lambda: get_assignments(user_id),
        )
        return {
            "profile": {k: v for k, v in user.items() if k != "password_hash"},
            "enrollments": got["enrollments"],
            "progress": [_out_subtopic(p) for p in got["progress"]],
            "quizzes": got["quizzes"],
            "papers": got["papers"],
            "classes": got["classes"],
            "assignments": got["assignments"],
        }
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
        "progress": [_out_subtopic(p) for p in progress],
        "quizzes": quizzes,
        "papers": get_paper_progress(user_id),
        "classes": get_class_log(user_id),
        "assignments": get_assignments(user_id),
    }


# ── Course catalog (admin-managed) ───────────────────────────────────────────

_COURSE_COLS = [
    'syllabus_code', 'slug', 'title', 'level', 'subject', 'tagline',
    'overview_html', 'approach_html', 'what_you_get_json', 'teacher_id',
    'meta_title', 'meta_description', 'published', 'sort_order',
    'created_at', 'updated_at', 'faq_json',
]


def get_all_courses(published_only: bool = False) -> list[dict]:
    if _USE_SUPABASE:
        q = _client().table("courses").select("*").order("sort_order")
        if published_only:
            q = q.eq("published", True)
        return q.execute().data or []
    with _local() as c:
        if published_only:
            rows = c.execute("SELECT * FROM courses WHERE published=1 ORDER BY sort_order").fetchall()
        else:
            rows = c.execute("SELECT * FROM courses ORDER BY sort_order").fetchall()
        return [dict(r) for r in rows]


def get_course_by_slug(slug: str) -> dict | None:
    if _USE_SUPABASE:
        r = _client().table("courses").select("*").eq("slug", slug).limit(1).execute()
        return r.data[0] if r.data else None
    with _local() as c:
        row = c.execute("SELECT * FROM courses WHERE slug=?", (slug,)).fetchone()
        return dict(row) if row else None


def get_course(course_id: int) -> dict | None:
    if _USE_SUPABASE:
        r = _client().table("courses").select("*").eq("id", course_id).limit(1).execute()
        return r.data[0] if r.data else None
    with _local() as c:
        row = c.execute("SELECT * FROM courses WHERE id=?", (course_id,)).fetchone()
        return dict(row) if row else None


def create_course(payload: dict) -> dict:
    payload.setdefault("created_at", _now())
    payload.setdefault("updated_at", _now())
    payload.setdefault("published", False if _USE_SUPABASE else 0)
    payload.setdefault("sort_order", 0)
    return _insert("courses", payload, _COURSE_COLS)


def update_course(course_id: int, fields: dict) -> dict | None:
    fields["updated_at"] = _now()
    if _USE_SUPABASE:
        _client().table("courses").update(fields).eq("id", course_id).execute()
    else:
        with _local() as c:
            c.execute(
                f"UPDATE courses SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?",
                (*fields.values(), course_id))
            c.commit()
    return get_course(course_id)


def delete_course(course_id: int) -> None:
    if _USE_SUPABASE:
        _client().table("courses").delete().eq("id", course_id).execute()
    else:
        with _local() as c:
            c.execute("DELETE FROM courses WHERE id=?", (course_id,))
            c.commit()


# ── Groups ────────────────────────────────────────────────────────────────────

_GROUP_COLS = ["name", "description", "teacher_id", "syllabus",
               "max_students", "schedule_json", "status", "created_at", "updated_at"]


def create_group(payload: dict) -> dict:
    payload.setdefault("created_at", _now())
    payload.setdefault("updated_at", _now())
    payload.setdefault("status", "draft")
    payload.setdefault("max_students", 6)
    payload.setdefault("schedule_json", "{}")
    return _insert("groups", payload, _GROUP_COLS)


def get_group(group_id: int) -> dict | None:
    if _USE_SUPABASE:
        r = _client().table("groups").select("*").eq("id", group_id).limit(1).execute()
        return r.data[0] if r.data else None
    with _local() as c:
        row = c.execute("SELECT * FROM groups WHERE id=?", (group_id,)).fetchone()
        return dict(row) if row else None


def get_all_groups() -> list[dict]:
    if _USE_SUPABASE:
        return (_client().table("groups").select("*")
                .order("created_at", desc=True).execute().data or [])
    with _local() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM groups ORDER BY created_at DESC")]


def get_teacher_groups(teacher_id: str) -> list[dict]:
    if _USE_SUPABASE:
        return (_client().table("groups").select("*")
                .eq("teacher_id", teacher_id)
                .order("created_at", desc=True).execute().data or [])
    with _local() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM groups WHERE teacher_id=? ORDER BY created_at DESC",
            (teacher_id,))]


def get_active_groups() -> list[dict]:
    if _USE_SUPABASE:
        return (_client().table("groups").select("*")
                .eq("status", "active")
                .order("created_at", desc=True).execute().data or [])
    with _local() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM groups WHERE status='active' ORDER BY created_at DESC")]


def update_group(group_id: int, fields: dict) -> dict | None:
    fields["updated_at"] = _now()
    if _USE_SUPABASE:
        _client().table("groups").update(fields).eq("id", group_id).execute()
    else:
        with _local() as c:
            c.execute(f"UPDATE groups SET {', '.join(f'{k}=?' for k in fields)} "
                      f"WHERE id=?", (*fields.values(), group_id))
            c.commit()
    return get_group(group_id)


def get_group_members(group_id: int) -> list[dict]:
    if _USE_SUPABASE:
        return (_client().table("group_memberships")
                .select("*, profiles(id, name, email, grade)")
                .eq("group_id", group_id).eq("status", "active").execute().data or [])
    with _local() as c:
        return [dict(r) for r in c.execute(
            "SELECT gm.*, p.name, p.email, p.grade FROM group_memberships gm "
            "JOIN profiles p ON p.id=gm.student_id "
            "WHERE gm.group_id=? AND gm.status='active'", (group_id,))]


def get_student_groups(student_id: str) -> list[dict]:
    if _USE_SUPABASE:
        return (_client().table("group_memberships")
                .select("*, groups(*)")
                .eq("student_id", student_id).eq("status", "active").execute().data or [])
    with _local() as c:
        return [dict(r) for r in c.execute(
            "SELECT gm.*, g.name, g.description, g.syllabus, g.schedule_json, "
            "g.status AS group_status, g.teacher_id FROM group_memberships gm "
            "JOIN groups g ON g.id=gm.group_id "
            "WHERE gm.student_id=? AND gm.status='active'", (student_id,))]


def join_group(group_id: int, student_id: str) -> dict:
    if _USE_SUPABASE:
        r = (_client().table("group_memberships").upsert(
            {"group_id": group_id, "student_id": student_id,
             "joined_at": _now(), "status": "active"},
            on_conflict="group_id,student_id").execute())
        return r.data[0] if r.data else {}
    with _local() as c:
        c.execute(
            "INSERT INTO group_memberships(group_id, student_id, joined_at, status) "
            "VALUES(?,?,?,'active') ON CONFLICT(group_id,student_id) "
            "DO UPDATE SET status='active', joined_at=excluded.joined_at",
            (group_id, student_id, _now()))
        c.commit()
    members = get_group_members(group_id)
    return next((m for m in members if m["student_id"] == student_id), {})


def leave_group(group_id: int, student_id: str) -> None:
    if _USE_SUPABASE:
        _client().table("group_memberships").update({"status": "left"}).eq(
            "group_id", group_id).eq("student_id", student_id).execute()
    else:
        with _local() as c:
            c.execute("UPDATE group_memberships SET status='left' "
                      "WHERE group_id=? AND student_id=?", (group_id, student_id))
            c.commit()


def get_group_member_count(group_id: int) -> int:
    if _USE_SUPABASE:
        r = (_client().table("group_memberships").select("id", count="exact")
             .eq("group_id", group_id).eq("status", "active").execute())
        return r.count or 0
    with _local() as c:
        return c.execute(
            "SELECT COUNT(*) FROM group_memberships WHERE group_id=? AND status='active'",
            (group_id,)).fetchone()[0]


# ── Group sessions ────────────────────────────────────────────────────────────

_GSESSION_COLS = ["group_id", "session_date", "duration_min",
                  "topic", "notes", "status", "created_at"]


def create_group_session(payload: dict) -> dict:
    payload.setdefault("created_at", _now())
    payload.setdefault("status", "held")
    return _insert("group_sessions", payload, _GSESSION_COLS)


def get_group_sessions(group_id: int, limit: int = 200) -> list[dict]:
    if _USE_SUPABASE:
        return (_client().table("group_sessions").select("*")
                .eq("group_id", group_id)
                .order("session_date", desc=True).limit(limit).execute().data or [])
    with _local() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM group_sessions WHERE group_id=? "
            "ORDER BY session_date DESC LIMIT ?", (group_id, limit))]


# ── Payment proofs ────────────────────────────────────────────────────────────

_PROOF_COLS = ["user_id", "plan", "amount_pkr", "method", "transaction_id",
               "screenshot_url", "note", "status", "created_at", "subjects_json",
               "period", "expected_pkr", "screenshot_sha256"]


def create_payment_proof(payload: dict) -> dict:
    payload.setdefault("created_at", _now())
    payload.setdefault("status", "pending")
    return _insert("payment_proofs", payload, _PROOF_COLS)


def _flatten_proof(row: dict) -> dict:
    """Supabase nests the join under 'profiles'; SQLite returns name/email flat."""
    p = row.pop("profiles", None) or {}
    row.setdefault("name", p.get("name"))
    row.setdefault("email", p.get("email"))
    return row


def get_payment_proofs(status: str | None = None, limit: int = 200) -> list[dict]:
    if _USE_SUPABASE:
        q = (_client().table("payment_proofs").select(
            "*, profiles(id, name, email)")
             .order("created_at", desc=True).limit(limit))
        if status:
            q = q.eq("status", status)
        return [_flatten_proof(r) for r in (q.execute().data or [])]
    with _local() as c:
        sql = ("SELECT pp.*, p.name, p.email FROM payment_proofs pp "
               "JOIN profiles p ON p.id=pp.user_id")
        if status:
            sql += " WHERE pp.status=?"
            rows = c.execute(sql + " ORDER BY pp.created_at DESC LIMIT ?",
                             (status, limit)).fetchall()
        else:
            rows = c.execute(sql + " ORDER BY pp.created_at DESC LIMIT ?",
                             (limit,)).fetchall()
        return [dict(r) for r in rows]


def get_payment_proof(proof_id: int) -> dict | None:
    if _USE_SUPABASE:
        r = (_client().table("payment_proofs").select("*, profiles(id, name, email)")
             .eq("id", proof_id).limit(1).execute())
        return _flatten_proof(r.data[0]) if r.data else None
    with _local() as c:
        row = c.execute(
            "SELECT pp.*, p.name, p.email FROM payment_proofs pp "
            "JOIN profiles p ON p.id=pp.user_id WHERE pp.id=?", (proof_id,)).fetchone()
        return dict(row) if row else None


def update_payment_proof(proof_id: int, fields: dict) -> dict | None:
    if _USE_SUPABASE:
        _client().table("payment_proofs").update(fields).eq("id", proof_id).execute()
    else:
        with _local() as c:
            c.execute(f"UPDATE payment_proofs SET {', '.join(f'{k}=?' for k in fields)} "
                      f"WHERE id=?", (*fields.values(), proof_id))
            c.commit()
    return get_payment_proof(proof_id)


# ── Student codes ─────────────────────────────────────────────────────────────

import random as _random
import string as _string

def _gen_code() -> str:
    chars = _string.ascii_uppercase + _string.digits
    return "".join(_random.choices(chars, k=6))


def ensure_student_code(user_id: str) -> str:
    """Return the student's code, generating and storing one if missing."""
    for _ in range(10):
        code = _gen_code()
        if _USE_SUPABASE:
            row = (_client().table("profiles").select("student_code")
                   .eq("id", user_id).limit(1).execute().data or [{}])[0]
            existing = row.get("student_code")
            if existing:
                return existing
            try:
                _client().table("profiles").update({"student_code": code}).eq("id", user_id).execute()
                return code
            except Exception:
                continue
        else:
            with _local() as c:
                row = c.execute("SELECT student_code FROM profiles WHERE id=?",
                                (user_id,)).fetchone()
                existing = dict(row).get("student_code") if row else None
                if existing:
                    return existing
                try:
                    c.execute("UPDATE profiles SET student_code=? WHERE id=?", (code, user_id))
                    c.commit()
                    return code
                except Exception:
                    continue
    raise RuntimeError("Could not generate unique student code")


def ensure_referral_code(user_id: str) -> str:
    """Return the user's referral code, generating one if missing."""
    user = get_user(user_id)
    if not user:
        return ""
    if user.get("referral_code"):
        return user["referral_code"]
    
    first = (user.get("name") or "TEE").split()[0].upper()
    clean_first = "".join(c for c in first if c.isalnum())[:6] or "PWT"
    for _ in range(10):
        code = f"{clean_first}-{_gen_code()[:4]}"
        try:
            if _USE_SUPABASE:
                _client().table("profiles").update({"referral_code": code}).eq("id", user_id).execute()
            else:
                with _local() as c:
                    c.execute("UPDATE profiles SET referral_code=? WHERE id=?", (code, user_id))
                    c.commit()
            return code
        except Exception:
            continue
    return f"REF-{_gen_code()}"


def record_referral(referee_id: str, code: str) -> bool:
    """If code is valid, link referee to referrer and award +50 points."""
    if not code:
        return False
    if _USE_SUPABASE:
        res = _client().table("profiles").select("id").eq("referral_code", code.strip().upper()).execute()
        referrer = res.data[0] if res.data else None
    else:
        with _local() as c:
            row = c.execute("SELECT id FROM profiles WHERE UPPER(referral_code)=?", (code.strip().upper(),)).fetchone()
            referrer = dict(row) if row else None

    if not referrer or referrer["id"] == referee_id:
        return False

    referrer_id = referrer["id"]
    now = _now()
    try:
        if _USE_SUPABASE:
            _client().table("referral_events").insert(
                {"referrer_id": referrer_id, "referee_id": referee_id, "status": "rewarded", "created_at": now}
            ).execute()
        else:
            with _local() as c:
                c.execute("INSERT INTO referral_events(referrer_id, referee_id, status, created_at) VALUES(?,?,?,?)",
                          (referrer_id, referee_id, "rewarded", now))
                c.commit()
        
        # Award 50 points to referrer
        add_user_points(referrer_id, 50, "referral_bonus", {"referee_id": referee_id})
        return True
    except Exception as exc:
        print(f"[referral] Could not record referral event: {exc}", flush=True)
        return False


def add_user_points(user_id: str, points: int, activity_type: str, details: dict | None = None) -> int:
    import json as _json
    now = _now()
    det_str = _json.dumps(details or {})
    if _USE_SUPABASE:
        try:
            _client().table("study_activities").insert(
                {"user_id": user_id, "activity_type": activity_type, "points_awarded": points,
                 "details_json": det_str, "created_at": now}
            ).execute()
        except Exception:
            pass

        res = _client().table("user_points").select("points").eq("user_id", user_id).execute()
        cur_pts = (res.data[0]["points"] if res.data else 0) + points
        _client().table("user_points").upsert(
            {"user_id": user_id, "points": cur_pts, "updated_at": now}, on_conflict="user_id"
        ).execute()
        return cur_pts
    else:
        with _local() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS user_points (user_id TEXT PRIMARY KEY, points INTEGER DEFAULT 0, updated_at TEXT)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS study_activities (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, activity_type TEXT, points_awarded INTEGER, details_json TEXT, created_at TEXT)"
            )
            c.execute(
                "INSERT INTO study_activities(user_id, activity_type, points_awarded, details_json, created_at) VALUES(?,?,?,?,?)",
                (user_id, activity_type, points, det_str, now)
            )
            row = c.execute("SELECT points FROM user_points WHERE user_id=?", (user_id,)).fetchone()
            cur_pts = (row["points"] if row else 0) + points
            c.execute(
                "INSERT INTO user_points(user_id, points, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET points=excluded.points, updated_at=excluded.updated_at",
                (user_id, cur_pts, now)
            )
            c.commit()
            return cur_pts


def get_user_points(user_id: str) -> dict:
    ref_code = ensure_referral_code(user_id)
    if _USE_SUPABASE:
        pts_res = _client().table("user_points").select("points").eq("user_id", user_id).execute()
        pts = pts_res.data[0]["points"] if pts_res.data else 0
        ref_res = _client().table("referral_events").select("id", count="exact").eq("referrer_id", user_id).execute()
        ref_count = ref_res.count or 0
    else:
        with _local() as c:
            c.execute("CREATE TABLE IF NOT EXISTS user_points (user_id TEXT PRIMARY KEY, points INTEGER DEFAULT 0, updated_at TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS referral_events (id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id TEXT, referee_id TEXT, status TEXT, created_at TEXT)")
            r1 = c.execute("SELECT points FROM user_points WHERE user_id=?", (user_id,)).fetchone()
            pts = r1["points"] if r1 else 0
            r2 = c.execute("SELECT COUNT(*) FROM referral_events WHERE referrer_id=?", (user_id,)).fetchone()
            ref_count = r2[0] if r2 else 0

    return {
        "user_id": user_id,
        "points": pts,
        "referral_code": ref_code,
        "referral_link": f"https://prepwithtee.com/login.html?ref={ref_code}",
        "referrals_count": ref_count,
    }


def get_profile_by_student_code(code: str) -> dict | None:
    if _USE_SUPABASE:
        r = (_client().table("profiles").select("id,name,email,grade,picture_url")
             .eq("student_code", code).limit(1).execute())
        return r.data[0] if r.data else None
    with _local() as c:
        row = c.execute(
            "SELECT id,name,email,grade,picture_url FROM profiles WHERE student_code=?",
            (code,)).fetchone()
        return dict(row) if row else None


# ── Parent-student links ──────────────────────────────────────────────────────

def create_parent_link(parent_id: str, student_id: str) -> dict:
    payload = {"parent_id": parent_id, "student_id": student_id, "created_at": _now()}
    return _insert("parent_student_links", payload,
                   ["parent_id", "student_id", "created_at"])


def get_parent_links(parent_id: str) -> list[dict]:
    if _USE_SUPABASE:
        return (_client().table("parent_student_links")
                .select("*, profiles!student_id(id,name,email,grade,picture_url,plan)")
                .eq("parent_id", parent_id).execute().data or [])
    with _local() as c:
        return [dict(r) for r in c.execute(
            "SELECT psl.*, p.name, p.email, p.grade, p.picture_url, p.plan "
            "FROM parent_student_links psl "
            "JOIN profiles p ON p.id=psl.student_id "
            "WHERE psl.parent_id=?", (parent_id,))]


def parent_link_exists(parent_id: str, student_id: str) -> bool:
    if _USE_SUPABASE:
        r = (_client().table("parent_student_links")
             .select("id").eq("parent_id", parent_id).eq("student_id", student_id)
             .limit(1).execute())
        return bool(r.data)
    with _local() as c:
        row = c.execute(
            "SELECT id FROM parent_student_links WHERE parent_id=? AND student_id=?",
            (parent_id, student_id)).fetchone()
        return row is not None


def get_linked_parents(student_id: str) -> list[dict]:
    if _USE_SUPABASE:
        return (_client().table("parent_student_links")
                .select("*, profiles!parent_id(id,name,email)")
                .eq("student_id", student_id).execute().data or [])
    with _local() as c:
        return [dict(r) for r in c.execute(
            "SELECT psl.*, p.name, p.email FROM parent_student_links psl "
            "JOIN profiles p ON p.id=psl.parent_id WHERE psl.student_id=?",
            (student_id,))]


# ── Direct messages ───────────────────────────────────────────────────────────

_MSG_COLS = ["sender_id", "recipient_id", "body", "created_at"]


def create_message(sender_id: str, recipient_id: str, body: str) -> dict:
    payload = {"sender_id": sender_id, "recipient_id": recipient_id,
               "body": body, "created_at": _now()}
    return _insert("messages", payload, _MSG_COLS)


def get_messages_between(user_a: str, user_b: str, limit: int = 100) -> list[dict]:
    if _USE_SUPABASE:
        return (_client().table("messages").select("*")
                .or_(f"and(sender_id.eq.{user_a},recipient_id.eq.{user_b}),"
                     f"and(sender_id.eq.{user_b},recipient_id.eq.{user_a})")
                .order("created_at", desc=False).limit(limit).execute().data or [])
    with _local() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM messages WHERE "
            "(sender_id=? AND recipient_id=?) OR (sender_id=? AND recipient_id=?) "
            "ORDER BY created_at ASC LIMIT ?",
            (user_a, user_b, user_b, user_a, limit))]


def get_conversations(user_id: str) -> list[dict]:
    """Return one row per conversation partner with the latest message and unread count."""
    if _USE_SUPABASE:
        sent = (_client().table("messages").select("*, profiles!recipient_id(id,name,picture_url)")
                .eq("sender_id", user_id).execute().data or [])
        recv = (_client().table("messages").select("*, profiles!sender_id(id,name,picture_url)")
                .eq("recipient_id", user_id).execute().data or [])
        partners: dict = {}
        for m in sent + recv:
            pid = m["recipient_id"] if m["sender_id"] == user_id else m["sender_id"]
            # FK join key is "profiles" regardless of the hint used
            profile = m.get("profiles") or {}
            name = profile.get("name") or ""
            pic  = profile.get("picture_url") or ""
            if pid not in partners or m["created_at"] > partners[pid]["last_at"]:
                partners[pid] = {
                    "partner_id":   pid,
                    "partner_name": name,
                    "partner_pic":  pic,
                    "last_at":      m["created_at"],
                    "last_body":    m["body"],
                }
        return list(partners.values())
    with _local() as c:
        rows = c.execute(
            "SELECT partner_id, MAX(created_at) last_at, "
            "  (SELECT body FROM messages m2 WHERE "
            "   (m2.sender_id=sq.partner_id AND m2.recipient_id=?1) OR "
            "   (m2.sender_id=?1 AND m2.recipient_id=sq.partner_id) "
            "   ORDER BY created_at DESC LIMIT 1) last_body, "
            "  p.name partner_name, p.picture_url partner_pic "
            "FROM ("
            "  SELECT CASE WHEN sender_id=?1 THEN recipient_id ELSE sender_id END partner_id "
            "  FROM messages WHERE sender_id=?1 OR recipient_id=?1"
            ") sq JOIN profiles p ON p.id=sq.partner_id "
            "GROUP BY partner_id ORDER BY last_at DESC",
            (user_id,)).fetchall()
        return [dict(r) for r in rows]


def mark_messages_read(reader_id: str, sender_id: str) -> None:
    if _USE_SUPABASE:
        (_client().table("messages").update({"read_at": _now()})
         .eq("recipient_id", reader_id).eq("sender_id", sender_id)
         .is_("read_at", "null").execute())
    else:
        with _local() as c:
            c.execute("UPDATE messages SET read_at=? "
                      "WHERE recipient_id=? AND sender_id=? AND read_at IS NULL",
                      (_now(), reader_id, sender_id))
            c.commit()


def count_unread_messages(user_id: str) -> int:
    if _USE_SUPABASE:
        r = (_client().table("messages").select("id", count="exact")
             .eq("recipient_id", user_id).is_("read_at", "null").execute())
        return r.count or 0
    with _local() as c:
        row = c.execute(
            "SELECT COUNT(*) FROM messages WHERE recipient_id=? AND read_at IS NULL",
            (user_id,)).fetchone()
        return row[0] if row else 0


# ── Teacher-student allocations ───────────────────────────────────────────────

def list_teacher_profiles() -> list[dict]:
    """All profiles with role=teacher — used for allocation dropdowns."""
    if _USE_SUPABASE:
        r = (_client().table("profiles")
             .select("id,name,email")
             .eq("role", "teacher")
             .order("name")
             .execute())
        return r.data or []
    with _local() as c:
        rows = c.execute(
            "SELECT id, name, email FROM profiles WHERE role='teacher' ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]


def get_allocations(teacher_id: str | None = None,
                    student_id: str | None = None,
                    status: str | None = "active") -> list[dict]:
    """Teacher-student links; status=None lists removed ones too."""
    if _USE_SUPABASE:
        q = (_client().table("teacher_students")
             .select("*, "
                     "teacher:profiles!teacher_id(id,name,email),"
                     "student:profiles!student_id(id,name,email,grade)"))
        if status:
            q = q.eq("status", status)
        if teacher_id:
            q = q.eq("teacher_id", teacher_id)
        if student_id:
            q = q.eq("student_id", student_id)
        rows = q.order("allocated_at", desc=True).execute().data or []
        # Flatten nested Supabase join objects into flat fields
        for r in rows:
            t = r.pop("teacher", None) or {}
            s = r.pop("student", None) or {}
            r.setdefault("teacher_name", t.get("name"))
            r.setdefault("teacher_email", t.get("email"))
            r.setdefault("student_name", s.get("name"))
            r.setdefault("student_email", s.get("email"))
            r.setdefault("student_grade", s.get("grade"))
        return rows
    with _local() as c:
        wheres, vals = [], []
        if status:
            wheres.append("ts.status=?"); vals.append(status)
        if teacher_id:
            wheres.append("ts.teacher_id=?"); vals.append(teacher_id)
        if student_id:
            wheres.append("ts.student_id=?"); vals.append(student_id)
        where = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        return [dict(r) for r in c.execute(
            f"SELECT ts.*, "
            f"  t.name teacher_name, t.email teacher_email, "
            f"  s.name student_name, s.email student_email, s.grade student_grade "
            f"FROM teacher_students ts "
            f"JOIN profiles t ON t.id=ts.teacher_id "
            f"JOIN profiles s ON s.id=ts.student_id "
            f"{where} ORDER BY ts.allocated_at DESC", vals)]


def create_allocation(teacher_id: str, student_id: str, syllabus: str) -> dict:
    """Same upsert as the Teachers drawer: re-assigning re-activates the old row."""
    assign_teacher_student(teacher_id, student_id, syllabus)
    rows = [r for r in get_allocations(teacher_id=teacher_id, student_id=student_id)
            if r.get("syllabus") == syllabus]
    return rows[0] if rows else {}


def delete_allocation(allocation_id: int) -> int:
    """Soft-remove one link by id (same style as remove_teacher_student)."""
    if _USE_SUPABASE:
        r = (_client().table("teacher_students").update({"status": "removed"})
             .eq("id", allocation_id).eq("status", "active").execute())
        return len(r.data or [])
    with _local() as c:
        n = c.execute("UPDATE teacher_students SET status='removed' "
                      "WHERE id=? AND status='active'", (allocation_id,)).rowcount
        c.commit()
        return n


# ── Contacts ──────────────────────────────────────────────────────────────────

def create_contact(name: str, email: str, subject: str, message: str) -> dict:
    payload = {"name": name, "email": email, "subject": subject,
               "message": message, "created_at": _now()}
    return _insert("contacts", payload, ["name", "email", "subject", "message", "created_at"])


def get_contacts(limit: int = 200) -> list[dict]:
    if _USE_SUPABASE:
        return (_client().table("contacts").select("*")
                .order("created_at", desc=True).limit(limit).execute().data or [])
    with _local() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM contacts ORDER BY created_at DESC LIMIT ?", (limit,))]


# ── Newsletter subscribers ────────────────────────────────────────────────────

def create_newsletter_subscriber(email: str, token: str | None = None) -> tuple[bool, str]:
    """Returns (is_new, token). An unsubscribed address that signs up again is
    subscribed again (and counts as new, so it gets the welcome email)."""
    import secrets
    email = (email or "").strip().lower()
    tok = token or secrets.token_urlsafe(24)
    now = _now()
    row = get_newsletter_subscriber(email)
    if row:
        fields: dict = {}
        if not row.get("unsubscribe_token"):
            fields["unsubscribe_token"] = tok
        resub = row.get("status") == "unsubscribed"
        if resub:
            fields.update(status="subscribed", unsubscribed_at=None, subscribed_at=now)
        if fields:
            update_newsletter_subscriber(row["id"], fields)
        return resub, fields.get("unsubscribe_token") or row.get("unsubscribe_token") or tok
    payload = {"email": email, "subscribed_at": now, "unsubscribe_token": tok, "status": "subscribed"}
    _insert("newsletter_subscribers", payload, ["email", "subscribed_at", "unsubscribe_token", "status"])
    return True, tok


def get_newsletter_subscriber(email: str) -> dict | None:
    if _USE_SUPABASE:
        r = (_client().table("newsletter_subscribers").select("*")
             .ilike("email", email.replace("%", r"\%").replace("_", r"\_")).limit(1).execute())
        return r.data[0] if r.data else None
    with _local() as c:
        row = c.execute("SELECT * FROM newsletter_subscribers WHERE lower(email)=lower(?)",
                        (email,)).fetchone()
        return dict(row) if row else None


def update_newsletter_subscriber(sub_id: int, fields: dict) -> None:
    if _USE_SUPABASE:
        _client().table("newsletter_subscribers").update(fields).eq("id", sub_id).execute()
        return
    with _local() as c:
        c.execute(f"UPDATE newsletter_subscribers SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?",
                  (*fields.values(), sub_id))
        c.commit()


def unsubscribe_newsletter(token: str) -> bool:
    now = _now()
    if _USE_SUPABASE:
        res = _client().table("newsletter_subscribers").update(
            {"status": "unsubscribed", "unsubscribed_at": now}).eq("unsubscribe_token", token).execute()
        return bool(res.data)
    with _local() as c:
        cur = c.execute("UPDATE newsletter_subscribers SET status='unsubscribed', unsubscribed_at=? WHERE unsubscribe_token=?",
                        (now, token))
        c.commit()
        return cur.rowcount > 0


def get_newsletter_subscribers(limit: int = 500, active_only: bool = False) -> list[dict]:
    """Newest first. Rows with no status (signed up before the column existed)
    are subscribed - a SQL `status != 'unsubscribed'` would silently drop them."""
    import secrets
    rows = fetch_all("newsletter_subscribers", order="subscribed_at", desc=True)
    if active_only:
        rows = [r for r in rows if (r.get("status") or "subscribed") != "unsubscribed"]
    for r in rows:                     # legacy rows get a real unsubscribe token
        if not r.get("unsubscribe_token"):
            r["unsubscribe_token"] = secrets.token_urlsafe(24)
            update_newsletter_subscriber(r["id"], {"unsubscribe_token": r["unsubscribe_token"]})
        r["status"] = r.get("status") or "subscribed"
    return rows[:limit]



# ── Grade options (overall combined thresholds) ──────────────────────────────

def get_grade_options(syllabus: str, year: int | None = None, session: str | None = None) -> list[dict]:
    if _USE_SUPABASE:
        q = _client().table("grade_options").select("*").eq("syllabus", syllabus)
        if year is not None:
            q = q.eq("year", int(year))
        if session:
            q = q.eq("session", session)
        return q.execute().data or []
    with _local() as c:
        sql = "SELECT * FROM grade_options WHERE syllabus=?"
        args: list = [syllabus]
        if year is not None:
            sql += " AND year=?"
            args.append(int(year))
        if session:
            sql += " AND session=?"
            args.append(session)
def get_grade_thresholds(syllabus: str, year: int | None = None, session: str | None = None) -> list[dict]:
    """All grade_thresholds rows for a syllabus, optionally filtered by year/session."""
    if _USE_SUPABASE:
        q = _client().table("grade_thresholds").select("*").eq("syllabus", syllabus)
        if year is not None:
            q = q.eq("year", int(year))
        if session:
            q = q.eq("session", session)
        return q.execute().data or []
    with _local() as c:
        sql = "SELECT * FROM grade_thresholds WHERE syllabus=?"
        args: list = [syllabus]
        if year is not None:
            sql += " AND year=?"
            args.append(int(year))
        if session:
            sql += " AND session=?"
            args.append(session)
        return [dict(r) for r in c.execute(sql + " ORDER BY year DESC, session, paper, variant", args)]


def get_grade_thresholds_history(syllabus: str, paper: int) -> list[dict]:
    """All grade_thresholds rows for a syllabus+paper across every year/session/variant."""
    if _USE_SUPABASE:
        return (_client().table("grade_thresholds").select("*")
                .eq("syllabus", syllabus).eq("paper", int(paper))
                .order("year", desc=False).execute().data or [])
    with _local() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM grade_thresholds WHERE syllabus=? AND paper=? "
            "ORDER BY year, session, variant",
            (syllabus, int(paper)))]


def get_grade_options_history(syllabus: str, option_code: str | None = None) -> list[dict]:
    """All grade_options rows for a syllabus across years, optionally filtered by option_code."""
    if _USE_SUPABASE:
        q = _client().table("grade_options").select("*").eq("syllabus", syllabus)
        if option_code:
            q = q.eq("option_code", option_code)
        return q.order("year", desc=False).execute().data or []
    with _local() as c:
        sql = "SELECT * FROM grade_options WHERE syllabus=?"
        args: list = [syllabus]
        if option_code:
            sql += " AND option_code=?"
            args.append(option_code)
        return [dict(r) for r in c.execute(sql + " ORDER BY year, session, option_code", args)]


# ── Student scores (per-component marks) ─────────────────────────────────────

def get_student_scores(user_id: str, syllabus: str) -> list[dict]:
    if _USE_SUPABASE:
        return (_client().table("student_scores").select("*")
                .eq("user_id", user_id).eq("syllabus", syllabus)
                .order("year", desc=True).execute().data or [])
    with _local() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM student_scores WHERE user_id=? AND syllabus=? "
            "ORDER BY year DESC, session, paper, variant",
            (user_id, syllabus))]


def upsert_student_score(user_id: str, syllabus: str, year: int, session: str,
                         paper: int, variant: str, raw_mark: int, max_mark: int,
                         component_grade: str | None = None,
                         option_code: str | None = None,
                         notes: str | None = None,
                         set_by: str = "student") -> dict:
    now = _now()
    payload = {
        "user_id": user_id, "syllabus": syllabus, "year": int(year),
        "session": session, "paper": int(paper), "variant": variant or "",
        "raw_mark": int(raw_mark), "max_mark": int(max_mark),
        "component_grade": component_grade, "option_code": option_code,
        "notes": notes, "set_by": set_by, "updated_at": now,
    }
    if _USE_SUPABASE:
        payload["recorded_at"] = now
        _client().table("student_scores").upsert(
            payload,
            on_conflict="user_id,syllabus,year,session,paper,variant"
        ).execute()
    else:
        with _local() as c:
            c.execute(
                "INSERT INTO student_scores "
                "(user_id, syllabus, year, session, paper, variant, raw_mark, max_mark, "
                "component_grade, option_code, notes, set_by, recorded_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id, syllabus, year, session, paper, variant) "
                "DO UPDATE SET raw_mark=excluded.raw_mark, max_mark=excluded.max_mark, "
                "component_grade=excluded.component_grade, option_code=excluded.option_code, "
                "notes=excluded.notes, set_by=excluded.set_by, updated_at=excluded.updated_at",
                (user_id, syllabus, int(year), session, int(paper), variant or "",
                 int(raw_mark), int(max_mark), component_grade, option_code,
                 notes, set_by, now, now))
            c.commit()
    return payload


# ── Tutor Sessions & Messages CRUD ───────────────────────────────────────────

def upload_attachment(user_id: str, session_id: str, filename: str, data_uri: str) -> str | None:
    import base64
    import re
    if not _USE_SUPABASE:
        return data_uri  # local SQLite dev: keep inline base64
        
    try:
        m = re.match(r"data:(image/(?:png|jpe?g|webp|gif));base64,(.+)$", data_uri, re.S)
        if not m:
            return None
        media_type, b64 = m.group(1), m.group(2)
        file_bytes = base64.b64decode(b64)
        
        path = f"{user_id}/{session_id}/{filename}"
        bucket = _client().storage.from_("tutor-attachments")
        
        # Upload to Supabase Storage
        bucket.upload(path=path, file=file_bytes, file_options={"content-type": media_type})
        
        # Create signed URL (valid for 60 days)
        res = bucket.create_signed_url(path, 5184000)
        return res.get("signedURL") or res.get("signedUrl")
    except Exception as e:
        print(f"Error uploading to Supabase storage: {e}", flush=True)
        return None


def create_tutor_session(user_id: str, session_id: str, subject: str | None, topic: str | None, mode: str = "normal") -> dict:
    import json as _json
    now = _now()
    title = f"{subject or 'General'} Chat"
    if subject and topic:
        title = f"{subject} — {topic}"
    elif topic:
        title = topic

    payload = {
        "id": session_id,
        "user_id": user_id,
        "title": title,
        "subject": subject,
        "topic": topic,
        "mode": mode,
        "pinned": False,
        "summary": None,
        "created_at": now,
        "updated_at": now,
    }
    if _USE_SUPABASE:
        r = _client().table("tutor_sessions").insert(payload).execute()
        return r.data[0]
    
    with _local() as c:
        c.execute(
            "INSERT INTO tutor_sessions (id, user_id, title, subject, topic, mode, pinned, summary, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
            (session_id, user_id, title, subject, topic, mode, None, now, now)
        )
        c.commit()
    return payload

def list_tutor_sessions(user_id: str, limit: int = 50, offset: int = 0) -> list[dict]:
    if _USE_SUPABASE:
        r = (_client().table("tutor_sessions")
             .select("*")
             .eq("user_id", user_id)
             .order("pinned", desc=True)
             .order("updated_at", desc=True)
             .range(offset, offset + limit - 1)
             .execute())
        return r.data or []
    
    with _local() as c:
        rows = c.execute(
            "SELECT * FROM tutor_sessions WHERE user_id=? ORDER BY pinned DESC, updated_at DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset)
        ).fetchall()
        return [dict(r) for r in rows]

def get_tutor_session(session_id: str, user_id: str) -> dict | None:
    import json as _json
    if _USE_SUPABASE:
        r = (_client().table("tutor_sessions")
             .select("*")
             .eq("id", session_id)
             .eq("user_id", user_id)
             .limit(1)
             .execute())
        session = r.data[0] if r.data else None
        if not session:
            return None
        
        m = (_client().table("tutor_messages")
             .select("*")
             .eq("session_id", session_id)
             .order("created_at", desc=False)
             .execute())
        session["messages"] = m.data or []
        return session

    with _local() as c:
        row = c.execute("SELECT * FROM tutor_sessions WHERE id=? AND user_id=?", (session_id, user_id)).fetchone()
        if not row:
            return None
        session = dict(row)
        msg_rows = c.execute(
            "SELECT * FROM tutor_messages WHERE session_id=? ORDER BY created_at ASC",
            (session_id,)
        ).fetchall()
        
        messages = []
        for r in msg_rows:
            m = dict(r)
            if isinstance(m.get("attachments"), str):
                try:
                    m["attachments"] = _json.loads(m["attachments"])
                except Exception:
                    m["attachments"] = []
            messages.append(m)
            
        session["messages"] = messages
        session["pinned"] = bool(session.get("pinned", 0))
        return session

def save_tutor_message(message_id: str, session_id: str, role: str, content: str, attachments: list | None = None, provider: str | None = None) -> dict:
    import json as _json
    now = _now()
    attachments = attachments or []
    
    payload = {
        "id": message_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "attachments": attachments,
        "provider": provider,
        "feedback": None,
        "created_at": now,
    }
    
    if _USE_SUPABASE:
        _client().table("tutor_messages").insert(payload).execute()
        _client().table("tutor_sessions").update({"updated_at": now}).eq("id", session_id).execute()
        return payload
        
    with _local() as c:
        c.execute(
            "INSERT INTO tutor_messages (id, session_id, role, content, attachments, provider, feedback, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (message_id, session_id, role, content, _json.dumps(attachments), provider, None, now)
        )
        c.execute(
            "UPDATE tutor_sessions SET updated_at=? WHERE id=?",
            (now, session_id)
        )
        c.commit()
    return payload

def rename_tutor_session(session_id: str, user_id: str, title: str) -> bool:
    if _USE_SUPABASE:
        r = (_client().table("tutor_sessions")
             .update({"title": title, "updated_at": _now()})
             .eq("id", session_id)
             .eq("user_id", user_id)
             .execute())
        return len(r.data) > 0
        
    with _local() as c:
        c.execute(
            "UPDATE tutor_sessions SET title=?, updated_at=? WHERE id=? AND user_id=?",
            (title, _now(), session_id, user_id)
        )
        c.commit()
        return True

def pin_tutor_session(session_id: str, user_id: str, pinned: bool) -> bool:
    val = pinned
    if _USE_SUPABASE:
        r = (_client().table("tutor_sessions")
             .update({"pinned": val})
             .eq("id", session_id)
             .eq("user_id", user_id)
             .execute())
        return len(r.data) > 0
        
    with _local() as c:
        c.execute(
            "UPDATE tutor_sessions SET pinned=? WHERE id=? AND user_id=?",
            (1 if val else 0, session_id, user_id)
        )
        c.commit()
        return True

def update_session_mode(session_id: str, user_id: str, mode: str) -> bool:
    if _USE_SUPABASE:
        r = (_client().table("tutor_sessions")
             .update({"mode": mode})
             .eq("id", session_id)
             .eq("user_id", user_id)
             .execute())
        return len(r.data) > 0
        
    with _local() as c:
        c.execute(
            "UPDATE tutor_sessions SET mode=? WHERE id=? AND user_id=?",
            (mode, session_id, user_id)
        )
        c.commit()
        return True

def delete_tutor_session(session_id: str, user_id: str) -> bool:
    if _USE_SUPABASE:
        r = (_client().table("tutor_sessions")
             .delete()
             .eq("id", session_id)
             .eq("user_id", user_id)
             .execute())
        return len(r.data) > 0
        
    with _local() as c:
        c.execute("DELETE FROM tutor_sessions WHERE id=? AND user_id=?", (session_id, user_id))
        c.commit()
        return True

def truncate_tutor_messages(session_id: str, user_id: str, message_id: str) -> int | None:
    """Delete one message and every later message in the session (regenerate /
    edit-and-resend). None if the session or message is not the user's."""
    if get_tutor_session(session_id, user_id) is None:
        return None
    if _USE_SUPABASE:
        m = (_client().table("tutor_messages").select("created_at").eq("id", message_id)
             .eq("session_id", session_id).execute().data or [])
        if not m:
            return None
        r = (_client().table("tutor_messages").delete().eq("session_id", session_id)
             .gte("created_at", m[0]["created_at"]).execute())
        return len(r.data or [])
    with _local() as c:
        row = c.execute("SELECT created_at FROM tutor_messages WHERE id=? AND session_id=?",
                        (message_id, session_id)).fetchone()
        if row is None:
            return None
        cur = c.execute("DELETE FROM tutor_messages WHERE session_id=? AND created_at >= ?",
                        (session_id, row[0]))
        c.commit()
        return cur.rowcount


def update_session_summary(session_id: str, summary: str) -> None:
    if _USE_SUPABASE:
        _client().table("tutor_sessions").update({"summary": summary}).eq("id", session_id).execute()
        return
        
    with _local() as c:
        c.execute("UPDATE tutor_sessions SET summary=? WHERE id=?", (summary, session_id))
        c.commit()

def set_message_feedback(message_id: str, feedback: str | None) -> bool:
    if _USE_SUPABASE:
        r = (_client().table("tutor_messages")
             .update({"feedback": feedback})
             .eq("id", message_id)
             .execute())
        return len(r.data) > 0

    with _local() as c:
        c.execute("UPDATE tutor_messages SET feedback=? WHERE id=?", (feedback, message_id))
        c.commit()
        return True


# -- Student personal notes --------------------------------------------------

def create_note(user_id: str, payload: dict) -> dict:
    """Insert a new note row and return it."""
    import json
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    loc = payload.get("location_json")
    data = {
        "user_id": user_id,
        "type": payload.get("type", "text"),
        "title": payload.get("title"),
        "content": payload.get("content"),
        "color": payload.get("color"),
        "linked_type": payload.get("linked_type"),
        "linked_id": str(payload["linked_id"]) if payload.get("linked_id") else None,
        "linked_label": payload.get("linked_label"),
        "syllabus": payload.get("syllabus"),
        "tags_json": payload.get("tags_json", "[]"),
        "pinned_to_dashboard": bool(payload.get("pinned_to_dashboard", False)),
        "location_json": loc,   # Supabase accepts dict for JSONB
        "is_mistake": bool(payload.get("is_mistake", False)),
        "is_exam_revision": bool(payload.get("is_exam_revision", False)),
        "created_at": now,
        "updated_at": now,
    }
    if _USE_SUPABASE:
        r = _client().table("notes").insert(data).execute()
        return r.data[0] if r.data else {}
    # SQLite: store location_json as serialised text
    data["location_json"] = json.dumps(loc) if loc else None
    with _local() as c:
        cur = c.execute(
            "INSERT INTO notes (user_id, type, title, content, color, linked_type, linked_id, "
            "linked_label, syllabus, tags_json, pinned_to_dashboard, location_json, "
            "is_mistake, is_exam_revision, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (data["user_id"], data["type"], data["title"], data["content"],
             data["color"], data["linked_type"], data["linked_id"], data["linked_label"],
             data["syllabus"], data["tags_json"], int(data["pinned_to_dashboard"]),
             data["location_json"], int(data["is_mistake"]), int(data["is_exam_revision"]),
             data["created_at"], data["updated_at"])
        )
        c.commit()
        row = c.execute("SELECT * FROM notes WHERE id=?", (cur.lastrowid,)).fetchone()
        return dict(row) if row else {}


def list_notes(user_id: str, syllabus=None, type_=None,
               linked_type=None, linked_id=None,
               pinned=None, is_mistake=None, is_exam_revision=None,
               q=None, limit: int = 50, offset: int = 0) -> list:
    """List notes for a user with optional filters."""
    if _USE_SUPABASE:
        qb = (_client().table("notes")
              .select("*")
              .eq("user_id", user_id)
              .order("updated_at", desc=True)
              .limit(limit)
              .offset(offset))
        if syllabus:    qb = qb.eq("syllabus", syllabus)
        if type_:       qb = qb.eq("type", type_)
        if linked_type: qb = qb.eq("linked_type", linked_type)
        if linked_id:   qb = qb.eq("linked_id", str(linked_id))
        if pinned is not None:          qb = qb.eq("pinned_to_dashboard", pinned)
        if is_mistake is not None:      qb = qb.eq("is_mistake", is_mistake)
        if is_exam_revision is not None: qb = qb.eq("is_exam_revision", is_exam_revision)
        r = qb.execute()
        rows = r.data or []
        if q:
            ql = q.lower()
            rows = [row for row in rows
                    if ql in (row.get("title") or "").lower()
                    or ql in (row.get("content") or "").lower()
                    or ql in (row.get("linked_label") or "").lower()]
        return rows
    with _local() as c:
        sql = "SELECT * FROM notes WHERE user_id=?"
        args = [user_id]
        if syllabus:    sql += " AND syllabus=?";            args.append(syllabus)
        if type_:       sql += " AND type=?";                args.append(type_)
        if linked_type: sql += " AND linked_type=?";         args.append(linked_type)
        if linked_id:   sql += " AND linked_id=?";           args.append(str(linked_id))
        if pinned is not None:
            sql += " AND pinned_to_dashboard=?";             args.append(int(pinned))
        if is_mistake is not None:
            sql += " AND is_mistake=?";                      args.append(int(is_mistake))
        if is_exam_revision is not None:
            sql += " AND is_exam_revision=?";                args.append(int(is_exam_revision))
        if q:
            ql = q.lower()
            sql += " AND (lower(title) LIKE ? OR lower(content) LIKE ? OR lower(coalesce(linked_label,'')) LIKE ?)"
            args += ["%" + ql + "%", "%" + ql + "%", "%" + ql + "%"]
        sql += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        args += [limit, offset]
        rows = c.execute(sql, args).fetchall()
        return [dict(r) for r in rows]


def get_note(note_id: int, user_id: str):
    """Return a single note row, checking ownership."""
    if _USE_SUPABASE:
        try:
            r = (_client().table("notes")
                 .select("*")
                 .eq("id", note_id)
                 .eq("user_id", user_id)
                 .single()
                 .execute())
            return r.data
        except Exception:
            return None
    with _local() as c:
        row = c.execute("SELECT * FROM notes WHERE id=? AND user_id=?",
                        (note_id, user_id)).fetchone()
        return dict(row) if row else None


def update_note(note_id: int, user_id: str, payload: dict):
    """Update allowed note fields and bump updated_at."""
    import json
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    allowed = {"title", "content", "color", "tags_json", "pinned_to_dashboard",
               "syllabus", "linked_type", "linked_id", "linked_label", "type",
               "location_json", "is_mistake", "is_exam_revision"}
    updates = {k: v for k, v in payload.items() if k in allowed}
    updates["updated_at"] = now
    if _USE_SUPABASE:
        r = (_client().table("notes")
             .update(updates)
             .eq("id", note_id)
             .eq("user_id", user_id)
             .execute())
        return r.data[0] if r.data else None
    # SQLite: serialise location_json if it's a dict
    if "location_json" in updates and isinstance(updates["location_json"], dict):
        updates["location_json"] = json.dumps(updates["location_json"])
    with _local() as c:
        sets = ", ".join(k + "=?" for k in updates)
        vals = list(updates.values()) + [note_id, user_id]
        c.execute("UPDATE notes SET " + sets + " WHERE id=? AND user_id=?", vals)
        c.commit()
        row = c.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
        return dict(row) if row else None


def delete_note(note_id: int, user_id: str) -> bool:
    """Delete a note. Returns True if a row was deleted."""
    if _USE_SUPABASE:
        r = (_client().table("notes")
             .delete()
             .eq("id", note_id)
             .eq("user_id", user_id)
             .execute())
        return len(r.data) > 0
    with _local() as c:
        cur = c.execute("DELETE FROM notes WHERE id=? AND user_id=?", (note_id, user_id))
        c.commit()
        return cur.rowcount > 0


def pin_note(note_id: int, user_id: str, pinned: bool):
    """Set pinned_to_dashboard for a note. Returns updated row."""
    return update_note(note_id, user_id, {"pinned_to_dashboard": pinned})


def get_pinned_notes(user_id: str, limit: int = 3) -> list:
    """Return up to limit pinned notes for the dashboard widget."""
    if _USE_SUPABASE:
        r = (_client().table("notes")
             .select("*")
             .eq("user_id", user_id)
             .eq("pinned_to_dashboard", True)
             .order("updated_at", desc=True)
             .limit(limit)
             .execute())
        return r.data or []
    with _local() as c:
        rows = c.execute(
            "SELECT * FROM notes WHERE user_id=? AND pinned_to_dashboard=1 "
            "ORDER BY updated_at DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]


# ── Gamification stats (XP, streak, badges) ───────────────────────────────────

def get_user_stats(user_id: str) -> dict | None:
    if _USE_SUPABASE:
        r = (_client().table("user_stats")
             .select("*")
             .eq("user_id", user_id)
             .limit(1)
             .execute())
        return r.data[0] if r.data else None
    with _local() as c:
        row = c.execute("SELECT * FROM user_stats WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None


def upsert_user_stats(user_id: str, payload: dict) -> None:
    import json
    now = _now()
    if _USE_SUPABASE:
        data = {
            "user_id":    user_id,
            "xp_total":   int(payload.get("xp_total", 0)),
            "xp_log":     payload.get("xp_log", []),
            "streak":     int(payload.get("streak", 0)),
            "streak_max": int(payload.get("streak_max", 0)),
            "badges":     payload.get("badges", []),
            "focus":      payload.get("focus", {}),
            "missions":   payload.get("missions", {}),
            "updated_at": now,
        }
        (_client().table("user_stats")
         .upsert(data, on_conflict="user_id")
         .execute())
    else:
        with _local() as c:
            c.execute(
                """INSERT INTO user_stats
                   (user_id, xp_total, xp_log, streak, streak_max,
                    badges, focus, missions, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id) DO UPDATE SET
                   xp_total=excluded.xp_total, xp_log=excluded.xp_log,
                   streak=excluded.streak,      streak_max=excluded.streak_max,
                   badges=excluded.badges,      focus=excluded.focus,
                   missions=excluded.missions,  updated_at=excluded.updated_at""",
                (user_id,
                 int(payload.get("xp_total", 0)),
                 json.dumps(payload.get("xp_log", [])),
                 int(payload.get("streak", 0)),
                 int(payload.get("streak_max", 0)),
                 json.dumps(payload.get("badges", [])),
                 json.dumps(payload.get("focus", {})),
                 json.dumps(payload.get("missions", {})),
                 now)
            )
            c.commit()


# ── Password reset tokens ─────────────────────────────────────────────────────

def create_reset_token(user_id: str, token: str, expires_at: str) -> None:
    now = _now()
    if _USE_SUPABASE:
        _client().table("password_reset_tokens").delete().eq("user_id", user_id).execute()
        _client().table("password_reset_tokens").insert({
            "token": token, "user_id": user_id,
            "expires_at": expires_at, "created_at": now,
        }).execute()
    else:
        with _local() as c:
            c.execute("DELETE FROM password_reset_tokens WHERE user_id=?", (user_id,))
            c.execute(
                "INSERT INTO password_reset_tokens (token, user_id, expires_at, created_at) "
                "VALUES (?, ?, ?, ?)",
                (token, user_id, expires_at, now)
            )
            c.commit()


def get_reset_token(token: str) -> dict | None:
    if _USE_SUPABASE:
        r = (_client().table("password_reset_tokens")
             .select("*")
             .eq("token", token)
             .limit(1)
             .execute())
        return r.data[0] if r.data else None
    with _local() as c:
        row = c.execute(
            "SELECT * FROM password_reset_tokens WHERE token=?", (token,)
        ).fetchone()
        return dict(row) if row else None


def delete_reset_token(token: str) -> None:
    if _USE_SUPABASE:
        _client().table("password_reset_tokens").delete().eq("token", token).execute()
    else:
        with _local() as c:
            c.execute("DELETE FROM password_reset_tokens WHERE token=?", (token,))
            c.commit()


def update_password(user_id: str, password_hash: str) -> None:
    now = _now()
    if _USE_SUPABASE:
        (_client().table("profiles")
         .update({"password_hash": password_hash, "updated_at": now})
         .eq("id", user_id)
         .execute())
    else:
        with _local() as c:
            c.execute(
                "UPDATE profiles SET password_hash=?, updated_at=? WHERE id=?",
                (password_hash, now, user_id)
            )
            c.commit()



# ── Admin console v2: audit log, saved views, admin notes ────────────────────

def fetch_all(table: str, columns: str = "*", eq: dict | None = None,
              order: str | None = None, desc: bool = False,
              gte: tuple[str, str] | None = None) -> list[dict]:
    """Every matching row. On Supabase this pages in 1000-row blocks: PostgREST
    silently caps an unpaged select at 1000 rows, which truncated counts."""
    eq = eq or {}
    if _USE_SUPABASE:
        out: list[dict] = []
        step, start = 1000, 0
        while True:
            q = _client().table(table).select(columns)
            for k, v in eq.items():
                q = q.eq(k, v)
            if gte:
                q = q.gte(gte[0], gte[1])
            if order:
                q = q.order(order, desc=desc)
            rows = q.range(start, start + step - 1).execute().data or []
            out.extend(rows)
            if len(rows) < step:
                return out
            start += step
    if not re.fullmatch(r"[a-z_]+", table) or not re.fullmatch(r"[a-z_,* ]+", columns):
        raise ValueError("bad table or column list")
    sql = f"SELECT {columns} FROM {table}"
    wheres, vals = [], []
    for k, v in eq.items():
        if not re.fullmatch(r"[a-z_]+", k):
            raise ValueError("bad column")
        wheres.append(f"{k}=?"); vals.append(v)
    if gte:
        if not re.fullmatch(r"[a-z_]+", gte[0]):
            raise ValueError("bad column")
        wheres.append(f"{gte[0]}>=?"); vals.append(gte[1])
    if wheres:
        sql += " WHERE " + " AND ".join(wheres)
    if order:
        if not re.fullmatch(r"[a-z_]+", order):
            raise ValueError("bad column")
        sql += f" ORDER BY {order}{' DESC' if desc else ''}"
    with _local() as c:
        return [dict(r) for r in c.execute(sql, vals)]


def add_admin_audit(row: dict) -> None:
    _insert("admin_audit", row, ["admin_id", "admin_email", "via", "action", "target",
                                 "details_json", "ok", "created_at"])


def list_admin_audit(limit: int = 100, offset: int = 0) -> list[dict]:
    if _USE_SUPABASE:
        r = (_client().table("admin_audit").select("*")
             .order("created_at", desc=True).range(offset, offset + limit - 1).execute())
        return r.data or []
    with _local() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM admin_audit ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (limit, offset))]


def list_admin_views(section: str) -> list[dict]:
    return fetch_all("admin_views", eq={"section": section}, order="created_at")


def create_admin_view(admin_id: str | None, section: str, name: str, params_json: str) -> dict:
    return _insert("admin_views", {"admin_id": admin_id, "section": section, "name": name,
                                   "params_json": params_json, "created_at": _now()},
                   ["admin_id", "section", "name", "params_json", "created_at"])


def delete_admin_view(view_id: int) -> int:
    if _USE_SUPABASE:
        return len(_client().table("admin_views").delete().eq("id", view_id).execute().data or [])
    with _local() as c:
        n = c.execute("DELETE FROM admin_views WHERE id=?", (view_id,)).rowcount
        c.commit()
        return n


def list_admin_notes(student_id: str) -> list[dict]:
    return fetch_all("admin_notes", eq={"student_id": student_id}, order="created_at", desc=True)


def add_admin_note(student_id: str, admin: dict, body: str) -> dict:
    return _insert("admin_notes", {"student_id": student_id, "admin_id": admin.get("id"),
                                   "admin_name": admin.get("name") or admin.get("email"),
                                   "body": body, "created_at": _now()},
                   ["student_id", "admin_id", "admin_name", "body", "created_at"])


def delete_admin_note(note_id: int, student_id: str) -> int:
    if _USE_SUPABASE:
        r = (_client().table("admin_notes").delete().eq("id", note_id)
             .eq("student_id", student_id).execute())
        return len(r.data or [])
    with _local() as c:
        n = c.execute("DELETE FROM admin_notes WHERE id=? AND student_id=?",
                      (note_id, student_id)).rowcount
        c.commit()
        return n


def touch_last_seen(user_id: str) -> None:
    """Cheap presence stamp from the time-spent beacon (real 'last active')."""
    now = _now()
    if _USE_SUPABASE:
        _client().table("profiles").update({"last_seen_at": now}).eq("id", user_id).execute()
        return
    with _local() as c:
        c.execute("UPDATE profiles SET last_seen_at=? WHERE id=?", (now, user_id))
        c.commit()



# ── Admin inbox status (one row per handled form submission) ─────────────────

def list_inbox_status() -> dict[tuple[str, str], dict]:
    return {(r["source"], str(r["item_id"])): r for r in fetch_all("inbox_status")}


def upsert_inbox_status(source: str, item_id: str, fields: dict) -> dict:
    row = {"source": source, "item_id": str(item_id), "updated_at": _now(), **fields}
    if _USE_SUPABASE:
        _client().table("inbox_status").upsert(row, on_conflict="source,item_id").execute()
    else:
        cols = list(row)
        with _local() as c:
            c.execute(f"INSERT INTO inbox_status ({','.join(cols)}) VALUES ({','.join('?' * len(cols))}) "
                      f"ON CONFLICT(source, item_id) DO UPDATE SET "
                      + ", ".join(f"{k}=excluded.{k}" for k in cols if k not in ("source", "item_id")),
                      [row[k] for k in cols])
            c.commit()
    return list_inbox_status().get((source, str(item_id)), row)


# ── Newsletter broadcasts (sent in the background, logged per recipient) ─────

_BROADCAST_COLS = ["subject", "body_markdown", "cta_label", "cta_url", "status", "scheduled_at",
                   "total", "sent", "failed", "created_by", "created_at", "started_at",
                   "finished_at", "error", "worker", "heartbeat_at"]


def claim_broadcast(bid: int, worker: str, stale_before: str) -> bool:
    """Atomically take a broadcast to send: queued, or 'sending' with a dead
    heartbeat (its worker crashed). Several web workers each run the scheduler;
    only the one whose UPDATE matched may send, so nobody gets it twice."""
    now = _now()
    fields = {"status": "sending", "worker": worker, "heartbeat_at": now}
    if _USE_SUPABASE:
        r = (_client().table("newsletter_broadcasts").update(fields)
             .eq("id", bid).eq("status", "queued").execute())
        if r.data:
            return True
        r = (_client().table("newsletter_broadcasts").update(fields)
             .eq("id", bid).eq("status", "sending").lt("heartbeat_at", stale_before).execute())
        return bool(r.data)
    with _local() as c:
        n = c.execute("UPDATE newsletter_broadcasts SET status='sending', worker=?, heartbeat_at=? "
                      "WHERE id=? AND (status='queued' OR (status='sending' AND "
                      "(heartbeat_at IS NULL OR heartbeat_at < ?)))",
                      (worker, now, bid, stale_before)).rowcount
        c.commit()
        return n == 1


def create_broadcast(fields: dict) -> dict:
    fields.setdefault("created_at", _now())
    fields.setdefault("status", "queued")
    return _insert("newsletter_broadcasts", fields, _BROADCAST_COLS)


def get_broadcast(bid: int) -> dict | None:
    rows = fetch_all("newsletter_broadcasts", eq={"id": bid})
    return rows[0] if rows else None


def list_broadcasts() -> list[dict]:
    return fetch_all("newsletter_broadcasts", order="created_at", desc=True)


def update_broadcast(bid: int, fields: dict) -> None:
    if _USE_SUPABASE:
        _client().table("newsletter_broadcasts").update(fields).eq("id", bid).execute()
        return
    with _local() as c:
        c.execute(f"UPDATE newsletter_broadcasts SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?",
                  (*fields.values(), bid))
        c.commit()


def broadcast_sent_emails(bid: int) -> set[str]:
    return {r["email"] for r in fetch_all("newsletter_sends", "email", eq={"broadcast_id": bid})}


def log_broadcast_send(bid: int, email: str, ok: bool, error: str | None = None) -> None:
    row = {"broadcast_id": bid, "email": email, "ok": 1 if ok else 0, "error": error, "sent_at": _now()}
    if _USE_SUPABASE:
        _client().table("newsletter_sends").upsert(row, on_conflict="broadcast_id,email").execute()
        return
    with _local() as c:
        c.execute("INSERT OR REPLACE INTO newsletter_sends (broadcast_id,email,ok,error,sent_at) "
                  "VALUES (?,?,?,?,?)", (bid, email, row["ok"], error, row["sent_at"]))
        c.commit()
