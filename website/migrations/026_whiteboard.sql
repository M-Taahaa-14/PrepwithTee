-- 026: PrepWithTee Board (website/whiteboard.py, wb_store.py) and images
-- pasted into any annotation layer (annotate.js). Run on Supabase BEFORE
-- deploying the whiteboard code. wb_store.WB_SCHEMA is the SQLite twin.

-- A board: a notebook of pages, or one infinite canvas. page_order lists the
-- page ids in order; settings = {size, paper, pattern, bg} (pages may override).
CREATE TABLE IF NOT EXISTS wb_boards (
    id                  TEXT PRIMARY KEY,
    owner_id            TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    title               TEXT NOT NULL DEFAULT 'Untitled board',
    kind                TEXT NOT NULL DEFAULT 'pages' CHECK (kind IN ('pages', 'infinite')),
    folder_id           TEXT,
    settings            JSONB NOT NULL DEFAULT '{}',
    page_order          JSONB NOT NULL DEFAULT '[]',
    starred             BOOLEAN NOT NULL DEFAULT false,
    shared_with_teacher BOOLEAN NOT NULL DEFAULT false,
    thumb               TEXT,                       -- /api/ink/assets/<id> (a small PNG)
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    opened_at           TIMESTAMPTZ,
    deleted_at          TIMESTAMPTZ                 -- in the trash
);
CREATE INDEX IF NOT EXISTS wb_boards_owner ON wb_boards (owner_id, updated_at DESC);

-- One page's ink: the same objects annotate.js stores for paper pages, each
-- with an id. version = optimistic lock (a stale save gets 409 + the server copy).
CREATE TABLE IF NOT EXISTS wb_pages (
    board_id    TEXT NOT NULL REFERENCES wb_boards(id) ON DELETE CASCADE,
    page_id     TEXT NOT NULL,
    settings    JSONB NOT NULL DEFAULT '{}',
    objects     JSONB NOT NULL DEFAULT '[]',
    version     INTEGER NOT NULL DEFAULT 1,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (board_id, page_id)
);

CREATE TABLE IF NOT EXISTS wb_folders (
    id          TEXT PRIMARY KEY,
    owner_id    TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    color       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS wb_folders_owner ON wb_folders (owner_id);

-- Share links: view-only, or view + "make a copy".
CREATE TABLE IF NOT EXISTS wb_shares (
    token       TEXT PRIMARY KEY,
    board_id    TEXT NOT NULL REFERENCES wb_boards(id) ON DELETE CASCADE,
    role        TEXT NOT NULL DEFAULT 'view' CHECK (role IN ('view', 'copy')),
    created_by  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ,
    revoked_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS wb_shares_board ON wb_shares (board_id);

-- Images (whiteboards and paper annotations). Files live on the server at
-- data/ink_assets/<owner>/<id>.<ext>; one copy per owner per image (sha256).
CREATE TABLE IF NOT EXISTS ink_assets (
    id          TEXT PRIMARY KEY,
    owner_id    TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    sha256      TEXT NOT NULL,
    mime        TEXT NOT NULL,
    ext         TEXT NOT NULL,
    bytes       INTEGER NOT NULL,
    w           INTEGER,
    h           INTEGER,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (owner_id, sha256)
);
