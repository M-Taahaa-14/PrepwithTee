-- migrations/012_notes.sql
-- Student personal notes — jot bullets, sticky notes, context-linked captures.
-- Distinct from resources (file-based study materials in resources.html).

CREATE TABLE IF NOT EXISTS notes (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    type                TEXT NOT NULL DEFAULT 'text',  -- 'text' | 'sticky'
    title               TEXT,
    content             TEXT,           -- plain text / markdown bullets
    color               TEXT,           -- sticky note colour: 'yellow'|'pink'|'blue'|'green'|'purple'
    linked_type         TEXT,           -- 'paper' | 'flashcard_block' | 'chapter' | 'tutor_message' | NULL
    linked_id           TEXT,           -- paper_key / fc_blocks.id / fc_chapters.id / tutor_messages.id
    linked_label        TEXT,           -- human-readable label stored at write time (e.g. "0625 S24 P1 Q3")
    syllabus            TEXT,           -- subject/syllabus code for filtering (e.g. '5054')
    tags_json           TEXT NOT NULL DEFAULT '[]',
    pinned_to_dashboard BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_notes_user   ON notes(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_notes_linked ON notes(linked_type, linked_id);
CREATE INDEX IF NOT EXISTS idx_notes_pinned ON notes(user_id, pinned_to_dashboard) WHERE pinned_to_dashboard = TRUE;
