-- 022: MCQ practice sessions (website/mcq.py) and per-page pen annotations
-- (static/annotate.js) for every in-site PDF / question view.

-- One row per practice session: a full past paper or a topical set. Answers
-- are saved as the student goes, so a session survives a reload or a device
-- switch; the correct letters are only revealed per question (live check) or
-- after submit.
CREATE TABLE IF NOT EXISTS mcq_sessions (
    id            TEXT PRIMARY KEY,                 -- short random id, used in the URL
    user_id       TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    syllabus      TEXT NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('paper', 'topical')),
    paper_id      BIGINT,                           -- the question paper (kind = 'paper')
    title         TEXT,
    question_ids  JSONB NOT NULL DEFAULT '[]',      -- in the order they are asked
    settings      JSONB NOT NULL DEFAULT '{}',      -- mode, live_check, time_limit_s
    answers       JSONB NOT NULL DEFAULT '{}',      -- {qid: {a, f, t, checked}}
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'submitted')),
    elapsed_s     INTEGER NOT NULL DEFAULT 0,       -- time on the clock so far
    score         INTEGER,
    total         INTEGER,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    submitted_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS mcq_sessions_user_updated ON mcq_sessions (user_id, updated_at DESC);

-- Pen / highlighter / shapes / text drawn over a page. doc_key names the
-- document: 'paper:<papers.id>', 'booklet:<id>', 'mcq:<session>:q<qid>'.
-- Coordinates are stored as fractions of the page, so zoom never matters.
CREATE TABLE IF NOT EXISTS page_annotations (
    user_id     TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    doc_key     TEXT NOT NULL,
    page        INTEGER NOT NULL,
    strokes     JSONB NOT NULL DEFAULT '[]',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, doc_key, page)
);
