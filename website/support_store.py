"""Storage for the help centre (support.py): chats handed to Tee and the
question log behind the support report.

Same dual backend as teach_store: Supabase (PostgREST) in production, the local
SQLite users DB otherwise. Postgres schema: migrations/030_support.sql - keep
SUPPORT_SCHEMA below in step with it.

Everything here degrades: without the migration a handoff is saved as a
feedback row instead (the admin still gets it) and question logging is skipped,
so deploying the code before the migration never breaks the widget.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timedelta, timezone

import users_db as _udb

JSON_COLS = {"transcript_json", "diag_json", "snips_json"}
_ready = False
_lock = threading.Lock()

SUPPORT_SCHEMA = """
CREATE TABLE IF NOT EXISTS support_threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, name TEXT NOT NULL, email TEXT NOT NULL,
    page TEXT, message TEXT NOT NULL, transcript_json TEXT NOT NULL DEFAULT '[]',
    diag_json TEXT NOT NULL DEFAULT '{}', snips_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS support_threads_user ON support_threads (user_id, created_at);
CREATE TABLE IF NOT EXISTS support_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, user_id TEXT, kind TEXT NOT NULL,
    intent TEXT, question TEXT, answer TEXT, page TEXT, vote INTEGER, lang TEXT, ref_id INTEGER
);
CREATE INDEX IF NOT EXISTS support_events_ts ON support_events (ts);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _local():
    global _ready
    c = _udb._local()
    if not _ready:
        with _lock:
            if not _ready:
                c.executescript(SUPPORT_SCHEMA)
                c.commit()
                _ready = True
    return c


def _row(r) -> dict:
    r = dict(r)
    for k in JSON_COLS & r.keys():
        if isinstance(r[k], str):
            try:
                r[k] = json.loads(r[k])
            except ValueError:
                r[k] = {} if k == "diag_json" else []
    return r


# ── Privacy: never keep contact or payment details in the question log ───────

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_DIGITS = re.compile(r"(?:\+?\d[\d\s-]{7,}\d)")


def scrub(text: str | None, limit: int = 500) -> str:
    t = _EMAIL.sub("[email]", text or "")
    t = _DIGITS.sub("[number]", t)
    return t.strip()[:limit]


# ── Threads (a chat handed to Tee) ────────────────────────────────────────────

def add_thread(row: dict) -> int | None:
    """Insert; returns the id, or None when the table doesn't exist yet."""
    row = {**row, "created_at": now()}
    try:
        if _udb._USE_SUPABASE:
            r = _udb._client().table("support_threads").insert(row).execute()
            return (r.data or [{}])[0].get("id")
        enc = {k: (json.dumps(v) if k in JSON_COLS else v) for k, v in row.items()}
        with _local() as c:
            cur = c.execute(f"INSERT INTO support_threads ({','.join(enc)}) "
                            f"VALUES ({','.join('?' * len(enc))})", tuple(enc.values()))
            c.commit()
            return cur.lastrowid
    except Exception as exc:
        print(f"[support] thread not stored ({exc}) - falling back to feedback", flush=True)
        return None


def get_thread(thread_id: int) -> dict | None:
    try:
        if _udb._USE_SUPABASE:
            r = _udb._client().table("support_threads").select("*").eq("id", thread_id).limit(1).execute()
            return _row(r.data[0]) if r.data else None
        with _local() as c:
            r = c.execute("SELECT * FROM support_threads WHERE id=?", (thread_id,)).fetchone()
            return _row(r) if r else None
    except Exception:
        return None


def list_threads(user_id: str | None = None, limit: int = 500) -> list[dict]:
    try:
        if _udb._USE_SUPABASE:
            q = _udb._client().table("support_threads").select("*")
            if user_id:
                q = q.eq("user_id", user_id)
            return [_row(r) for r in (q.order("created_at", desc=True).limit(limit).execute().data or [])]
        sql, args = "SELECT * FROM support_threads", []
        if user_id:
            sql += " WHERE user_id=?"
            args.append(user_id)
        with _local() as c:
            rows = c.execute(sql + " ORDER BY created_at DESC LIMIT ?", (*args, limit)).fetchall()
            return [_row(r) for r in rows]
    except Exception as exc:
        print(f"[support] threads unavailable: {exc}", flush=True)
        return []


# ── Events (question log) ─────────────────────────────────────────────────────

def log_event(kind: str, **fields) -> int | None:
    row = {"ts": now(), "kind": kind, **{k: v for k, v in fields.items() if v is not None}}
    for k in ("question", "answer"):
        if k in row:
            row[k] = scrub(row[k], 500 if k == "question" else 1500)
    try:
        if _udb._USE_SUPABASE:
            r = _udb._client().table("support_events").insert(row).execute()
            return (r.data or [{}])[0].get("id")
        with _local() as c:
            cur = c.execute(f"INSERT INTO support_events ({','.join(row)}) "
                            f"VALUES ({','.join('?' * len(row))})", tuple(row.values()))
            c.commit()
            return cur.lastrowid
    except Exception as exc:
        print(f"[support] event not logged: {exc}", flush=True)
        return None


def get_event(event_id: int) -> dict | None:
    try:
        if _udb._USE_SUPABASE:
            r = _udb._client().table("support_events").select("*").eq("id", event_id).limit(1).execute()
            return r.data[0] if r.data else None
        with _local() as c:
            r = c.execute("SELECT * FROM support_events WHERE id=?", (event_id,)).fetchone()
            return dict(r) if r else None
    except Exception:
        return None


def set_vote(event_id: int, vote: int) -> bool:
    try:
        if _udb._USE_SUPABASE:
            _udb._client().table("support_events").update({"vote": vote}).eq("id", event_id).execute()
        else:
            with _local() as c:
                c.execute("UPDATE support_events SET vote=? WHERE id=?", (vote, event_id))
                c.commit()
        return True
    except Exception:
        return False


def events_since(days: float) -> list[dict]:
    since = ago(days)
    try:
        if _udb._USE_SUPABASE:
            return _udb.fetch_all("support_events", gte=("ts", since), order="ts", desc=True)
        with _local() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM support_events WHERE ts>=? ORDER BY ts DESC", (since,)).fetchall()]
    except Exception:
        return []


def prune_guest_events(days: int = 30) -> int:
    """Signed-out visitors' questions are kept for 30 days only."""
    cutoff = ago(days)
    try:
        if _udb._USE_SUPABASE:
            r = (_udb._client().table("support_events").delete()
                 .is_("user_id", "null").lt("ts", cutoff).execute())
            return len(r.data or [])
        with _local() as c:
            cur = c.execute("DELETE FROM support_events WHERE user_id IS NULL AND ts<?", (cutoff,))
            c.commit()
            return cur.rowcount
    except Exception:
        return 0
