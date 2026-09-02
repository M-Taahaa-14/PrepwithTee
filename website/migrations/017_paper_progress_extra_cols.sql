-- migrations/017_paper_progress_extra_cols.sql
--
-- Four columns added to paper_progress via SQLite _safe_alters but never
-- migrated to Supabase Postgres.  Run once in the Supabase SQL editor.

ALTER TABLE paper_progress
    ADD COLUMN IF NOT EXISTS grade       TEXT,
    ADD COLUMN IF NOT EXISTS confidence  TEXT,
    ADD COLUMN IF NOT EXISTS attempts_json TEXT DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS synced      INTEGER DEFAULT 0;
