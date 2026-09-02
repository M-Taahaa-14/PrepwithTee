"""Flashcard / study-recall API for PrepWithTee.

Endpoints (all under /api/fc/):
  GET  /api/fc/taxonomy          public  → boards/subjects/papers/chapters tree
  GET  /api/fc/blocks            public  → filtered content blocks
  GET  /api/fc/due               auth    → due cards for a study session
  POST /api/fc/rate              auth    → rate a card (spaced repetition)
  POST /api/fc/save              auth    → toggle saved_for_review
  POST /api/fc/session/end       auth    → log a completed session
  GET  /api/fc/quiz              auth    → auto-generate MCQ from scope
  POST /api/fc/quiz/result       auth    → submit quiz results
  GET  /api/fc/progress          auth    → mastery stats + streak
"""

import json
import random
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query
from pydantic import BaseModel

from . import db as _db
from .auth import get_current_user, maybe_user

router = APIRouter()

# ── DB helpers ────────────────────────────────────────────────────────────

def _con():
    return _db.plain_connect()


# Ensure tables exist on first use (SQLite only — Postgres has schema.sql).
_FC_DDL_SQLITE = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS fc_boards (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, code TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS fc_subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT, board_id INTEGER NOT NULL,
    name TEXT NOT NULL, code TEXT NOT NULL UNIQUE, level TEXT, alt_codes_json TEXT DEFAULT '[]');
CREATE TABLE IF NOT EXISTS fc_papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT, subject_id INTEGER NOT NULL,
    name TEXT NOT NULL, code TEXT NOT NULL, UNIQUE(subject_id, code));
CREATE TABLE IF NOT EXISTS fc_chapters (
    id INTEGER PRIMARY KEY AUTOINCREMENT, paper_id INTEGER NOT NULL,
    name TEXT NOT NULL, order_index INTEGER NOT NULL DEFAULT 0, UNIQUE(paper_id, name));
CREATE TABLE IF NOT EXISTS fc_blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chapter_id INTEGER NOT NULL,
    type TEXT NOT NULL, topic_label TEXT, payload_json TEXT NOT NULL DEFAULT '{}',
    source_hash TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE UNIQUE INDEX IF NOT EXISTS fc_blocks_uq ON fc_blocks(chapter_id, type, source_hash)
    WHERE source_hash IS NOT NULL;
