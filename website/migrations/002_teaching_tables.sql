-- PrepWithTee — teaching-side tables (paper tracker, class log, diary).
--
-- Mirrors _LOCAL_SCHEMA in website/users_db.py. Purely additive and idempotent:
-- safe to run more than once, and it touches nothing that already exists.
--
-- Apply with:
--   psql "$DATABASE_URL" -f website/migrations/002_teaching_tables.sql
-- or paste into the Supabase SQL editor.

-- ── 1. Past-paper practice tracker ──────────────────────────────────────────
-- Which whole past papers a student has worked through. Same three-state
-- vocabulary as topic_progress so the two read alike on the dashboard.
--
-- variant is NOT NULL DEFAULT '' rather than nullable: in Postgres a NULL never
-- equals another NULL, so a nullable column in the UNIQUE key would let
-- duplicate rows through for every paper that has no variant.
CREATE TABLE IF NOT EXISTS paper_progress (
    id         BIGSERIAL PRIMARY KEY,
    user_id    TEXT REFERENCES profiles(id) ON DELETE CASCADE,
    syllabus   TEXT    NOT NULL,
    year       INTEGER NOT NULL,
    session    TEXT    NOT NULL,
    paper      INTEGER NOT NULL,
    variant    TEXT    NOT NULL DEFAULT '',
    status     TEXT    DEFAULT 'not_started',
    score      INTEGER,
    max_score  INTEGER,
    note       TEXT,
    set_by     TEXT    DEFAULT 'student',
    updated_at TEXT    DEFAULT now()::text,
    CONSTRAINT paper_progress_unique
        UNIQUE (user_id, syllabus, year, session, paper, variant)
);

CREATE INDEX IF NOT EXISTS paper_progress_user_idx
    ON paper_progress (user_id, syllabus);

-- ── 2. Class log (per-student attendance calendar) ──────────────────────────
-- One row per lesson. The tutor owns it; the student sees it read-only.
CREATE TABLE IF NOT EXISTS class_log (
    id           BIGSERIAL PRIMARY KEY,
    user_id      TEXT REFERENCES profiles(id) ON DELETE CASCADE,
    class_date   TEXT NOT NULL,          -- YYYY-MM-DD
    start_time   TEXT,                   -- HH:MM
    duration_min INTEGER,
    syllabus     TEXT,
    status       TEXT DEFAULT 'held',    -- held|cancelled|missed|rescheduled
    topic        TEXT,
    note         TEXT,
    created_at   TEXT DEFAULT now()::text,
    updated_at   TEXT DEFAULT now()::text
);

CREATE INDEX IF NOT EXISTS class_log_user_date_idx
    ON class_log (user_id, class_date DESC);

-- ── 3. Assignments (the student diary) ──────────────────────────────────────
-- attachments_json is a list of
--   {"type":"upload",   "rel":"<file in data/uploads/homework>", "name":…}
--   {"type":"resource", "rel":"<file in data/resources>",        "name":…}
--   {"type":"booklet",  "params":{…/api/generate body…},          "name":…}
-- so one assignment can carry an uploaded worksheet, a notes PDF and a
-- generated topical booklet at once.
--
-- Stored as TEXT, not JSONB: users_db.py writes json.dumps() in both backends,
-- and the SQLite fallback has no JSON type. Keeping the column types identical
-- is what lets one code path serve both.
CREATE TABLE IF NOT EXISTS assignments (
    id               BIGSERIAL PRIMARY KEY,
    user_id          TEXT REFERENCES profiles(id) ON DELETE CASCADE,
    syllabus         TEXT,
    kind             TEXT DEFAULT 'homework',   -- homework|reading|practice|test
    title            TEXT NOT NULL,
    instructions     TEXT,
    topics_json      TEXT DEFAULT '[]',
    attachments_json TEXT DEFAULT '[]',
    due_date         TEXT,                      -- YYYY-MM-DD
    status           TEXT DEFAULT 'assigned',   -- assigned|done
    student_note     TEXT,
    seen_at          TEXT,
    completed_at     TEXT,
    created_at       TEXT DEFAULT now()::text,
    updated_at       TEXT DEFAULT now()::text
);

CREATE INDEX IF NOT EXISTS assignments_user_idx
    ON assignments (user_id, status);

-- ── Row-level security ──────────────────────────────────────────────────────
-- The app reaches Supabase with the service-role key, which bypasses RLS. These
-- tables are therefore only ever touched through the FastAPI layer, which does
-- its own ownership checks (_own_assignment / _student_or_404). Enabling RLS
-- with no policy keeps the anon key from reading them if it is ever exposed.
ALTER TABLE paper_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE class_log      ENABLE ROW LEVEL SECURITY;
ALTER TABLE assignments    ENABLE ROW LEVEL SECURITY;
