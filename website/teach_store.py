"""Storage for teaching: the shared student folder, collaborative ink, board
members, presence, live classes, lesson plans, feedback and parent reports.

Same dual backend as users_db / wb_store: Supabase (PostgREST) in production,
the local SQLite users DB otherwise. Postgres schema: migrations/029_teaching.sql
- keep TEACH_SCHEMA below in step with it.
"""
from __future__ import annotations

import json
import secrets
import threading
from datetime import datetime, timedelta, timezone

import users_db as _udb

JSON_COLS = {"chapters_json", "meta_json", "objects", "items_json", "data_json", "settings", "page_order"}
BOOL_COLS = {"follow"}
PRESENCE_S = 8                       # a poll at least this recent = "here"
_ready = False
_lock = threading.Lock()

TEACH_SCHEMA = """
CREATE TABLE IF NOT EXISTS teach_items (
    id TEXT PRIMARY KEY, student_id TEXT NOT NULL, teacher_id TEXT, syllabus TEXT NOT NULL,
    kind TEXT NOT NULL, ref_id TEXT, title TEXT NOT NULL, chapters_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'todo', due_at TEXT, created_by TEXT, created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, student_opened_at TEXT, student_done_at TEXT, marked_at TEXT,
    meta_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS teach_items_student ON teach_items (student_id, syllabus, updated_at);
CREATE INDEX IF NOT EXISTS teach_items_ref ON teach_items (kind, ref_id);
CREATE TABLE IF NOT EXISTS shared_ink (
    doc_key TEXT NOT NULL, page INTEGER NOT NULL, objects TEXT NOT NULL DEFAULT '[]',
    version INTEGER NOT NULL DEFAULT 1, updated_by TEXT, updated_at TEXT NOT NULL,
    PRIMARY KEY (doc_key, page)
);
CREATE TABLE IF NOT EXISTS wb_members (
    board_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'edit',
    added_by TEXT, added_at TEXT NOT NULL, PRIMARY KEY (board_id, user_id)
);
CREATE TABLE IF NOT EXISTS collab_presence (
    doc_key TEXT NOT NULL, user_id TEXT NOT NULL, page TEXT, seen_at TEXT NOT NULL,
    PRIMARY KEY (doc_key, user_id)
);
CREATE TABLE IF NOT EXISTS live_sessions (
    id TEXT PRIMARY KEY, teacher_id TEXT NOT NULL, student_id TEXT NOT NULL, syllabus TEXT,
    started_at TEXT NOT NULL, ended_at TEXT, doc_url TEXT, doc_key TEXT, page TEXT,
    follow INTEGER NOT NULL DEFAULT 0, items_json TEXT NOT NULL DEFAULT '[]', class_log_id INTEGER
);
CREATE TABLE IF NOT EXISTS lesson_plan (
    id INTEGER PRIMARY KEY AUTOINCREMENT, student_id TEXT NOT NULL, syllabus TEXT NOT NULL,
    chapter TEXT NOT NULL, subtopic TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT 'planned',
    planned_for TEXT, taught_at TEXT, note TEXT, updated_by TEXT, updated_at TEXT NOT NULL,
    UNIQUE (student_id, syllabus, chapter, subtopic)
);
CREATE TABLE IF NOT EXISTS teach_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT NOT NULL, question_id INTEGER,
    marks REAL, max_marks REAL, comment TEXT, by_id TEXT, at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS parent_reports (
    id TEXT PRIMARY KEY, student_id TEXT NOT NULL, teacher_id TEXT, period_from TEXT NOT NULL,
    period_to TEXT NOT NULL, data_json TEXT NOT NULL DEFAULT '{}', teacher_comment TEXT,
    status TEXT NOT NULL DEFAULT 'draft', sent_to TEXT, sent_at TEXT, created_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ago(seconds: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def new_id() -> str:
    return secrets.token_urlsafe(9)


def _local():
    global _ready
    c = _udb._local()
    if not _ready:
        with _lock:
            if not _ready:
                c.executescript(TEACH_SCHEMA)
                c.commit()
                _ready = True
    return c


def _sb():
    return _udb._client()


def _row(r) -> dict | None:
    if r is None:
        return None
    r = dict(r)
    for k in JSON_COLS & r.keys():
        if isinstance(r[k], str):
            try:
                r[k] = json.loads(r[k])
            except ValueError:
                r[k] = {} if k in ("meta_json", "data_json", "settings") else []
    for k in BOOL_COLS & r.keys():
        r[k] = bool(r[k])
    return r


def _enc(fields: dict) -> dict:
    if _udb._USE_SUPABASE:
        return fields
    out = {}
    for k, v in fields.items():
        if k in JSON_COLS:
            out[k] = json.dumps(v, separators=(",", ":"))
        elif k in BOOL_COLS:
            out[k] = 1 if v else 0
        else:
            out[k] = v
    return out


def _insert(table: str, row: dict) -> None:
    if _udb._USE_SUPABASE:
        _sb().table(table).insert(row).execute()
        return
    row = _enc(row)
    with _local() as c:
        c.execute(f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join('?' * len(row))})",
                  tuple(row.values()))
        c.commit()


def _upsert(table: str, row: dict, conflict: tuple[str, ...]) -> None:
    if _udb._USE_SUPABASE:
        _sb().table(table).upsert(row, on_conflict=",".join(conflict)).execute()
        return
    row = _enc(row)
    sets = ",".join(f"{k}=excluded.{k}" for k in row if k not in conflict)
    with _local() as c:
        c.execute(f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join('?' * len(row))}) "
                  f"ON CONFLICT({','.join(conflict)}) DO UPDATE SET {sets}", tuple(row.values()))
        c.commit()


def _update(table: str, where: dict, fields: dict) -> int:
    if _udb._USE_SUPABASE:
        q = _sb().table(table).update(fields)
        for k, v in where.items():
            q = q.eq(k, v)
        return len(q.execute().data or [])
    fields = _enc(fields)
    with _local() as c:
        cur = c.execute(f"UPDATE {table} SET {','.join(f'{k}=?' for k in fields)} "
                        f"WHERE {' AND '.join(f'{k}=?' for k in where)}",
                        (*fields.values(), *where.values()))
        c.commit()
        return cur.rowcount


def _delete(table: str, where: dict) -> None:
    if _udb._USE_SUPABASE:
        q = _sb().table(table).delete()
        for k, v in where.items():
            q = q.eq(k, v)
        q.execute()
        return
    with _local() as c:
        c.execute(f"DELETE FROM {table} WHERE {' AND '.join(f'{k}=?' for k in where)}", tuple(where.values()))
        c.commit()


def _select(table: str, where: dict, order: str | None = None, desc: bool = False,
            gt: tuple[str, str] | None = None, cols: str = "*", limit: int | None = None) -> list[dict]:
    """Rows matching `where` (equality) and, optionally, gt=(column, value)."""
    if _udb._USE_SUPABASE:
        q = _sb().table(table).select(cols)
        for k, v in where.items():
            q = q.eq(k, v)
        if gt:
            q = q.gt(gt[0], gt[1])
        if order:
            q = q.order(order, desc=desc)
        q = q.limit(limit or 1000)
        return [_row(r) for r in (q.execute().data or [])]
    sql = f"SELECT {cols} FROM {table}"
    conds, args = [f"{k}=?" for k in where], list(where.values())
    if gt:
        conds.append(f"{gt[0]}>?")
        args.append(gt[1])
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    if order:
        sql += f" ORDER BY {order} {'DESC' if desc else 'ASC'}"
    if limit:
        sql += f" LIMIT {int(limit)}"
    with _local() as c:
        return [_row(r) for r in c.execute(sql, args).fetchall()]


def _one(table: str, where: dict) -> dict | None:
    rows = _select(table, where, limit=1)
    return rows[0] if rows else None


def available() -> bool:
    """False when migration 029 hasn't been applied (Supabase) - features hide."""
    try:
        _select("teach_items", {}, limit=1, cols="id")
        return True
    except Exception as exc:
        print(f"[teach] tables unavailable: {exc}", flush=True)
        return False


