-- Migration 008: flashcard / study-recall system
-- All statements are idempotent (CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS).
-- Apply in the Supabase SQL editor or via psql.

-- ── Content taxonomy ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS fc_boards (
    id   BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    code TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS fc_subjects (
    id             BIGSERIAL PRIMARY KEY,
    board_id       BIGINT NOT NULL REFERENCES fc_boards(id) ON DELETE CASCADE,
    name           TEXT NOT NULL,
    code           TEXT NOT NULL UNIQUE,
    level          TEXT,
    alt_codes_json TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS fc_papers (
    id         BIGSERIAL PRIMARY KEY,
    subject_id BIGINT NOT NULL REFERENCES fc_subjects(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    code       TEXT NOT NULL,
    UNIQUE(subject_id, code)
);

CREATE TABLE IF NOT EXISTS fc_chapters (
    id          BIGSERIAL PRIMARY KEY,
    paper_id    BIGINT NOT NULL REFERENCES fc_papers(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    order_index INTEGER NOT NULL DEFAULT 0,
    UNIQUE(paper_id, name)
);

-- ── Content blocks ───────────────────────────────────────────────────────────
-- payload_json is type-specific:
--   card:    {"question": "...", "answer": "..."}
--   def:     {"term": "...", "meaning": "...", "unit": "...", "context": "..."}
--   formula: {"name": "...", "equation": "...", "variables": "...", "notes": "...", "in_formula_booklet": null|true|false}
--   list:    {"title": "...", "list_type": "ordered|unordered", "items": ["..."]}

CREATE TABLE IF NOT EXISTS fc_blocks (
    id           BIGSERIAL PRIMARY KEY,
    chapter_id   BIGINT NOT NULL REFERENCES fc_chapters(id) ON DELETE CASCADE,
    type         TEXT NOT NULL,
    topic_label  TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    source_hash  TEXT,
    created_at   TEXT NOT NULL DEFAULT (now()::text),
    UNIQUE (chapter_id, type, source_hash)
);

CREATE INDEX IF NOT EXISTS fc_blocks_chapter ON fc_blocks (chapter_id);
CREATE INDEX IF NOT EXISTS fc_blocks_type    ON fc_blocks (type, chapter_id);

-- ── Per-student spaced-repetition state ──────────────────────────────────────

CREATE TABLE IF NOT EXISTS fc_card_progress (
    id               BIGSERIAL PRIMARY KEY,
    student_id       TEXT    NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    block_id         BIGINT  NOT NULL REFERENCES fc_blocks(id) ON DELETE CASCADE,
    status           TEXT    NOT NULL DEFAULT 'new',
    times_reviewed   INTEGER NOT NULL DEFAULT 0,
    times_correct    INTEGER NOT NULL DEFAULT 0,
    ease_factor      REAL    NOT NULL DEFAULT 2.5,
    interval_days    REAL    NOT NULL DEFAULT 0.0,
    next_review_at   TEXT,
    saved_for_review INTEGER NOT NULL DEFAULT 0,
    last_result      TEXT,
    updated_at       TEXT    NOT NULL DEFAULT (now()::text),
    UNIQUE(student_id, block_id)
);

CREATE INDEX IF NOT EXISTS fc_progress_due
    ON fc_card_progress (student_id, next_review_at)
    WHERE status != 'mastered';

-- ── Append-only review log ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS fc_review_events (
    id          BIGSERIAL PRIMARY KEY,
    student_id  TEXT   NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    block_id    BIGINT NOT NULL REFERENCES fc_blocks(id) ON DELETE CASCADE,
    rating      TEXT   NOT NULL,
    reviewed_at TEXT   NOT NULL DEFAULT (now()::text)
);

-- ── Study sessions ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS fc_study_sessions (
    id             BIGSERIAL PRIMARY KEY,
    student_id     TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    scope_json     TEXT,
    started_at     TEXT NOT NULL DEFAULT (now()::text),
    ended_at       TEXT,
    cards_reviewed INTEGER NOT NULL DEFAULT 0,
    cards_aced     INTEGER NOT NULL DEFAULT 0
);

-- ── Streak tracking ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS fc_streaks (
    student_id       TEXT PRIMARY KEY REFERENCES profiles(id) ON DELETE CASCADE,
    current_streak   INTEGER NOT NULL DEFAULT 0,
    longest_streak   INTEGER NOT NULL DEFAULT 0,
    last_active_date TEXT
);
