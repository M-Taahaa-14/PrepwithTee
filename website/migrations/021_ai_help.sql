-- 021: AI help on past-paper questions (website/ai_help.py).

-- Shared, pre-generated per question (pipeline/explain.py). One row per
-- question: the full worked solution, three Guide-me hints and, for MCQs,
-- why each option is right or wrong - generated once, served to everyone.
CREATE TABLE IF NOT EXISTS question_explanations (
    question_id    BIGINT PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
    content_json   JSONB  NOT NULL,
    model          TEXT,
    prompt_version INTEGER NOT NULL DEFAULT 1,
    input_tokens   INTEGER,
    output_tokens  INTEGER,
    flagged        INTEGER NOT NULL DEFAULT 0,   -- students reported it as wrong
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Which explanations a student has opened. Free students get ONE (and may
-- reopen it); this is what makes "first one free" per question, not per view.
CREATE TABLE IF NOT EXISTS explanation_unlocks (
    user_id     TEXT   NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    question_id BIGINT NOT NULL,
    unlocked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, question_id)
);

-- Follow-up chat about one question (per student).
CREATE TABLE IF NOT EXISTS explanation_messages (
    id          BIGSERIAL PRIMARY KEY,
    user_id     TEXT   NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    question_id BIGINT NOT NULL,
    role        TEXT   NOT NULL CHECK (role IN ('user', 'assistant')),
    quoted_text TEXT,                         -- the highlighted part asked about
    content     TEXT   NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS explanation_messages_thread
    ON explanation_messages (user_id, question_id, id);

-- Student reports of a wrong explanation (admin review).
CREATE TABLE IF NOT EXISTS explanation_reports (
    id          BIGSERIAL PRIMARY KEY,
    user_id     TEXT REFERENCES profiles(id) ON DELETE SET NULL,
    question_id BIGINT NOT NULL,
    reason      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
