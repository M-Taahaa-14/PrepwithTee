-- 020: topical booklets built by the web builder (website/booklets.py).
-- One row per build; the PDF itself lives on the server disk
-- (data/booklets/<id>.pdf) and is rebuilt from question_ids if it goes missing.
CREATE TABLE IF NOT EXISTS booklets (
    id            TEXT PRIMARY KEY,                -- short random id, used in the URL
    user_id       TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    syllabus      TEXT NOT NULL,
    title         TEXT,
    params_json   JSONB NOT NULL DEFAULT '{}',     -- the builder's selection + filters
    question_ids  JSONB NOT NULL DEFAULT '[]',     -- final mixed order
    seed          BIGINT,
    status        TEXT NOT NULL DEFAULT 'queued'
                  CHECK (status IN ('queued', 'building', 'ready', 'failed')),
    progress      INTEGER NOT NULL DEFAULT 0,      -- 0-100, drives the loader
    stage         TEXT,                            -- human label for the loader
    page_map_json JSONB,                           -- where each question landed
    error         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS booklets_user_created ON booklets (user_id, created_at DESC);
