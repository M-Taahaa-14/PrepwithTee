-- Grade threshold schema extensions
-- Run in Supabase Dashboard → SQL Editor after reviewing the seed files.
-- Safe to re-run (IF NOT EXISTS / DO $$ guards everywhere).

-- ── 1. Extend existing grade_thresholds ──────────────────────────────────────
-- 'board' is always 'CAIE' for our subjects; kept for completeness / future
-- use if non-Cambridge subjects are ever added.

DO $$ BEGIN
  ALTER TABLE grade_thresholds ADD COLUMN IF NOT EXISTS board    TEXT    NOT NULL DEFAULT 'CAIE';
  -- IGCSE subjects are graded A*–G; F and G are NULL for O Level and A Level.
  ALTER TABLE grade_thresholds ADD COLUMN IF NOT EXISTS grade_f  INTEGER;
  ALTER TABLE grade_thresholds ADD COLUMN IF NOT EXISTS grade_g  INTEGER;
END $$;

-- ── 2. Overall / option-level grade thresholds ───────────────────────────────
--
-- Cambridge grades are awarded on a "profile of component grades" model, but
-- the grade threshold document also publishes the TOTAL MARK (after any
-- weighting) that yields each overall grade for each combination of components
-- ("option").  This table stores those option-level thresholds so the grade
-- calculator can map a student's total weighted score to their predicted grade.
--
-- Components: a comma-separated string of 2-digit component codes, e.g.
--   '11,21,31'  means Component 11 + Component 21 + Component 31.
--   '50'        single-component option (e.g. 9702 AS coursework route).
--
-- is_as_level: TRUE for AS-only option codes (e.g. S1–S5 in 9702).
--   AS options never carry A* — grade_astar will always be NULL there.
--
-- UNIQUE key: a syllabus/year/session/option_code tuple is unique.
--   Option codes are reused across years (AX always means the same combination
--   for a given syllabus), so the year+session is part of the key.

CREATE TABLE IF NOT EXISTS grade_options (
    id            BIGSERIAL PRIMARY KEY,
    syllabus      TEXT    NOT NULL,
    subject       TEXT    NOT NULL,
    level         TEXT    NOT NULL,
    board         TEXT    NOT NULL DEFAULT 'CAIE',
    year          INTEGER NOT NULL,
    session       TEXT    NOT NULL,   -- 's' | 'w' | 'm'
    option_code   TEXT    NOT NULL,   -- 'AX', 'BY', 'S1', 'P1', etc.
    components    TEXT    NOT NULL,   -- '11,21,31'
    max_mark      INTEGER NOT NULL,   -- total after any weighting
    is_as_level   BOOLEAN NOT NULL DEFAULT FALSE,
    grade_astar   INTEGER,            -- NULL if not awarded (O Level, AS options)
    grade_a       INTEGER NOT NULL,
    grade_b       INTEGER NOT NULL,
    grade_c       INTEGER NOT NULL,
    grade_d       INTEGER NOT NULL,
    grade_e       INTEGER NOT NULL,
    grade_f       INTEGER,            -- IGCSE only
    grade_g       INTEGER,            -- IGCSE only
    status        TEXT    NOT NULL DEFAULT 'official',
    UNIQUE (syllabus, year, session, option_code)
);

CREATE INDEX IF NOT EXISTS idx_grade_options_lookup
    ON grade_options (syllabus, year, session);

-- ── 3. Student paper scores (for the score-tracking feature) ─────────────────
--
-- One row per paper component a student has sat.
--  paper_key    — ties back to the papers table ('5054_s25_22')
--  component    — 2-digit Cambridge component code matching grade_thresholds
--                 (e.g. '22' = paper 2, variant 2)
--  raw_mark     — the mark the student actually got
--  max_mark     — copied from grade_thresholds at insert time (for quick display)
--  component_grade — derived A/B/C/D/E for this component alone
--  option_code  — which overall option the student is sitting (e.g. 'AX'),
--                 used to sum marks and look up overall grade
--
-- The overall grade is NOT stored here: it is computed on-the-fly by summing
-- raw_marks for all components in the student's option and querying
-- grade_options.  This avoids stale data when thresholds are updated.

CREATE TABLE IF NOT EXISTS student_scores (
    id               BIGSERIAL PRIMARY KEY,
    user_id          TEXT    NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    syllabus         TEXT    NOT NULL,
    year             INTEGER NOT NULL,
    session          TEXT    NOT NULL,
    paper            INTEGER NOT NULL,   -- first digit of component code
    variant          TEXT    NOT NULL,   -- second digit of component code
    raw_mark         INTEGER NOT NULL,
    max_mark         INTEGER NOT NULL,
    component_grade  TEXT,               -- 'A'|'B'|'C'|'D'|'E'|'U' — computed
    option_code      TEXT,               -- 'AX', 'BY', … for overall calc
    notes            TEXT,               -- teacher/student notes
    recorded_at      TEXT    NOT NULL DEFAULT (now()::text),
    updated_at       TEXT    NOT NULL DEFAULT (now()::text),
    UNIQUE (user_id, syllabus, year, session, paper, variant)
);

CREATE INDEX IF NOT EXISTS idx_student_scores_user
    ON student_scores (user_id, syllabus, year, session);
