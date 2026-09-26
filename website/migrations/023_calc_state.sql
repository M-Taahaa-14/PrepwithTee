-- 023: the scientific calculator's memory and history, per student (P2-c).
-- One row per student: M memory, Ans, variables A-F, DEG/RAD and the last 200
-- calculations, so the calculator looks the same on every device. Guests keep
-- the same thing in localStorage and it is merged in when they sign in.
CREATE TABLE IF NOT EXISTS calc_state (
    user_id     TEXT PRIMARY KEY REFERENCES profiles(id) ON DELETE CASCADE,
    mem         DOUBLE PRECISION NOT NULL DEFAULT 0,
    ans         DOUBLE PRECISION NOT NULL DEFAULT 0,
    vars        JSONB NOT NULL DEFAULT '{}',       -- {"A": 3.2, ...}
    deg         BOOLEAN NOT NULL DEFAULT TRUE,
    history     JSONB NOT NULL DEFAULT '[]',       -- newest first: [{q, a, t}]
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