# ── shared ink ───────────────────────────────────────────────────────────────
def ink_pages(doc_key: str, since: str | None = None) -> list[dict]:
    return _select("shared_ink", {"doc_key": doc_key}, "page",
                   gt=("updated_at", since) if since else None)


def ink_page(doc_key: str, page: int) -> dict | None:
    return _one("shared_ink", {"doc_key": doc_key, "page": page})


def save_ink(doc_key: str, page: int, objects: list, version: int, by: str) -> int | None:
    """Write a page if it is still at `version` (0 = never saved). The new
    version, or None when someone else saved first."""
    if version <= 0:
        try:
            _insert("shared_ink", {"doc_key": doc_key, "page": page, "objects": objects, "version": 1,
                                   "updated_by": by, "updated_at": now()})
            return 1
        except Exception:
            return None                      # it exists after all: stale
    n = _update("shared_ink", {"doc_key": doc_key, "page": page, "version": version},
                {"objects": objects, "version": version + 1, "updated_by": by, "updated_at": now()})
    return version + 1 if n else None


# ── presence ─────────────────────────────────────────────────────────────────
def touch_presence(doc_key: str, user_id: str, page: str | None) -> None:
    _upsert("collab_presence", {"doc_key": doc_key, "user_id": user_id, "page": page, "seen_at": now()},
            ("doc_key", "user_id"))