CREATE TABLE IF NOT EXISTS fc_card_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT, student_id TEXT NOT NULL,
    block_id INTEGER NOT NULL REFERENCES fc_blocks(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'new', times_reviewed INTEGER NOT NULL DEFAULT 0,
    times_correct INTEGER NOT NULL DEFAULT 0, ease_factor REAL NOT NULL DEFAULT 2.5,
    interval_days REAL NOT NULL DEFAULT 0.0, next_review_at TEXT,
    saved_for_review INTEGER NOT NULL DEFAULT 0, last_result TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')), UNIQUE(student_id, block_id));
CREATE TABLE IF NOT EXISTS fc_review_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, student_id TEXT NOT NULL,
    block_id INTEGER NOT NULL REFERENCES fc_blocks(id) ON DELETE CASCADE,
    rating TEXT NOT NULL, reviewed_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS fc_study_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, student_id TEXT NOT NULL,
    scope_json TEXT, started_at TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at TEXT, cards_reviewed INTEGER NOT NULL DEFAULT 0, cards_aced INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS fc_streaks (
    student_id TEXT PRIMARY KEY, current_streak INTEGER NOT NULL DEFAULT 0,
    longest_streak INTEGER NOT NULL DEFAULT 0, last_active_date TEXT);
"""

_tables_ready = False
_tables_lock = threading.Lock()


def _ensure_tables():
    global _tables_ready
    if _tables_ready:
        return
    with _tables_lock:
        if _tables_ready:
            return
        if not _db.USE_PG:
            con = _con()
            con.executescript(_FC_DDL_SQLITE)
            con.commit()
            con.close()
        _tables_ready = True


# ── Spaced-repetition (SM-2) ──────────────────────────────────────────────

@dataclass
class _CardState:
    ease_factor: float = 2.5
    interval_days: float = 0.0
    times_reviewed: int = 0


def sm2_schedule(state: _CardState, rating: str) -> tuple[_CardState, str, str]:
    """Pure SM-2 scheduler — no DB access, fully testable in isolation.

    Returns (new_state, status, next_review_iso).
    status: 'new' | 'learning' | 'review' | 'mastered'
    """
    q = {"again": 1, "hard": 2, "good": 4, "easy": 5}.get(rating, 3)

    # Ease factor update (SM-2 formula)
    ef = state.ease_factor + 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)
    ef = max(1.3, ef)

    n = state.times_reviewed

    if q < 3:          # again or hard → reset to 1 day
        new_interval = 1.0
        status = "learning"
    elif n == 0:
        new_interval = 1.0
        status = "learning"
    elif n == 1:
        new_interval = 6.0
        status = "learning"
    else:
        new_interval = max(1.0, round(state.interval_days * state.ease_factor))
        status = "review"

    if rating == "easy":
        new_interval = max(new_interval, 4.0) * 1.3
        status = "mastered"
    elif new_interval >= 21:
        status = "mastered"

    new_state = _CardState(
        ease_factor=ef,
        interval_days=float(new_interval),
        times_reviewed=n + 1,
    )
    now = datetime.now(timezone.utc)
    next_review = (now + timedelta(days=new_interval)).isoformat()
    return new_state, status, next_review


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_str() -> str:
    return date.today().isoformat()


# ── Taxonomy ──────────────────────────────────────────────────────────────

@router.get("/api/fc/taxonomy")
def fc_taxonomy(user: Optional[dict] = Depends(maybe_user)):
    """Full board → subject → paper → chapter tree with block counts."""
    _ensure_tables()
    con = _con()
    con.row_factory = sqlite3.Row
    try:
        boards_rows = con.execute(
            "SELECT id, name, code FROM fc_boards ORDER BY name"
        ).fetchall()

        subjects_rows = con.execute(
            "SELECT id, board_id, name, code, level, alt_codes_json "
            "FROM fc_subjects ORDER BY name"
        ).fetchall()

        if user:
            from . import users_db as _udb
            active_codes = set(_udb.get_enrollments(user["id"]))
            filtered_subjects = []
            for s in subjects_rows:
                alt = json.loads(s["alt_codes_json"] or "[]")
                if s["code"] in active_codes or any(c in active_codes for c in alt):
                    filtered_subjects.append(s)
            subjects_rows = filtered_subjects

            active_board_ids = {s["board_id"] for s in subjects_rows}
            boards_rows = [b for b in boards_rows if b["id"] in active_board_ids]

        papers_rows = con.execute(
            "SELECT id, subject_id, name, code FROM fc_papers ORDER BY subject_id, code"
        ).fetchall()

        # Chapter counts per paper
        counts = con.execute(
            """SELECT ch.paper_id, COUNT(b.id) AS n
               FROM fc_chapters ch
               JOIN fc_blocks b ON b.chapter_id = ch.id
               GROUP BY ch.paper_id"""
        ).fetchall()
        count_by_paper = {r["paper_id"]: r["n"] for r in counts}

        chapters_rows = con.execute(
            "SELECT id, paper_id, name, order_index FROM fc_chapters ORDER BY paper_id, order_index, name"
        ).fetchall()

        block_counts = con.execute(
            "SELECT chapter_id, type, COUNT(*) AS n FROM fc_blocks GROUP BY chapter_id, type"
        ).fetchall()
        block_ct: dict[int, dict] = {}
        for r in block_counts:
            d = block_ct.setdefault(r["chapter_id"], {})
            d[r["type"]] = r["n"]
            d["total"] = d.get("total", 0) + r["n"]

    finally:
        con.close()

    # Assemble tree
    chapters_by_paper: dict[int, list] = {}
    for ch in chapters_rows:
        ct = block_ct.get(ch["id"], {})
        chapters_by_paper.setdefault(ch["paper_id"], []).append({
            "id": ch["id"],
            "name": ch["name"],
            "order_index": ch["order_index"],
            "counts": ct,
        })

    papers_by_subject: dict[int, list] = {}
    for p in papers_rows:
        papers_by_subject.setdefault(p["subject_id"], []).append({
            "id": p["id"],
            "code": p["code"],
            "name": p["name"],
            "total_blocks": count_by_paper.get(p["id"], 0),
            "chapters": chapters_by_paper.get(p["id"], []),
        })

    subjects_by_board: dict[int, list] = {}
    for s in subjects_rows:
        subjects_by_board.setdefault(s["board_id"], []).append({
            "id": s["id"],
            "name": s["name"],
            "code": s["code"],
            "level": s["level"],
            "alt_codes": json.loads(s["alt_codes_json"] or "[]"),
            "papers": papers_by_subject.get(s["id"], []),
        })

    boards = [
        {
            "id": b["id"],
            "name": b["name"],
            "code": b["code"],
            "subjects": subjects_by_board.get(b["id"], []),
        }
        for b in boards_rows
    ]
    return {"boards": boards}


# ── Block listing ─────────────────────────────────────────────────────────

@router.get("/api/fc/blocks")
def fc_blocks(
    chapter_id: Optional[int] = Query(None),
    subject_id: Optional[int] = Query(None),
    paper_id:   Optional[int] = Query(None),
    type_:      Optional[str] = Query(None, alias="type"),
    search:     Optional[str] = Query(None),
    saved_only: bool = Query(False),
    limit:      int  = Query(50),
    offset:     int  = Query(0),
    user: Optional[dict] = Depends(maybe_user),
):
    """Return filtered blocks. Public; saved_only requires auth."""
    _ensure_tables()
    if saved_only and not user:
        raise HTTPException(401, "Login required to view saved cards")
    if limit > 200:
        limit = 200

    con = _con()
    con.row_factory = sqlite3.Row
    try:
        clauses = []
        params: list = []

        if chapter_id:
            clauses.append("b.chapter_id = ?")
            params.append(chapter_id)
        elif paper_id:
            clauses.append("ch.paper_id = ?")
            params.append(paper_id)
        elif subject_id:
            clauses.append("p.subject_id = ?")
            params.append(subject_id)

        if type_ and type_ in ("card", "def", "formula", "list"):
            clauses.append("b.type = ?")
            params.append(type_)

        if search:
            q = f"%{search}%"
            clauses.append("b.payload_json LIKE ?")
            params.append(q)

        if saved_only and user:
            clauses.append(
                "EXISTS (SELECT 1 FROM fc_card_progress cp "
                "WHERE cp.block_id = b.id AND cp.student_id = ? AND cp.saved_for_review = 1)"
            )
            params.append(user["id"])

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        rows = con.execute(
            f"""SELECT b.id, b.chapter_id, b.type, b.topic_label, b.payload_json,
                       ch.name AS chapter_name, ch.paper_id,
                       p.code AS paper_code, p.name AS paper_name,
                       s.id AS subject_id, s.name AS subject_name, s.code AS subject_code
                FROM fc_blocks b
                JOIN fc_chapters ch ON ch.id = b.chapter_id
                JOIN fc_papers p    ON p.id  = ch.paper_id
                JOIN fc_subjects s  ON s.id  = p.subject_id
                {where}
                ORDER BY s.name, p.code, ch.order_index, ch.name, b.id
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()

        # Attach per-user progress if authenticated
        progress_map: dict[int, dict] = {}
        if user and rows:
            block_ids = [r["id"] for r in rows]
            ph = ",".join("?" for _ in block_ids)
            prog_rows = con.execute(
                f"SELECT block_id, status, saved_for_review, last_result, next_review_at "
                f"FROM fc_card_progress WHERE student_id = ? AND block_id IN ({ph})",
                [user["id"]] + block_ids,
            ).fetchall()
            progress_map = {
                r["block_id"]: {
                    "status": r["status"],
                    "saved": bool(r["saved_for_review"]),
                    "last_result": r["last_result"],
                    "next_review_at": r["next_review_at"],
                }
                for r in prog_rows
            }

    finally:
        con.close()

    blocks = []
    for r in rows:
        payload = json.loads(r["payload_json"] or "{}")
        b = {
            "id": r["id"],
            "type": r["type"],
            "topic_label": r["topic_label"],
            "chapter": {"id": r["chapter_id"], "name": r["chapter_name"]},
            "paper": {"id": r["paper_id"], "code": r["paper_code"], "name": r["paper_name"]},
            "subject": {"id": r["subject_id"], "name": r["subject_name"], "code": r["subject_code"]},
            "payload": payload,
            "progress": progress_map.get(r["id"]),
        }
        blocks.append(b)

    return {"blocks": blocks, "returned": len(blocks), "offset": offset}


# ── Study session — due cards ─────────────────────────────────────────────

@router.get("/api/fc/due")
def fc_due(
    chapter_ids: str = Query(""),   # comma-separated
    subject_id:  Optional[int] = Query(None),
    paper_id:    Optional[int] = Query(None),
    type_:       Optional[str] = Query(None, alias="type"),
    limit:       int = Query(30),
    user: dict = Depends(get_current_user),
):
    """Return due cards for a study session, SM-2 priority:
       1. overdue (next_review_at <= now)
       2. new (never reviewed)
    Only returns 'card' and 'def' blocks by default (studyable types).
    """
    _ensure_tables()

    cids = [int(x) for x in chapter_ids.split(",") if x.strip().isdigit()]

    con = _con()
    con.row_factory = sqlite3.Row
    try:
        now_iso = _now_iso()

        # Build scope filter
        scope_clauses: list[str] = []
        scope_params: list = []

        if cids:
            ph = ",".join("?" for _ in cids)
            scope_clauses.append(f"b.chapter_id IN ({ph})")
            scope_params.extend(cids)
        elif paper_id:
            scope_clauses.append("ch.paper_id = ?")
            scope_params.append(paper_id)
        elif subject_id:
            scope_clauses.append("p.subject_id = ?")
            scope_params.append(subject_id)

        # Default to studyable types unless caller specifies
        studyable = ["card", "def"]
        if type_ and type_ in ("card", "def", "formula", "list"):
            studyable = [type_]
        type_ph = ",".join("?" for _ in studyable)
        scope_clauses.append(f"b.type IN ({type_ph})")
        scope_params.extend(studyable)

        where = "WHERE " + " AND ".join(scope_clauses) if scope_clauses else ""

        # Overdue cards (progress row exists, next_review_at <= now, not mastered)
        overdue = con.execute(
            f"""SELECT b.id, b.type, b.payload_json, b.chapter_id,
                       ch.name AS chapter_name,
                       s.name AS subject_name, s.code AS subject_code,
                       cp.status, cp.ease_factor, cp.interval_days,
                       cp.times_reviewed, cp.next_review_at
                FROM fc_blocks b
                JOIN fc_chapters ch ON ch.id = b.chapter_id
                JOIN fc_papers   p  ON p.id  = ch.paper_id
                JOIN fc_subjects s  ON s.id  = p.subject_id
                JOIN fc_card_progress cp ON cp.block_id = b.id AND cp.student_id = ?
                {where}
                AND cp.status != 'mastered'
                AND cp.next_review_at <= ?
                ORDER BY cp.next_review_at ASC
                LIMIT ?""",
            [user["id"]] + scope_params + [now_iso, limit],
        ).fetchall()

        remaining = limit - len(overdue)
        new_cards = []
        if remaining > 0:
            # New cards (no progress row)
            overdue_ids = {r["id"] for r in overdue}
            new_cards = con.execute(
                f"""SELECT b.id, b.type, b.payload_json, b.chapter_id,
                           ch.name AS chapter_name,
                           s.name AS subject_name, s.code AS subject_code,
                           'new' AS status,
                           2.5 AS ease_factor, 0.0 AS interval_days,
                           0 AS times_reviewed, NULL AS next_review_at
                    FROM fc_blocks b
                    JOIN fc_chapters ch ON ch.id = b.chapter_id
                    JOIN fc_papers   p  ON p.id  = ch.paper_id
                    JOIN fc_subjects s  ON s.id  = p.subject_id
                    {where}
                    AND NOT EXISTS (
                        SELECT 1 FROM fc_card_progress cp
                        WHERE cp.block_id = b.id AND cp.student_id = ?
                    )
                    ORDER BY b.id ASC
                    LIMIT ?""",
                scope_params + [user["id"], remaining],
            ).fetchall()
            new_cards = [r for r in new_cards if r["id"] not in overdue_ids]

    finally:
        con.close()

    def _fmt(r):
        return {
            "id": r["id"],
            "type": r["type"],
            "payload": json.loads(r["payload_json"] or "{}"),
            "chapter": {"id": r["chapter_id"], "name": r["chapter_name"]},
            "subject": {"name": r["subject_name"], "code": r["subject_code"]},
            "status": r["status"],
            "times_reviewed": r["times_reviewed"],
            "next_review_at": r["next_review_at"],
        }

    cards = [_fmt(r) for r in overdue] + [_fmt(r) for r in new_cards]
    return {"cards": cards, "total": len(cards),
            "overdue": len(overdue), "new": len(new_cards)}


# ── Rating a card ─────────────────────────────────────────────────────────

class RateReq(BaseModel):
    block_id: int
    rating: str     # 'again' | 'hard' | 'good' | 'easy'


@router.post("/api/fc/rate")
def fc_rate(req: RateReq, user: dict = Depends(get_current_user)):
    """Apply SM-2 rating and update progress."""
    _ensure_tables()
    if req.rating not in ("again", "hard", "good", "easy"):
        raise HTTPException(400, "rating must be again|hard|good|easy")

    con = _con()
    con.row_factory = sqlite3.Row
    try:
        # Verify block exists
        blk = con.execute("SELECT id, type FROM fc_blocks WHERE id = ?",
                          (req.block_id,)).fetchone()
        if not blk:
            raise HTTPException(404, "block not found")

        # Load current state
        prog = con.execute(
            "SELECT ease_factor, interval_days, times_reviewed, times_correct "
            "FROM fc_card_progress WHERE student_id = ? AND block_id = ?",
            (user["id"], req.block_id),
        ).fetchone()

        state = _CardState(
            ease_factor=prog["ease_factor"] if prog else 2.5,
            interval_days=prog["interval_days"] if prog else 0.0,
            times_reviewed=prog["times_reviewed"] if prog else 0,
        )

        new_state, new_status, next_review = sm2_schedule(state, req.rating)
        correct = 1 if req.rating in ("good", "easy") else 0

        # Upsert progress
        if _db.USE_PG:
            con.execute(
                """INSERT INTO fc_card_progress
                       (student_id, block_id, status, times_reviewed, times_correct,
                        ease_factor, interval_days, next_review_at, last_result, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,now()::text)
                   ON CONFLICT (student_id, block_id) DO UPDATE SET
                       status=EXCLUDED.status, times_reviewed=EXCLUDED.times_reviewed,
                       times_correct=EXCLUDED.times_correct, ease_factor=EXCLUDED.ease_factor,
                       interval_days=EXCLUDED.interval_days, next_review_at=EXCLUDED.next_review_at,
                       last_result=EXCLUDED.last_result, updated_at=now()::text""",
                (user["id"], req.block_id, new_status,
                 new_state.times_reviewed,
                 (prog["times_correct"] if prog else 0) + correct,
                 new_state.ease_factor, new_state.interval_days,
                 next_review, req.rating),
            )
        else:
            con.execute(
                """INSERT INTO fc_card_progress
                       (student_id, block_id, status, times_reviewed, times_correct,
                        ease_factor, interval_days, next_review_at, last_result, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))
                   ON CONFLICT(student_id, block_id) DO UPDATE SET
                       status=excluded.status, times_reviewed=excluded.times_reviewed,
                       times_correct=excluded.times_correct, ease_factor=excluded.ease_factor,
                       interval_days=excluded.interval_days, next_review_at=excluded.next_review_at,
                       last_result=excluded.last_result, updated_at=datetime('now')""",
                (user["id"], req.block_id, new_status,
                 new_state.times_reviewed,
                 (prog["times_correct"] if prog else 0) + correct,
                 new_state.ease_factor, new_state.interval_days,
                 next_review, req.rating),
            )

        # Log review event
        con.execute(
            "INSERT INTO fc_review_events (student_id, block_id, rating) VALUES (?,?,?)",
            (user["id"], req.block_id, req.rating),
        )
        con.commit()

        # Update streak
        _update_streak(con, user["id"])

    finally:
        con.close()

    return {
        "status": new_status,
        "interval_days": new_state.interval_days,
        "next_review_at": next_review,
        "ease_factor": new_state.ease_factor,
    }


# ── Save / star a block ───────────────────────────────────────────────────

class SaveReq(BaseModel):
    block_id: int
    saved: bool


@router.post("/api/fc/save")
def fc_save(req: SaveReq, user: dict = Depends(get_current_user)):
    _ensure_tables()
    con = _con()
    try:
        if _db.USE_PG:
            con.execute(
                """INSERT INTO fc_card_progress (student_id, block_id, saved_for_review)
                   VALUES (%s,%s,%s)
                   ON CONFLICT(student_id, block_id) DO UPDATE SET saved_for_review=EXCLUDED.saved_for_review""",
                (user["id"], req.block_id, int(req.saved)),
            )
        else:
            con.execute(
                """INSERT INTO fc_card_progress (student_id, block_id, saved_for_review)
                   VALUES (?,?,?)
                   ON CONFLICT(student_id, block_id) DO UPDATE SET saved_for_review=excluded.saved_for_review""",
                (user["id"], req.block_id, int(req.saved)),
            )
        con.commit()
    finally:
        con.close()
    return {"saved": req.saved}


# ── Session end ───────────────────────────────────────────────────────────

class SessionEndReq(BaseModel):
    scope_json: Optional[str] = None
    started_at: Optional[str] = None
    cards_reviewed: int = 0
    cards_aced: int = 0


@router.post("/api/fc/session/end")
def fc_session_end(req: SessionEndReq, user: dict = Depends(get_current_user)):
    _ensure_tables()
    con = _con()
    try:
        con.execute(
            "INSERT INTO fc_study_sessions (student_id, scope_json, started_at, ended_at, cards_reviewed, cards_aced) "
            "VALUES (?,?,?,datetime('now'),?,?)",
            (user["id"], req.scope_json, req.started_at or _now_iso(),
             req.cards_reviewed, req.cards_aced),
        )
        con.commit()
    finally:
        con.close()
    return {"ok": True}


# ── Progress ──────────────────────────────────────────────────────────────

@router.get("/api/fc/progress")
def fc_progress(
    subject_id: Optional[int] = Query(None),
    user: dict = Depends(get_current_user),
):
    _ensure_tables()
    con = _con()
    con.row_factory = sqlite3.Row
    try:
        # Streak
        streak_row = con.execute(
            "SELECT current_streak, longest_streak, last_active_date "
            "FROM fc_streaks WHERE student_id = ?",
            (user["id"],),
        ).fetchone()
        streak = dict(streak_row) if streak_row else {
            "current_streak": 0, "longest_streak": 0, "last_active_date": None
        }

        # Reviews today / this week / all-time
        today = _today_str()
        week_start = (date.today() - timedelta(days=6)).isoformat()
        counts = con.execute(
            """SELECT
               COUNT(*) FILTER (WHERE DATE(reviewed_at) = ?)          AS today,
               COUNT(*) FILTER (WHERE DATE(reviewed_at) >= ?)         AS week,
               COUNT(*)                                                AS all_time
               FROM fc_review_events WHERE student_id = ?""",
            (today, week_start, user["id"]),
        ).fetchone() if _db.USE_PG else con.execute(
            """SELECT
               SUM(CASE WHEN DATE(reviewed_at) = ? THEN 1 ELSE 0 END)  AS today,
               SUM(CASE WHEN DATE(reviewed_at) >= ? THEN 1 ELSE 0 END) AS week,
               COUNT(*)                                                  AS all_time
               FROM fc_review_events WHERE student_id = ?""",
            (today, week_start, user["id"]),
        ).fetchone()

        # Mastery breakdown per chapter
        extra = "AND s.id = ?" if subject_id else ""
        extra_params = [subject_id] if subject_id else []

        mastery_rows = con.execute(
            f"""SELECT ch.id, ch.name AS chapter_name,
                       s.name AS subject_name, s.code AS subject_code, s.alt_codes_json AS alt_codes_json,
                       p.name AS paper_name, p.code AS paper_code,
                       COUNT(b.id) AS total_blocks,
                       SUM(CASE WHEN cp.status = 'mastered' THEN 1 ELSE 0 END) AS mastered,
                       SUM(CASE WHEN cp.status = 'review'   THEN 1 ELSE 0 END) AS in_review,
                       SUM(CASE WHEN cp.status = 'learning' THEN 1 ELSE 0 END) AS learning,
                       SUM(CASE WHEN cp.status IS NULL OR cp.status = 'new' THEN 1 ELSE 0 END) AS new_count
                FROM fc_chapters ch
                JOIN fc_papers   p  ON p.id  = ch.paper_id
                JOIN fc_subjects s  ON s.id  = p.subject_id
                JOIN fc_blocks   b  ON b.chapter_id = ch.id
                LEFT JOIN fc_card_progress cp
                    ON cp.block_id = b.id AND cp.student_id = ?
                {f'WHERE {extra[4:]}' if extra else 'WHERE 1=1'}
                GROUP BY ch.id, ch.name, s.name, s.code, s.alt_codes_json, p.name, p.code, ch.order_index
                ORDER BY s.name, p.code, ch.order_index, ch.name""",
            [user["id"]] + extra_params,
        ).fetchall()

        if user:
            from . import users_db as _udb
            import json as _json
            active_codes = set(_udb.get_enrollments(user["id"]))
            filtered = []
            for r in mastery_rows:
                alt = _json.loads(r["alt_codes_json"] or "[]")
                if r["subject_code"] in active_codes or any(c in active_codes for c in alt):
                    filtered.append(r)
            mastery_rows = filtered

        mastery = [
            {
                "chapter_id": r["id"],
                "chapter_name": r["chapter_name"],
                "subject": r["subject_name"],
                "subject_code": r["subject_code"],
                "paper": r["paper_name"],
                "paper_code": r["paper_code"],
                "total": r["total_blocks"],
                "mastered": r["mastered"] or 0,
                "in_review": r["in_review"] or 0,
                "learning": r["learning"] or 0,
                "new": r["new_count"] or 0,
                "pct": round((r["mastered"] or 0) / r["total_blocks"] * 100)
                       if r["total_blocks"] else 0,
            }
            for r in mastery_rows
        ]

        # Weak topics — chapters with lowest accuracy among reviewed blocks
        weak = sorted(
            [m for m in mastery if m["mastered"] + m["in_review"] + m["learning"] > 0],
            key=lambda m: m["pct"],
        )[:10]

        # Session history (last 10)
        sessions = con.execute(
            "SELECT id, scope_json, started_at, ended_at, cards_reviewed, cards_aced "
            "FROM fc_study_sessions WHERE student_id = ? "
            "ORDER BY started_at DESC LIMIT 10",
            (user["id"],),
        ).fetchall()
        sessions_out = [dict(r) for r in sessions]

    finally:
        con.close()

    return {
        "streak": streak,
        "reviews": {
            "today": counts["today"] or 0,
            "week": counts["week"] or 0,
            "all_time": counts["all_time"] or 0,
        },
        "mastery": mastery,
        "weak_topics": weak,
        "sessions": sessions_out,
    }


# ── Quiz generation ───────────────────────────────────────────────────────

@router.get("/api/fc/quiz")
def fc_quiz(
    chapter_ids: str = Query(""),
    subject_id:  Optional[int] = Query(None),
    paper_id:    Optional[int] = Query(None),
    count:       int = Query(10),
    user: dict = Depends(get_current_user),
):
    """Generate MCQ questions from CARD blocks in the current scope.
    Correct answer = the card's A field.
    Distractors = answers from other cards in the same chapter(s).
    """
    _ensure_tables()
    if count > 40:
        count = 40

    cids = [int(x) for x in chapter_ids.split(",") if x.strip().isdigit()]
    con = _con()
    con.row_factory = sqlite3.Row
    try:
        clauses, params = ["b.type = 'card'"], []

        if cids:
            ph = ",".join("?" for _ in cids)
            clauses.append(f"b.chapter_id IN ({ph})")
            params.extend(cids)
        elif paper_id:
            clauses.append("ch.paper_id = ?")
            params.append(paper_id)
        elif subject_id:
            clauses.append("p.subject_id = ?")
            params.append(subject_id)

        where = "WHERE " + " AND ".join(clauses)

        rows = con.execute(
            f"""SELECT b.id, b.payload_json, b.chapter_id,
                       ch.name AS chapter_name
                FROM fc_blocks b
                JOIN fc_chapters ch ON ch.id = b.chapter_id
                JOIN fc_papers   p  ON p.id  = ch.paper_id
                JOIN fc_subjects s  ON s.id  = p.subject_id
                {where}
                ORDER BY RANDOM()
                LIMIT ?""",
            params + [count * 3],   # pull extra so we have distractors
        ).fetchall()

    finally:
        con.close()

    if len(rows) < 2:
        raise HTTPException(400, "Not enough cards in this scope to generate a quiz")

    rng = random.SystemRandom()
    rows = list(rows)
    rng.shuffle(rows)
    questions = rows[:count]
    distractor_pool = rows  # may overlap; filtered per question

    out = []
    for q in questions:
        payload = json.loads(q["payload_json"] or "{}")
        question_text = payload.get("question", "")
        correct_answer = payload.get("answer", "")

        # Pick 3 distractors from other cards
        others = [
            json.loads(r["payload_json"] or "{}").get("answer", "")
            for r in distractor_pool
            if r["id"] != q["id"]
        ]
        others = list({o for o in others if o and o != correct_answer})
        rng.shuffle(others)
        distractors = others[:3]

        if len(distractors) < 1:
            continue

        # Pad to 4 options if fewer distractors available
        options = ([correct_answer] + distractors)[:4]
        rng.shuffle(options)
        correct_idx = options.index(correct_answer)

        out.append({
            "block_id": q["id"],
            "chapter": {"id": q["chapter_id"], "name": q["chapter_name"]},
            "question": question_text,
            "options": options,
            "correct_index": correct_idx,
        })

    return {"questions": out, "total": len(out)}


class QuizResultItem(BaseModel):
    block_id: int
    correct: bool


class QuizResultReq(BaseModel):
    items: list[QuizResultItem]


@router.post("/api/fc/quiz/result")
def fc_quiz_result(req: QuizResultReq, user: dict = Depends(get_current_user)):
    """Record quiz results: correct → 'good' rating, wrong → 'again' rating."""
    _ensure_tables()
    con = _con()
    con.row_factory = sqlite3.Row
    try:
        for item in req.items:
            blk = con.execute("SELECT id FROM fc_blocks WHERE id = ?",
                              (item.block_id,)).fetchone()
            if not blk:
                continue
            rating = "good" if item.correct else "again"
            prog = con.execute(
                "SELECT ease_factor, interval_days, times_reviewed, times_correct "
                "FROM fc_card_progress WHERE student_id = ? AND block_id = ?",
                (user["id"], item.block_id),
            ).fetchone()
            state = _CardState(
                ease_factor=prog["ease_factor"] if prog else 2.5,
                interval_days=prog["interval_days"] if prog else 0.0,
                times_reviewed=prog["times_reviewed"] if prog else 0,
            )
            new_state, new_status, next_review = sm2_schedule(state, rating)
            correct_inc = 1 if item.correct else 0

            if _db.USE_PG:
                con.execute(
                    """INSERT INTO fc_card_progress
                           (student_id, block_id, status, times_reviewed, times_correct,
                            ease_factor, interval_days, next_review_at, last_result, updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,now()::text)
                       ON CONFLICT(student_id, block_id) DO UPDATE SET
                           status=EXCLUDED.status, times_reviewed=EXCLUDED.times_reviewed,
                           times_correct=EXCLUDED.times_correct, ease_factor=EXCLUDED.ease_factor,
                           interval_days=EXCLUDED.interval_days, next_review_at=EXCLUDED.next_review_at,
                           last_result=EXCLUDED.last_result, updated_at=now()::text""",
                    (user["id"], item.block_id, new_status, new_state.times_reviewed,
                     (prog["times_correct"] if prog else 0) + correct_inc,
                     new_state.ease_factor, new_state.interval_days, next_review, rating),
                )
            else:
                con.execute(
                    """INSERT INTO fc_card_progress
                           (student_id, block_id, status, times_reviewed, times_correct,
                            ease_factor, interval_days, next_review_at, last_result, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))
                       ON CONFLICT(student_id, block_id) DO UPDATE SET
                           status=excluded.status, times_reviewed=excluded.times_reviewed,
                           times_correct=excluded.times_correct, ease_factor=excluded.ease_factor,
                           interval_days=excluded.interval_days, next_review_at=excluded.next_review_at,
                           last_result=excluded.last_result, updated_at=datetime('now')""",
                    (user["id"], item.block_id, new_status, new_state.times_reviewed,
                     (prog["times_correct"] if prog else 0) + correct_inc,
                     new_state.ease_factor, new_state.interval_days, next_review, rating),
                )
            con.execute(
                "INSERT INTO fc_review_events (student_id, block_id, rating) VALUES (?,?,?)",
                (user["id"], item.block_id, rating),
            )

        con.commit()
        _update_streak(con, user["id"])
    finally:
        con.close()

    return {"ok": True, "processed": len(req.items)}


# ── Streak helper ─────────────────────────────────────────────────────────

def _update_streak(con, student_id: str) -> None:
    """Update the streak for a student after a review. Best-effort."""
    try:
        today = _today_str()
        row = con.execute(
            "SELECT current_streak, longest_streak, last_active_date "
            "FROM fc_streaks WHERE student_id = ?",
            (student_id,),
        ).fetchone()
        if row is None:
            con.execute(
                "INSERT INTO fc_streaks (student_id, current_streak, longest_streak, last_active_date) "
                "VALUES (?,1,1,?) ON CONFLICT(student_id) DO NOTHING",
                (student_id, today),
            )
            return

        last = row["last_active_date"]
        current = row["current_streak"]
        longest = row["longest_streak"]

        if last == today:
            return  # already counted today
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        if last == yesterday:
            current += 1
        else:
            current = 1   # streak broken

        longest = max(longest, current)
        con.execute(
            "UPDATE fc_streaks SET current_streak=?, longest_streak=?, last_active_date=? "
            "WHERE student_id=?",
            (current, longest, today, student_id),
        )
    except Exception:
        pass  # streak failure must never break a rating call
