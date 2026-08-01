"""Dual-mode database layer for the PrepWithTee website.

If DATABASE_URL is set → Supabase Postgres via psycopg2.
Otherwise         → SQLite at data/index.db (local dev, existing pipeline data).

Provides a sqlite3-compatible Row interface in both modes so the existing
app.py code (which uses r["col"] and fetchone()[0]) works unchanged.
"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_INDEX_DB = ROOT / "data" / "index.db"

USE_PG: bool = bool(os.environ.get("DATABASE_URL"))

if USE_PG:
    import psycopg2
    from psycopg2.extras import RealDictCursor


class _Row(dict):
    """Dict that also supports positional [0] indexing (like sqlite3.Row)."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)
    def keys(self):
        return super().keys()


class _PgResult:
    """Wraps a psycopg2 cursor result so it behaves like a sqlite3 cursor."""
    def __init__(self, rows):
        self._rows = [_Row(r) for r in (rows or [])]
        self._idx = 0

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
    # SQLite IS NOT 'value' → Postgres IS DISTINCT FROM 'value'
    sql = sql.replace("IS NOT 'excluded'", "IS DISTINCT FROM 'excluded'")
    sql = sql.replace("IS NOT 'segmented'", "IS DISTINCT FROM 'segmented'")
    # SQLite datetime() → Postgres now()
    sql = sql.replace("datetime('now')", "now()::text")
    return sql


@contextmanager
def connect():
    """Context manager that yields a sqlite3-compatible connection to the pipeline DB."""
    if USE_PG:
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        conn.autocommit = False
        try:
            yield _PgConn(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(_INDEX_DB)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()


def plain_connect():
    """Non-context-manager version for callers that manage the conn themselves.

    Returns an object with .execute(), .commit(), .close() — sqlite3-compatible.
    Call .close() when done.
    """
    if USE_PG:
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        conn.autocommit = False
        return _PgConn(conn)
    else:
        conn = sqlite3.connect(_INDEX_DB)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
