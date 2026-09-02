-- migrations/009_tutor_sessions.sql

-- Tutor chat sessions
CREATE TABLE IF NOT EXISTS tutor_sessions (
    id            TEXT PRIMARY KEY,           -- UUID
    user_id       TEXT REFERENCES profiles(id) ON DELETE CASCADE,
    title         TEXT,                        -- auto-generated or user-edited
    subject       TEXT,                        -- syllabus code (e.g. '5054')
    topic         TEXT,
    pinned        BOOLEAN DEFAULT FALSE,
    summary       TEXT,                        -- compressed older turns
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now()
);

-- Individual messages within a session
CREATE TABLE IF NOT EXISTS tutor_messages (
    id            TEXT PRIMARY KEY,           -- UUID
    session_id    TEXT REFERENCES tutor_sessions(id) ON DELETE CASCADE,
    role          TEXT NOT NULL,              -- 'user' | 'assistant'
    content       TEXT NOT NULL,              -- raw text (user) or HTML (assistant)
    attachments   JSONB DEFAULT '[]',         -- [{url, type, thumbnail_url}]
    provider      TEXT,                        -- which LLM answered
    feedback      TEXT,                        -- 'up' | 'down' | null
    created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tutor_sessions_user ON tutor_sessions(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_messages_session ON tutor_messages(session_id, created_at);
