-- 030: help centre (support.py / static/support.js).
--
-- support_threads: a chat a student handed to Tee ("Send this to Tee"). Shows in
-- the admin Inbox as source 'support'; Tee's replies live in inbox_status
-- (source 'support', item_id = id) like every other inbox item.
-- support_events: the question log behind the admin Support report
-- (kind: ask | vote | handoff | action). Questions are scrubbed of emails and
-- phone/card numbers before they are stored; signed-out rows are pruned after
-- 30 days.
-- Keep support_store.SUPPORT_SCHEMA (the local SQLite copy) in step with this file.

CREATE TABLE IF NOT EXISTS support_threads (
    id               BIGSERIAL PRIMARY KEY,
    user_id          TEXT REFERENCES profiles(id) ON DELETE SET NULL,
    name             TEXT NOT NULL,
    email            TEXT NOT NULL,
    page             TEXT,
    message          TEXT NOT NULL,
    transcript_json  JSONB NOT NULL DEFAULT '[]',
    diag_json        JSONB NOT NULL DEFAULT '{}',
    snips_json       JSONB NOT NULL DEFAULT '[]',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS support_threads_user ON support_threads (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS support_events (
    id        BIGSERIAL PRIMARY KEY,
    ts        TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id   TEXT REFERENCES profiles(id) ON DELETE SET NULL,
    kind      TEXT NOT NULL,
    intent    TEXT,
    question  TEXT,
    answer    TEXT,
    page      TEXT,
    vote      SMALLINT,
    lang      TEXT,
    ref_id    BIGINT
);
CREATE INDEX IF NOT EXISTS support_events_ts ON support_events (ts DESC);

ALTER TABLE support_threads ENABLE ROW LEVEL SECURITY;
ALTER TABLE support_events ENABLE ROW LEVEL SECURITY;
