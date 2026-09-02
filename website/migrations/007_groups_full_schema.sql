-- Migration 007: complete groups / group_sessions schema
-- The original schema only had minimal columns; the app code expects these extras.
-- Safe to run more than once (all statements are idempotent).
-- Apply in the Supabase SQL editor or via psql.

-- ── groups: add missing columns ──────────────────────────────────────────────
ALTER TABLE groups ADD COLUMN IF NOT EXISTS description  TEXT;
ALTER TABLE groups ADD COLUMN IF NOT EXISTS max_students INTEGER NOT NULL DEFAULT 6;
ALTER TABLE groups ADD COLUMN IF NOT EXISTS schedule_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE groups ADD COLUMN IF NOT EXISTS status       TEXT NOT NULL DEFAULT 'draft';
ALTER TABLE groups ADD COLUMN IF NOT EXISTS updated_at   TEXT NOT NULL DEFAULT (now()::text);

-- ── group_sessions: fix column name + add status ──────────────────────────────
-- Rename 'date' → 'session_date' if the old column still exists
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='group_sessions' AND column_name='date'
  ) THEN
    ALTER TABLE group_sessions RENAME COLUMN date TO session_date;
  END IF;
END$$;

ALTER TABLE group_sessions ADD COLUMN IF NOT EXISTS session_date TEXT;
ALTER TABLE group_sessions ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'held';
