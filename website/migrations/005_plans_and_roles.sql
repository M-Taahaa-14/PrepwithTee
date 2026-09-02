-- Migration 005: subscription plans, roles, usage quotas
-- Run in Supabase Dashboard → SQL Editor

-- ── profiles: plan + role ────────────────────────────────────────────────────

ALTER TABLE profiles ADD COLUMN IF NOT EXISTS plan
    TEXT NOT NULL DEFAULT 'free';
-- valid: 'free' | 'pro' | 'premium' | 'tutoring'

ALTER TABLE profiles ADD COLUMN IF NOT EXISTS plan_expires_at
    TEXT;
-- ISO-8601 timestamp; NULL = no expiry (lifetime or manually managed)

ALTER TABLE profiles ADD COLUMN IF NOT EXISTS role
    TEXT NOT NULL DEFAULT 'student';
-- valid: 'student' | 'teacher' | 'admin'

-- ── usage_events: monthly quota tracking ─────────────────────────────────────

CREATE TABLE IF NOT EXISTS usage_events (
    id          BIGSERIAL PRIMARY KEY,
    user_id     TEXT REFERENCES profiles(id) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,
    -- 'topical_paper' | 'yearly_paper' | 'ai_tutor' | 'ai_quiz' | 'topic_test'
    created_at  TEXT NOT NULL DEFAULT (now()::text)
);

CREATE INDEX IF NOT EXISTS usage_events_user_month
    ON usage_events(user_id, event_type, created_at);

-- ── teachers: link to a real profiles row ────────────────────────────────────
-- (Phase 2 prerequisite — safe to add now)

ALTER TABLE teachers ADD COLUMN IF NOT EXISTS profile_id
    TEXT REFERENCES profiles(id);

ALTER TABLE teachers ADD COLUMN IF NOT EXISTS status
    TEXT NOT NULL DEFAULT 'approved';
-- existing rows remain 'approved'; new applicants start 'pending'

-- ── teacher_students: allocation table (Phase 3) ─────────────────────────────

CREATE TABLE IF NOT EXISTS teacher_students (
    id           BIGSERIAL PRIMARY KEY,
    teacher_id   TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    student_id   TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    syllabus     TEXT NOT NULL,
    allocated_at TEXT NOT NULL DEFAULT (now()::text),
    status       TEXT NOT NULL DEFAULT 'active',  -- 'active' | 'paused'
    UNIQUE(teacher_id, student_id, syllabus)
);

-- ── assignments: track which teacher created it (Phase 4) ────────────────────

ALTER TABLE assignments ADD COLUMN IF NOT EXISTS assigned_by
    TEXT REFERENCES profiles(id);
-- NULL = created via legacy ADMIN_KEY flow (backward-compatible)

-- ── pdf_annotations: per-user annotation state (Phase 5) ────────────────────

CREATE TABLE IF NOT EXISTS pdf_annotations (
    id            BIGSERIAL PRIMARY KEY,
    user_id       TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    paper_id      BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    assignment_id BIGINT,
    -- NULL = self-study annotation; set = tied to a specific homework submission
    data          TEXT NOT NULL DEFAULT '{}',
    -- JSON: Fabric.js canvas state keyed by page index e.g. {"0": {...}, "1": {...}}
    created_at    TEXT NOT NULL DEFAULT (now()::text),
    updated_at    TEXT NOT NULL DEFAULT (now()::text),
    UNIQUE(user_id, paper_id, assignment_id)
);
