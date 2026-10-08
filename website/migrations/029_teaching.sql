-- 029: teaching console (/teach) + the shared student folder.
--
-- A teacher (teacher_students) teaches a student through the site: booklets,
-- mock tests and whiteboards built FOR the student, inked on by both of them
-- near-live, all filed in one per-student, per-subject folder that both see.
-- Keep teach_store.TEACH_SCHEMA (the local SQLite copy) in step with this file.

-- teach_items: the folder. One row per thing the teacher and student share.
-- kind: booklet | test | board | homework | class | report | file | note
-- status: todo | in_progress | done | marked
CREATE TABLE IF NOT EXISTS teach_items (
    id                 TEXT PRIMARY KEY,
    student_id         TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    teacher_id         TEXT REFERENCES profiles(id) ON DELETE SET NULL,
    syllabus           TEXT NOT NULL,
    kind               TEXT NOT NULL,
    ref_id             TEXT,
    title              TEXT NOT NULL,
    chapters_json      JSONB NOT NULL DEFAULT '[]',
    status             TEXT NOT NULL DEFAULT 'todo',
    due_at             TIMESTAMPTZ,
    created_by         TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    student_opened_at  TIMESTAMPTZ,
    student_done_at    TIMESTAMPTZ,
    marked_at          TIMESTAMPTZ,
    meta_json          JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS teach_items_student ON teach_items (student_id, syllabus, updated_at DESC);
CREATE INDEX IF NOT EXISTS teach_items_teacher ON teach_items (teacher_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS teach_items_ref ON teach_items (kind, ref_id);

-- shared_ink: one ink layer per page of a collaborative document
-- (booklet:<id>, booklet:<id>:ms). Every object carries its author in `by`.
-- `version` is the optimistic lock (PUT with a stale version -> 409 + merge).
CREATE TABLE IF NOT EXISTS shared_ink (
    doc_key     TEXT NOT NULL,
    page        INTEGER NOT NULL,
    objects     JSONB NOT NULL DEFAULT '[]',
    version     INTEGER NOT NULL DEFAULT 1,
    updated_by  TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (doc_key, page)
);
CREATE INDEX IF NOT EXISTS shared_ink_changed ON shared_ink (doc_key, updated_at);

-- wb_members: people other than the owner who may open (view) or draw on
-- (edit) a whiteboard - the student's teacher on a board built for them.
CREATE TABLE IF NOT EXISTS wb_members (
    board_id    TEXT NOT NULL REFERENCES wb_boards(id) ON DELETE CASCADE,
    user_id     TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    role        TEXT NOT NULL DEFAULT 'edit' CHECK (role IN ('view', 'edit')),
    added_by    TEXT,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (board_id, user_id)
);
CREATE INDEX IF NOT EXISTS wb_members_user ON wb_members (user_id);

-- collab_presence: who has a shared document open right now (a row is
-- "here" while seen_at is a few seconds old; refreshed by every poll).
CREATE TABLE IF NOT EXISTS collab_presence (
    doc_key     TEXT NOT NULL,
    user_id     TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    page        TEXT,
    seen_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (doc_key, user_id)
);

-- live_sessions: a class in progress. The student's pages show a Join banner;
-- with follow on, they jump to the teacher's doc + page.
CREATE TABLE IF NOT EXISTS live_sessions (
    id            TEXT PRIMARY KEY,
    teacher_id    TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    student_id    TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    syllabus      TEXT,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at      TIMESTAMPTZ,
    doc_url       TEXT,
    doc_key       TEXT,
    page          TEXT,
    follow        BOOLEAN NOT NULL DEFAULT false,
    items_json    JSONB NOT NULL DEFAULT '[]',
    class_log_id  BIGINT
);
CREATE INDEX IF NOT EXISTS live_sessions_student ON live_sessions (student_id, ended_at);

-- lesson_plan: per student, subject and chapter (subtopic optional):
-- planned -> taught -> practised -> mastered.
CREATE TABLE IF NOT EXISTS lesson_plan (
    id           BIGSERIAL PRIMARY KEY,
    student_id   TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    syllabus     TEXT NOT NULL,
    chapter      TEXT NOT NULL,
    subtopic     TEXT NOT NULL DEFAULT '',
    state        TEXT NOT NULL DEFAULT 'planned',
    planned_for  DATE,
    taught_at    TIMESTAMPTZ,
    note         TEXT,
    updated_by   TEXT,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (student_id, syllabus, chapter, subtopic)
);

-- teach_feedback: marks + comments on a folder item (question_id NULL = the
-- whole item).
CREATE TABLE IF NOT EXISTS teach_feedback (
    id           BIGSERIAL PRIMARY KEY,
    item_id      TEXT NOT NULL REFERENCES teach_items(id) ON DELETE CASCADE,
    question_id  INTEGER,
    marks        REAL,
    max_marks    REAL,
    comment      TEXT,
    by_id        TEXT,
    at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS teach_feedback_item ON teach_feedback (item_id);

-- parent_reports: progress reports a teacher sends to a student's parent.
CREATE TABLE IF NOT EXISTS parent_reports (
    id               TEXT PRIMARY KEY,
    student_id       TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    teacher_id       TEXT REFERENCES profiles(id) ON DELETE SET NULL,
    period_from      DATE NOT NULL,
    period_to        DATE NOT NULL,
    data_json        JSONB NOT NULL DEFAULT '{}',
    teacher_comment  TEXT,
    status           TEXT NOT NULL DEFAULT 'draft',
    sent_to          TEXT,
    sent_at          TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS parent_reports_student ON parent_reports (student_id, created_at DESC);

-- Only the server (service key) touches these.
ALTER TABLE teach_items     ENABLE ROW LEVEL SECURITY;
ALTER TABLE shared_ink      ENABLE ROW LEVEL SECURITY;
ALTER TABLE wb_members      ENABLE ROW LEVEL SECURITY;
ALTER TABLE collab_presence ENABLE ROW LEVEL SECURITY;
ALTER TABLE live_sessions   ENABLE ROW LEVEL SECURITY;
ALTER TABLE lesson_plan     ENABLE ROW LEVEL SECURITY;
ALTER TABLE teach_feedback  ENABLE ROW LEVEL SECURITY;
ALTER TABLE parent_reports  ENABLE ROW LEVEL SECURITY;
