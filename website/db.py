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

import env_guard as _env_guard

ROOT = Path(__file__).resolve().parent.parent
_INDEX_DB = Path(os.environ.get("INDEX_DB_PATH") or ROOT / "data" / "index.db")

_env_guard.check()
USE_PG: bool = bool(os.environ.get("DATABASE_URL"))

if USE_PG:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    # Ensure ms_entries has 'answer' column in Postgres
    try:
        _conn = psycopg2.connect(os.environ["DATABASE_URL"])
        with _conn.cursor() as _cur:
            _cur.execute("ALTER TABLE ms_entries ADD COLUMN IF NOT EXISTS answer TEXT")
        _conn.commit()
        _conn.close()
    except Exception as _e:
        print(f"Database startup migration warning: {_e}")


# ── Connection pool ──────────────────────────────────────────────────────────
# Every query used to open a fresh TLS connection to the Supabase pooler
# (~0.3-1 s each from the server), so a page that asked the DB once per subject
# (/yearly: 13 subjects) took 14 s and a signed-in /papers much longer. Keep a
# small pool of open connections per worker instead. A connection idle for a
# while is pinged before reuse (the pooler drops idle clients).
#
# HARD CAP (2026-10-01): the Supabase pooler runs in SESSION mode with
# pool_size 15 for the WHOLE project - every open connection is one of 15
# seats. The first version never waited and kept up to 12 idle per worker
# (2 workers = 24 > 15), so the pooler filled up and every booklet build (its
# own subprocess, its own connection) died with EMAXCONNSESSION - 134 of 252
# builds in a week. Now each worker holds at most PG_POOL_MAX connections in
# total (idle + in use) and a request waits for a free one; connections idle
# for PG_IDLE_CLOSE_S are closed so a quiet worker gives its seats back.
# Budget: 2 workers x 4 + 4 build subprocesses (2 per worker) + scripts <= 15.
import threading as _threading
import time as _time

_POOL_LOCK = _threading.Lock()
_POOL_MAX = int(os.environ.get("PG_POOL_MAX", "4"))     # open connections per worker
_POOL_WAIT_S = float(os.environ.get("PG_POOL_WAIT_S", "20"))
_IDLE_CLOSE_S = float(os.environ.get("PG_IDLE_CLOSE_S", "120"))
_IDLE_PING_S = 60
_SEATS = _threading.BoundedSemaphore(_POOL_MAX)
_idle: list = []                                        # [(conn, last_used)]
# NOT psycopg2.pool: its pools close every returned connection above `minconn`,
# so with minconn=0 nothing was ever reused (and a big minconn opens them all
# at import).


def _dsn_kwargs() -> dict:
    return {"keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10,
            "keepalives_count": 3, "connect_timeout": 15}


def pooler_full(exc: BaseException) -> bool:
    """The pooler refused us because every seat is taken (worth a short wait)."""
    s = str(exc)
    return "EMAXCONN" in s or "max clients reached" in s or "too many clients" in s


def _new_conn():
    for delay in (0.5, 1.5, 3, 5, 0):
        try:
            conn = psycopg2.connect(os.environ["DATABASE_URL"], **_dsn_kwargs())
            conn.autocommit = False
            return conn
        except psycopg2.OperationalError as exc:
            if not delay or not pooler_full(exc):
                raise
            _time.sleep(delay)


def _close_quietly(conn) -> None:
    try:
        conn.close()
    except Exception:
        pass


def _reap_idle() -> None:
    """Close connections nobody has used for a while (their seats go back)."""
    now = _time.time()
    with _POOL_LOCK:
        stale = [it for it in _idle if now - it[1] > _IDLE_CLOSE_S]
        _idle[:] = [it for it in _idle if now - it[1] <= _IDLE_CLOSE_S]
    for conn, _ in stale:
        _close_quietly(conn)
        _SEATS.release()


def _pg_acquire():
    """(raw psycopg2 connection, pooled?). Pooled connections hold a seat until
    they are closed; an idle one is reused first."""
    _reap_idle()
    while True:
        with _POOL_LOCK:
            item = _idle.pop() if _idle else None
        if item is None:
            break
        conn, last = item
        if not conn.closed and _time.time() - last <= _IDLE_PING_S:
            return conn, True
        if not conn.closed:                          # the pooler drops idle clients
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                conn.rollback()
                return conn, True
            except Exception:
                pass
        _close_quietly(conn)
        _SEATS.release()
    if not _SEATS.acquire(timeout=_POOL_WAIT_S):
        # Every seat busy for 20 s - most likely a leaked connection. Don't hang
        # the request: open one outside the pool (closed again on release).
        print(f"[db] pool exhausted ({_POOL_MAX} in use for {_POOL_WAIT_S:.0f}s) - "
              "opening an unpooled connection", flush=True)
        return _new_conn(), False
    try:
        return _new_conn(), True
    except BaseException:
        _SEATS.release()
        raise


def _pg_release(conn, pooled: bool) -> None:
    keep = pooled and not conn.closed
    if keep:
        try:
            conn.rollback()                          # never hand on an open transaction
        except Exception:
            keep = False
    if keep:
        with _POOL_LOCK:
            _idle.append((conn, _time.time()))
        return
    _close_quietly(conn)
    if pooled:
        _SEATS.release()


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

    def __init__(self, conn, pooled: bool = False):
        self._conn = conn
        self._pooled = pooled
        self._released = False

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
        if self._released:
            return
        self._released = True
        _pg_release(self._conn, self._pooled)

    def __del__(self):                           # a caller that forgot close()
        try:
            self.close()
        except Exception:
            pass

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
        conn, pooled = _pg_acquire()
        wrapped = _PgConn(conn, pooled)
        try:
            yield wrapped
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            wrapped.close()
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
        conn, pooled = _pg_acquire()
        return _PgConn(conn, pooled)
    else:
        conn = sqlite3.connect(_INDEX_DB)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
