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
    answer          TEXT,
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

-- Cached AI worked solutions for MCQ questions. The prompt carries no student
-- answer, so one row is the correct explanation for every student who reaches
-- that question — the solver and the review PDF both read it instead of
-- paying for a fresh vision call. app.py creates this on demand too; it is
-- listed here so a fresh Supabase project starts with it.
--
-- Keyed on the Cambridge coordinates ('0625_s21_12_q07'), NOT questions.id:
-- re-segmenting a paper deletes and re-inserts its question rows with fresh
-- ids, so an id-keyed cache would eventually serve one question's worked
-- solution under another question's number. question_id is kept for debugging
-- only and carries no foreign key for the same reason.
CREATE TABLE IF NOT EXISTS mcq_explanations (
    q_key       TEXT PRIMARY KEY,
    question_id BIGINT,
    html        TEXT NOT NULL,
    provider    TEXT,
    created_at  TEXT NOT NULL DEFAULT (now()::text)
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
    status      TEXT DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
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

CREATE TABLE IF NOT EXISTS teacher_students (
    id           BIGSERIAL PRIMARY KEY,
    teacher_id   TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    student_id   TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    syllabus     TEXT NOT NULL,
    allocated_at TEXT NOT NULL DEFAULT (now()::text),
    status       TEXT NOT NULL DEFAULT 'active',
    UNIQUE(teacher_id, student_id, syllabus)
);

CREATE TABLE IF NOT EXISTS daily_time_spent (
    id          BIGSERIAL PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    date        DATE NOT NULL DEFAULT CURRENT_DATE,
    seconds     INTEGER NOT NULL DEFAULT 0,
    UNIQUE(user_id, date)
);

CREATE INDEX IF NOT EXISTS daily_time_spent_user_date ON daily_time_spent(user_id, date);

CREATE TABLE IF NOT EXISTS assignments (
    id                       BIGSERIAL PRIMARY KEY,
    user_id                  TEXT REFERENCES profiles(id) ON DELETE CASCADE,
    syllabus                 TEXT,
    kind                     TEXT DEFAULT 'homework',
    title                    TEXT NOT NULL,
    instructions             TEXT,
    topics_json              TEXT DEFAULT '[]',
    attachments_json         TEXT DEFAULT '[]',
    due_date                 TEXT,
    status                   TEXT DEFAULT 'assigned',
    student_note             TEXT,
    seen_at                  TEXT,
    completed_at             TEXT,
    student_submissions_json TEXT DEFAULT '[]',
    created_at               TEXT DEFAULT (now()::text),
    updated_at               TEXT DEFAULT (now()::text)
);

-- ── Blog posts (admin-authored, server-rendered for SEO) ───────────────────
-- Written in Markdown via the admin dashboard; served at /blog and /blog/{slug}
-- as full server-rendered HTML pages, so no client-side JS is needed for SEO.

CREATE TABLE IF NOT EXISTS blog_posts (
    id            BIGSERIAL PRIMARY KEY,
    title         TEXT NOT NULL,
    slug          TEXT UNIQUE NOT NULL,        -- URL path: /blog/{slug}
    excerpt       TEXT,                        -- shown on list page + meta description fallback
    body_markdown TEXT NOT NULL DEFAULT '',
    cover_url     TEXT,                        -- og:image + hero image
    author        TEXT NOT NULL DEFAULT 'Muhammad Taahaa',
    published     BOOLEAN NOT NULL DEFAULT FALSE,
    published_at  TEXT,                        -- ISO timestamp, set on first publish
    meta_title    TEXT,                        -- overrides <title> if set
    meta_desc     TEXT,                        -- overrides meta description if set
    created_at    TEXT NOT NULL DEFAULT (now()::text),
    updated_at    TEXT NOT NULL DEFAULT (now()::text)
);

-- ── Course catalog (admin-managed, SEO landing pages) ───────────────────────
-- Each row is one course offering. The admin panel creates / edits these;
-- /course.html?slug=<slug> fetches the row and renders a full course page.
-- teacher_id references teachers.id (nullable — course may have multiple tutors).

CREATE TABLE IF NOT EXISTS courses (
    id               BIGSERIAL PRIMARY KEY,
    syllabus_code    TEXT NOT NULL,              -- '4024', '0625' etc.
    slug             TEXT UNIQUE NOT NULL,        -- 'o-level-mathematics-4024'
    title            TEXT NOT NULL,              -- 'Mathematics D — O Level'
    level            TEXT NOT NULL,              -- 'O Level', 'IGCSE', 'A Level'
    subject          TEXT NOT NULL,              -- 'Mathematics', 'Physics', 'CS'
    tagline          TEXT,                       -- short italic blurb on card
    overview_html    TEXT,                       -- rich-text body for course page
    approach_html    TEXT,                       -- "How we teach" section
    what_you_get_json TEXT DEFAULT '[]',         -- JSON array of outcome strings
    teacher_id       BIGINT REFERENCES teachers(id) ON DELETE SET NULL,
    meta_title       TEXT,
    meta_description TEXT,
    published        BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order       INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL DEFAULT (now()::text),
    updated_at       TEXT NOT NULL DEFAULT (now()::text)
);

-- ── Missing columns on profiles (idempotent ALTER TABLE) ───────────────────
-- These columns are required by the app but were not in the original schema.
-- The DO $$ ... $$ blocks guard each ALTER so re-running is safe.

DO $$ BEGIN
  ALTER TABLE profiles ADD COLUMN IF NOT EXISTS plan            TEXT    NOT NULL DEFAULT 'free';
  ALTER TABLE profiles ADD COLUMN IF NOT EXISTS plan_expires_at  TEXT;
  ALTER TABLE profiles ADD COLUMN IF NOT EXISTS plan_started_at  TEXT;
  ALTER TABLE profiles ADD COLUMN IF NOT EXISTS plan_trial        INTEGER NOT NULL DEFAULT 0;
  ALTER TABLE profiles ADD COLUMN IF NOT EXISTS plan_subjects_json TEXT NOT NULL DEFAULT '[]';
  ALTER TABLE profiles ADD COLUMN IF NOT EXISTS role             TEXT    NOT NULL DEFAULT 'student';
  ALTER TABLE profiles ADD COLUMN IF NOT EXISTS flags_json      TEXT    NOT NULL DEFAULT '{}';
  ALTER TABLE profiles ADD COLUMN IF NOT EXISTS persona         TEXT;
  ALTER TABLE profiles ADD COLUMN IF NOT EXISTS student_code    TEXT    UNIQUE;
END $$;

-- ── Parent-student links ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS parent_student_links (
    id          BIGSERIAL PRIMARY KEY,
    parent_id   TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    student_id  TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL DEFAULT (now()::text),
    UNIQUE(parent_id, student_id)
);

-- ── Direct messages ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS messages (
    id           BIGSERIAL PRIMARY KEY,
    sender_id    TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    recipient_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    body         TEXT NOT NULL,
    read_at      TEXT,
    created_at   TEXT NOT NULL DEFAULT (now()::text)
);

CREATE INDEX IF NOT EXISTS messages_recipient_unread
    ON messages (recipient_id, read_at) WHERE read_at IS NULL;

-- ── Contact form submissions ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS contacts (
    id         BIGSERIAL PRIMARY KEY,
    name       TEXT,
    email      TEXT NOT NULL,
    subject    TEXT,
    message    TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (now()::text)
);

-- ── Newsletter subscribers ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS newsletter_subscribers (
    id            BIGSERIAL PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    subscribed_at TEXT NOT NULL DEFAULT (now()::text)
);

-- ── Flashcard / Study content system ────────────────────────────────────────
-- Stores structured CARD / DEF / FORMULA / LIST blocks parsed from
-- data/flashcards/*.md files. Completely separate from the pipeline tables.

CREATE TABLE IF NOT EXISTS fc_boards (
    id   BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,                -- "Cambridge O-Level", "Cambridge A-Level"
    code TEXT NOT NULL UNIQUE          -- "cambridge-ol", "cambridge-al"
);

CREATE TABLE IF NOT EXISTS fc_subjects (
    id             BIGSERIAL PRIMARY KEY,
    board_id       BIGINT NOT NULL REFERENCES fc_boards(id) ON DELETE CASCADE,
    name           TEXT NOT NULL,      -- "Physics", "Mathematics"
    code           TEXT NOT NULL UNIQUE, -- primary syllabus code e.g. "5054"
    level          TEXT,               -- "O-Level / IGCSE", "A-Level"
    alt_codes_json TEXT DEFAULT '[]'   -- JSON array of additional codes e.g. ["0625"]
);

CREATE TABLE IF NOT EXISTS fc_papers (
    id         BIGSERIAL PRIMARY KEY,
    subject_id BIGINT NOT NULL REFERENCES fc_subjects(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,           -- "Paper 1 · Theory", "Mechanics 1", "All"
    code       TEXT NOT NULL,           -- "P1", "M1", "ALL"
    UNIQUE(subject_id, code)
);

CREATE TABLE IF NOT EXISTS fc_chapters (
    id          BIGSERIAL PRIMARY KEY,
    paper_id    BIGINT NOT NULL REFERENCES fc_papers(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    order_index INTEGER NOT NULL DEFAULT 0,
    UNIQUE(paper_id, name)
);

-- payload_json is type-specific:
--   card:    {"question": "...", "answer": "..."}
--   def:     {"term": "...", "meaning": "...", "unit": "...", "context": "..."}
--   formula: {"name": "...", "equation": "...", "variables": "...", "notes": "...", "in_formula_booklet": null|true|false}
--   list:    {"title": "...", "list_type": "ordered|unordered", "items": ["..."]}
CREATE TABLE IF NOT EXISTS fc_blocks (
    id          BIGSERIAL PRIMARY KEY,
    chapter_id  BIGINT NOT NULL REFERENCES fc_chapters(id) ON DELETE CASCADE,
    type        TEXT NOT NULL,          -- 'card' | 'def' | 'formula' | 'list'
    topic_label TEXT,                   -- raw Topic: field from the source file
    payload_json TEXT NOT NULL DEFAULT '{}',
    source_hash TEXT,                   -- MD5 of (type, payload) for idempotent re-import
    created_at  TEXT NOT NULL DEFAULT (now()::text),
    UNIQUE (chapter_id, type, source_hash)
);

CREATE INDEX IF NOT EXISTS fc_blocks_chapter ON fc_blocks (chapter_id);
CREATE INDEX IF NOT EXISTS fc_blocks_type    ON fc_blocks (type, chapter_id);

-- Per-student, per-block spaced-repetition state.
-- Unique on (student_id, block_id) — upserted on every rating.
CREATE TABLE IF NOT EXISTS fc_card_progress (
    id               BIGSERIAL PRIMARY KEY,
    student_id       TEXT   NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    block_id         BIGINT NOT NULL REFERENCES fc_blocks(id) ON DELETE CASCADE,
    status           TEXT   NOT NULL DEFAULT 'new',  -- new|learning|review|mastered
    times_reviewed   INTEGER NOT NULL DEFAULT 0,
    times_correct    INTEGER NOT NULL DEFAULT 0,
    ease_factor      REAL    NOT NULL DEFAULT 2.5,
    interval_days    REAL    NOT NULL DEFAULT 0.0,
    next_review_at   TEXT,
    saved_for_review INTEGER NOT NULL DEFAULT 0,
    last_result      TEXT,             -- 'again'|'hard'|'good'|'easy'
    updated_at       TEXT NOT NULL DEFAULT (now()::text),
    UNIQUE(student_id, block_id)
);

CREATE INDEX IF NOT EXISTS fc_progress_due
    ON fc_card_progress (student_id, next_review_at)
    WHERE status != 'mastered';

-- Append-only log — never updated, only inserted. fc_card_progress is the
-- derived summary; this is the audit trail / analytics source.
CREATE TABLE IF NOT EXISTS fc_review_events (
    id          BIGSERIAL PRIMARY KEY,
    student_id  TEXT   NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    block_id    BIGINT NOT NULL REFERENCES fc_blocks(id) ON DELETE CASCADE,
    rating      TEXT   NOT NULL,       -- 'again'|'hard'|'good'|'easy'
    reviewed_at TEXT   NOT NULL DEFAULT (now()::text)
);

CREATE TABLE IF NOT EXISTS fc_study_sessions (
    id             BIGSERIAL PRIMARY KEY,
    student_id     TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    scope_json     TEXT,               -- JSON snapshot of the filter applied
    started_at     TEXT NOT NULL DEFAULT (now()::text),
    ended_at       TEXT,
    cards_reviewed INTEGER NOT NULL DEFAULT 0,
    cards_aced     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS fc_streaks (
    student_id       TEXT PRIMARY KEY REFERENCES profiles(id) ON DELETE CASCADE,
    current_streak   INTEGER NOT NULL DEFAULT 0,
    longest_streak   INTEGER NOT NULL DEFAULT 0,
    last_active_date TEXT                           -- ISO date "2026-08-26"
);

-- ── Subscription plans ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS subscriptions (
    id              BIGSERIAL PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    plan            TEXT NOT NULL,                  -- 'solo' | 'three' | 'all'
    started_at      TEXT NOT NULL DEFAULT (now()::text),
    expires_at      TEXT,
    auto_renew      BOOLEAN NOT NULL DEFAULT FALSE,
    status          TEXT NOT NULL DEFAULT 'active', -- 'active' | 'cancelled' | 'expired'
    created_at      TEXT NOT NULL DEFAULT (now()::text)
);

-- ── Payment proofs ──────────────────────────────────────────────────────────
-- user_id is TEXT (matches profiles.id, which is TEXT PRIMARY KEY).
-- If you previously created this table with user_id UUID, drop it first:
--   DROP TABLE IF EXISTS payment_proofs;
-- then re-run this file.

CREATE TABLE IF NOT EXISTS payment_proofs (
    id              BIGSERIAL PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    plan            TEXT NOT NULL,
    amount_pkr      INTEGER,
    method          TEXT,                           -- 'jazzcash' | 'easypaisa' | 'bank'
    transaction_id  TEXT,
    screenshot_url  TEXT,
    note            TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',-- 'pending' | 'approved' | 'rejected'
    reviewed_by     TEXT,
    reviewed_at     TEXT,
    reviewer_note   TEXT,
    subjects_json   TEXT,                           -- subjects a 'three' plan covers
    created_at      TEXT NOT NULL DEFAULT (now()::text)
);

-- ── Usage events (quota tracking) ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS usage_events (
    id          BIGSERIAL PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,
    syllabus    TEXT,
    created_at  TEXT NOT NULL DEFAULT (now()::text)
);

CREATE INDEX IF NOT EXISTS usage_events_user_month
    ON usage_events (user_id, event_type, created_at);

-- ── PDF annotations ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS pdf_annotations (
    id          BIGSERIAL PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    paper_key   TEXT NOT NULL,
    page_num    INTEGER NOT NULL,
    data_json   TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (now()::text),
    UNIQUE(user_id, paper_key, page_num)
);

-- ── Student paper progress ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS paper_progress (
    id              BIGSERIAL PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    paper_key       TEXT NOT NULL,
    question_number INTEGER NOT NULL,
    status          TEXT NOT NULL DEFAULT 'unseen', -- 'unseen' | 'attempted' | 'done'
    self_mark       INTEGER,
    updated_at      TEXT NOT NULL DEFAULT (now()::text),
    UNIQUE(user_id, paper_key, question_number)
);

-- ── Class log (teacher session notes) ───────────────────────────────────────

CREATE TABLE IF NOT EXISTS class_log (
    id          BIGSERIAL PRIMARY KEY,
    teacher_id  TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    student_id  TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    syllabus    TEXT NOT NULL,
    topic       TEXT,
    notes       TEXT,
    date        TEXT NOT NULL,
    duration_min INTEGER,
    created_at  TEXT NOT NULL DEFAULT (now()::text)
);

-- ── Groups (tutor groups / class cohorts) ────────────────────────────────────

CREATE TABLE IF NOT EXISTS groups (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    teacher_id  TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    syllabus    TEXT,
    created_at  TEXT NOT NULL DEFAULT (now()::text)
);

CREATE TABLE IF NOT EXISTS group_memberships (
    id          BIGSERIAL PRIMARY KEY,
    group_id    BIGINT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    student_id  TEXT   NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    joined_at   TEXT NOT NULL DEFAULT (now()::text),
    UNIQUE(group_id, student_id)
);

CREATE TABLE IF NOT EXISTS group_sessions (
    id          BIGSERIAL PRIMARY KEY,
    group_id    BIGINT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    topic       TEXT,
    notes       TEXT,
    date        TEXT NOT NULL,
    duration_min INTEGER,
    created_at  TEXT NOT NULL DEFAULT (now()::text)
);

CREATE TABLE IF NOT EXISTS grade_thresholds (
    id          BIGSERIAL PRIMARY KEY,
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
CREATE INDEX IF NOT EXISTS idx_grade_thresholds_lookup ON grade_thresholds(syllabus, year, session, paper, variant);

-- ── Student personal notes ────────────────────────────────────────────────────
-- Jot-down notes, sticky notes, context-linked captures while solving papers,
-- reviewing flashcards, or chatting with the AI Tutor.
-- Distinct from resources.html (file-based study materials uploaded by staff).

CREATE TABLE IF NOT EXISTS notes (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    type                TEXT NOT NULL DEFAULT 'text',  -- 'text' | 'sticky'
    title               TEXT,
    content             TEXT,           -- plain text / markdown bullets
    color               TEXT,           -- sticky: 'yellow'|'pink'|'blue'|'green'|'purple'
    linked_type         TEXT,           -- 'paper'|'flashcard_block'|'chapter'|'tutor_message'|NULL
    linked_id           TEXT,           -- the linked row's id / key
    linked_label        TEXT,           -- human-readable label stored at write time
    syllabus            TEXT,           -- syllabus code for scoped filtering
    tags_json           TEXT NOT NULL DEFAULT '[]',
    pinned_to_dashboard BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_notes_user   ON notes(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_notes_linked ON notes(linked_type, linked_id);
CREATE INDEX IF NOT EXISTS idx_notes_pinned ON notes(user_id, pinned_to_dashboard) WHERE pinned_to_dashboard = TRUE;

-- ── Gamification stats (XP, streak, badges — cross-device sync) ────────────

CREATE TABLE IF NOT EXISTS user_stats (
    user_id    TEXT PRIMARY KEY REFERENCES profiles(id) ON DELETE CASCADE,
    xp_total   INTEGER NOT NULL DEFAULT 0,
    xp_log     JSONB NOT NULL DEFAULT '[]',
    streak     INTEGER NOT NULL DEFAULT 0,
    streak_max INTEGER NOT NULL DEFAULT 0,
    badges     JSONB NOT NULL DEFAULT '[]',
    focus      JSONB NOT NULL DEFAULT '{}',
    missions   JSONB NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT (now()::text)
);

-- ── Password reset tokens ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    token      TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (now()::text)
);

-- ── Automated email log (prevents duplicate campaign sends) ───────────────────

CREATE TABLE IF NOT EXISTS email_log (
    id          BIGSERIAL PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    template_id TEXT NOT NULL,   -- e.g. 'W1', 'R1', 'F1'
    sent_at     TEXT NOT NULL DEFAULT (now()::text)
);

-- No unique constraint — the Python side handles dedup windows per template type.
-- Index makes the "was this sent recently?" lookup fast.
CREATE INDEX IF NOT EXISTS email_log_user_template
    ON email_log (user_id, template_id, sent_at);

-- ── Admin console v2 (migration 025) ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS admin_audit (
    id           BIGSERIAL PRIMARY KEY,
    admin_id     TEXT,
    admin_email  TEXT,
    via          TEXT,                 -- 'session' | 'key'
    action       TEXT NOT NULL,        -- e.g. 'PATCH /api/admin/students/{user_id}/plan'
    target       TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    ok           INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL DEFAULT (now()::text)
);
CREATE INDEX IF NOT EXISTS admin_audit_created ON admin_audit (created_at);

CREATE TABLE IF NOT EXISTS admin_views (
    id          BIGSERIAL PRIMARY KEY,
    admin_id    TEXT,
    section     TEXT NOT NULL,
    name        TEXT NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (now()::text)
);

CREATE TABLE IF NOT EXISTS admin_notes (
    id          BIGSERIAL PRIMARY KEY,
    student_id  TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    admin_id    TEXT,
    admin_name  TEXT,
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (now()::text)
);
CREATE INDEX IF NOT EXISTS admin_notes_student ON admin_notes (student_id, created_at);

ALTER TABLE profiles ADD COLUMN IF NOT EXISTS last_seen_at TEXT;

-- Phase 3: payments record the billing period, the amount the plan costs and a
-- fingerprint of the screenshot (duplicate detection).
ALTER TABLE payment_proofs ADD COLUMN IF NOT EXISTS period TEXT;
ALTER TABLE payment_proofs ADD COLUMN IF NOT EXISTS expected_pkr INTEGER;
ALTER TABLE payment_proofs ADD COLUMN IF NOT EXISTS screenshot_sha256 TEXT;

-- One status row per handled form submission (demo request, contact, feedback,
-- subject request) - the admin Inbox.
CREATE TABLE IF NOT EXISTS inbox_status (
    source       TEXT NOT NULL,          -- lead | contact | feedback | request
    item_id      TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'new',
    handled_by   TEXT,
    note         TEXT,
    replies_json TEXT NOT NULL DEFAULT '[]',
    updated_at   TEXT NOT NULL DEFAULT (now()::text),
    PRIMARY KEY (source, item_id)
);

-- Newsletter broadcasts are a background job, logged per recipient.
CREATE TABLE IF NOT EXISTS newsletter_broadcasts (
    id            BIGSERIAL PRIMARY KEY,
    subject       TEXT NOT NULL,
    body_markdown TEXT NOT NULL,
    cta_label     TEXT,
    cta_url       TEXT,
    status        TEXT NOT NULL DEFAULT 'queued',   -- queued|sending|sent|failed|cancelled
    scheduled_at  TEXT,
    total         INTEGER NOT NULL DEFAULT 0,
    sent          INTEGER NOT NULL DEFAULT 0,
    failed        INTEGER NOT NULL DEFAULT 0,
    created_by    TEXT,
    created_at    TEXT NOT NULL DEFAULT (now()::text),
    started_at    TEXT,
    finished_at   TEXT,
    error         TEXT,
    worker        TEXT,
    heartbeat_at  TEXT
);
CREATE TABLE IF NOT EXISTS newsletter_sends (
    id           BIGSERIAL PRIMARY KEY,
    broadcast_id BIGINT NOT NULL REFERENCES newsletter_broadcasts(id) ON DELETE CASCADE,
    email        TEXT NOT NULL,
    ok           INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    sent_at      TEXT NOT NULL DEFAULT (now()::text),
    UNIQUE (broadcast_id, email)
);

-- Phase 4: blog scheduling + FAQ + keywords + revision history; course FAQ.
-- (blog.ensure_table also adds these on start-up; listed here so the schema is
-- complete before the code arrives.)
ALTER TABLE blog_posts ADD COLUMN IF NOT EXISTS publish_at TEXT;
ALTER TABLE blog_posts ADD COLUMN IF NOT EXISTS faq_json TEXT;
ALTER TABLE blog_posts ADD COLUMN IF NOT EXISTS keywords TEXT;
CREATE TABLE IF NOT EXISTS blog_revisions (
    id            BIGSERIAL PRIMARY KEY,
    post_id       BIGINT NOT NULL,
    title         TEXT,
    body_markdown TEXT,
    excerpt       TEXT,
    meta_title    TEXT,
    meta_desc     TEXT,
    source        TEXT,                 -- 'manual' | 'ai:<provider:model>' | 'restore'
    created_by    TEXT,
    created_at    TEXT NOT NULL DEFAULT (now()::text)
);
ALTER TABLE courses ADD COLUMN IF NOT EXISTS faq_json TEXT;
