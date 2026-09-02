-- Migration 006: per-user onboarding / UI flags
-- Run in Supabase Dashboard → SQL Editor

ALTER TABLE profiles ADD COLUMN IF NOT EXISTS flags_json
    TEXT NOT NULL DEFAULT '{}';
-- JSON object storing onboarding state per user, e.g.
--   {"tour_dashboard": true, "tour_revise": true, "onboarding_dismissed": true}
-- Written via PATCH /api/flags; read back from the JWT fast-path field.
