"""SQLite storage (data/index.db), with optional Supabase/Postgres backend.

If DATABASE_URL is set in the environment the pipeline reads from Supabase
so that compose/testgen on the server see the same data as the meta endpoint.
Write-heavy stages (fetch, segment, classify) are only run locally where
DATABASE_URL is absent, so they always use SQLite as before.
"""

import os
import sqlite3

from . import config

USE_PG: bool = bool(os.environ.get("DATABASE_URL"))

if USE_PG:
    import psycopg2  # type: ignore
    from psycopg2.extras import RealDictCursor  # type: ignore


class _Row(dict):
    """Dict that also supports positional [0] indexing (like sqlite3.Row)."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)
    def keys(self):
        return super().keys()


class _PgResult:
    """Wraps a psycopg2 cursor so it behaves like a sqlite3 cursor."""
    def __init__(self, rows):
        self._rows = [_Row(r) for r in (rows or [])]

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class _PgConn:
    """sqlite3-compatible wrapper around a psycopg2 connection."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        sql = _pg_sql(sql)
        cur = self._conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, list(params) if params else [])
        try:
            rows = cur.fetchall()
        except psycopg2.ProgrammingError:
            rows = []
        return _PgResult(rows)

    def executemany(self, sql, params_seq):
        sql = _pg_sql(sql)
        cur = self._conn.cursor()
        cur.executemany(sql, params_seq)

    def executescript(self, _sql):
        pass  # Schema is managed by Supabase; skip DDL on Postgres

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        self.close()


def _pg_sql(sql: str) -> str:
    """Adapt SQLite SQL syntax to Postgres."""
    sql = sql.replace("?", "%s")
    sql = sql.replace("IS NOT 'excluded'", "IS DISTINCT FROM 'excluded'")
    sql = sql.replace("IS NOT 'segmented'", "IS DISTINCT FROM 'segmented'")
    sql = sql.replace("datetime('now')", "now()::text")
    return sql

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

-- AI worked solutions + Guide-me hints, one per question (pipeline/explain.py).
-- CAUTION: cascades with questions, so re-segmenting a paper drops its
-- explanations too (new question ids) - re-run explain for that paper.
CREATE TABLE IF NOT EXISTS question_explanations (
    question_id    INTEGER PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
    content_json   TEXT    NOT NULL,
    model          TEXT,
    prompt_version INTEGER NOT NULL DEFAULT 1,
    input_tokens   INTEGER,
    output_tokens  INTEGER,
    flagged        INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS examiner_reports (
    id          INTEGER PRIMARY KEY,
    syllabus    TEXT NOT NULL,
    year        INTEGER NOT NULL,
    session     TEXT NOT NULL,
    filename    TEXT NOT NULL,
    rel_path    TEXT NOT NULL,
    fetched_at  TEXT,
    UNIQUE (syllabus, year, session)
);

CREATE TABLE IF NOT EXISTS grade_thresholds (
    id          INTEGER PRIMARY KEY,
    syllabus    TEXT NOT NULL,
    year        INTEGER NOT NULL,
    session     TEXT NOT NULL,
    component   TEXT NOT NULL,   -- e.g. 'Paper 2', 'Overall'
    grade       TEXT NOT NULL,   -- 'A*', 'A', 'B', 'C', 'D', 'E', 'U'
    mark        INTEGER,
    max_mark    INTEGER,
    gt_file     TEXT,            -- rel path to the source gt PDF
    UNIQUE (syllabus, year, session, component, grade)
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

    # create examiner_reports and grade_thresholds if they don't exist yet
    # (CREATE TABLE IF NOT EXISTS in SCHEMA handles new DBs; existing DBs need the migration)
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "examiner_reports" not in tables:
        con.executescript("""
            CREATE TABLE examiner_reports (
                id          INTEGER PRIMARY KEY,
                syllabus    TEXT NOT NULL,
                year        INTEGER NOT NULL,
                session     TEXT NOT NULL,
                filename    TEXT NOT NULL,
                rel_path    TEXT NOT NULL,
                fetched_at  TEXT,
                UNIQUE (syllabus, year, session)
            );
            CREATE TABLE grade_thresholds (
                id          INTEGER PRIMARY KEY,
                syllabus    TEXT NOT NULL,
                year        INTEGER NOT NULL,
                session     TEXT NOT NULL,
                component   TEXT NOT NULL,
                grade       TEXT NOT NULL,
                mark        INTEGER,
                max_mark    INTEGER,
                gt_file     TEXT,
                UNIQUE (syllabus, year, session, component, grade)
            );
        """)
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


def connect():
    """Return a sqlite3-compatible connection (SQLite locally; Supabase on server)."""
    if USE_PG:
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        conn.autocommit = False
        return _PgConn(conn)
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