def present(doc_key: str) -> list[dict]:
    return _select("collab_presence", {"doc_key": doc_key}, gt=("seen_at", ago(PRESENCE_S)))


def leave(doc_key: str, user_id: str) -> None:
    _delete("collab_presence", {"doc_key": doc_key, "user_id": user_id})


# ── whiteboard members ───────────────────────────────────────────────────────
def board_role(board_id: str, user_id: str) -> str | None:
    try:
        r = _one("wb_members", {"board_id": board_id, "user_id": user_id})
    except Exception:
        return None
    return r["role"] if r else None


def board_members(board_id: str) -> list[dict]:
    return _select("wb_members", {"board_id": board_id})


def set_board_member(board_id: str, user_id: str, role: str | None, added_by: str) -> None:
    if role is None:
        _delete("wb_members", {"board_id": board_id, "user_id": user_id})
    else:
        _upsert("wb_members", {"board_id": board_id, "user_id": user_id, "role": role,
                               "added_by": added_by, "added_at": now()}, ("board_id", "user_id"))


def member_boards(user_id: str) -> list[dict]:
    return _select("wb_members", {"user_id": user_id})


# ── folder ───────────────────────────────────────────────────────────────────
def add_item(row: dict) -> dict:
    t = now()
    row = {"id": new_id(), "status": "todo", "chapters_json": [], "meta_json": {},
           "created_at": t, "updated_at": t, **row}
    _insert("teach_items", row)
    return get_item(row["id"])


def get_item(item_id: str) -> dict | None:
    return _one("teach_items", {"id": item_id})


def item_for(kind: str, ref_id: str) -> dict | None:
    return _one("teach_items", {"kind": kind, "ref_id": ref_id})


def update_item(item_id: str, fields: dict) -> None:
    _update("teach_items", {"id": item_id}, {**fields, "updated_at": now()})


def delete_item(item_id: str) -> None:
    _delete("teach_feedback", {"item_id": item_id})
    _delete("teach_items", {"id": item_id})


