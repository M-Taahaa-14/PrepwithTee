"""Storage for the whiteboard (whiteboard.py) and for images pasted into any
annotation layer: boards, their pages, folders, share links, image assets.

Same dual backend as users_db: Supabase (PostgREST) in production, the local
SQLite users DB otherwise. Postgres schema: migrations/026_whiteboard.sql -
keep WB_SCHEMA below in step with it.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

import users_db as _udb

WB_SCHEMA = """
CREATE TABLE IF NOT EXISTS wb_boards (
    id                  TEXT PRIMARY KEY,
    owner_id            TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    title               TEXT NOT NULL DEFAULT 'Untitled board',
    kind                TEXT NOT NULL DEFAULT 'pages',
    folder_id           TEXT,
    settings            TEXT NOT NULL DEFAULT '{}',
    page_order          TEXT NOT NULL DEFAULT '[]',
    starred             INTEGER NOT NULL DEFAULT 0,
    shared_with_teacher INTEGER NOT NULL DEFAULT 0,
    thumb               TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    opened_at           TEXT,
    deleted_at          TEXT
);
CREATE INDEX IF NOT EXISTS wb_boards_owner ON wb_boards (owner_id, updated_at);
CREATE TABLE IF NOT EXISTS wb_pages (
    board_id    TEXT NOT NULL REFERENCES wb_boards(id) ON DELETE CASCADE,
    page_id     TEXT NOT NULL,
    settings    TEXT NOT NULL DEFAULT '{}',
    objects     TEXT NOT NULL DEFAULT '[]',
    version     INTEGER NOT NULL DEFAULT 1,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (board_id, page_id)
);
CREATE TABLE IF NOT EXISTS wb_folders (
    id          TEXT PRIMARY KEY,
    owner_id    TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    color       TEXT,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wb_shares (
    token       TEXT PRIMARY KEY,
    board_id    TEXT NOT NULL REFERENCES wb_boards(id) ON DELETE CASCADE,
    role        TEXT NOT NULL DEFAULT 'view',
    created_by  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT,
    revoked_at  TEXT
);
CREATE TABLE IF NOT EXISTS ink_assets (
    id          TEXT PRIMARY KEY,
    owner_id    TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    sha256      TEXT NOT NULL,
    mime        TEXT NOT NULL,
    ext         TEXT NOT NULL,
    bytes       INTEGER NOT NULL,
    w           INTEGER,
    h           INTEGER,
    created_at  TEXT NOT NULL,
    UNIQUE (owner_id, sha256)
);
"""
JSON_COLS = {"settings", "page_order", "objects"}
BOOL_COLS = {"starred", "shared_with_teacher"}
_ready = False
_lock = threading.Lock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _local():
    """The SQLite users DB, with the whiteboard tables made on first use."""
    global _ready
    c = _udb._local()
    if not _ready:
        with _lock:
            if not _ready:
                c.executescript(WB_SCHEMA)
                c.commit()
                _ready = True
    return c


def _sb():
    return _udb._client()


def _row(r: dict | None) -> dict | None:
    """Rows look the same from both backends: JSON parsed, booleans real."""
    if r is None:
        return None
    r = dict(r)
    for k in JSON_COLS & r.keys():
        if isinstance(r[k], str):
            try:
                r[k] = json.loads(r[k])
            except ValueError:
                r[k] = [] if k != "settings" else {}
    for k in BOOL_COLS & r.keys():
        r[k] = bool(r[k])
    return r


def _enc(fields: dict) -> dict:
    """Values as the backend wants them (SQLite: JSON text, 0/1)."""
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
        c.execute(f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))
        c.commit()


def _update(table: str, where: dict, fields: dict) -> int:
    """Rows changed (Supabase: the rows the filtered update returned)."""
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


def _select(table: str, where: dict, order: str | None = None, desc: bool = False) -> list[dict]:
    if _udb._USE_SUPABASE:
        return [_row(r) for r in _udb.fetch_all(table, "*", eq=where, order=order, desc=desc)]
    with _local() as c:
        sql = f"SELECT * FROM {table}" + (f" WHERE {' AND '.join(f'{k}=?' for k in where)}" if where else "")
        if order:
            sql += f" ORDER BY {order} {'DESC' if desc else 'ASC'}"
        return [_row(r) for r in c.execute(sql, tuple(where.values())).fetchall()]


def _one(table: str, where: dict) -> dict | None:
    if _udb._USE_SUPABASE:
        q = _sb().table(table).select("*")
        for k, v in where.items():
            q = q.eq(k, v)
        rows = q.limit(1).execute().data or []
        return _row(rows[0]) if rows else None
    with _local() as c:
        r = c.execute(f"SELECT * FROM {table} WHERE {' AND '.join(f'{k}=?' for k in where)} LIMIT 1",
                      tuple(where.values())).fetchone()
        return _row(r)


# ── boards ───────────────────────────────────────────────────────────────────
def list_boards(owner_id: str) -> list[dict]:
    return _select("wb_boards", {"owner_id": owner_id}, "updated_at", desc=True)


def get_board(board_id: str) -> dict | None:
    return _one("wb_boards", {"id": board_id})


def create_board(row: dict) -> dict:
    _insert("wb_boards", row)
    return get_board(row["id"])


def update_board(board_id: str, fields: dict) -> None:
    _update("wb_boards", {"id": board_id}, fields)


def delete_board(board_id: str) -> None:
    _delete("wb_pages", {"board_id": board_id})
    _delete("wb_shares", {"board_id": board_id})
    _delete("wb_boards", {"id": board_id})


def boards_shared_with_teacher(owner_ids: list[str]) -> list[dict]:
    out = []
    for oid in owner_ids:
        out += [b for b in list_boards(oid) if b.get("shared_with_teacher") and not b.get("deleted_at")]
    return out


# ── pages ────────────────────────────────────────────────────────────────────
def get_pages(board_id: str) -> list[dict]:
    return _select("wb_pages", {"board_id": board_id})


def get_page(board_id: str, page_id: str) -> dict | None:
    return _one("wb_pages", {"board_id": board_id, "page_id": page_id})


def insert_page(board_id: str, page_id: str, settings: dict | None = None, objects: list | None = None) -> None:
    _insert("wb_pages", {"board_id": board_id, "page_id": page_id, "settings": settings or {},
                         "objects": objects or [], "version": 1, "updated_at": now()})


def save_page(board_id: str, page_id: str, objects: list, version: int) -> int | None:
    """Write a page if it is still at `version` (optimistic lock). The new
    version, or None when someone else saved first."""
    n = _update("wb_pages", {"board_id": board_id, "page_id": page_id, "version": version},
                {"objects": objects, "version": version + 1, "updated_at": now()})
    return version + 1 if n else None


def set_page_settings(board_id: str, page_id: str, settings: dict) -> None:
    _update("wb_pages", {"board_id": board_id, "page_id": page_id}, {"settings": settings, "updated_at": now()})


def delete_page(board_id: str, page_id: str) -> None:
    _delete("wb_pages", {"board_id": board_id, "page_id": page_id})


# ── folders ──────────────────────────────────────────────────────────────────
def list_folders(owner_id: str) -> list[dict]:
    return _select("wb_folders", {"owner_id": owner_id}, "created_at")


def get_folder(folder_id: str) -> dict | None:
    return _one("wb_folders", {"id": folder_id})


def create_folder(row: dict) -> None:
    _insert("wb_folders", row)


def update_folder(folder_id: str, fields: dict) -> None:
    _update("wb_folders", {"id": folder_id}, fields)


def delete_folder(folder_id: str, owner_id: str) -> None:
    for b in list_boards(owner_id):
        if b.get("folder_id") == folder_id:
            update_board(b["id"], {"folder_id": None})
    _delete("wb_folders", {"id": folder_id})


# ── share links ──────────────────────────────────────────────────────────────
def create_share(row: dict) -> None:
    _insert("wb_shares", row)


def get_share(token: str) -> dict | None:
    return _one("wb_shares", {"token": token})


def list_shares(board_id: str) -> list[dict]:
    return [s for s in _select("wb_shares", {"board_id": board_id}, "created_at", desc=True) if not s.get("revoked_at")]


def revoke_share(token: str) -> None:
    _update("wb_shares", {"token": token}, {"revoked_at": now()})


# ── image assets ─────────────────────────────────────────────────────────────
def add_asset(row: dict) -> None:
    _insert("ink_assets", row)


def get_asset(asset_id: str) -> dict | None:
    return _one("ink_assets", {"id": asset_id})


def find_asset(owner_id: str, sha256: str) -> dict | None:
    return _one("ink_assets", {"owner_id": owner_id, "sha256": sha256})


def delete_asset(asset_id: str) -> None:
    _delete("ink_assets", {"id": asset_id})


def owner_bytes(owner_id: str) -> int:
    if _udb._USE_SUPABASE:
        rows = _udb.fetch_all("ink_assets", "bytes", eq={"owner_id": owner_id})
        return sum(int(r.get("bytes") or 0) for r in rows)
    with _local() as c:
        r = c.execute("SELECT COALESCE(SUM(bytes), 0) FROM ink_assets WHERE owner_id=?", (owner_id,)).fetchone()
        return int(r[0] or 0)


def owner_stats(owner_id: str) -> dict:
    boards = list_boards(owner_id)
    return {"boards": sum(1 for b in boards if not b.get("deleted_at")),
            "trash": sum(1 for b in boards if b.get("deleted_at")),
            "bytes": owner_bytes(owner_id)}
