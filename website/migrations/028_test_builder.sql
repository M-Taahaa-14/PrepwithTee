-- 028: test builder v2 (preview, customise, share).
--
-- question_ratings: teachers rate a past-paper question's difficulty 1-3
-- (easy / medium / hard). Students see the median of every teacher's rating;
-- a teacher sees their own first. question_id points at the pipeline's
-- questions table, which lives in another schema, so there is no FK.
CREATE TABLE IF NOT EXISTS question_ratings (
    question_id INTEGER NOT NULL,
    rater_id    TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    difficulty  SMALLINT NOT NULL CHECK (difficulty BETWEEN 1 AND 3),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (question_id, rater_id)
);

-- booklet_shares: a teacher's booklet / mock test opened by a student, either
-- assigned as homework (via='assign') or joined through a share link
-- (via='link'). One build, many students; each keeps their own ink.
-- ms_policy: after_finish | now | teacher_only (when the student may open the
-- mark scheme of a mock test).
CREATE TABLE IF NOT EXISTS booklet_shares (
    booklet_id    TEXT NOT NULL REFERENCES booklets(id) ON DELETE CASCADE,
    student_id    TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    via           TEXT NOT NULL DEFAULT 'assign',
    assignment_id BIGINT,
    ms_policy     TEXT NOT NULL DEFAULT 'after_finish',
    opened_at     TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (booklet_id, student_id)
);
CREATE INDEX IF NOT EXISTS booklet_shares_student ON booklet_shares (student_id, created_at DESC);

-- Only the server (service key) touches these.
ALTER TABLE question_ratings ENABLE ROW LEVEL SECURITY;
ALTER TABLE booklet_shares   ENABLE ROW LEVEL SECURITY;
