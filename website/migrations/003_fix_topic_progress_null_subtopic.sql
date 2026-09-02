-- Fix: chapter-level topic_progress rows never de-duplicated.
--
-- topic_progress has UNIQUE (user_id, syllabus, topic, subtopic), but a
-- chapter-level row stores subtopic = NULL, and in both Postgres and SQLite a
-- NULL is never equal to another NULL — so the constraint never fires for
-- chapter rows and every save INSERTed instead of UPDATEing.
--
-- Effects seen in production before this fix:
--   * one student had 5 rows for (0580, "Arithematics", NULL), each a different
--     status, so which one "won" on read was arbitrary;
--   * get_progress_summary() counts rows, so the dashboard rings divided by an
--     inflated total and under-reported real progress.
--
-- The portable fix is to store '' rather than NULL for a chapter-level row:
-- Postgres 15+ could use UNIQUE NULLS NOT DISTINCT, but SQLite (the local
-- fallback) has no equivalent, and keeping one code path across both backends
-- is what users_db.py is built around. users_db now writes '' and maps it back
-- to None on read, so nothing above the data layer changes.
--
-- Apply with:
--   psql "$DATABASE_URL" -f website/migrations/003_fix_topic_progress_null_subtopic.sql

BEGIN;

-- 1. Collapse existing duplicates, keeping the most recently updated row of
--    each group. updated_at is TEXT but ISO-8601, so it sorts correctly.
DELETE FROM topic_progress t
USING (
    SELECT id,
           ROW_NUMBER() OVER (
               PARTITION BY user_id, syllabus, topic, COALESCE(subtopic, '')
               ORDER BY updated_at DESC NULLS LAST, id DESC
           ) AS rn
    FROM topic_progress
) dup
WHERE t.id = dup.id AND dup.rn > 1;

-- 2. Normalise NULL -> '' so the UNIQUE constraint can actually see them.
UPDATE topic_progress SET subtopic = '' WHERE subtopic IS NULL;

-- 3. Make the invariant permanent.
ALTER TABLE topic_progress ALTER COLUMN subtopic SET DEFAULT '';
ALTER TABLE topic_progress ALTER COLUMN subtopic SET NOT NULL;

COMMIT;