def folder(student_id: str, syllabus: str | None = None) -> list[dict]:
    where = {"student_id": student_id}
    if syllabus:
        where["syllabus"] = syllabus
    return _select("teach_items", where, "updated_at", desc=True)


def teacher_items(teacher_id: str) -> list[dict]:
    return _select("teach_items", {"teacher_id": teacher_id}, "updated_at", desc=True)


# ── feedback ─────────────────────────────────────────────────────────────────
def feedback(item_id: str) -> list[dict]:
    return _select("teach_feedback", {"item_id": item_id}, "at")


def set_feedback(item_id: str, rows: list[dict], by: str) -> None:
    """Replace an item's marks + comments (question_id None = overall)."""
    _delete("teach_feedback", {"item_id": item_id})
    t = now()
    for r in rows:
        _insert("teach_feedback", {"item_id": item_id, "question_id": r.get("question_id"),
                                   "marks": r.get("marks"), "max_marks": r.get("max_marks"),
                                   "comment": r.get("comment"), "by_id": by, "at": t})


# ── lesson plan ──────────────────────────────────────────────────────────────
def plan(student_id: str, syllabus: str) -> list[dict]:
    return _select("lesson_plan", {"student_id": student_id, "syllabus": syllabus}, "chapter")


def set_plan(student_id: str, syllabus: str, chapter: str, subtopic: str, fields: dict, by: str) -> None:
    _upsert("lesson_plan", {"student_id": student_id, "syllabus": syllabus, "chapter": chapter,
                            "subtopic": subtopic or "", **fields, "updated_by": by, "updated_at": now()},
            ("student_id", "syllabus", "chapter", "subtopic"))


# ── live sessions ────────────────────────────────────────────────────────────
def live_for_student(student_id: str) -> dict | None:
    rows = [r for r in _select("live_sessions", {"student_id": student_id}, "started_at", desc=True, limit=5)
            if not r.get("ended_at")]
    return rows[0] if rows else None


def live_for_teacher(teacher_id: str) -> list[dict]:
    return [r for r in _select("live_sessions", {"teacher_id": teacher_id}, "started_at", desc=True, limit=50)
            if not r.get("ended_at")]


def get_live(session_id: str) -> dict | None:
    return _one("live_sessions", {"id": session_id})


def start_live(row: dict) -> dict:
    row = {"id": new_id(), "started_at": now(), "items_json": [], "follow": False, **row}
    _insert("live_sessions", row)
    return get_live(row["id"])


def update_live(session_id: str, fields: dict) -> None:
    _update("live_sessions", {"id": session_id}, fields)


# ── parent reports ───────────────────────────────────────────────────────────
def reports(student_id: str) -> list[dict]:
    return _select("parent_reports", {"student_id": student_id}, "created_at", desc=True)


def get_report(report_id: str) -> dict | None:
    return _one("parent_reports", {"id": report_id})


def add_report(row: dict) -> dict:
    row = {"id": new_id(), "created_at": now(), "status": "draft", **row}
    _insert("parent_reports", row)
    return get_report(row["id"])


def update_report(report_id: str, fields: dict) -> None:
    _update("parent_reports", {"id": report_id}, fields)


def student_event(kinds: tuple[str, ...], ref_id: str, done: bool = False) -> None:
    """The student opened (or finished) something in their folder: todo ->
    in_progress on first open, -> done when finished. Never moves an item
    backwards (a marked paper stays marked). Silent if 029 isn't applied."""
    try:
        for k in kinds:
            it = item_for(k, ref_id)
            if not it:
                continue
            f: dict = {}
            if not it.get("student_opened_at"):
                f["student_opened_at"] = now()
            if it["status"] == "todo":
                f["status"] = "in_progress"
            if done and it["status"] in ("todo", "in_progress"):
                f.update(status="done", student_done_at=now())
            if f:
                update_item(it["id"], f)
    except Exception as exc:
        print(f"[teach] student_event: {exc}", flush=True)
