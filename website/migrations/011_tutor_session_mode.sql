-- migrations/011_tutor_session_mode.sql

-- Add mode column to tutor_sessions table for Supabase Postgres
ALTER TABLE tutor_sessions ADD COLUMN IF NOT EXISTS mode TEXT DEFAULT 'normal';
