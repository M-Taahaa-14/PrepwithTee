-- PrepWithTee — Supabase Postgres Schema
-- Run this entire file in: Supabase Dashboard → SQL Editor → New query → Run
-- Safe to re-run (CREATE TABLE IF NOT EXISTS everywhere).

-- ── Pipeline tables (migrated from data/index.db) ──────────────────────────

CREATE TABLE IF NOT EXISTS papers (
    id          BIGINT PRIMARY KEY,
    syllabus    TEXT    NOT NULL,
    year        INTEGER NOT NULL,
    session     TEXT    NOT NULL,
    paper       INTEGER NOT NULL,
    variant     TEXT    NOT NULL DEFAULT '',
    kind        TEXT    NOT NULL,
    filename    TEXT    NOT NULL,
    rel_path    TEXT    NOT NULL,
    page_count  INTEGER,
    fetched_at  TEXT,
    UNIQUE (syllabus, year, session, paper, variant, kind)
);

CREATE TABLE IF NOT EXISTS questions (
    id          BIGINT PRIMARY KEY,
    paper_id    BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    number      INTEGER NOT NULL,
    sub_part    TEXT    NOT NULL DEFAULT '',
    text        TEXT,
    marks       INTEGER,
    crop_path   TEXT,
    debug_png   TEXT,
    rects_json  TEXT,
    status      TEXT    NOT NULL DEFAULT 'segmented',
    UNIQUE (paper_id, number, sub_part)
);

CREATE TABLE IF NOT EXISTS classifications (
    question_id     BIGINT PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
    topic           TEXT NOT NULL,
    secondary_topic TEXT,
    subtopic        TEXT,
    difficulty      INTEGER,
    confidence      REAL NOT NULL,
    rationale       TEXT,
    backend         TEXT NOT NULL,
    classified_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ms_entries (
    id              BIGINT PRIMARY KEY,
    paper_id        BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    question_number INTEGER NOT NULL,
    sub_part        TEXT    NOT NULL DEFAULT '',
    crop_path       TEXT,
    rects_json      TEXT,
    UNIQUE (paper_id, question_number, sub_part)
);

CREATE TABLE IF NOT EXISTS review_queue (
    id          BIGINT PRIMARY KEY,
    question_id BIGINT REFERENCES questions(id) ON DELETE CASCADE,
    paper_id    BIGINT REFERENCES papers(id) ON DELETE CASCADE,
    reason      TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (now()::text),
    resolved    INTEGER NOT NULL DEFAULT 0
);

-- ── Student / user tables ───────────────────────────────────────────────────

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
    created_at       TEXT DEFAULT (now()::text),
    updated_at       TEXT DEFAULT (now()::text)
);

CREATE TABLE IF NOT EXISTS enrollments (
    id          BIGSERIAL PRIMARY KEY,
    user_id     TEXT REFERENCES profiles(id) ON DELETE CASCADE,
    syllabus    TEXT NOT NULL,
    enrolled_at TEXT DEFAULT (now()::text),
    status      TEXT DEFAULT 'active',
    UNIQUE(user_id, syllabus)
);

CREATE TABLE IF NOT EXISTS topic_progress (
    id            BIGSERIAL PRIMARY KEY,
    user_id       TEXT REFERENCES profiles(id) ON DELETE CASCADE,
    syllabus      TEXT NOT NULL,
    topic         TEXT NOT NULL,
    subtopic      TEXT,
    status        TEXT DEFAULT 'not_started',
    last_reviewed TEXT,
    updated_at    TEXT DEFAULT (now()::text),
    UNIQUE(user_id, syllabus, topic, subtopic)
);

CREATE TABLE IF NOT EXISTS quiz_sessions (
    id             BIGSERIAL PRIMARY KEY,
    user_id        TEXT REFERENCES profiles(id) ON DELETE CASCADE,
    syllabus       TEXT NOT NULL,
    topic          TEXT NOT NULL,
    subtopic       TEXT,
    question_text  TEXT NOT NULL,
    student_answer TEXT,
    score          INTEGER,
    ideal_answer   TEXT,
    feedback       TEXT,
    created_at     TEXT DEFAULT (now()::text)
);

CREATE TABLE IF NOT EXISTS teachers (
    id               BIGSERIAL PRIMARY KEY,
    name             TEXT NOT NULL,
    role             TEXT,
    subjects_json    TEXT NOT NULL DEFAULT '[]',
    bio              TEXT,
    picture_url      TEXT,
    qualifications   TEXT,
    experience_years INTEGER,
    display_order    INTEGER DEFAULT 0,
    active           BOOLEAN DEFAULT true
);

CREATE TABLE IF NOT EXISTS teacher_applications (
    id             BIGSERIAL PRIMARY KEY,
    name           TEXT,
    email          TEXT,
    phone          TEXT,
    subjects       TEXT,
    qualifications TEXT,
    experience     TEXT,
    message        TEXT,
    status         TEXT DEFAULT 'pending',
    created_at     TEXT DEFAULT (now()::text)
);

-- ── Runtime tables (form submissions) ──────────────────────────────────────

CREATE TABLE IF NOT EXISTS leads (
    id           BIGSERIAL PRIMARY KEY,
    parent_name  TEXT,
    student_name TEXT,
    contact      TEXT,
    grade        TEXT,
    subjects     TEXT,
    message      TEXT,
    timestamp    TEXT DEFAULT (now()::text)
);

CREATE TABLE IF NOT EXISTS feedback (
    id      BIGSERIAL PRIMARY KEY,
    rating  INTEGER,
    message TEXT,
    name    TEXT,
    page    TEXT,
    type    TEXT,
    ts      TEXT DEFAULT (now()::text)
);

CREATE TABLE IF NOT EXISTS subject_requests (
    id      BIGSERIAL PRIMARY KEY,
    subject TEXT,
    board   TEXT,
    message TEXT,
    ts      TEXT DEFAULT (now()::text)
);
