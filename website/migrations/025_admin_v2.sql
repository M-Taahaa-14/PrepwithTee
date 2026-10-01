-- 025: admin console v2 (2026-10-01). Run on Supabase BEFORE deploying the code.
-- Phase 1 fixes:
-- The admin's review note used to overwrite the student's own note on the proof.
ALTER TABLE payment_proofs ADD COLUMN IF NOT EXISTS reviewer_note TEXT;

-- "3 Subjects" plan is enforced (tutor, 2026-10-01): the plan covers exactly the
-- subjects the student picked when paying; every other subject gets free limits.
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS plan_subjects_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE payment_proofs ADD COLUMN IF NOT EXISTS subjects_json TEXT;
-- Usage is recorded per subject, so the free allowance for subjects outside the
-- plan only counts usage in those subjects.
ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS syllabus TEXT;

-- Phase 2: admin sign-in is the site session with role='admin'; every change is
-- recorded; saved table views; private admin notes on a student; real last-seen.
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
