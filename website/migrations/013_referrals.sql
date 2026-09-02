-- website/migrations/013_referrals.sql
-- Referral system, points ledger, and verified study action tracking.

ALTER TABLE profiles ADD COLUMN IF NOT EXISTS referral_code TEXT UNIQUE;

CREATE TABLE IF NOT EXISTS referral_events (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  referrer_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  referee_id  TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  status      TEXT NOT NULL DEFAULT 'pending',  -- pending|rewarded
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(referee_id)
);

CREATE TABLE IF NOT EXISTS user_points (
  user_id    TEXT PRIMARY KEY REFERENCES profiles(id) ON DELETE CASCADE,
  points     INT NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS study_activities (
  id             BIGSERIAL PRIMARY KEY,
  user_id        TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  activity_type  TEXT NOT NULL, -- 'daily_study_30m' | 'topical_completed' | 'formulas_reviewed' | 'referral_bonus'
  points_awarded INT NOT NULL DEFAULT 0,
  details_json   TEXT DEFAULT '{}',
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_referral_events_referrer ON referral_events(referrer_id);
CREATE INDEX IF NOT EXISTS idx_study_activities_user ON study_activities(user_id, created_at DESC);
