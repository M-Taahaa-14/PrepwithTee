"""SQLite storage (data/index.db).

Schema is kept Postgres-portable for a later Supabase migration: plain column
types, no SQLite-specific features beyond AUTOINCREMENT-style rowid PKs.
"""

import sqlite3

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id          INTEGER PRIMARY KEY,
    syllabus    TEXT    NOT NULL,
    year        INTEGER NOT NULL,
    session     TEXT    NOT NULL,           -- s | w | m
    paper       INTEGER NOT NULL,           -- 1, 2, 4 ...
    variant     TEXT    NOT NULL DEFAULT '',-- '' | '1' | '2' | '3'
    kind        TEXT    NOT NULL,           -- qp | ms
    filename    TEXT    NOT NULL,
    rel_path    TEXT    NOT NULL,           -- relative to repo root
    page_count  INTEGER,
    fetched_at  TEXT,
    UNIQUE (syllabus, year, session, paper, variant, kind)
);

CREATE TABLE IF NOT EXISTS questions (
    id          INTEGER PRIMARY KEY,
    paper_id    INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    number      INTEGER NOT NULL,
    sub_part    TEXT    NOT NULL DEFAULT '',  -- '' whole question | 'a'/'b'/'c'/'d' sub-part
    text        TEXT,
    marks       INTEGER,
    crop_path   TEXT,
    debug_png   TEXT,
    rects_json  TEXT,                         -- [{page,x0,y0,x1,y1}, ...]
    status      TEXT    NOT NULL DEFAULT 'segmented', -- segmented|classified|review
    UNIQUE (paper_id, number, sub_part)
);

CREATE TABLE IF NOT EXISTS classifications (
    question_id     INTEGER PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
    topic           TEXT    NOT NULL,
    secondary_topic TEXT,
    subtopic        TEXT,                   -- fine-grained subtopic within the topic
    difficulty      INTEGER,                -- 1..3
    confidence      REAL    NOT NULL,
    rationale       TEXT,
    backend         TEXT    NOT NULL,       -- heuristic|session|tracker|api
    classified_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS ms_entries (
    id              INTEGER PRIMARY KEY,
    paper_id        INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    question_number INTEGER NOT NULL,
    sub_part        TEXT    NOT NULL DEFAULT '',
    crop_path       TEXT,
    rects_json      TEXT,
    UNIQUE (paper_id, question_number, sub_part)
);

CREATE TABLE IF NOT EXISTS review_queue (
    id          INTEGER PRIMARY KEY,
    question_id INTEGER REFERENCES questions(id) ON DELETE CASCADE,
    paper_id    INTEGER REFERENCES papers(id) ON DELETE CASCADE,
    reason      TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    resolved    INTEGER NOT NULL DEFAULT 0
);
"""


def _migrate(con: sqlite3.Connection):
    """Idempotent schema migrations — run once on every connect."""
    # questions: add sub_part and change UNIQUE to (paper_id, number, sub_part)
    q_cols = {r[1] for r in con.execute("PRAGMA table_info(questions)").fetchall()}
    if "sub_part" not in q_cols:
        con.execute("PRAGMA foreign_keys = OFF")
        con.executescript("""
            BEGIN;
            CREATE TABLE questions_v2 (
                id          INTEGER PRIMARY KEY,
                paper_id    INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
                number      INTEGER NOT NULL,
                sub_part    TEXT    NOT NULL DEFAULT '',
                text        TEXT,
                marks       INTEGER,
                crop_path   TEXT,
                debug_png   TEXT,
                rects_json  TEXT,
                status      TEXT    NOT NULL DEFAULT 'segmented',
                UNIQUE (paper_id, number, sub_part)
            );
            INSERT INTO questions_v2
                SELECT id, paper_id, number, '', text, marks, crop_path,
                       debug_png, rects_json, status FROM questions;
            DROP TABLE questions;
            ALTER TABLE questions_v2 RENAME TO questions;
            COMMIT;
        """)
        con.execute("PRAGMA foreign_keys = ON")

    # classifications: add subtopic column
    c_cols = {r[1] for r in con.execute("PRAGMA table_info(classifications)").fetchall()}
    if "subtopic" not in c_cols:
        con.execute("ALTER TABLE classifications ADD COLUMN subtopic TEXT")
        con.commit()

    # ms_entries: add sub_part and change UNIQUE to (paper_id, question_number, sub_part)
    ms_cols = {r[1] for r in con.execute("PRAGMA table_info(ms_entries)").fetchall()}
    if "sub_part" not in ms_cols:
        con.execute("PRAGMA foreign_keys = OFF")
        con.executescript("""
            BEGIN;
            CREATE TABLE ms_entries_v2 (
                id              INTEGER PRIMARY KEY,
                paper_id        INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
                question_number INTEGER NOT NULL,
                sub_part        TEXT    NOT NULL DEFAULT '',
                crop_path       TEXT,
                rects_json      TEXT,
                UNIQUE (paper_id, question_number, sub_part)
            );
            INSERT INTO ms_entries_v2
                SELECT id, paper_id, question_number, '', crop_path, rects_json
                FROM ms_entries;
            DROP TABLE ms_entries;
            ALTER TABLE ms_entries_v2 RENAME TO ms_entries;
            COMMIT;
        """)
        con.execute("PRAGMA foreign_keys = ON")


def connect() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    _migrate(con)
    return con


def upsert_paper(con, rec: dict, rel_path: str, page_count: int | None = None) -> int:
    con.execute(
        """
        INSERT INTO papers (syllabus, year, session, paper, variant, kind,
                            filename, rel_path, page_count, fetched_at)
        VALUES (:syllabus, :year, :session, :paper, :variant, :kind,
                :filename, :rel_path, :page_count, datetime('now'))
        ON CONFLICT (syllabus, year, session, paper, variant, kind)
        DO UPDATE SET filename   = excluded.filename,
                      rel_path   = excluded.rel_path,
                      page_count = COALESCE(excluded.page_count, papers.page_count)
        """,
        {**rec, "rel_path": rel_path, "page_count": page_count},
    )
    con.commit()
    row = con.execute(
        """
        SELECT id FROM papers
        WHERE syllabus=:syllabus AND year=:year AND session=:session
          AND paper=:paper AND variant=:variant AND kind=:kind
        """,
        rec,
    ).fetchone()
    return row["id"]


def add_review(con, reason: str, question_id: int | None = None, paper_id: int | None = None):
    con.execute(
        "INSERT INTO review_queue (question_id, paper_id, reason) VALUES (?, ?, ?)",
        (question_id, paper_id, reason),
    )
    con.commit()
