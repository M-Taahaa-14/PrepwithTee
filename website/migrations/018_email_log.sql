-- Migration 018: email_log table for automated campaign deduplication

CREATE TABLE IF NOT EXISTS email_log (
    id          BIGSERIAL PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    template_id TEXT NOT NULL,   -- e.g. 'W1', 'R1', 'F1'
    sent_at     TEXT NOT NULL DEFAULT (now()::text)
);

CREATE INDEX IF NOT EXISTS email_log_user_template
    ON email_log (user_id, template_id, sent_at);
