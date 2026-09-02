-- Per-topic past-paper practice.
--
-- The yearly tracker (paper_progress) answers "which whole papers have I sat?".
-- This answers a different question the tutor asked for: "have I done the
-- past-paper questions for THIS chapter?" — which is the step after learning it.
--
-- A chapter is only really exam-ready when both are true:
--     status = 'confident'  (I understand it)
--   AND papers_status = 'confident'  (I've drilled its past-paper questions)
-- so the two live side by side on the same row rather than in a second table.
--
-- Apply with:
--   psql "$DATABASE_URL" -f website/migrations/004_topic_papers_status.sql

ALTER TABLE topic_progress
    ADD COLUMN IF NOT EXISTS papers_status TEXT NOT NULL DEFAULT 'not_started';

-- Timestamp kept separate from last_reviewed so the tutor can see when the
-- student last *practised* a chapter, not just when they last re-rated it.
ALTER TABLE topic_progress
    ADD COLUMN IF NOT EXISTS papers_updated_at TEXT;
