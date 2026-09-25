"""PrepWithTee student portal - FastAPI backend.

Serves the static frontend and wraps the pipeline CLIs:
  GET  /api/meta      live subjects, topics (with question counts), year range
  POST /api/generate  build a topical booklet or topic test, stream it back

PDF generation shells out to `python -m pipeline.compose` / `pipeline.testgen`
rather than importing their mains: the CLIs are the tested interface, and each
request gets a clean process. Subjects are discovered from the database, so a
newly classified syllabus appears on the site with zero code changes.

Run:  python -m uvicorn app:app --app-dir website --port 8017   (from repo root)
"""

import hashlib
import json
import os
import random
import re
import secrets
import shutil
import sqlite3
import smtplib
import subprocess
import sys
import tempfile

# When gunicorn loads this as website.app:app from the project root, the
# website/ directory is not on sys.path, so sibling modules (db, auth,
# users_db, …) need it to be added explicitly.
_website_dir = os.path.dirname(os.path.abspath(__file__))
if _website_dir not in sys.path:
    sys.path.insert(0, _website_dir)
import threading
import time
import zipfile
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator
from starlette.background import BackgroundTask

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "index.db"

# ── Dual-mode DB: psycopg2 (Supabase) or SQLite ────────────────────────────
import db as _db
_USE_PG = _db.USE_PG

def _con():
    """Open a pipeline DB connection.  Caller must call .close()."""
    return _db.plain_connect()
YEAR_MIN, YEAR_MAX = 2010, 2026

# Display names for each paper component. The components actually offered are
# read from the database (only papers with classified questions appear), so a
# syllabus missing from this map still works - it just gets plain "P1"/"P2"
# labels. Each component carries its own topic list: 9709 P5 (Statistics) and
# P1 (Pure 1) share almost nothing, so the topic grid is filtered per paper.
PAPER_LABELS = {
    "9709": {1: "P1 · Pure 1", 3: "P3 · Pure 3",
             4: "P4 · Mechanics", 5: "P5 · Statistics"},
    "9702": {1: "P1 · MCQ", 2: "P2 · AS Structured",
             4: "P4 · A Level", 5: "P5 · Planning"},
    "9618": {1: "P1 · Theory", 2: "P2 · Problem-solving",
             3: "P3 · Advanced Theory", 4: "P4 · Practical"},
    "0580": {2: "P2 · Extended", 4: "P4 · Extended"},
    "0625": {1: "P1 · MCQ Core", 2: "P2 · MCQ Extended", 4: "P4 · Extended"},
    "5054": {1: "P1 · MCQ", 2: "P2 · Theory"},
    "5070": {1: "P1 · MCQ", 2: "P2 · Theory"},
    "0620": {1: "P1 · MCQ Core", 2: "P2 · MCQ Extended",
             3: "P3 · Theory Core", 4: "P4 · Theory Extended"},
    "2210": {1: "P1 · Theory", 2: "P2 · Problem-solving"},
    "0478": {1: "P1 · Theory", 2: "P2 · Problem-solving"},
    # These two examine different content per component, so the labels are what
    # the student actually revises from, not just a paper number.
    "2058": {1: "P1 · Qur'an & the Prophet", 2: "P2 · Hadith & the Caliphs"},
    "2059": {1: "P1 · History of Pakistan", 2: "P2 · Environment of Pakistan"},
}

app = FastAPI(title="PrepWithTee")

import admin as _admin_mod, auth as _auth_mod, users as _users_mod, access as _access_mod, teacher as _teacher_mod, blog as _blog_mod, flashcards as _fc_mod
from auth import get_current_user as _get_current_user
from fastapi import Depends as _Depends
app.include_router(_auth_mod.router)
app.include_router(_users_mod.router)
app.include_router(_admin_mod.router)
app.include_router(_teacher_mod.router)
app.include_router(_blog_mod.router)
app.include_router(_fc_mod.router)
import catalog as _catalog_mod
import booklets as _booklets_mod
# booklets first: /papers/view/{id} must win over catalog's /papers/{board}/{subject}
app.include_router(_booklets_mod.router)
import ai_help as _ai_help_mod
app.include_router(_ai_help_mod.router)
import yearly as _yearly_mod
app.include_router(_yearly_mod.router)
app.include_router(_catalog_mod.router)

# ── Public course catalog ─────────────────────────────────────────────────────

from fastapi import HTTPException as _HTTPException

@app.get("/api/courses")
def public_courses():
    """Published courses for the public course page and pricing catalog."""
    import users_db as _udb
    return {"courses": _udb.get_all_courses(published_only=True)}


@app.get("/api/courses/{slug}")
def public_course(slug: str):
    """Single published course by slug — powers /course.html."""
    import users_db as _udb
    course = _udb.get_course_by_slug(slug)
    if course is None or not course.get("published"):
        raise _HTTPException(404, "Course not found or not published")
    return {"course": course}


class GenerateReq(BaseModel):
    mode: str                          # "topical" | "test"
    syllabus: str
    topics: list[str]
    subtopics: list[str] | None = None     # fine-grained subtopic filter
    year_from: int = YEAR_MIN
    year_to: int = YEAR_MAX
    papers: list[int] | None = None        # multi-paper filter [1,2] etc.
    paper: int | None = None               # legacy single-paper alias
    count: int | None = None               # test: number of questions
    marks: int | None = None               # test: fill to target marks (wins over count)
    seed: int | None = None
    include_ms: bool = True                # topical only
    sessions: list[str] | None = None      # [] or None = all; ["s","w"] = M/J + Oct/Nov
    variants: list[str] | None = None      # [] or None = all; ["1","2"] = v1 + v2
    contains: str | None = None            # regex keyword filter (cross-topic search)
    question_ids: list[int] | None = None  # preview-and-curate: skip random sampling
    # Legacy single-value aliases kept for backward compatibility
    session: str | None = None
    variant: str | None = None

    @field_validator("syllabus")
    @classmethod
    def _check_syllabus(cls, v: str) -> str:
        if not re.match(r"^[0-9A-Za-z]{4,6}$", v):
            raise ValueError("invalid syllabus code")
        return v

    @field_validator("contains")
    @classmethod
    def _check_contains(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if len(v) > 200:
            raise ValueError("contains pattern too long (max 200 chars)")
        # Reject nested quantifiers that cause catastrophic backtracking
        if re.search(r"\([^)]*[+*{][^)]*\)[+*{]", v):
            raise ValueError("contains pattern is too complex")
        try:
            re.compile(v, re.I)
        except re.error as exc:
            raise ValueError(f"invalid regex: {exc}")
        return v


class QuestionListReq(BaseModel):
    """Filters for the preview step — returns metadata, no PDF."""
    syllabus: str
    topics: list[str]
    subtopics: list[str] | None = None
    year_from: int = YEAR_MIN
    year_to: int = YEAR_MAX
    papers: list[int] | None = None
    count: int | None = None
    marks: int | None = None
    seed: int | None = None
    sessions: list[str] | None = None
    variants: list[str] | None = None
    contains: str | None = None

    @field_validator("syllabus")
    @classmethod
    def _check_syllabus(cls, v: str) -> str:
        if not re.match(r"^[0-9A-Za-z]{4,6}$", v):
            raise ValueError("invalid syllabus code")
        return v

    @field_validator("contains")
    @classmethod
    def _check_contains(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if len(v) > 200:
            raise ValueError("contains pattern too long")
        if re.search(r"\([^)]*[+*{][^)]*\)[+*{]", v):
            raise ValueError("contains pattern is too complex")
        try:
            re.compile(v, re.I)
        except re.error as exc:
            raise ValueError(f"invalid regex: {exc}")
        return v


def _question_pool(req, con):
    """Shared query used by /api/questions and reused by generate when ids absent."""
    syllabuses = [req.syllabus]
    marks_ph = ",".join("?" for _ in syllabuses)

    sessions = [s for s in (req.sessions or []) if s and s != "all"]
    variants = [v for v in (req.variants or []) if v and v != "all"]
    papers_list = list(req.papers or [])

    session_clause = (f" AND p.session IN ({','.join('?' for _ in sessions)})"
                      if sessions else "")
    variant_clause = (f" AND p.variant IN ({','.join('?' for _ in variants)})"
                      if variants else "")
    paper_clause = (f" AND p.paper IN ({','.join('?' for _ in papers_list)})"
                    if papers_list else "")

    rows = con.execute(
        f"""
        SELECT q.id, q.number, q.sub_part, q.marks, q.text, c.topic,
               c.secondary_topic, c.subtopic, p.syllabus, p.year,
               p.session, p.paper, p.variant
        FROM questions q
        JOIN classifications c ON c.question_id = q.id
        JOIN papers p ON p.id = q.paper_id
        WHERE p.syllabus IN ({marks_ph}) AND p.kind = 'qp'
          AND p.year BETWEEN ? AND ?
          AND q.status IS NOT 'excluded'
        """ + paper_clause + session_clause + variant_clause
        + " ORDER BY p.year, p.session, p.variant, q.number",
        [*syllabuses, req.year_from, req.year_to]
        + papers_list + sessions + variants
    ).fetchall()

    if req.contains:
        try:
            pat = re.compile(req.contains, re.I)
        except re.error:
            raise HTTPException(400, "invalid contains regex")
        rows = [r for r in rows if pat.search(r["text"] or "")]

    subtopic_filter = set(req.subtopics or [])
    pool, seen = [], set()
    topics_list = req.topics
    for r in rows:
        if r["id"] in seen:
            continue
        home = (next((t for t in topics_list if r["topic"] == t), None)
                or next((t for t in topics_list if r["secondary_topic"] == t), None))
        if home:
            if subtopic_filter and r["subtopic"] not in subtopic_filter:
                continue
            pool.append(r)
            seen.add(r["id"])
    return pool


def _apply_random_selection(pool, count, marks, seed):
    """Weighted random selection mirroring testgen.select()."""
    if not pool:
        return []
    rng = random.Random(seed)

    def _key(q):
        w = 1.5 ** ((q["year"] or YEAR_MIN) - YEAR_MIN)
        return rng.random() ** (1.0 / w)

    order = sorted(pool, key=_key, reverse=True)
    if marks:
        chosen, total = [], 0
        for q in order:
            chosen.append(q)
            total += q["marks"] or 0
            if total >= marks:
                break
    else:
        k = min(count or 6, len(pool))
        chosen = order[:k]
    chosen.sort(key=lambda q: (q["year"], q["session"], q["variant"], q["number"]))
    return chosen


_SESSION_ABBR = {"s": "M/J", "w": "O/N", "m": "F/M"}

# ── MCQ Live Solver endpoints ─────────────────────────────────────────────────

@app.get("/api/mcq/answer/{question_id}")
def mcq_answer(question_id: int):
    """Return the stored MCQ answer letter for a question.

    ms_entries.answer is populated by `python -m pipeline.mcq` for every MCQ
    mark-scheme PDF. Returns {"answer": "B", "has_answer": true} or
    {"answer": null, "has_answer": false} when the pipeline hasn't run yet for
    that paper.
    """
    con = _con()
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            """SELECT m.answer, m.crop_path IS NOT NULL AS has_crop,
                      q.number, q.sub_part,
                      p.syllabus, p.year, p.session, p.paper, p.variant
               FROM questions q
               JOIN papers p ON p.id = q.paper_id
               LEFT JOIN ms_entries m ON (
                   m.paper_id = (
                       SELECT p2.id FROM papers p2
                       WHERE p2.syllabus = p.syllabus AND p2.year = p.year
                         AND p2.session = p.session AND p2.paper = p.paper
                         AND p2.variant = p.variant AND p2.kind = 'ms'
                   )
                   AND m.question_number = q.number
                   AND m.sub_part = q.sub_part
               )
               WHERE q.id = ?""",
            (question_id,)).fetchone()
    finally:
        con.close()

    if row is None:
        raise HTTPException(404, "question not found")

    return {
        "question_id": question_id,
        "answer": row["answer"],           # "A" | "B" | "C" | "D" | null
        "has_answer": row["answer"] is not None,
        "has_ms_crop": bool(row["has_crop"]),
    }


class MCQSessionReq(BaseModel):
    """Filters for the MCQ solver — topic mode or full-paper mode."""
    syllabus: str
    topics: list[str] = []
    subtopics: list[str] | None = None
    year_from: int = YEAR_MIN
    year_to: int = YEAR_MAX
    papers: list[int] | None = None
    count: int | None = None
    seed: int | None = None
    sessions: list[str] | None = None
    variants: list[str] | None = None
    paper_id: int | None = None       # full-paper mode: DB id of the QP paper

    @field_validator("syllabus")
    @classmethod
    def _check_syllabus(cls, v: str) -> str:
        if not re.match(r"^[0-9A-Za-z]{4,6}$", v):
            raise ValueError("invalid syllabus code")
        return v


@app.get("/api/mcq/papers")
def mcq_papers_list(syllabus: str = Query(...)):
    """Return all QP papers for a syllabus that have questions segmented.

    Used by the MCQ Live Solver "Full Past Paper" mode to populate the
    year + variant picker.  Client filters to MCQ-only papers with isMCQPaper().
    """
    if not re.match(r"^[0-9A-Za-z]{4,6}$", syllabus):
        raise HTTPException(400, "invalid syllabus")
    con = _con()
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """SELECT p.id, p.year, p.session, p.paper, p.variant,
                      COUNT(q.id) AS q_count
               FROM papers p
               JOIN questions q ON q.paper_id = p.id
               WHERE p.syllabus = ? AND p.kind = 'qp'
                 AND q.status IS NOT 'excluded'
               GROUP BY p.id, p.year, p.session, p.paper, p.variant
               ORDER BY p.year DESC, p.session, p.paper, p.variant""",
            (syllabus,)).fetchall()
    finally:
        con.close()
    abbr = _SESSION_ABBR
    papers = [
        {"id": p["id"], "year": p["year"], "session": p["session"],
         "paper": p["paper"], "variant": p["variant"],
         "session_label": abbr.get(p["session"], p["session"].upper()),
         "q_count": p["q_count"]}
        for p in rows if p["q_count"] > 0
    ]
    return {"papers": papers}


@app.post("/api/mcq/questions")
def mcq_questions(req: MCQSessionReq):
    """Return MCQ questions with their stored answer letters.

    Topic mode: random selection from topic pool (default 40 questions).
    Full-paper mode: all questions from a specific QP in order (req.paper_id set).
    Attaches `answer` (A/B/C/D or null) and `has_answer` to each row.
    """
    # ── Full-paper mode ────────────────────────────────────────────────────────
    if req.paper_id is not None:
        con = _con()
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(
                """SELECT q.id, q.number, q.sub_part, q.marks, q.text,
                          c.topic, c.subtopic,
                          p.syllabus, p.year, p.session, p.paper, p.variant
                   FROM questions q
                   JOIN papers p ON p.id = q.paper_id
                   LEFT JOIN classifications c ON c.question_id = q.id
                   WHERE p.id = ? AND p.kind = 'qp'
                     AND q.status IS NOT 'excluded'
                   ORDER BY q.number""",
                (req.paper_id,)).fetchall()
            if not rows:
                raise HTTPException(404, "No questions found for this paper.")
            qids = [r["id"] for r in rows]
            ph = ",".join("?" for _ in qids)
            answer_rows = con.execute(
                f"""SELECT q.id AS qid, m.answer
                    FROM questions q
                    JOIN papers p ON p.id = q.paper_id
                    LEFT JOIN ms_entries m ON (
                        m.paper_id = (
                            SELECT p2.id FROM papers p2
                            WHERE p2.syllabus = p.syllabus AND p2.year = p.year
                              AND p2.session = p.session AND p2.paper = p.paper
                              AND p2.variant = p.variant AND p2.kind = 'ms'
                        )
                        AND m.question_number = q.number
                        AND m.sub_part = q.sub_part
                    )
                    WHERE q.id IN ({ph})""",
                qids).fetchall()
            answer_map = {r["qid"]: r["answer"] for r in answer_rows}
        finally:
            con.close()
        abbr = _SESSION_ABBR
        questions = []
        for q in rows:
            sa = abbr.get(q["session"], q["session"].upper())
            ref = (f"{q['syllabus']}/P{q['paper']} {sa} {q['year']} "
                   f"Q{q['number']}{('(' + q['sub_part'] + ')') if q['sub_part'] else ''}")
            answer = answer_map.get(q["id"])
            questions.append({
                "id": q["id"], "ref": ref,
                "year": q["year"], "session": q["session"],
                "paper": q["paper"], "variant": q["variant"],
                "number": q["number"], "sub_part": q["sub_part"],
                "topic": q["topic"] or "MCQ", "subtopic": q["subtopic"],
                "marks": q["marks"] or 1,
                "text_snippet": (q["text"] or "")[:160].strip(),
                "answer": answer, "has_answer": answer is not None,
            })
        return {
            "questions": questions,
            "total_marks": len(questions),
            "pool_size": len(questions),
            "seed": None,
            "has_answers": any(q["has_answer"] for q in questions),
        }

    # ── Topic mode ─────────────────────────────────────────────────────────────
    if not req.topics:
        raise HTTPException(400, "pick at least one topic")

    # Reuse the shared question pool logic via a compatible object
    class _Compat:
        syllabus = req.syllabus
        topics = req.topics
        subtopics = req.subtopics
        year_from = req.year_from
        year_to = req.year_max if hasattr(req, 'year_max') else req.year_to
        papers = req.papers or []
        sessions = req.sessions or []
        variants = req.variants or []
        contains = None

    compat = _Compat()
    compat.year_to = req.year_to

    con = _con()
    con.row_factory = sqlite3.Row
    try:
        pool = _question_pool(compat, con)

        # Apply random selection (default 40 for MCQ, otherwise user's count)
        k = req.count or 40
        seed = req.seed
        chosen = _apply_random_selection(pool, k, None, seed)

        # Attach the stored MCQ answer letter from ms_entries
        # Build a lookup: (paper_id → ms_paper_id) so one query covers all
        if chosen:
            qids = [q["id"] for q in chosen]
            ph = ",".join("?" for _ in qids)
            answer_rows = con.execute(
                f"""SELECT q.id AS qid, m.answer
                    FROM questions q
                    JOIN papers p ON p.id = q.paper_id
                    LEFT JOIN ms_entries m ON (
                        m.paper_id = (
                            SELECT p2.id FROM papers p2
                            WHERE p2.syllabus = p.syllabus AND p2.year = p.year
                              AND p2.session = p.session AND p2.paper = p.paper
                              AND p2.variant = p.variant AND p2.kind = 'ms'
                        )
                        AND m.question_number = q.number
                        AND m.sub_part = q.sub_part
                    )
                    WHERE q.id IN ({ph})""",
                qids).fetchall()
            answer_map = {r["qid"]: r["answer"] for r in answer_rows}
        else:
            answer_map = {}

    finally:
        con.close()

    sess_abbr = _SESSION_ABBR
    questions = []
    for q in chosen:
        sa = sess_abbr.get(q["session"], q["session"].upper())
        ref = (f"{q['syllabus']}/P{q['paper']} {sa} {q['year']} "
               f"Q{q['number']}{('(' + q['sub_part'] + ')') if q['sub_part'] else ''}")
        snippet = (q["text"] or "")[:160].strip()
        answer = answer_map.get(q["id"])
        questions.append({
            "id": q["id"],
            "ref": ref,
            "year": q["year"],
            "session": q["session"],
            "paper": q["paper"],
            "variant": q["variant"],
            "number": q["number"],
            "sub_part": q["sub_part"],
            "topic": q["topic"],
            "subtopic": q["subtopic"],
            "marks": q["marks"],
            "text_snippet": snippet,
            "answer": answer,            # "A"|"B"|"C"|"D"|null
            "has_answer": answer is not None,
        })

    return {
        "questions": questions,
        "total_marks": len(questions),   # MCQ: 1 mark each
        "pool_size": len(pool),
        "seed": seed,
        "has_answers": any(q["has_answer"] for q in questions),
    }


# ── MCQ PDF stitch ─────────────────────────────────────────────────────────────

class MCQPreviewPdfReq(BaseModel):
    question_ids: list[int]

    @field_validator("question_ids")
    @classmethod
    def _check_ids(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("at least one question id required")
        if len(v) > 200:
            raise ValueError("max 200 questions")
        return v


@app.post("/api/mcq/preview-pdf")
def mcq_preview_pdf(req: MCQPreviewPdfReq):
    """Build an A4-layout exam-style PDF with branding, watermark, and headers.

    Uses the same Booklet-style layout as compose.py: each question gets a
    Q1/Q2/... header, pages carry the PrepWithTee watermark, and a footer
    with page number and brand name.
    """
    import fitz

    PAGE_W, PAGE_H = 595.28, 841.89
    MARGIN_X = 24.0
    TOP_Y = 40.0
    BOTTOM_Y = PAGE_H - 40.0
    CONTENT_W = PAGE_W - 2 * MARGIN_X
    Q_HEADER_H = 18.0
    DIVIDER_GAP = 14.0
    ACCENT = (0.161, 0.208, 0.329)
    GREY = (0.35, 0.35, 0.35)
    GOLD = (0.957, 0.651, 0.196)
    BRAND = "PrepWithTee"
    WM_STRENGTH = 0.12
    WM_TEXT_GREY = 0.92
    LOGO_PATH = ROOT / "website" / "static" / "prepwithtee-logo.png"
    LOGO_OWL_CLIP = (414, 252, 786, 834)

    _wm_cache = getattr(mcq_preview_pdf, "_wm_cache", {})
    mcq_preview_pdf._wm_cache = _wm_cache

    def _watermark(pg):
        if LOGO_PATH.exists():
            if "owl" not in _wm_cache:
                clip = fitz.IRect(*LOGO_OWL_CLIP)
                src = fitz.Pixmap(str(LOGO_PATH))
                rgb = fitz.Pixmap(fitz.csRGB, clip, False)
                rgb.copy(src, clip)
                gray = fitz.Pixmap(fitz.csGRAY, rgb)
                faint = bytes(
                    255 if s >= 200 else 255 - int(WM_STRENGTH * (255 - s))
                    for s in gray.samples)
                _wm_cache["owl"] = fitz.Pixmap(fitz.csGRAY, gray.w, gray.h, faint, 0)
            pix = _wm_cache["owl"]
            h = 300.0
            w = h * pix.width / pix.height
            r = fitz.Rect((PAGE_W - w) / 2, (PAGE_H - h) / 2 - 26,
                          (PAGE_W + w) / 2, (PAGE_H + h) / 2 - 26)
            pg.insert_image(r, pixmap=pix)
            ty = r.y1 + 40
        else:
            ty = PAGE_H / 2
        fs = 30
        tw = fitz.get_text_length(BRAND, fontname="hebo", fontsize=fs)
        pg.insert_text(((PAGE_W - tw) / 2, ty), BRAND, fontsize=fs,
                       fontname="hebo",
                       color=(WM_TEXT_GREY, WM_TEXT_GREY, WM_TEXT_GREY))

    keys = _question_keys(req.question_ids)
    pdf_out = fitz.open()
    missing = 0
    q_num = 0
    page = None
    y = TOP_Y
    body_pages = 0

    def new_page():
        nonlocal page, y, body_pages
        page = pdf_out.new_page(width=PAGE_W, height=PAGE_H)
        body_pages += 1
        _watermark(page)
        page.insert_text(
            (MARGIN_X, PAGE_H - 22), BRAND,
            fontsize=7.5, fontname="hebo", color=ACCENT)
        num = f"Page {body_pages}"
        w = fitz.get_text_length(num, fontname="helv", fontsize=7)
        page.insert_text(
            ((PAGE_W - w) / 2, PAGE_H - 22), num,
            fontsize=7, fontname="helv", color=GREY)
        y = TOP_Y

    def ensure(height):
        nonlocal page, y
        if page is None or y + height > BOTTOM_Y:
            new_page()

    for qid in req.question_ids:
        q_key = keys.get(qid)
        files = _crop_files_for_key(q_key) if q_key else None
        if not files:
            missing += 1
            q_num += 1
            continue
        _, crop_path = files
        if crop_path is None or not crop_path.exists():
            missing += 1
            q_num += 1
            continue
        try:
            with fitz.open(str(crop_path)) as crop_doc:
                crop_pages = crop_doc.page_count
                if crop_pages == 0:
                    missing += 1
                    q_num += 1
                    continue
                q_num += 1

                first_crop = crop_doc[0]
                first_h = first_crop.rect.height * (CONTENT_W / first_crop.rect.width)

                if q_num > 1 and page is not None and y + DIVIDER_GAP < BOTTOM_Y:
                    mid = y + DIVIDER_GAP / 2
                    page.draw_line(
                        fitz.Point(MARGIN_X, mid),
                        fitz.Point(PAGE_W - MARGIN_X, mid),
                        color=(0.75, 0.75, 0.75), width=0.5)
                    y += DIVIDER_GAP

                max_keep = BOTTOM_Y - TOP_Y - Q_HEADER_H
                ensure(Q_HEADER_H + min(first_h, max_keep))

                label = f"Q{q_num}"
                bar_w = 4.0
                page.draw_rect(
                    fitz.Rect(MARGIN_X, y + 2, MARGIN_X + bar_w, y + Q_HEADER_H - 2),
                    color=None, fill=ACCENT)
                lx = MARGIN_X + bar_w + 6
                page.insert_text((lx, y + 11), label,
                                 fontsize=12, fontname="hebo", color=ACCENT)
                x = lx + fitz.get_text_length(label, fontname="hebo", fontsize=12)
                ref_str = (q_key or "").replace("_", "/") if q_key else ""
                if ref_str:
                    page.insert_text((x + 8, y + 10), ref_str,
                                     fontsize=8.5, fontname="helv", color=GREY)
                rule_y = y + Q_HEADER_H - 1
                page.draw_line(
                    fitz.Point(MARGIN_X, rule_y),
                    fitz.Point(PAGE_W - MARGIN_X, rule_y),
                    color=GOLD, width=0.6)
                y += Q_HEADER_H

                for pg_idx in range(crop_pages):
                    cp = crop_doc[pg_idx]
                    scale = CONTENT_W / cp.rect.width
                    h = cp.rect.height * scale
                    ensure(h)
                    target = fitz.Rect(MARGIN_X, y, MARGIN_X + CONTENT_W, y + h)
                    page.show_pdf_page(target, crop_doc, pg_idx)
                    y += h + 4

        except Exception:
            missing += 1
            q_num += 1

    if pdf_out.page_count == 0:
        pdf_out.close()
        raise HTTPException(404, "no crop PDFs found for these questions")

    pdf_bytes = pdf_out.tobytes(garbage=3, deflate=True)
    pdf_out.close()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"X-Missing-Crops": str(missing)},
    )


# ── MCQ AI explanation ─────────────────────────────────────────────────────────

MCQ_EXPLAIN_SYSTEM = """\
You are a Cambridge exam tutor at PrepWithTee writing a worked solution to a \
multiple-choice question. Show the working. Do not lecture.

You are shown an IMAGE of the question exactly as it appears in the paper.
Read the equations, symbols, diagrams and options from the image — it is the
authoritative source. Any text supplied alongside it was machine-extracted
from the PDF and mangles fractions, square roots, powers and subscripts, so
never let it override what you can see. Read carefully: a fraction is a
fraction, not a power.

Output exactly these four sections, in this order:

<h3>Working</h3>
An <ol> in which every <li> is ONE line of real mathematics that advances the
derivation — a substitution, a rearrangement, a cancellation, a result. Wrap
each equation or quantity in <code>…</code>. Carry units through every line.
Never write a step that merely describes a step; write the mathematics itself.

<h3>Answer</h3>
One short <p>: the correct option letter and what it is.

<h3>Why the others are wrong</h3>
A <ul> with one <li> per wrong option, each of the form
<strong>A</strong> — the specific slip that produces it.
One line each. Name the actual mistake (dropped the square root, m² instead of
m, inverted the fraction, factor of 2, degrees for radians, per-second for
seconds). Do not re-derive.

<h3>Remember</h3>
One sentence: the transferable rule for the next question of this type.

GRANULARITY: the Working list must contain at least FOUR <li> steps. Never
compress two operations onto one line. Show separately: the governing principle
or equation, each substitution, each simplification, and the final rearrangement.

Hard rules:
- Commit to ONE derivation. Never write "however", "but wait", "the correct
  approach is", "on reconsideration", or any other mid-answer reversal. Work
  the problem out fully before you begin writing, then state it once, cleanly.
- Never restate the question. No preamble, no sign-off, no pep talk.
- Prefer short lines of algebra over sentences of prose. The Working section
  is the answer; everything else is trimming.
- Output clean HTML only: <h3>, <p>, <ol>, <ul>, <li>, <strong>, <code>.
  No markdown, no code fences, no <html> or <body> wrapper.
- Plain maths only (×, ÷, ², ³, ⁻¹, √, Δ, π, °, ±, ≈) — never LaTeX, never $…$.
- Match the Cambridge level implied by the syllabus code (O Level / IGCSE /
  A Level).
- If the image is missing or unreadable, say exactly that in one <p> and stop.
  Never guess at an equation you cannot see."""


class MCQExplainReq(BaseModel):
    question_id: int
    your_answer: str | None = None
    correct_answer: str | None = None
    syllabus: str | None = None
    topic: str | None = None
    refresh: bool = False        # ignore the stored copy and re-generate


# ── Durable explanation store ──────────────────────────────────────────────
#
# Worked solutions are expensive (a vision call each) and completely static:
# the prompt deliberately carries NO student answer, so one stored explanation
# is correct for every student who ever sees that question. Storing them means
# the second student to reach a question pays nothing, and the review PDF can
# be assembled from cache instead of re-billing forty calls.
#
# In Supabase mode the table sits beside the pipeline tables. In SQLite mode it
# lives in a SIDECAR file, not data/index.db: index.db is rebuilt locally and
# rsynced over the top on every deploy, which would throw the whole cache away.
_EXPL_DB = ROOT / "data" / "mcq_cache.db"
_expl_lock = threading.Lock()
_expl_ready = False

_EXPL_DDL = """
CREATE TABLE IF NOT EXISTS mcq_explanations (
    q_key        TEXT PRIMARY KEY,
    question_id  {int_type},
    html         TEXT NOT NULL,
    provider     TEXT,
    created_at   TEXT NOT NULL
)"""

# Rows are keyed on the Cambridge coordinates rather than questions.id, because
# `segment` deletes and re-inserts a paper's question rows on every re-run and
# SQLite happily hands the vacated ids to different questions. An id-keyed
# cache would then quietly serve the wrong worked solution.
_QKEY_CACHE: dict[int, str] = {}


def _qkey_of(row) -> str:
    return (f"{row['syllabus']}_{row['session']}{row['year'] % 100:02d}"
            f"_{row['paper']}{row['variant']}_q{row['number']:02d}"
            f"{row['sub_part'] or ''}")


def _question_keys(question_ids: list[int]) -> dict[int, str]:
    """Natural keys for many questions in ONE query.

    Batched on purpose. Against Supabase every _con() is a fresh connection to
    a remote pooler (~0.3 s), so resolving a 40-question paper one id at a time
    cost 40 round trips before the report had done any work at all.
    """
    want = [q for q in question_ids if q not in _QKEY_CACHE]
    if want:
        try:
            con = _con()
            con.row_factory = sqlite3.Row
            try:
                ph = ",".join("?" for _ in want)
                rows = con.execute(
                    f"""SELECT q.id, q.number, q.sub_part,
                               p.syllabus, p.year, p.session, p.paper, p.variant
                        FROM questions q JOIN papers p ON p.id = q.paper_id
                        WHERE q.id IN ({ph})""", want).fetchall()
            finally:
                con.close()
            if len(_QKEY_CACHE) > 20000:
                _QKEY_CACHE.clear()
            for r in rows:
                _QKEY_CACHE[r["id"]] = _qkey_of(r)
        except Exception:
            pass
    return {q: _QKEY_CACHE[q] for q in question_ids if q in _QKEY_CACHE}


def _question_key(question_id: int) -> str | None:
    """Stable natural key for one question, e.g. '0625_s21_12_q07'.

    Same shape as the crop paths on disk, so a cached row can always be traced
    back to the PDF it came from. Memoised: ids are stable within a process.
    """
    return _question_keys([question_id]).get(question_id)


def _expl_con():
    """Connection to whichever store holds the explanations, table ensured."""
    global _expl_ready
    if _USE_PG:
        con = _con()
        if not _expl_ready:
            with _expl_lock:
                con.execute(_EXPL_DDL.format(int_type="BIGINT"))
                con.commit()
                _expl_ready = True
        return con
    _EXPL_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(_EXPL_DB, timeout=15)
    con.row_factory = sqlite3.Row
    if not _expl_ready:
        with _expl_lock:
            con.execute(_EXPL_DDL.format(int_type="INTEGER"))
            con.commit()
            _expl_ready = True
    return con


def _explanation_get(question_id: int) -> dict | None:
    """Stored worked solution for a question, or None. Never raises: a broken
    cache must degrade to a fresh generation, not a 500."""
    q_key = _question_key(question_id)
    if not q_key:
        return None
    try:
        con = _expl_con()
        try:
            row = con.execute(
                "SELECT html, provider FROM mcq_explanations WHERE q_key = ?",
                (q_key,)).fetchone()
        finally:
            con.close()
        if row and row["html"]:
            return {"html": row["html"], "provider": row["provider"]}
    except Exception:
        pass
    return None


def _explanations_get_many(question_ids: list[int]) -> dict[int, str]:
    """Stored worked solutions for many questions in ONE query.

    Same reason as _question_keys: probing a 40-question paper one row at a
    time meant 40 fresh Supabase connections, which is most of the wait before
    the progress bar could show anything.
    """
    keys = _question_keys(question_ids)
    if not keys:
        return {}
    by_key = {}
    try:
        con = _expl_con()
        try:
            uniq = sorted(set(keys.values()))
            ph = ",".join("?" for _ in uniq)
            rows = con.execute(
                f"SELECT q_key, html FROM mcq_explanations WHERE q_key IN ({ph})",
                uniq).fetchall()
        finally:
            con.close()
        by_key = {r["q_key"]: r["html"] for r in rows if r["html"]}
    except Exception:
        return {}
    return {qid: by_key[k] for qid, k in keys.items() if k in by_key}


def _explanation_put(question_id: int, html: str, provider: str | None) -> None:
    """Store (or replace) a worked solution. Best-effort, never raises."""
    q_key = _question_key(question_id)
    if not html or not q_key:
        return
    try:
        con = _expl_con()
        try:
            con.execute(
                """INSERT INTO mcq_explanations
                       (q_key, question_id, html, provider, created_at)
                   VALUES (?, ?, ?, ?, datetime('now'))
                   ON CONFLICT (q_key) DO UPDATE
                     SET question_id = excluded.question_id,
                         html = excluded.html,
                         provider = excluded.provider,
                         created_at = excluded.created_at""",
                (q_key, question_id, html, provider))
            con.commit()
        finally:
            con.close()
    except Exception:
        pass


def _generate_explanation(question_id: int, correct_answer: str | None,
                          syllabus: str | None, topic: str | None) -> dict:
    """Produce a worked solution for one MCQ. Returns
    {html, provider, truncated}; raises HTTPException(503) if no provider.

    Deliberately answer-agnostic: the prompt's "Why the others are wrong"
    section already covers every distractor, so naming the student's own pick
    would buy nothing and would make the result unshareable between students.
    """
    q_text = ""
    try:
        con = _con()
        con.row_factory = sqlite3.Row
        row = con.execute(
            """SELECT q.text, q.number, p.syllabus, p.year, p.session, p.paper
               FROM questions q JOIN papers p ON p.id = q.paper_id
               WHERE q.id = ?""", (question_id,)).fetchone()
        con.close()
        if row:
            q_text = (row["text"] or "")[:600].strip()
    except Exception:
        pass  # proceed without question text — the LLM can still explain

    prompt_parts = []
    if syllabus:
        prompt_parts.append(f"Syllabus: {syllabus}")
    if topic:
        prompt_parts.append(f"Topic: {topic}")
    if q_text:
        prompt_parts.append(f"Question text: {q_text}")
    if correct_answer:
        prompt_parts.append(f"Correct answer: {correct_answer}")
    prompt_parts.append(
        "Write the full worked solution for this MCQ, using the required "
        "section headings and showing every step of the working.")
    user_text = "\n".join(prompt_parts)

    # Vision first. The student is looking at the crop; the explainer should be
    # looking at the same crop, or it ends up explaining a different question.
    png = _question_png_bytes(question_id)
    if png and len(png) <= VISION_MAX_PNG_BYTES:
        # Sized against the 8000 tokens/minute cap: the image+prompt costs
        # ~1430 and a full answer ~350, so 1600 leaves generous headroom while
        # still letting several explanations through per minute. Raising this
        # does not buy longer answers, it just reserves budget and triggers 413.
        text, prov, truncated = _vision_complete(
            MCQ_EXPLAIN_SYSTEM, user_text, png, max_tokens=800)
        if text is not None:
            return {"html": _clean_html(text), "provider": prov,
                    "truncated": truncated}

    # Text-only fallback (no crop on disk, or no multimodal provider). Warn the
    # model that what it is reading is lossy so it hedges instead of inventing.
    msgs = [
        {"role": "system", "content": MCQ_EXPLAIN_SYSTEM},
        {"role": "user", "content":
            "NOTE: no image of this question is available, and the text below "
            "is machine-extracted, so fractions, roots and powers may be "
            "scrambled or missing. If the equation is ambiguous, say so and "
            "explain the method rather than guessing at the algebra.\n\n"
            + user_text},
    ]
    text, prov = _chat_complete(msgs, max_tokens=1100)
    if text is None:
        raise HTTPException(503, "AI service unavailable — set GROQ_API_KEY. (" + prov + ")")
    return {"html": _clean_html(_strip_reasoning(text)), "provider": prov,
            "truncated": False}


def _explanation_for(question_id: int, correct_answer: str | None,
                     syllabus: str | None, topic: str | None,
                     refresh: bool = False) -> dict:
    """Cache-first worked solution. Adds `cached` to the returned dict.

    A truncated answer is returned to the caller but never stored — caching a
    half-written derivation would make "Explain" replay it forever.
    """
    if not refresh:
        hit = _explanation_get(question_id)
        if hit:
            return {"html": hit["html"], "provider": hit["provider"],
                    "truncated": False, "cached": True}
    out = _generate_explanation(question_id, correct_answer, syllabus, topic)
    if not out.get("truncated"):
        _explanation_put(question_id, out["html"], out.get("provider"))
    out["cached"] = False
    return out


@app.post("/api/mcq/explain")
def mcq_explain(req: MCQExplainReq, request: Request):
    """AI explanation for an MCQ question: why the correct answer is right."""
    # A cache hit costs no API budget, so it must not burn the caller's quota
    # either — only a real generation is rate limited.
    if req.refresh or _explanation_get(req.question_id) is None:
        wait = _tutor_rate_limited(_client_ip(request))
        if wait is not None:
            raise HTTPException(
                429, f"Rate limit — try again in {wait // 60 + 1} minutes.")
    return _explanation_for(req.question_id, req.correct_answer,
                            req.syllabus, req.topic, refresh=req.refresh)


# ── MCQ session review PDF ─────────────────────────────────────────────────
#
# The student finishes a session and downloads the whole thing: every question
# crop, the option they picked, the mark-scheme answer, and the worked
# solution. Filling in the missing explanations is a run of vision calls, far
# too slow to hold a request open for, so this is a job:
#
#     POST /api/mcq/report            -> {job_id}
#     GET  /api/mcq/report/{job_id}   -> {state, phase, done, total}
#     GET  /api/mcq/report/{job_id}/pdf
#
# Job state lives on disk, not in a module global, because gunicorn runs two
# workers and the poll is not guaranteed to land on the worker that started
# the job.
REPORTS_DIR = ROOT / "data" / "reports"
REPORT_TTL_S = 3 * 3600          # a finished PDF is collectable for 3 hours
REPORT_MAX_QUESTIONS = 120       # one full paper is ~40; this is generous
REPORT_MAX_EXPLAIN = 60          # cap on fresh vision calls for one report
REPORT_LIMIT, REPORT_WINDOW = 6, 3600
_report_hits: dict[str, list] = {}
_JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class MCQReportItem(BaseModel):
    """One answered question, as the browser saw it.

    Only the student's own pick is taken from the client — ref, topic and the
    mark-scheme answer are re-read from the database, so a tampered payload
    can't put a made-up "correct answer" into a PrepWithTee-branded PDF.
    """
    question_id: int
    your_answer: str | None = None
    time_secs: int | None = None


class MCQReportReq(BaseModel):
    items: list[MCQReportItem]
    syllabus: str | None = None
    title: str | None = None
    subtitle: str | None = None
    time_label: str | None = None
    explain: str = "wrong"       # "none" | "wrong" | "all"

    @field_validator("explain")
    @classmethod
    def _check_explain(cls, v: str) -> str:
        if v not in ("none", "wrong", "all"):
            raise ValueError("explain must be none, wrong or all")
        return v


def _report_rate_limited(ip: str) -> int | None:
    now = time.time()
    hits = [t for t in _report_hits.get(ip, []) if now - t < REPORT_WINDOW]
    if len(hits) >= REPORT_LIMIT:
        _report_hits[ip] = hits
        return int(REPORT_WINDOW - (now - hits[0])) + 1
    hits.append(now)
    _report_hits[ip] = hits
    return None


def _report_dir(job_id: str) -> Path:
    if not _JOB_ID_RE.match(job_id):
        raise HTTPException(400, "invalid job id")
    d = (REPORTS_DIR / job_id).resolve()
    if not str(d).startswith(str(REPORTS_DIR.resolve())):
        raise HTTPException(400, "invalid job id")
    return d


def _report_status_write(job_dir: Path, **fields):
    """Write-then-rename so a poller never reads a half-written file.

    The temp file is uniquely named: the progress callback and the phase
    changes can overlap, and two writers sharing one scratch path would have
    the second rename fail on a file the first had already moved away.
    """
    try:
        job_dir.mkdir(parents=True, exist_ok=True)
        fields["updated"] = time.time()
        tmp = job_dir / f"status.{os.getpid()}.{threading.get_ident()}.tmp"
        tmp.write_text(json.dumps(fields), encoding="utf-8")
        os.replace(tmp, job_dir / "status.json")
    except Exception:
        pass


def _report_status_read(job_dir: Path) -> dict | None:
    """Parsed status, or None if it genuinely isn't readable.

    Retried: on Windows a read that lands in the middle of the rename above
    fails with a sharing violation, and treating that one unlucky poll as
    "your report expired" would abandon a build that was running perfectly.
    """
    path = job_dir / "status.json"
    for attempt in range(3):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            if not job_dir.exists():
                return None
        except Exception:
            pass
        if attempt < 2:
            time.sleep(0.05)
    return None


def _report_sweep():
    """Drop job directories past their TTL. Called when a new job starts, so
    there is no timer to own and nothing to leak if the process restarts."""
    try:
        cutoff = time.time() - REPORT_TTL_S
        for d in REPORTS_DIR.iterdir():
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
    except Exception:
        pass


# A vision call takes roughly eight seconds and three run at once, so each
# outstanding question costs about this much wall-clock time. Only used until
# the first real completion gives us a measured rate.
EXPLAIN_SECS_EACH = 3.0


def _eta_explanations(done: int, total: int, rate: float | None = None):
    """Seconds still to wait on the worked-solution phase, or None."""
    left = max(0, total - done)
    if not left:
        return 0
    return round(left * (rate if rate and rate > 0 else EXPLAIN_SECS_EACH))


def _report_question_rows(qids: list[int]) -> dict[int, dict]:
    """Reference, topic and mark-scheme answer for each question id."""
    if not qids:
        return {}
    con = _con()
    con.row_factory = sqlite3.Row
    try:
        ph = ",".join("?" for _ in qids)
        rows = con.execute(
            f"""SELECT q.id, q.number, q.sub_part, c.topic, c.subtopic,
                       p.syllabus, p.year, p.session, p.paper, p.variant
                FROM questions q
                JOIN papers p ON p.id = q.paper_id
                LEFT JOIN classifications c ON c.question_id = q.id
                WHERE q.id IN ({ph})""", qids).fetchall()
        answers = con.execute(
            f"""SELECT q.id AS qid, m.answer
                FROM questions q
                JOIN papers p ON p.id = q.paper_id
                LEFT JOIN ms_entries m ON (
                    m.paper_id = (
                        SELECT p2.id FROM papers p2
                        WHERE p2.syllabus = p.syllabus AND p2.year = p.year
                          AND p2.session = p.session AND p2.paper = p.paper
                          AND p2.variant = p.variant AND p2.kind = 'ms'
                    )
                    AND m.question_number = q.number
                    AND m.sub_part = q.sub_part
                )
                WHERE q.id IN ({ph})""", qids).fetchall()
    finally:
        con.close()
    answer_map = {r["qid"]: r["answer"] for r in answers}
    out = {}
    for r in rows:
        sa = _SESSION_ABBR.get(r["session"], r["session"].upper())
        sub = f"({r['sub_part']})" if r["sub_part"] else ""
        out[r["id"]] = {
            "ref": (f"{r['syllabus']}/P{r['paper']}{r['variant']} {sa} "
                    f"{r['year']} Q{r['number']}{sub}"),
            "topic": r["topic"] or "",
            "subtopic": r["subtopic"] or "",
            "syllabus": r["syllabus"],
            "answer": answer_map.get(r["id"]),
        }
    return out


def _report_worker(job_dir: Path, req: MCQReportReq):
    """Build one review PDF. Runs in a plain thread; owns all its own errors."""
    import mcq_report

    try:
        meta = _report_question_rows([i.question_id for i in req.items])

        # Pair every submitted answer with what the database says about it.
        items, wanted = [], []
        for n, it in enumerate(req.items, start=1):
            m = meta.get(it.question_id)
            if m is None:
                continue          # question no longer in the DB — drop the row
            correct = m["answer"]
            your = (it.your_answer or "").strip().upper()[:1] or None
            if your not in ("A", "B", "C", "D"):
                your = None
            if your is None:
                result = "skipped"
            elif correct is None:
                result = "no-key"
            else:
                result = "correct" if your == correct else "wrong"
            row = {
                "n": n, "question_id": it.question_id,
                "ref": m["ref"],
                "topic": " · ".join(x for x in (m["topic"], m["subtopic"]) if x),
                "your": your, "correct": correct, "result": result,
                "time_secs": it.time_secs,
                "syllabus": m["syllabus"], "topic_only": m["topic"],
            }
            items.append(row)
            if req.explain == "all" or (req.explain == "wrong"
                                        and result in ("wrong", "skipped")):
                wanted.append(row)

        # ── Phase 1: what is already written ──
        # ONE query for every stored solution, not one per question. Against
        # Supabase each connection is a remote round trip, and probing a
        # 40-question paper individually cost about two minutes before the
        # progress bar could move at all.
        cached = dict(_explanations_get_many([r["question_id"] for r in wanted]))
        missing = [r for r in wanted if r["question_id"] not in cached]
        missing = missing[:REPORT_MAX_EXPLAIN]

        # ── Phase 2: worked solutions ──
        total = len(missing)
        _report_status_write(job_dir, state="running", phase="explanations",
                             done=0, total=total, eta_s=_eta_explanations(0, total))

        if total:
            from concurrent.futures import ThreadPoolExecutor
            counter = {"n": 0}
            lock = threading.Lock()
            started = time.time()

            def one(row):
                try:
                    out = _explanation_for(row["question_id"], row["correct"],
                                           row["syllabus"], row["topic_only"])
                    html = out.get("html")
                except Exception:
                    html = None
                with lock:
                    counter["n"] += 1
                    n = counter["n"]
                    # Estimate from the rate actually observed; fall back to the
                    # nominal per-question cost until the first one lands.
                    rate = (time.time() - started) / n if n else None
                    _report_status_write(
                        job_dir, state="running", phase="explanations",
                        done=n, total=total,
                        eta_s=_eta_explanations(n, total, rate))
                return row["question_id"], html

            # Three at a time: the vision providers are token-per-minute capped
            # and a wider pool just converts into 429s.
            with ThreadPoolExecutor(max_workers=3) as pool:
                for qid, html in pool.map(one, missing):
                    if html:
                        cached[qid] = html

        # ── Phase 3: crops ──
        # Paths come from the natural key, so this touches no database at all.
        keys = _question_keys([r["question_id"] for r in items])
        _report_status_write(job_dir, state="running", phase="images",
                             done=0, total=len(items), eta_s=None)
        for i, row in enumerate(items, start=1):
            row["png"] = _png_bytes_for_key(keys.get(row["question_id"]))
            row["explanation"] = cached.get(row["question_id"])
            if i % 10 == 0 or i == len(items):
                _report_status_write(job_dir, state="running", phase="images",
                                     done=i, total=len(items), eta_s=None)

        # ── Phase 4: render ──
        _report_status_write(job_dir, state="running", phase="pdf",
                             done=0, total=len(items), eta_s=None)

        attempted = sum(1 for r in items if r["result"] in ("correct", "wrong", "no-key"))
        correct_n = sum(1 for r in items if r["result"] == "correct")
        summary = {
            "title": req.title or "MCQ Session Review",
            "subtitle": req.subtitle,
            "correct": correct_n,
            "attempted": attempted,
            "wrong": sum(1 for r in items if r["result"] == "wrong"),
            "skipped": sum(1 for r in items if r["result"] == "skipped"),
            "pct": round(correct_n / attempted * 100) if attempted else 0,
            "time_label": req.time_label or "—",
        }

        out = job_dir / "report.pdf"
        mcq_report.build_report(
            summary, items, out,
            progress=lambda d, t: _report_status_write(
                job_dir, state="running", phase="pdf", done=d, total=t,
                eta_s=None))

        slug = re.sub(r"[^A-Za-z0-9]+", "-", (req.title or "mcq-review")).strip("-").lower()
        _report_status_write(job_dir, state="done", phase="done",
                             done=len(items), total=len(items),
                             filename=f"{slug[:60] or 'mcq-review'}.pdf")
    except Exception as exc:
        _report_status_write(job_dir, state="error", phase="error",
                             done=0, total=0, error=str(exc)[:300])


@app.post("/api/mcq/report")
def mcq_report_start(req: MCQReportReq, request: Request):
    """Kick off a review-PDF build. Returns a job id to poll."""
    if not req.items:
        raise HTTPException(400, "no questions to report on")
    if len(req.items) > REPORT_MAX_QUESTIONS:
        raise HTTPException(400,
                            f"too many questions (max {REPORT_MAX_QUESTIONS})")
    wait = _report_rate_limited(_client_ip(request))
    if wait is not None:
        raise HTTPException(
            429, f"Too many report downloads — try again in {wait // 60 + 1} minutes.")

    _report_sweep()
    job_id = secrets.token_urlsafe(12).replace(".", "-")
    job_dir = _report_dir(job_id)
    _report_status_write(job_dir, state="running", phase="starting",
                         done=0, total=len(req.items))
    threading.Thread(target=_report_worker, args=(job_dir, req),
                     daemon=True, name=f"mcq-report-{job_id}").start()
    return {"job_id": job_id}


@app.get("/api/mcq/report/{job_id}")
def mcq_report_status(job_id: str):
    job_dir = _report_dir(job_id)
    st = _report_status_read(job_dir)
    if st is None:
        # The job directory still being there means the build is alive and the
        # status file was simply mid-rename; only a missing directory is a
        # genuinely expired or unknown job.
        if job_dir.exists():
            return {"state": "running", "phase": "working",
                    "done": 0, "total": 0, "ready": False}
        raise HTTPException(404, "that report has expired — build it again")
    # A worker that died mid-build would otherwise leave the poller spinning.
    if (st.get("state") == "running"
            and time.time() - st.get("updated", 0) > 300):
        st = {**st, "state": "error",
              "error": "the build stalled — please try again"}
    st["ready"] = st.get("state") == "done" and (job_dir / "report.pdf").exists()
    return st


@app.get("/api/mcq/report/{job_id}/pdf")
def mcq_report_pdf(job_id: str):
    job_dir = _report_dir(job_id)
    pdf = job_dir / "report.pdf"
    if not pdf.exists():
        raise HTTPException(404, "report not ready")
    st = _report_status_read(job_dir) or {}
    return FileResponse(pdf, media_type="application/pdf",
                        filename=st.get("filename") or "mcq-review.pdf")



@app.post("/api/questions")
def list_questions(req: QuestionListReq):
    """Return matching question metadata without generating a PDF.

    When count or marks is supplied, applies the same weighted random selection
    as testgen so the preview matches what the test would contain.
    Seed is echoed back so the caller can regenerate the exact same pick.
    """
    if not req.topics:
        raise HTTPException(400, "pick at least one topic")

    con = _con()
    con.row_factory = sqlite3.Row
    try:
        pool = _question_pool(req, con)
    finally:
        con.close()

    if req.count or req.marks:
        chosen = _apply_random_selection(pool, req.count, req.marks, req.seed)
    else:
        chosen = pool

    sess_abbr = _SESSION_ABBR
    questions = []
    for q in chosen:
        sa = sess_abbr.get(q["session"], q["session"].upper())
        ref = (f"{q['syllabus']}/P{q['paper']} {sa} {q['year']} "
               f"Q{q['number']}{('(' + q['sub_part'] + ')') if q['sub_part'] else ''}")
        snippet = (q["text"] or "")[:160].strip()
        questions.append({
            "id": q["id"],
            "ref": ref,
            "year": q["year"],
            "session": q["session"],
            "paper": q["paper"],
            "variant": q["variant"],
            "number": q["number"],
            "sub_part": q["sub_part"],
            "topic": q["topic"],
            "subtopic": q["subtopic"],
            "marks": q["marks"],
            "text_snippet": snippet,
        })

    total_marks = sum(q["marks"] or 0 for q in chosen)
    return {"questions": questions, "total_marks": total_marks,
            "pool_size": len(pool), "seed": req.seed}


@app.get("/api/health")
def health():
    """Liveness probe. Also what the keep-alive cron hits so a low-traffic
    box does not look idle to the host's reclamation policy."""
    try:
        con = _con()
        papers = con.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        con.close()
    except Exception as exc:
        raise HTTPException(503, f"database unreachable: {exc}")
    raw = ROOT / "data" / "raw"
    return {"status": "ok", "papers": papers, "archive_present": raw.is_dir()}


# /api/meta runs ~6 aggregate queries per syllabus. Against a local SQLite file
# that was free; against Supabase every one is a network round-trip, which puts
# a cold build at ~15 s. The answer only changes when the pipeline reclassifies
# (an offline, manual step), so it is cached hard.
#
# Three rules, learned the hard way — a 600 s TTL with a synchronous rebuild
# meant that every ten minutes the next student to load /revise.html or
# /dashboard.html paid the full 15 s build in their own request:
#   1. NEVER rebuild in the request path once any data exists. Stale meta is
#      indistinguishable from fresh unless the pipeline just ran; a 15 s wait
#      is not. Serve stale, refresh on a background thread.
#   2. The cache is per-process and gunicorn runs 2 workers, so the build was
#      being paid twice. Workers share it through a file on disk, which also
#      survives a restart/redeploy.
#   3. Longer TTL (1 h) because the data behind it only changes when an offline
#      pipeline run reclassifies. Since the refresh is now off the request path,
#      the TTL only trades DB load against staleness, never against latency —
#      and `POST /api/meta/refresh` busts it the moment the pipeline finishes.
_META_CACHE: dict = {"at": 0.0, "data": None, "etag": ""}
_META_TTL_S = 3600
_META_FILE = ROOT / "data" / "meta_cache.json"
_META_LOCK = threading.Lock()
_META_REFRESHING = threading.Event()


def _meta_store(data: dict, *, to_disk: bool = True) -> dict:
    """Publish a freshly built payload to the in-process cache (and disk)."""
    blob = json.dumps(data, sort_keys=True, default=str)
    etag = hashlib.md5(blob.encode("utf-8")).hexdigest()
    _META_CACHE.update(at=time.time(), data=data, etag=etag)
    if to_disk:
        try:                                 # best-effort; a read-only FS is survivable
            _META_FILE.parent.mkdir(parents=True, exist_ok=True)
            # Unique temp name per writer: the startup warm thread and a
            # request-path build can run concurrently, and a shared ".tmp" made
            # them collide (on Windows the rename then fails outright).
            tmp = _META_FILE.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
            try:
                tmp.write_text(blob, "utf-8")
                tmp.replace(_META_FILE)      # atomic, so a reader never sees a half file
            finally:
                tmp.unlink(missing_ok=True)  # nothing left behind if replace() failed
        except Exception as exc:
            print(f"[meta] disk cache write failed: {exc}", flush=True)
    return data


def _meta_load_disk() -> bool:
    """Seed the in-process cache from the shared file. True if it was usable."""
    try:
        built_at = _META_FILE.stat().st_mtime
        age = time.time() - built_at
        if age > _META_TTL_S:
            return False
        # The disk cache deliberately outlives a restart, so `sync.sh` pushing a
        # new index.db followed by `systemctl restart` would otherwise serve the
        # OLD subject/topic counts for up to the full TTL. Trust the file only
        # while it is newer than the database it was built from.
        if not _USE_PG and DB.exists() and DB.stat().st_mtime > built_at:
            return False
        data = json.loads(_META_FILE.read_text("utf-8"))
    except Exception:
        return False
    _meta_store(data, to_disk=False)
    _META_CACHE["at"] = time.time() - age     # keep the file's real age
    return True


def _meta_refresh_async():
    """Rebuild off the request path. Only one build at a time, per worker."""
    if _META_REFRESHING.is_set():
        return
    def build():
        _META_REFRESHING.set()
        try:
            with _META_LOCK:
                _meta_store(_build_meta())
        except Exception as exc:              # keep serving stale on failure
            print(f"[meta] refresh failed: {exc}", flush=True)
        finally:
            _META_REFRESHING.clear()
    threading.Thread(target=build, daemon=True).start()


@app.get("/api/stats")
def get_stats(user: dict = _Depends(_get_current_user)):
    import users_db as _udb
    stats = _udb.get_user_stats(user["id"])
    if stats is None:
        return {"xp_total": 0, "xp_log": [], "streak": 0,
                "streak_max": 0, "badges": [], "focus": {}, "missions": {}}
    import json as _j
    def _parse(v, default):
        if isinstance(v, (dict, list)):
            return v
        if isinstance(v, str):
            try: return _j.loads(v)
            except: return default
        return default
    return {
        "xp_total":   stats.get("xp_total", 0),
        "xp_log":     _parse(stats.get("xp_log"), []),
        "streak":     stats.get("streak", 0),
        "streak_max": stats.get("streak_max", 0),
        "badges":     _parse(stats.get("badges"), []),
        "focus":      _parse(stats.get("focus"), {}),
        "missions":   _parse(stats.get("missions"), {}),
    }


class _StatsPayload(BaseModel):
    xp_total:   int  = 0
    xp_log:     list = []
    streak:     int  = 0
    streak_max: int  = 0
    badges:     list = []
    focus:      dict = {}
    missions:   dict = {}


@app.post("/api/stats")
def post_stats(payload: _StatsPayload, user: dict = _Depends(_get_current_user)):
    import users_db as _udb
    _udb.upsert_user_stats(user["id"], payload.dict())
    return {"ok": True}


@app.get("/api/meta")
def meta(request: Request):
    fresh = (_META_CACHE["data"] is not None
             and time.time() - _META_CACHE["at"] < _META_TTL_S)
    if not fresh:
        # Another worker may have rebuilt it since we last looked.
        if not _meta_load_disk():
            if _META_CACHE["data"] is None:   # nothing to serve — must block
                with _META_LOCK:
                    if _META_CACHE["data"] is None:
                        _meta_store(_build_meta())
                return _meta_response(request)
        _meta_refresh_async()                 # stale-while-revalidate
    return _meta_response(request)


def _meta_response(request: Request):
    """Serve the cached payload, honouring If-None-Match so a repeat page load
    costs a 304 instead of 70 KB of gzipped JSON."""
    etag = f'W/"{_META_CACHE["etag"]}"'
    headers = {"ETag": etag, "Cache-Control": "private, max-age=60"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return JSONResponse(_META_CACHE["data"], headers=headers)


def _meta_data() -> dict:
    """The /api/meta payload without the HTTP wrapper (catalog pages use it)."""
    if _META_CACHE["data"] is None and not _meta_load_disk():
        with _META_LOCK:
            if _META_CACHE["data"] is None:
                _meta_store(_build_meta())
    return _META_CACHE["data"]


_catalog_mod.set_meta_provider(_meta_data)


@app.post("/api/meta/refresh")
def meta_refresh(_: bool = _admin_mod._Admin):
    """Bust the cache after a pipeline run / an index.db sync, without a
    restart. Admin-gated: a rebuild is ~20 s of database work, so it must not
    be something an anonymous caller can queue up at will."""
    _META_CACHE["at"] = 0.0
    try:
        _META_FILE.unlink()                   # so sibling workers rebuild too
    except OSError:
        pass
    _meta_refresh_async()
    return {"status": "refreshing"}


@app.on_event("startup")
def _warm_meta_cache():
    """Build the meta cache off-thread so the first visitor never waits on it."""
    def build():
        if _meta_load_disk():                 # a sibling worker already paid for it
            print("[meta] warmed from disk cache", flush=True)
            return
        try:
            _meta_store(_build_meta())
        except Exception as exc:              # a cold cache is recoverable
            print(f"[meta] warm-up failed: {exc}", flush=True)
    threading.Thread(target=build, daemon=True).start()

    # Same idea for the Supabase read pool: open its connections now so the
    # first student to load a dashboard does not pay eight TLS handshakes.
    def warm_db():
        try:
            import users_db as _udb
            _udb.warm_pool()
        except Exception as exc:
            print(f"[db] pool warm-up failed: {exc}", flush=True)
    threading.Thread(target=warm_db, daemon=True).start()

    # And the archive search index — building it costs one full scan of the
    # papers table, which is a couple of seconds against Supabase. Paying that
    # here rather than on the first keystroke is the difference between search
    # feeling instant and feeling broken.
    def warm_library():
        try:
            n = len(_library_index())
            print(f"[library] search index warmed ({n} sittings)", flush=True)
        except Exception as exc:
            print(f"[library] index warm-up failed: {exc}", flush=True)
    threading.Thread(target=warm_library, daemon=True).start()


def _build_meta():
    con = _con()
    con.row_factory = sqlite3.Row
    subs = [r["syllabus"] for r in con.execute(
        """SELECT DISTINCT p.syllabus FROM classifications c
           JOIN questions q ON q.id = c.question_id
           JOIN papers p ON p.id = q.paper_id ORDER BY p.syllabus""")]
    # Board + short subject name per syllabus, so the generator can group the
    # subject picker the same way the library and resources pages do.
    board_of = {code: board for board, sl in BOARDS for code, _ in sl}
    short_of = {code: name for _, sl in BOARDS for code, name in sl}
    out = []
    for syl in subs:
        tax = json.loads((ROOT / "taxonomy" / f"{syl}.json").read_text("utf-8"))
        pool: dict[str, int] = {}            # topic -> count across all papers
        per_paper: dict[str, dict[str, int]] = {}   # topic -> {paper: count}
        for col in ("topic", "secondary_topic"):
            for r in con.execute(
                    f"""SELECT c.{col} AS t, p.paper AS pp, COUNT(*) AS n
                        FROM classifications c
                        JOIN questions q ON q.id = c.question_id
                        JOIN papers p ON p.id = q.paper_id
                        WHERE p.syllabus = ? AND c.{col} IS NOT NULL
                        GROUP BY c.{col}, p.paper""", (syl,)):
                pool[r["t"]] = pool.get(r["t"], 0) + r["n"]
                seen = per_paper.setdefault(r["t"], {})
                key = str(r["pp"])
                seen[key] = seen.get(key, 0) + r["n"]
        # A topic is offered under a component only if the syllabus actually
        # examines it there. Without this the heuristic classifier's long tail
        # leaks across papers - 9709 P5 (Statistics) was listing Vectors,
        # whose "OA"/"AB" keywords collide with Venn-diagram labels.
        # Subtopic counts per topic (for syllabuses that have subtopics)
        subtopic_counts: dict[str, dict[str, int]] = {}
        for r in con.execute(
                """SELECT c.topic, c.subtopic, COUNT(*) AS n
                   FROM classifications c
                   JOIN questions q ON q.id = c.question_id
                   JOIN papers p ON p.id = q.paper_id
                   WHERE p.syllabus = ? AND c.subtopic IS NOT NULL
                   GROUP BY c.topic, c.subtopic""", (syl,)):
            subtopic_counts.setdefault(r["topic"], {})[r["subtopic"]] = r["n"]

        # Per-year counts for topics (all papers combined) — lets the frontend
        # update the displayed count when the user changes the year range.
        topic_year: dict[str, dict[str, int]] = {}   # topic -> {str(year): n}
        paper_year: dict[str, dict[str, dict[str, int]]] = {}  # topic -> {paper -> {year: n}}
        for r in con.execute(
                """SELECT c.topic AS t, p.year AS yr, p.paper AS pp, COUNT(*) AS n
                   FROM classifications c
                   JOIN questions q ON q.id = c.question_id
                   JOIN papers p ON p.id = q.paper_id
                   WHERE p.syllabus = ?
                   GROUP BY c.topic, p.year, p.paper""", (syl,)):
            yk = str(r["yr"])
            pk = str(r["pp"])
            ty = topic_year.setdefault(r["t"], {})
            ty[yk] = ty.get(yk, 0) + r["n"]
            py = paper_year.setdefault(r["t"], {}).setdefault(pk, {})
            py[yk] = py.get(yk, 0) + r["n"]

        # Per-year counts for subtopics
        subtopic_year: dict[str, dict[str, dict[str, int]]] = {}  # topic->subtopic->{year:n}
        for r in con.execute(
                """SELECT c.topic, c.subtopic, p.year AS yr, COUNT(*) AS n
                   FROM classifications c
                   JOIN questions q ON q.id = c.question_id
                   JOIN papers p ON p.id = q.paper_id
                   WHERE p.syllabus = ? AND c.subtopic IS NOT NULL
                   GROUP BY c.topic, c.subtopic, p.year""", (syl,)):
            subtopic_year.setdefault(r["topic"], {}).setdefault(
                r["subtopic"], {})[str(r["yr"])] = r["n"]

        topics = []
        for t in tax["topics"]:
            total = pool.get(t["name"], 0)
            # Zero-count chapters are KEPT. A chapter with no classified
            # questions yet is still part of the syllabus the student has to
            # prepare, so the progress tracker must list it; the paper builder
            # already skips anything with count 0 on its own.
            seen = per_paper.get(t["name"], {})
            allowed = t.get("papers")
            if allowed is not None:
                seen = {k: v for k, v in seen.items() if int(k) in allowed}
            # Build subtopic list from taxonomy (preserving order) with question counts
            raw_subs = t.get("subtopics", [])
            sc = subtopic_counts.get(t["name"], {})
            sy = subtopic_year.get(t["name"], {})
            subtopics = [
                # `detail` is the verbatim syllabus statement behind the short
                # label, so the tracker can show a student exactly what
                # Cambridge expects; `tier` is Core vs Supplement.
                {"name": s["name"], "count": sc.get(s["name"], 0),
                 "counts_by_year": sy.get(s["name"], {}),
                 "detail": s.get("detail"), "tier": s.get("tier")}
                for s in raw_subs
            ] if raw_subs else []
            topics.append({"name": t["name"], "count": total,
                           # `name` is the storage key questions are classified
                           # against; `display` is what the student reads. They
                           # differ where a chapter appears in two components
                           # ("Trigonometry (P3)" -> "Trigonometry").
                           "display": t.get("display") or t["name"],
                           "papers": seen, "subtopics": subtopics,
                           "counts_by_year": topic_year.get(t["name"], {}),
                           "paper_year": paper_year.get(t["name"], {}),
                           # Which components examine this chapter, straight
                           # from the syllabus — NOT derived from question
                           # counts. `papers` above says where questions were
                           # found; this says where the chapter belongs, which
                           # is what a revision checklist must go by.
                           "paper_scope": allowed})

        # Components come from the data, not a hardcoded list. A single-paper
        # syllabus gets none - the filter row would offer no real choice.
        counts = {r["pp"]: r["n"] for r in con.execute(
            """SELECT p.paper AS pp, COUNT(*) AS n FROM classifications c
               JOIN questions q ON q.id = c.question_id
               JOIN papers p ON p.id = q.paper_id
               WHERE p.syllabus = ? GROUP BY p.paper ORDER BY p.paper""",
            (syl,))}
        labels = PAPER_LABELS.get(syl, {})
        components = [] if len(counts) < 2 else [
            {"paper": pno, "label": labels.get(pno, f"P{pno}"), "count": n}
            for pno, n in sorted(counts.items())]

        # Available sessions and variants for multi-filter pills
        avail_sessions = sorted({r["session"] for r in con.execute(
            "SELECT DISTINCT p.session FROM papers p "
            "JOIN questions q ON q.paper_id = p.id "
            "JOIN classifications c ON c.question_id = q.id "
            "WHERE p.syllabus = ?", (syl,))})
        avail_variants = sorted({r["variant"] for r in con.execute(
            "SELECT DISTINCT p.variant FROM papers p "
            "JOIN questions q ON q.paper_id = p.id "
            "JOIN classifications c ON c.question_id = q.id "
            "WHERE p.syllabus = ? AND p.variant != ''", (syl,))})

        yr = con.execute(
            """SELECT MIN(p.year) AS y0, MAX(p.year) AS y1
               FROM classifications c
               JOIN questions q ON q.id = c.question_id
               JOIN papers p ON p.id = q.paper_id
               WHERE p.syllabus = ?""", (syl,)).fetchone()
        syl_year_min = yr["y0"] if yr and yr["y0"] else YEAR_MIN
        syl_year_max = yr["y1"] if yr and yr["y1"] else YEAR_MAX

        # A Level maths/physics/CS and O Level Islamiyat/Pak Studies examine
        # different content in each component, so their chapters must be shown
        # per paper. Everything else shares one syllabus across all papers.
        # Detected from the taxonomy rather than hardcoded: if the chapters do
        # not all carry the same scope, the split is real.
        scopes = {tuple(sorted(t["paper_scope"])) for t in topics
                  if t.get("paper_scope")}
        split_by_paper = len(scopes) > 1

        # Components that examine an identical chapter set are shown together,
        # not repeated: 9702 P1 and P2 cover the same AS content, and printing
        # the same 11 chapters twice just makes the tracker longer.
        paper_groups = []
        if split_by_paper:
            merged: dict[tuple, list[int]] = {}
            for pno in sorted({p for s in scopes for p in s}):
                names = tuple(t["name"] for t in topics
                              if pno in (t.get("paper_scope") or []))
                if names:
                    merged.setdefault(names, []).append(pno)
            for names, papers in sorted(merged.items(), key=lambda kv: kv[1][0]):
                if len(papers) == 1:
                    label = labels.get(papers[0], f"Paper {papers[0]}")
                else:
                    # "P1 · MCQ" + "P2 · AS Structured" -> "P1 & P2 · AS Structured"
                    tail = (labels.get(papers[-1], "") .split("·", 1)[-1]).strip()
                    label = " & ".join(f"P{p}" for p in papers) + (f" · {tail}" if tail else "")
                paper_groups.append({
                    "paper": papers[0], "papers": papers,
                    "label": label, "topics": list(names),
                })

        out.append({"syllabus": syl, "subject": tax.get("subject", syl),
                    "short": short_of.get(syl, tax.get("subject", syl)),
                    "board": board_of.get(syl, "Other"),
                    "split_by_paper": split_by_paper,
                    "paper_groups": paper_groups,
                    "topics": topics, "components": components,
                    "sessions": avail_sessions,
                    "variants": avail_variants,
                    "year_min": syl_year_min, "year_max": syl_year_max})
    con.close()
    # Board order for the grouped picker (unknown boards fall to the end).
    board_order = [b for b, _ in BOARDS]
    return {"subjects": out, "board_order": board_order,
            "year_min": YEAR_MIN, "year_max": YEAR_MAX}


# The pipeline exits with this when the filters are valid but select nothing.
# It is the single most common "error" a student can produce — picking a
# chapter that only appears in one component, or a year range that predates it
# — and it is not a server fault, so it must not surface as a 500.
_NO_MATCH_MARKER = "no classified questions match these filters"


def _run(cmd: list[str]):
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           timeout=600)
    except subprocess.TimeoutExpired:
        raise HTTPException(
            503,
            "Generation took too long — this booklet is very large. "
            "Try fewer topics or a shorter year range and generate again."
        )
    if r.returncode != 0:
        out = (r.stderr or r.stdout).strip()
        print(f"[compose] failed:\n{out[-3000:]}", flush=True)
        if _NO_MATCH_MARKER in out:
            raise HTTPException(
                400, "No questions match that combination. Try widening the "
                     "year range, or clearing the paper/session/variant filters "
                     "— some chapters only appear in one component.")
        if "database is locked" in out or "OperationalError" in out:
            raise HTTPException(
                503, "The server was busy generating another paper — "
                     "please wait a few seconds and try again.")
        lines = [l for l in out.splitlines() if l.strip()]
        tail = lines[-3:] if lines else []
        raise HTTPException(500, " | ".join(tail) if tail else "generation failed")


@app.post("/api/generate")
def generate(req: GenerateReq,
             user: dict = _Depends(_get_current_user)):
    if req.mode not in ("topical", "test"):
        raise HTTPException(400, "mode must be 'topical' or 'test'")
    if not req.topics:
        raise HTTPException(400, "pick at least one topic")
    event = "topic_test" if req.mode == "test" else "topical_paper"
    _access_mod.check_quota_gate(user, event)  # raises 429 but does NOT record yet

    tmp = Path(tempfile.mkdtemp(prefix="pwt_"))
    cleanup = BackgroundTask(shutil.rmtree, tmp, ignore_errors=True)
    slug = re.sub(r"[^a-z0-9]+", "-", "-".join(req.topics).lower()).strip("-")[:60]
    if req.subtopics:
        sub_slug = re.sub(r"[^a-z0-9]+", "-", ",".join(req.subtopics).lower()).strip("-")[:40]
        slug = (slug + "_" + sub_slug)[:100]
    topics_arg = "|".join(req.topics)
    span = [f"--from={req.year_from}", f"--to={req.year_to}"]

    # Merge papers: new list wins, legacy single value falls back
    papers_merged: list[int] = list(req.papers or [])
    if not papers_merged and req.paper:
        papers_merged.append(req.paper)
    papers_merged = sorted(set(papers_merged))

    # Filename stem: P1, P1+2, or no component suffix
    if papers_merged:
        stem = f"{req.syllabus}_p{''.join(str(p) for p in papers_merged)}"
    else:
        stem = req.syllabus

    # Merge legacy single-value fields into multi-value lists
    sessions = list(req.sessions or [])
    if req.session and req.session not in ("all", "") and req.session not in sessions:
        sessions.append(req.session)
    sessions = [s for s in sessions if s and s != "all"]

    variants = list(req.variants or [])
    if req.variant and req.variant not in ("all", "") and req.variant not in variants:
        variants.append(req.variant)
    variants = [v for v in variants if v and v != "all"]

    session_arg = ["--sessions", ",".join(sessions)] if sessions else []
    variant_arg = ["--variants", ",".join(variants)] if variants else []
    subtopic_arg = ["--subtopics", ",".join(req.subtopics)] if req.subtopics else []
    contains_arg = ["--contains", req.contains] if req.contains else []
    papers_arg = ["--papers", ",".join(str(p) for p in papers_merged)] if papers_merged else []

    if req.mode == "topical":
        out = tmp / f"{stem}_{slug}.pdf"
        cmd = [sys.executable, "-m", "pipeline.compose",
               "--syllabus", req.syllabus, "--topics", topics_arg,
               *span, "--out", str(out),
               *papers_arg, *session_arg, *variant_arg, *subtopic_arg, *contains_arg]
        if not req.include_ms:
            cmd.append("--no-ms")
        _run(cmd)
        _access_mod.record_quota(user, event)  # only count successful generations
        return FileResponse(out, media_type="application/pdf",
                            filename=out.name, background=cleanup)

    out = tmp / f"{stem}_{slug}_test.pdf"
    cmd = [sys.executable, "-m", "pipeline.testgen",
           "--syllabus", req.syllabus, "--topics", topics_arg,
           *span, "--out", str(out),
           *papers_arg, *session_arg, *variant_arg, *contains_arg]
    if req.question_ids:
        # Preview-and-curate flow: exact IDs chosen by the student, skip sampling
        cmd += ["--ids", ",".join(str(i) for i in req.question_ids)]
    elif req.marks:
        cmd += ["--marks", str(req.marks)]
    else:
        cmd += ["--count", str(req.count or 6)]
        if req.seed is not None:
            cmd += ["--seed", str(req.seed)]
    _run(cmd)
    _access_mod.record_quota(user, event)  # only count successful test generations

    zpath = tmp / f"{stem}_{slug}_test.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(out, out.name)
        ms = out.with_name(out.stem + "_ms.pdf")
        z.write(ms, ms.name)
    return FileResponse(zpath, media_type="application/zip",
                        filename=zpath.name, background=cleanup)


SESSION_NAMES = {"s": "May/June", "w": "Oct/Nov", "m": "Feb/March"}

# Board and display name per syllabus live in catalog.py (one registry for the
# library, meta, generator and the /papers SEO pages).
from catalog import BOARDS  # noqa: E402


@app.get("/api/library")
def library(syllabus: str | None = None, year: int | None = None, user: dict | None = _Depends(_auth_mod.maybe_user)):
    """Browse the downloaded paper archive.

    No argument  -> syllabuses with their year span and paper count
    ?syllabus    -> that syllabus's years
    ?syllabus&year -> every paper in that year, question paper + mark scheme
                      paired onto one row so the viewer can toggle between them
    """
    con = _con()
    con.row_factory = sqlite3.Row
    try:
        if syllabus is None:
            stats = {r["syllabus"]: r for r in con.execute(
                """SELECT p.syllabus, COUNT(*) n, MIN(p.year) y0, MAX(p.year) y1
                   FROM papers p GROUP BY p.syllabus""")}
            
            boards = []
            for board, subjects in BOARDS:
                entries = []
                for code, name in subjects:
                    r = stats.get(code)
                    if not r:
                        continue          # nothing fetched for that code yet
                    entries.append({"syllabus": code, "subject": name,
                                    "count": r["n"], "year_from": r["y0"],
                                    "year_to": r["y1"]})
                if entries:
                    boards.append({"board": board, "subjects": entries,
                                   "count": sum(e["count"] for e in entries)})
            return {"boards": boards,
                    # flat list kept for anything still reading the old shape
                    "syllabuses": [s for b in boards for s in b["subjects"]]}

        if year is None:
            rows = con.execute(
                """SELECT year, COUNT(*) n FROM papers WHERE syllabus = ?
                   GROUP BY year ORDER BY year DESC""", (syllabus,)).fetchall()
            return {"years": [{"year": r["year"], "count": r["n"]} for r in rows]}

        rows = con.execute(
            """SELECT id, session, paper, variant, kind, filename
               FROM papers WHERE syllabus = ? AND year = ?
               ORDER BY session, paper, variant, kind""", (syllabus, year)).fetchall()
        merged: dict[tuple, dict] = {}
        for r in rows:
            key = (r["session"], r["paper"], r["variant"])
            entry = merged.setdefault(key, {
                "session": r["session"],
                "session_name": SESSION_NAMES.get(r["session"], r["session"]),
                "paper": r["paper"], "variant": r["variant"],
                "code": f"{r['paper']}{r['variant']}", "qp": None, "ms": None})
            entry[r["kind"]] = {"id": r["id"], "filename": r["filename"]}
        return {"papers": sorted(
            merged.values(),
            key=lambda e: (e["session"], e["paper"], e["variant"]))}
    finally:
        con.close()


@app.get("/api/library/tree")
def library_tree(syllabus: str):
    """One syllabus as a year -> session -> files tree, for the sidebar.

    Files carry the paper/variant they belong to so the viewer can pair a
    question paper with its mark scheme when either one is clicked.
    """
    con = _con()
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """SELECT id, year, session, paper, variant, kind, filename
           FROM papers WHERE syllabus = ?
           ORDER BY year DESC, session, paper, variant, kind""",
        (syllabus,)).fetchall()
    con.close()

    years: dict[int, dict] = {}
    for r in rows:
        y = years.setdefault(r["year"], {"year": r["year"], "sessions": {}})
        s = y["sessions"].setdefault(r["session"], {
            "session": r["session"],
            "name": SESSION_NAMES.get(r["session"], r["session"]),
            "files": []})
        s["files"].append({
            "id": r["id"], "filename": r["filename"], "kind": r["kind"],
            "paper": r["paper"], "variant": r["variant"],
            "code": f"{r['paper']}{r['variant']}"})
    return {"years": [
        {"year": y["year"],
         "count": sum(len(s["files"]) for s in y["sessions"].values()),
         "sessions": sorted(y["sessions"].values(), key=lambda s: s["session"])}
        for y in sorted(years.values(), key=lambda y: -y["year"])]}


# ── Library search ─────────────────────────────────────────────────────────
#
# The sidebar tree is lazy — a subject's papers only exist once you have
# clicked into it — so "find 0625 June 2021 paper 2" meant four clicks through
# folders. This searches the whole archive at once.
#
# The whole `papers` table is only a few thousand rows, so it is loaded once
# and matched in Python against a pre-built haystack per sitting. That is what
# lets one box accept "0625", "physics", "p2", "v3", "june", "2021" and
# "0625_s21_qp_22" without the caller having to say which is which.
_LIB_INDEX: dict = {"built_at": 0.0, "rows": []}
_LIB_INDEX_TTL = 600
_lib_index_lock = threading.Lock()

_SESSION_WORDS = {
    "s": "s may june may/june mj m/j summer",
    "w": "w oct nov october november oct/nov on o/n winter",
    "m": "m feb mar march february feb/march fm f/m",
}

# What students actually type. "maths" is not a substring of "Mathematics",
# so without these the most obvious search in the whole archive returns
# nothing.
_SUBJECT_ALIASES = {
    "Mathematics": "maths math",
    "Mathematics (Syllabus D)": "maths math d syllabus-d",
    "Physics": "phy",
    "Chemistry": "chem",
    "Computer Science": "cs comp compsci computing ict",
    "Islamiyat": "islamiat islamiyaat islamic studies",
    "Pakistan Studies": "pak studies pakstudies history geography",
}
_BOARD_ALIASES = {
    "Cambridge O Level": "ol o-level olevel",
    "Cambridge IGCSE": "igcse gcse",
    "Cambridge A Level": "al a-level alevel as a2",
}


def _library_index() -> list[dict]:
    """Every sitting in the archive with a searchable text blob. Cached."""
    now = time.time()
    if _LIB_INDEX["rows"] and now - _LIB_INDEX["built_at"] < _LIB_INDEX_TTL:
        return _LIB_INDEX["rows"]
    with _lib_index_lock:
        if _LIB_INDEX["rows"] and now - _LIB_INDEX["built_at"] < _LIB_INDEX_TTL:
            return _LIB_INDEX["rows"]
        con = _con()
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(
                """SELECT id, syllabus, year, session, paper, variant, kind, filename
                   FROM papers
                   ORDER BY year DESC, session, paper, variant""").fetchall()
        finally:
            con.close()

        names = {code: name for _board, subs in BOARDS for code, name in subs}
        boards = {code: board for board, subs in BOARDS for code, _n in subs}

        # One entry per sitting, carrying both its QP and its MS — the viewer
        # always opens the pair, so the result list is per paper, not per file.
        sittings: dict[tuple, dict] = {}
        for r in rows:
            k = (r["syllabus"], r["year"], r["session"], r["paper"], r["variant"])
            e = sittings.get(k)
            if e is None:
                syl = r["syllabus"]
                sess_name = SESSION_NAMES.get(r["session"], r["session"])
                e = sittings[k] = {
                    "syllabus": syl,
                    "subject": names.get(syl, syl),
                    "board": boards.get(syl, ""),
                    "year": r["year"],
                    "session": r["session"],
                    "session_name": sess_name,
                    "paper": r["paper"],
                    "variant": r["variant"] or "",
                    "code": f"{r['paper']}{r['variant'] or ''}",
                    "qp": None, "ms": None,
                }
                e["label"] = (f"{names.get(syl, syl)} {syl} · {sess_name} "
                              f"{r['year']} · Paper {r['paper']}"
                              + (f" variant {r['variant']}" if r["variant"] else ""))
                subject = names.get(syl, syl)
                board = boards.get(syl, "")
                e["_hay"] = " ".join(str(x).lower() for x in (
                    syl, subject, _SUBJECT_ALIASES.get(subject, ""),
                    board, _BOARD_ALIASES.get(board, ""),
                    r["year"], f"'{str(r['year'])[2:]}",
                    _SESSION_WORDS.get(r["session"], r["session"]),
                    f"paper{r['paper']} p{r['paper']} {r['paper']}",
                    f"variant{r['variant']} v{r['variant']}" if r["variant"] else "",
                    e["code"],
                ))
            if r["kind"] in ("qp", "ms"):
                e[r["kind"]] = {"id": r["id"], "filename": r["filename"],
                                "kind": r["kind"]}
                e["_hay"] += " " + r["filename"].lower()

        # Tokens are matched against WORDS, not the raw blob: plain substring
        # matching made "cs" hit every IGCSE paper, because "igcse" contains
        # it. Filenames are split on their separators too, so "qp" and "s21"
        # are searchable parts of "0625_s21_qp_22.pdf".
        out = []
        for e in sittings.values():
            e["_words"] = set(re.split(r"[^a-z0-9']+", e.pop("_hay")))
            e["_words"].discard("")
            out.append(e)
        _LIB_INDEX["rows"] = out
        _LIB_INDEX["built_at"] = now
        return out


@app.get("/api/library/search")
def library_search(q: str = Query(..., max_length=120), limit: int = 40):
    """Free-text search over the whole archive.

    Every whitespace-separated token must match somewhere in the sitting, so
    tokens narrow rather than widen — "0625 2021 p2" finds exactly the paper a
    student means, in any order.
    """
    # Split the query exactly the way the index splits its words, so pasting a
    # whole filename ("0625_s21_qp_22.pdf") becomes the tokens 0625/s21/qp/22
    # and matches. Splitting only on whitespace left it as one token that
    # matched nothing.
    tokens = [t for t in re.split(r"[^a-z0-9']+", q.lower().strip()) if t][:8]
    if not tokens:
        return {"results": [], "total": 0}
    limit = max(1, min(int(limit or 40), 100))

    hits = []
    for e in _library_index():
        words = e["_words"]
        # Prefix match, so "chem" finds Chemistry but "cs" does not find IGCSE.
        if all(any(w.startswith(t) for w in words) for t in tokens):
            hits.append(e)

    total = len(hits)
    return {
        "total": total,
        "truncated": total > limit,
        "results": [{k: v for k, v in e.items() if k != "_words"}
                    for e in hits[:limit]],
    }


@app.get("/api/library/check-quota")
def library_check_quota(user: dict = _Depends(_get_current_user)):
    """Check if user has remaining quota for viewing past paper PDFs."""
    try:
        _access_mod.check_quota(user, "yearly_paper")
        return {"ok": True}
    except HTTPException as exc:
        if exc.status_code in (403, 429):
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        raise exc


@app.get("/api/library/pdf/{paper_id}")
def library_pdf(paper_id: int,
                user: dict | None = _Depends(_auth_mod.maybe_user)):
    """Stream one archived PDF, inline so the browser viewer can render it."""
    con = _con()
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT rel_path, filename FROM papers WHERE id = ?",
                      (paper_id,)).fetchone()
    con.close()
    if row is None:
        raise HTTPException(404, "no such paper")
    path = (ROOT / str(row["rel_path"]).replace("\\", "/")).resolve()
    # rel_path comes from our own fetch stage, but resolve-and-check anyway so
    # a bad row can never serve a file from outside the archive.
    if not str(path).startswith(str((ROOT / "data" / "raw").resolve())) \
            or not path.exists():
        raise HTTPException(404, "file missing from the archive")
    return FileResponse(path, media_type="application/pdf",
                        headers={"Content-Disposition":
                                 f'inline; filename="{row["filename"]}"'})


SOLVER_SYSTEM = """You are a Cambridge examiner and tutor for PrepWithTee, \
helping an O Level / IGCSE / A Level student with a question they photographed.

Reply in this shape, using clean HTML (no markdown, no code fences):
  <h3>What this question is testing</h3>
  <p>One sentence naming the syllabus topic.</p>
  <h3>Working</h3>
  <div class="step">...</div> for each step, in order, showing the actual
  substitution and arithmetic - never just the final line.
  <h3>Answer</h3>
  <p>The final answer with its unit and correct significant figures.</p>
  <h3>Where marks get lost</h3>
  <p>The specific mistake an examiner sees most on this type of question.</p>

Rules: teach the method so it transfers to the next question. If the photo is
unreadable or is not a question, say so plainly and ask for a clearer picture -
never guess at what it might have said."""


class SolveReq(BaseModel):
    image: str                      # data URL from the browser
    note: str | None = None         # optional "I got stuck at part (b)"


def _client_ip(request: Request) -> str:
    """Return the real client IP.

    x-forwarded-for is only trusted when the direct TCP peer is localhost
    (i.e. nginx on the same machine is proxying) — an external peer could
    forge the header and bypass rate limiting otherwise.
    """
    peer = request.client.host if request.client else ""
    if peer in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            return xff.split(",")[0].strip()
    return peer or "unknown"


# Every solve call costs real money on the tutor's Anthropic account, and the
# endpoint is unauthenticated, so cap it per IP. Generous for a student working
# through a paper, expensive for anyone scripting it. In-memory is fine while
# this runs as a single uvicorn process; move to Redis if it is ever scaled out.
SOLVE_LIMIT = 15
SOLVE_WINDOW = 3600
_solve_hits: dict[str, list[float]] = {}


def _rate_limited(ip: str) -> int | None:
    """Returns seconds to wait, or None if the caller may proceed."""
    now = time.time()
    hits = [t for t in _solve_hits.get(ip, []) if now - t < SOLVE_WINDOW]
    if len(hits) >= SOLVE_LIMIT:
        _solve_hits[ip] = hits
        return int(SOLVE_WINDOW - (now - hits[0])) + 1
    hits.append(now)
    _solve_hits[ip] = hits
    if len(_solve_hits) > 5000:            # cheap sweep so the dict cannot grow
        for k in [k for k, v in _solve_hits.items()
                  if not any(now - t < SOLVE_WINDOW for t in v)]:
            _solve_hits.pop(k, None)
    return None


@app.post("/api/solve")
def solve(req: SolveReq, request: Request):
    """Photo of a question -> worked solution, via Claude's vision model."""
    import os

    client_ip = _client_ip(request)
    wait = _rate_limited(client_ip)
    if wait is not None:
        raise HTTPException(
            429, f"That's {SOLVE_LIMIT} questions in an hour — take a break and "
                 f"try again in {wait // 60 + 1} minutes, or message us on "
                 f"WhatsApp for help.")

    m = re.match(r"data:(image/(?:png|jpe?g|webp|gif));base64,(.+)$",
                 req.image or "", re.S)
    if not m:
        raise HTTPException(400, "Send a PNG, JPEG or WebP photo.")
    media_type, b64 = m.group(1), m.group(2)
    if len(b64) > 8_000_000:
        raise HTTPException(413, "That image is too large - try a photo under 5 MB.")

    prompt = ("Here is my question. " + (req.note.strip() if req.note else "")).strip()
    html, provider = _solve_vision_complete(SOLVER_SYSTEM, prompt, media_type, b64)
    if html is None:
        print(f"[solve] no vision provider answered: {provider}", flush=True)
        raise HTTPException(
            503, "The photo solver is unavailable right now — try again shortly, "
                 "or send the photo to us on WhatsApp.")
    return {"html": _clean_html(html), "provider": provider}


# ── Live Help Chatbot Widget Endpoint (Task 17) ────────────────────────────────

CHATBOT_SYSTEM = """You are PrepWithTee's concise, friendly support assistant. PrepWithTee is a Cambridge O Level, IGCSE & A Level exam prep platform based in Lahore, Pakistan, built by Tee (a Cambridge-trained tutor).

== SUBJECTS ==
- Physics: O Level 5054 & IGCSE 0625
- Mathematics D: O Level 4024 & IGCSE 0580
- Computer Science: O Level 2210 & IGCSE 0478
- Chemistry: O Level 5070 & IGCSE 0620
- A Level: Maths 9709, Physics 9702, CS 9618
Coverage: 2020–2025 papers, all sessions and variants.

== FEATURES ==
- Topical Past Papers: 5,000+ questions organised by topic, with official mark schemes (filter by year, session, variant)
- AI Tutor (/tutor.html): Step-by-step explanations for any past-paper question; guided hints before full solutions
- MCQ Practice (/quiz.html): Timed topic-based drills with instant feedback
- Resources (/resources.html): Formula sheets, definitions glossary, Cambridge command words guide, periodic table, scientific calculator, graph tool, pseudocode editor
- Notes (/notes.html): Save text or sticky notes linked to any question or topic
- Flashcards (/flashcards.html): Spaced-repetition card decks for key facts
- Study Hub (/study-hub.html): Personalised revision plans tracking topic coverage
- Dashboard (/dashboard.html): Progress analytics, streaks, achievements, yearly & topical performance charts
- Papers Library (/library.html): Full past-paper PDFs with topic filtering

== PRICING ==
- Free: Monthly capped topical access + all free tools (no card required)
- Solo Subject: PKR 1,000/month — unlimited access to 1 syllabus
- 3 Subjects: PKR 2,000/month — unlimited access to 3 syllabuses
- All Subjects + AI Tutor: PKR 3,000/month — everything unlimited
- 1-on-1 Tutoring: PKR 20,000/month — personal Cambridge tutor + all features
Payment: JazzCash, EasyPaisa, Bank Transfer. Account upgraded within 24 hours after payment.

== CONTACT ==
- WhatsApp Tee: https://wa.me/923204884375 (+92 320 488 4375) — typically replies within a few hours
- Contact page: /contact.html
- Sign up / login: /login.html

== COMMON FAQs ==
Q: Is there a free trial?
A: Yes — the Free plan gives capped monthly access with no credit card needed.
Q: How do I pay?
A: JazzCash, EasyPaisa, or Bank Transfer. WhatsApp Tee after payment to confirm.
Q: Do you cover A Level?
A: Yes — Maths (9709), Physics (9702), and CS (9618).
Q: Can I change my plan?
A: Yes — contact Tee on WhatsApp to upgrade or change anytime.
Q: Is there a mobile app?
A: The website works on mobile browsers. A dedicated app is coming soon.

== RESPONSE RULES ==
1. Answer in 2–4 sentences maximum. Never write long paragraphs.
2. Always give a direct action: link to a page, tell them to WhatsApp Tee, or tell them to sign up.
3. Use **bold** for key terms. Use bullet lists only when listing 3+ items.
4. When mentioning a page, include its path like (→ /pricing.html).
5. If you can't help or the issue is complex, say: "For this, please message Tee directly on WhatsApp (+92 320 488 4375) or visit /contact.html"
6. Tone: warm, direct, and professional. No filler phrases like "Great question!" or "Absolutely!"."""

class ChatbotReq(BaseModel):
    message: str
    history: list[dict] | None = None

_chatbot_hits: dict[str, list[float]] = {}

@app.post("/api/chatbot")
def chatbot_reply(req: ChatbotReq, request: Request):
    msg = (req.message or "").strip()
    if not msg:
        raise HTTPException(400, "Message required")

    ip = _client_ip(request)
    now = time.time()
    hits = [t for t in _chatbot_hits.get(ip, []) if now - t < 3600]
    if len(hits) >= 20:
        raise HTTPException(429, "You've reached the message limit for this hour. Message Tee directly on WhatsApp (+92 320 488 4375) for further help.")
    hits.append(now)
    _chatbot_hits[ip] = hits

    messages = [{"role": "system", "content": CHATBOT_SYSTEM}]
    for h in (req.history or [])[-6:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            messages.append({"role": h["role"], "content": str(h["content"])[:500]})
    messages.append({"role": "user", "content": msg[:1000]})

    reply, provider = _chat_complete(messages, max_tokens=300)
    if reply is None:
        return {"reply": "We offer topicals, mark schemes, and AI tutor help for Cambridge Physics, Maths & CS! Sign up for free or message Tee on WhatsApp for instant guidance."}

    return {"reply": reply, "provider": provider}


# Vision providers for the Photo Solver tab. Tried in order; first key that is
# set wins. Groq's qwen model is multimodal and confirmed available on this plan.
SOLVE_VISION_PROVIDERS = [
    {"name": "groq", "env": "GROQ_API_KEY",
     "url": "https://api.groq.com/openai/v1/chat/completions",
     "model": os.environ.get("GROQ_VISION_MODEL", "qwen/qwen3.8-27b"),
     "extra": {"reasoning_effort": "none"}},
    {"name": "openrouter", "env": "OPENROUTER_API_KEY",
     "url": "https://openrouter.ai/api/v1/chat/completions",
     "model": os.environ.get("OPENROUTER_VISION_MODEL",
                             "meta-llama/llama-3.2-11b-vision-instruct:free")},
    {"name": "gemini", "env": "GEMINI_API_KEY",
     "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
     "model": os.environ.get("GEMINI_VISION_MODEL", "gemini-2.0-flash")},
]


def _solve_vision_complete(system: str, prompt: str, media_type: str, b64: str):
    """Photo Solver: image + prompt -> text via Anthropic or OpenAI-compat providers."""
    import requests
    errors = []

    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        try:
            import anthropic
            msg = anthropic.Anthropic(api_key=key).messages.create(
                model="claude-sonnet-4-6", max_tokens=2000, system=system,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64",
                                                 "media_type": media_type, "data": b64}},
                    {"type": "text", "text": prompt},
                ]}])
            text = "".join(b.text for b in msg.content
                           if getattr(b, "type", "") == "text")
            if text.strip():
                return text, "anthropic"
        except Exception as exc:
            errors.append(f"anthropic: {exc}")

    # OpenAI-compatible providers take the image as a data URL.
    data_url = f"data:{media_type};base64,{b64}"
    for p in SOLVE_VISION_PROVIDERS:
        pkey = os.environ.get(p["env"])
        if not pkey:
            continue
        try:
            payload = {"model": p["model"], "max_tokens": 2000, "temperature": 0.3,
                       "messages": [
                          {"role": "system", "content": system},
                          {"role": "user", "content": [
                              {"type": "text", "text": prompt},
                              {"type": "image_url",
                               "image_url": {"url": data_url}},
                          ]},
                      ]}
            payload.update(p.get("extra") or {})
            r = requests.post(
                p["url"], timeout=90,
                headers={"Authorization": f"Bearer {pkey}",
                         "Content-Type": "application/json"},
                json=payload)
            if r.status_code == 200:
                text = r.json()["choices"][0]["message"]["content"]
                if text.strip():
                    return text, p["name"]
            errors.append(f'{p["name"]} HTTP {r.status_code}: {r.text[:120]}')
        except Exception as exc:
            errors.append(f'{p["name"]}: {exc}')

    return None, ("; ".join(errors) if errors else "no vision provider configured")


# ---------------------------------------------------------------------------
# Question generator / tutor chat.
#
# A student types a prompt ("give me 5 questions on electrolysis", "explain
# moments") and gets practice questions or an explanation back. Backed by free
# hosted LLMs with a fallback chain: the first provider whose key is set on the
# server and that answers wins, so a Groq outage silently falls through to the
# next. All OpenAI-compatible, called over plain HTTP (no extra dependency).
# Groq is primary per the tutor's choice (2026-07-23); add other keys to enable
# more fallbacks.
# ---------------------------------------------------------------------------
CHAT_PROVIDERS = [
    {"name": "groq", "env": "GROQ_API_KEY",
     "url": "https://api.groq.com/openai/v1/chat/completions",
     "model": os.environ.get("GROQ_CHAT_MODEL", "openai/gpt-oss-120b")},
    {"name": "openrouter", "env": "OPENROUTER_API_KEY",
     "url": "https://openrouter.ai/api/v1/chat/completions",
     "model": "meta-llama/llama-3.3-70b-instruct:free"},
    {"name": "cerebras", "env": "CEREBRAS_API_KEY",
     "url": "https://api.cerebras.ai/v1/chat/completions",
     "model": "llama-3.3-70b"},
    # Gemini exposes an OpenAI-compatible endpoint, so it drops straight in.
    {"name": "gemini", "env": "GEMINI_API_KEY",
     "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
     "model": os.environ.get("GEMINI_CHAT_MODEL", "gemini-2.0-flash")},
]

# Multimodal siblings of the above. Needed because the PDF text layer destroys
# mathematical layout: "1/T = b/(root D) + c" extracts as the stacked lines
# "T / 1 = / D / b + c" with the radical gone entirely, and a text-only model
# duly reads that as "T = D^b + c". For anything with a fraction, radical or
# superscript the question crop is the only trustworthy source.
VISION_PROVIDERS = [
    # Qwen is the only multimodal model on our Groq plan (verified against
    # /v1/models). It is a reasoning model, and reasoning_effort matters a lot
    # here: the plan allows only 8000 tokens/minute for it, and letting it think
    # burns ~2500 completion tokens per answer, which both truncates the reply
    # and blows the whole minute's budget on one request (HTTP 413 "request too
    # large"). With reasoning off the same question costs ~350 tokens and the
    # answer is MORE complete; the granularity rule in the prompt is what keeps
    # the working detailed without it. Groq accepts only "none" or "default".
    {"name": "groq-vision", "env": "GROQ_API_KEY",
     "url": "https://api.groq.com/openai/v1/chat/completions",
     "model": os.environ.get("GROQ_VISION_MODEL", "qwen/qwen3.8-27b"),
     "extra": {"reasoning_effort": "none"},
     "timeout": 30},   # fail fast so text fallback kicks in quickly
    {"name": "gemini-vision", "env": "GEMINI_API_KEY",
     "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
     "model": os.environ.get("GEMINI_VISION_MODEL", "gemini-2.0-flash")},
    {"name": "openrouter-vision", "env": "OPENROUTER_API_KEY",
     "url": "https://openrouter.ai/api/v1/chat/completions",
     "model": os.environ.get("OPENROUTER_VISION_MODEL",
                             "qwen/qwen2.5-vl-72b-instruct:free")},
]

# Above this the base64 payload costs more than the answer is worth.
VISION_MAX_PNG_BYTES = 4 * 1024 * 1024

TUTOR_SYSTEM = """You are the study assistant at PrepWithTee, a Cambridge \
tutoring service (O Level, IGCSE and A Level). You help students practise and \
understand their syllabus.

Decide what the student wants:
- If they share an image of their written solution or a question they are stuck \
on: examine the image carefully first. Praise what they got right, identify \
exactly where they went wrong and why, then show the correct worked solution \
step by step. End with one exam tip to remember.
- If they ask for practice/exam questions on a topic, WRITE original \
Cambridge-style questions numbered Q1, Q2, ..., each ending with its mark \
allocation like [3]. Match Cambridge command words (State, Explain, Calculate, \
Describe, Show that). Wrap the worked answer/solution for each question inside \
an HTML <details> tag with a <summary>View Answer / Worked Solution</summary> tag, \
placed directly below the question, so the student can attempt it before revealing it.
- If they ask a doubt or to explain a concept, explain it step by step in plain \
language, then give one short worked example.

Formatting rules:
- Format all math equations using standard LaTeX math notation: `$ ... $` for inline math and `$$ ... $$` for block equations.
- For fractions, ALWAYS use `\\dfrac{numerator}{denominator}` so fractions render vertically and clearly instead of raw slash syntax like `a/b`.
- Wrap every numbered step in step-by-step solutions inside `<step>` tags (e.g. `<step><strong>Step 1:</strong> ...</step>`).
- Output clean, minimal HTML: `<h3>` for section titles, `<p>` for prose, \
`<ol><li>` for numbered questions, `<details>` and `<summary>` for collapsible answers, \
`<step>` for step cards, `<strong>` for emphasis. No markdown code fences, no `<html>`/`<body>` wrapper.

Stay strictly within the Cambridge syllabus level the student names. Never \
invent facts or fabricate that something is on the syllabus. If a request is \
off-topic for their course, say so briefly and steer back."""

TUTOR_SOCRATIC_PREFIX = """IMPORTANT — SOCRATIC MODE IS ACTIVE. Do NOT give direct answers. \
Instead, ask 1–2 short guiding questions that nudge the student toward the answer themselves. \
Acknowledge what they said, probe with questions like 'What happens to X when Y changes?' \
or 'Can you recall the formula for Z?'. Only after they attempt should you confirm or correct. \
Keep responses brief — max 3 short paragraphs."""

TUTOR_EXAM_PREFIX = """IMPORTANT — EXAM MODE IS ACTIVE. Be concise and exam-technique focused. \
Lead with the exact command-word behaviour expected (State = one sentence; Explain = cause→effect \
with because/therefore; Calculate = show working with units). Add mark-scheme hints in brackets \
e.g. [1 mark]. Minimal prose — the student needs exam-ready answers, not long explanations."""


def _build_system_prompt(mode: str | None = None) -> str:
    """Return the full system prompt, optionally prefixed with a mode instruction."""
    base = TUTOR_SYSTEM
    if mode == "socratic":
        return TUTOR_SOCRATIC_PREFIX + "\n\n" + base
    if mode == "exam":
        return TUTOR_EXAM_PREFIX + "\n\n" + base
    return base


TUTOR_LIMIT = 30
TUTOR_WINDOW = 3600
_tutor_hits: dict[str, list[float]] = {}


def _tutor_rate_limited(ip: str) -> int | None:
    now = time.time()
    hits = [t for t in _tutor_hits.get(ip, []) if now - t < TUTOR_WINDOW]
    if len(hits) >= TUTOR_LIMIT:
        _tutor_hits[ip] = hits
        return int(TUTOR_WINDOW - (now - hits[0])) + 1
    hits.append(now)
    _tutor_hits[ip] = hits
    if len(_tutor_hits) > 5000:
        for k in [k for k, v in _tutor_hits.items()
                  if not any(now - t < TUTOR_WINDOW for t in v)]:
            _tutor_hits.pop(k, None)
    return None


def _chat_complete(messages, max_tokens=1500):
    """Try each configured provider in order. Returns (text, provider_name) or
    (None, diagnostic-string) if none is configured or all failed."""
    import os
    import requests
    errors = []
    for p in CHAT_PROVIDERS:
        key = os.environ.get(p["env"])
        if not key:
            continue
        try:
            payload = {"model": p["model"], "messages": messages,
                       "max_tokens": max_tokens, "temperature": 0.45}
            payload.update(p.get("extra") or {})
            r = requests.post(
                p["url"], timeout=45,
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json=payload)
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"], p["name"]
            errors.append(f'{p["name"]} HTTP {r.status_code}')
        except Exception as exc:                       # network / timeout
            errors.append(f'{p["name"]}: {exc}')
    return None, ("; ".join(errors) if errors else "no provider configured")


_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S | re.I)
_THINK_OPEN = re.compile(r"<think>.*$", re.S | re.I)


def _strip_reasoning(text: str) -> str:
    """Drop a reasoning model's chain-of-thought.

    reasoning_format=hidden normally handles this, but an unterminated <think>
    (budget exhausted mid-thought) would otherwise be rendered to the student
    as the answer.
    """
    t = _THINK_BLOCK.sub("", text or "")
    t = _THINK_OPEN.sub("", t)
    return t.strip()


def _trim_truncated(text: str) -> str:
    """Cut a length-truncated reply back to its last complete element.

    Without this the student is left staring at a half-written equation like
    "s2 = 10(11". Rewind to the last closed tag and close any list we cut
    inside so the HTML is still well formed.
    """
    end = -1
    for tag in ("</li>", "</p>", "</ol>", "</ul>", "</h3>"):
        i = text.rfind(tag)
        if i >= 0:
            end = max(end, i + len(tag))
    if end > 0:
        text = text[:end]
    for open_t, close_t in (("<ol", "</ol>"), ("<ul", "</ul>")):
        if text.count(open_t) > text.count(close_t):
            text += close_t
    return text


def _vision_complete(system: str, user_text: str, png_bytes: bytes,
                     max_tokens: int = 1200):
    """Like _chat_complete, but shows the model the question crop.

    Returns (text, provider_name, truncated) or (None, diagnostic, False).
    Callers should fall back to _chat_complete when the text is None, so a
    missing or non-multimodal provider degrades to text-only behaviour.
    """
    import os
    import base64
    import requests

    data_uri = "data:image/png;base64," + base64.b64encode(png_bytes).decode()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": [
            {"type": "text", "text": user_text},
            {"type": "image_url", "image_url": {"url": data_uri}},
        ]},
    ]
    errors = []
    for p in VISION_PROVIDERS:
        key = os.environ.get(p["env"])
        if not key:
            continue
        payload = {"model": p["model"], "messages": messages,
                   "max_tokens": max_tokens, "temperature": 0.25}
        payload.update(p.get("extra") or {})
        try:
            r = requests.post(
                p["url"], timeout=p.get("timeout", 45),
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json=payload)
            if r.status_code == 200:
                choice = r.json()["choices"][0]
                content = _strip_reasoning(choice["message"].get("content") or "")
                truncated = choice.get("finish_reason") == "length"
                if content:
                    if truncated:
                        content = _trim_truncated(content)
                    return content, p["name"], truncated
                # Reasoning ate the whole budget and left no answer.
                errors.append(f'{p["name"]}: empty response')
                continue
            errors.append(f'{p["name"]} HTTP {r.status_code}')
        except Exception as exc:                       # network / timeout
            errors.append(f'{p["name"]}: {exc}')
    return None, ("; ".join(errors) if errors else "no vision provider configured"), False


def _vision_chat_complete(messages: list, max_tokens: int = 1500):
    """Like _chat_complete but uses VISION_PROVIDERS with a pre-built messages array.

    Used by /api/ask when the student attaches an image — the caller builds the
    full conversation (with image_url in the final user message) and passes it here.
    Returns (text, provider_name) or (None, diagnostic).
    """
    import os
    import requests

    errors = []
    for p in VISION_PROVIDERS:
        key = os.environ.get(p["env"])
        if not key:
            continue
        payload = {"model": p["model"], "messages": messages,
                   "max_tokens": max_tokens, "temperature": 0.45}
        payload.update(p.get("extra") or {})
        try:
            r = requests.post(p["url"], timeout=90,
                              headers={"Authorization": f"Bearer {key}",
                                       "Content-Type": "application/json"},
                              json=payload)
            if r.status_code == 200:
                choice = r.json()["choices"][0]
                content = _strip_reasoning(choice["message"].get("content") or "")
                if content:
                    return content, p["name"]
                errors.append(f'{p["name"]}: empty response')
                continue
            errors.append(f'{p["name"]} HTTP {r.status_code}')
        except Exception as exc:
            errors.append(f'{p["name"]}: {exc}')
    return None, ("; ".join(errors) if errors else "no vision provider configured")


def _chat_stream(messages, max_tokens=1500):
    import os
    import requests
    import json
    errors = []
    for p in CHAT_PROVIDERS:
        key = os.environ.get(p["env"])
        if not key:
            continue
        try:
            payload = {"model": p["model"], "messages": messages,
                       "max_tokens": max_tokens, "temperature": 0.45,
                       "stream": True}
            payload.update(p.get("extra") or {})
            r = requests.post(
                p["url"], timeout=45,
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json=payload,
                stream=True)
            if r.status_code == 200:
                def gen():
                    for line in r.iter_lines():
                        if not line:
                            continue
                        line_str = line.decode("utf-8")
                        if line_str.startswith("data: "):
                            data_content = line_str[6:].strip()
                            if data_content == "[DONE]":
                                break
                            try:
                                data_json = json.loads(data_content)
                                choice = data_json["choices"][0]
                                delta = choice.get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content, p["name"]
                            except Exception:
                                pass
                return gen, p["name"]
            errors.append(f'{p["name"]} HTTP {r.status_code}')
        except Exception as exc:
            errors.append(f'{p["name"]}: {exc}')
    return None, ("; ".join(errors) if errors else "no provider configured")


def _vision_chat_stream(messages, max_tokens=1500):
    import os
    import requests
    import json
    errors = []
    for p in VISION_PROVIDERS:
        key = os.environ.get(p["env"])
        if not key:
            continue
        payload = {"model": p["model"], "messages": messages,
                   "max_tokens": max_tokens, "temperature": 0.45,
                   "stream": True}
        payload.update(p.get("extra") or {})
        try:
            r = requests.post(
                p["url"], timeout=90,
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json=payload,
                stream=True)
            if r.status_code == 200:
                def gen():
                    for line in r.iter_lines():
                        if not line:
                            continue
                        line_str = line.decode("utf-8")
                        if line_str.startswith("data: "):
                            data_content = line_str[6:].strip()
                            if data_content == "[DONE]":
                                break
                            try:
                                data_json = json.loads(data_content)
                                choice = data_json["choices"][0]
                                delta = choice.get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content, p["name"]
                            except Exception:
                                pass
                return gen, p["name"]
            errors.append(f'{p["name"]} HTTP {r.status_code}')
        except Exception as exc:
            errors.append(f'{p["name"]}: {exc}')
    return None, ("; ".join(errors) if errors else "no vision provider configured")


def _topic_samples(syllabus: str | None, topic: str | None, k: int = 4) -> str:
    """A few real question stems for the topic, to anchor the model's style.

    A light touch of grounding without a full RAG index: it just nudges the
    generated questions towards genuine Cambridge phrasing and difficulty."""
    if not syllabus or not topic:
        return ""
    try:
        con = _con()
        con.row_factory = sqlite3.Row
        # RANDOM() is SQLite; Postgres spells it random().
        rnd = "random()" if _USE_PG else "RANDOM()"
        rows = con.execute(
            f"""SELECT q.text FROM classifications c
                JOIN questions q ON q.id = c.question_id
                JOIN papers p ON p.id = q.paper_id
                WHERE p.syllabus = ? AND (c.topic = ? OR c.secondary_topic = ?)
                  AND q.text IS NOT NULL AND length(q.text) > 40
                ORDER BY {rnd} LIMIT ?""",
            (syllabus, topic, topic, k)).fetchall()
        con.close()
    except Exception:
        return ""
    return "\n---\n".join(re.sub(r"\s+", " ", r["text"])[:420] for r in rows)


_DANGEROUS_TAGS = re.compile(
    r"<(script|iframe|object|embed|style|link|base|meta)\b[^>]*>.*?</\1>|"
    r"<(script|iframe|object|embed|style|link|base|meta)\b[^>]*/?>",
    re.I | re.S)
_EVENT_ATTRS = re.compile(r"\s+on\w+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]*)", re.I)
_JS_HREF = re.compile(r'(?:href|src|action)\s*=\s*(["\'])javascript:', re.I)


def _sanitize(html: str) -> str:
    html = _DANGEROUS_TAGS.sub("", html)
    html = _EVENT_ATTRS.sub("", html)
    html = _JS_HREF.sub(r'href=\1#', html)
    return html


_SUPERS = str.maketrans("0123456789+-n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻ⁿ")
_SUBS = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
_LATEX_WORDS = {
    r"\pm": "±", r"\mp": "∓", r"\times": "×", r"\div": "÷", r"\cdot": "·",
    r"\leq": "≤", r"\le": "≤", r"\geq": "≥", r"\ge": "≥", r"\neq": "≠",
    r"\pi": "π", r"\theta": "θ", r"\alpha": "α", r"\beta": "β", r"\lambda": "λ",
    r"\mu": "μ", r"\omega": "ω", r"\Delta": "Δ", r"\delta": "δ",
    r"\circ": "°", r"\degree": "°", r"\infty": "∞", r"\approx": "≈",
    r"\rightarrow": "→", r"\to": "→", r"\Rightarrow": "⇒",
    r"\left": "", r"\right": "", r"\,": " ", r"\;": " ", r"\!": "",
    r"\quad": " ", r"\qquad": "  ", r"\%": "%", r"\$": "$",
}


def _plain_math(s: str | None, collapse_ws: bool = True) -> str:
    """Rewrite LaTeX / caret notation as the plain Unicode a printed paper uses.

    Free models slip into LaTeX ($x^2$, \\frac{a}{b}) whatever the prompt says,
    and the raw markup renders as noise like "xA2". Cambridge papers are typeset
    plainly, so everything the student sees goes through here.

    collapse_ws is off for HTML, where runs of spaces are load-bearing inside
    <pre> blocks (CS pseudocode).
    """
    if not s:
        return s or ""
    t = str(s)
    # A literal currency $ arrives escaped as \$ and must survive the pass that
    # strips math delimiters, so park it out of reach first.
    SENTINEL = "\x00CUR\x00"
    t = t.replace(r"\$", SENTINEL)
    # \begin{...} ... \end{...} wrappers add nothing once the markup is gone
    t = re.sub(r"\\(?:begin|end)\s*\{[^{}]*\}", "", t)
    # Degrees before the word table, or ^\circ leaves a stranded caret.
    t = re.sub(r"\^\s*(?:\{\s*\\circ\s*\}|\\circ)", "°", t)
    t = re.sub(r"\\(?:text|mathrm|mathbf|textbf|mbox|operatorname)\s*\{([^{}]*)\}",
               r"\1", t)
    # \frac and \sqrt nest, and the brace groups cannot match across an inner
    # pair, so rewrite innermost-first until the string stops changing.
    for _ in range(6):
        before = t
        t = re.sub(r"\\sqrt\s*\[\s*3\s*\]\s*\{([^{}]*)\}", r"∛(\1)", t)
        t = re.sub(r"\\sqrt\s*\{([^{}]*)\}", r"√(\1)", t)
        t = re.sub(r"\\sqrt\s+(\w+)", r"√\1", t)
        t = re.sub(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"(\1)/(\2)", t)
        if t == before:
            break
    for k, v in _LATEX_WORDS.items():
        t = t.replace(k, v)
    # ^{...} / ^n -> superscript, _{...} / _n -> subscript
    t = re.sub(r"\^\{([0-9+\-n]+)\}", lambda m: m.group(1).translate(_SUPERS), t)
    t = re.sub(r"\^([0-9n])", lambda m: m.group(1).translate(_SUPERS), t)
    t = re.sub(r"_\{([0-9]+)\}", lambda m: m.group(1).translate(_SUBS), t)
    t = re.sub(r"(?<=[A-Za-z])_([0-9])", lambda m: m.group(1).translate(_SUBS), t)
    # Inline/display math delimiters, now that their contents are plain
    t = re.sub(r"\\[\[\]()]", "", t)
    t = t.replace("$$", "").replace("$", "")
    # Any stray control sequence left over: drop the backslash, keep the word
    t = re.sub(r"\\([A-Za-z]+)", r"\1", t)
    t = t.replace("\\", "").replace(SENTINEL, "$")
    if collapse_ws:
        t = re.sub(r"[ \t]{2,}", " ", t)
        return t.strip()
    return t


def _clean_html(text: str, strip_latex: bool = True) -> str:
    """Models sometimes wrap output in ```html fences or emit a little markdown.
    Strip the fences; if it clearly isn't HTML, do a minimal markdown pass."""
    t = text.strip()
    t = re.sub(r"^```(?:html)?\s*|\s*```$", "", t).strip()
    # Every student-facing answer goes through here, so this is the one place
    # LaTeX has to be normalised for the tutor, the solver and the quiz alike.
    if strip_latex:
        t = _plain_math(t, collapse_ws=False)
    if re.search(r"<(h3|p|ol|ul|li|div|strong)\b", t, re.I):
        return _sanitize(t)
    # Minimal markdown -> HTML for the rare plain-text reply.
    t = re.sub(r"^###\s*(.+)$", r"<h3>\1</h3>", t, flags=re.M)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    blocks = []
    for para in re.split(r"\n\s*\n", t):
        para = para.strip()
        if not para:
            continue
        if para.startswith("<h3>"):
            blocks.append(para)
        elif re.match(r"^(\d+\.|[-*])\s", para):
            _clean = [re.sub(r'^(\d+\.|[-*])\s', '', ln).strip()
                      for ln in para.splitlines() if ln.strip()]
            items = "".join("<li>" + part + "</li>" for part in _clean)
            blocks.append(f"<ol>{items}</ol>")
        else:
            blocks.append(f"<p>{para}</p>")
    return _sanitize("".join(blocks))


class AskReq(BaseModel):
    message: str
    syllabus: str | None = None
    topic: str | None = None
    history: list[dict] | None = None   # prior [{role, content}] turns
    image: str | None = None            # data-URI from student's attached image (legacy)
    images: list[str] | None = None     # array of data-URIs from student's attached images
    session_id: str | None = None       # to associate with a persistent session
    summary: str | None = None          # client-held rolling summary of older turns
    mode: str | None = None             # 'socratic' | 'exam' | None (normal)


class RenameSessionReq(BaseModel):
    title: str


class PinSessionReq(BaseModel):
    pinned: bool


class FeedbackReq(BaseModel):
    feedback: str | None # "up" | "down" | None


@app.get("/api/tutor/sessions")
def get_tutor_sessions(user: dict = _Depends(_get_current_user)):
    import users_db as _udb
    sessions = _udb.list_tutor_sessions(user["id"])
    return {"sessions": sessions}


@app.get("/api/tutor/sessions/{session_id}")
def get_tutor_session_details(session_id: str, user: dict = _Depends(_get_current_user)):
    import users_db as _udb
    session = _udb.get_tutor_session(session_id, user["id"])
    if not session:
        raise _HTTPException(404, "Session not found")
    return {"session": session}


@app.post("/api/tutor/sessions/{session_id}/title")
def rename_tutor_session(session_id: str, req: RenameSessionReq, user: dict = _Depends(_get_current_user)):
    import users_db as _udb
    ok = _udb.rename_tutor_session(session_id, user["id"], req.title)
    if not ok:
        raise _HTTPException(404, "Session not found")
    return {"ok": True}


@app.patch("/api/tutor/sessions/{session_id}")
def pin_tutor_session(session_id: str, req: PinSessionReq, user: dict = _Depends(_get_current_user)):
    import users_db as _udb
    ok = _udb.pin_tutor_session(session_id, user["id"], req.pinned)
    if not ok:
        raise _HTTPException(404, "Session not found")
    return {"ok": True}


@app.delete("/api/tutor/sessions/{session_id}")
def delete_tutor_session(session_id: str, user: dict = _Depends(_get_current_user)):
    import users_db as _udb
    ok = _udb.delete_tutor_session(session_id, user["id"])
    if not ok:
        raise _HTTPException(404, "Session not found")
    return {"ok": True}


@app.post("/api/tutor/messages/{message_id}/feedback")
def set_tutor_message_feedback(message_id: str, req: FeedbackReq, user: dict = _Depends(_get_current_user)):
    import users_db as _udb
    ok = _udb.set_message_feedback(message_id, req.feedback)
    if not ok:
        raise _HTTPException(404, "Message not found")
    return {"ok": True}


@app.post("/api/ask")
def ask(req: AskReq, request: Request):
    """Chat: generate practice questions or explain a concept (non-streaming fallback)."""
    import uuid
    import users_db as _udb
    
    user = _auth_mod.maybe_user(request.cookies.get("session"))
    session_id = req.session_id
    new_session_created = False
    
    if user:
        from access import check_quota
        check_quota(user, "ai_tutor")
        if not session_id:
            session_id = str(uuid.uuid4())
            _udb.create_tutor_session(user["id"], session_id, req.syllabus, req.topic)
            new_session_created = True
    else:
        client_ip = _client_ip(request)
        wait = _tutor_rate_limited(client_ip)
        if wait is not None:
            raise HTTPException(
                429, f"That's {TUTOR_LIMIT} questions this hour — take a short break "
                     f"and try again in {wait // 60 + 1} minutes.")

    message = (req.message or "").strip()
    images_to_process = req.images or []
    if req.image and not images_to_process:
        images_to_process = [req.image]

    if not message and not images_to_process:
        raise HTTPException(400, "Type what you'd like to practise or ask.")

    history = req.history or []
    if user and session_id and not history:
        session_details = _udb.get_tutor_session(session_id, user["id"])
        if session_details and "messages" in session_details:
            history = [{"role": m["role"], "content": m["content"]} for m in session_details["messages"]]

    user_msg_id = str(uuid.uuid4())
    bot_msg_id = str(uuid.uuid4())
    
    user_attachments = []
    if user and session_id:
        import secrets
        for idx, img_data in enumerate(images_to_process):
            rand_hex = secrets.token_hex(4)
            filename = f"att_{idx}_{rand_hex}.webp"
            signed_url = _udb.upload_attachment(user["id"], session_id, filename, img_data)
            if signed_url:
                user_attachments.append({"type": "image", "url": signed_url})
            else:
                user_attachments.append({"type": "image", "url": img_data})
        _udb.save_tutor_message(user_msg_id, session_id, "user", message, user_attachments)

    msgs = [{"role": "system", "content": _build_system_prompt(req.mode)}]
    
    if req.summary:
        msgs.append({"role": "system", "content": f"Recap of earlier conversation: {req.summary}"})
        
    if req.syllabus:
        where = f"The student is studying syllabus {req.syllabus}"
        if req.topic:
            where += f", topic: {req.topic}"
        msgs.append({"role": "system", "content": where + "."})
        
    if user and req.syllabus:
        try:
            progress_list = _udb.get_progress(user["id"], req.syllabus)
            if progress_list:
                confident_count = sum(1 for p in progress_list if p.get("status") == "confident")
                in_progress_count = sum(1 for p in progress_list if p.get("status") == "in_progress")
                prog_msg = f"Student progress on this syllabus: {confident_count} topics confident, {in_progress_count} in-progress."
                if req.topic:
                    active_progress = next((p for p in progress_list if p.get("topic") == req.topic), None)
                    if active_progress:
                        prog_msg += f" Current topic '{req.topic}' status is '{active_progress.get('status', 'not_started')}'."
                msgs.append({"role": "system", "content": prog_msg})
        except Exception:
            pass

    ctx = _topic_samples(req.syllabus, req.topic)
    if ctx:
        msgs.append({"role": "system",
                     "content": "Real Cambridge question stems on this topic, "
                                "for style reference only (do not copy):\n" + ctx})

    sliced_history = history[-6:]
    for h in sliced_history:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            msgs.append({"role": h["role"], "content": str(h["content"])[:4000]})

    if images_to_process:
        content_list = [{"type": "text", "text": (message or "Please review my work and tell me what I did wrong.")[:4000]}]
        for img in images_to_process:
            data_uri = img if img.startswith("data:") else f"data:image/jpeg;base64,{img}"
            content_list.append({"type": "image_url", "image_url": {"url": data_uri}})
        msgs.append({"role": "user", "content": content_list})
        text, prov = _vision_chat_complete(msgs)
        if text is None:
            raise HTTPException(503, "Image review unavailable — no vision provider responded. (" + prov + ")")
    else:
        msgs.append({"role": "user", "content": message[:4000]})
        text, prov = _chat_complete(msgs)
        if text is None:
            raise HTTPException(
                503, "The question generator is not switched on yet — set "
                     "GROQ_API_KEY on the server and restart. (" + prov + ")")

    clean_text = _strip_reasoning(text)
    clean_html = _clean_html(clean_text, strip_latex=False)

    # Summarize if long
    new_summary = None
    if len(history) >= 12:
        try:
            recap_prompt = [
                {"role": "system", "content": "Condense the following conversation history into a 2-3 sentence summary/recap of what has been discussed and explained so far, to serve as context for the continuation of the tutoring session. Be concise and factual."},
            ]
            if req.summary:
                recap_prompt.append({"role": "system", "content": f"Prior recap: {req.summary}"})
            for h in history[:-6]:
                recap_prompt.append({"role": h["role"], "content": h["content"]})
            
            summary_text, _ = _chat_complete(recap_prompt, max_tokens=150)
            if summary_text:
                new_summary = summary_text.strip()
                if user and session_id:
                    _udb.update_session_summary(session_id, new_summary)
        except Exception:
            pass

    if user and session_id:
        _udb.save_tutor_message(bot_msg_id, session_id, "assistant", clean_html, [], prov)
        
        if new_session_created or len(history) == 0:
            try:
                title_prompt = [
                    {"role": "system", "content": "Generate a short, 3-5 word title summarizing the following student query and response. Do not use quotes or punctuation. Return ONLY the title. E.g. 'Electrolysis Revision'"},
                    {"role": "user", "content": f"Query: {message}\nResponse: {clean_text[:500]}"}
                ]
                title_text, _ = _chat_complete(title_prompt, max_tokens=15)
                if title_text:
                    title = title_text.strip().replace('"', '').replace("'", "")
                    _udb.rename_tutor_session(session_id, user["id"], title[:50])
            except Exception:
                pass

    return {
        "html": clean_html, 
        "provider": prov,
        "session_id": session_id,
        "user_message_id": user_msg_id,
        "bot_message_id": bot_msg_id,
        "summary": new_summary or req.summary
    }


@app.post("/api/tutor/stream")
def tutor_stream(req: AskReq, request: Request):
    """Chat: generate practice questions or explain a concept with streaming response (SSE)."""
    import uuid
    import users_db as _udb
    
    user = _auth_mod.maybe_user(request.cookies.get("session"))
    session_id = req.session_id
    new_session_created = False
    
    if user:
        from access import check_quota
        check_quota(user, "ai_tutor")
        existing_session = _udb.get_tutor_session(session_id, user["id"]) if session_id else None
        if not existing_session:
            session_id = str(uuid.uuid4())
            _udb.create_tutor_session(user["id"], session_id, req.syllabus, req.topic, req.mode or "normal")
            new_session_created = True
    else:
        client_ip = _client_ip(request)
        wait = _tutor_rate_limited(client_ip)
        if wait is not None:
            raise HTTPException(
                429, f"That's {TUTOR_LIMIT} questions this hour — take a short break "
                     f"and try again in {wait // 60 + 1} minutes.")

    message = (req.message or "").strip()
    images_to_process = req.images or []
    if req.image and not images_to_process:
        images_to_process = [req.image]

    history = req.history or []
    active_mode = req.mode or "normal"
    
    if user and session_id:
        session_details = _udb.get_tutor_session(session_id, user["id"])
        if session_details:
            if "messages" in session_details and not history:
                history = [{"role": m["role"], "content": m["content"]} for m in session_details["messages"]]
            if req.mode:
                if session_details.get("mode") != req.mode:
                    _udb.update_session_mode(session_id, user["id"], req.mode)
            elif session_details.get("mode"):
                active_mode = session_details["mode"]

    user_msg_id = str(uuid.uuid4())
    bot_msg_id = str(uuid.uuid4())
    
    user_attachments = []
    if user and session_id:
        import secrets
        for idx, img_data in enumerate(images_to_process):
            rand_hex = secrets.token_hex(4)
            filename = f"att_{idx}_{rand_hex}.webp"
            signed_url = _udb.upload_attachment(user["id"], session_id, filename, img_data)
            if signed_url:
                user_attachments.append({"type": "image", "url": signed_url})
            else:
                user_attachments.append({"type": "image", "url": img_data})
        try:
            _udb.save_tutor_message(user_msg_id, session_id, "user", message, user_attachments)
        except Exception as err:
            print(f"Non-fatal error saving user message: {err}", flush=True)

    msgs = [{"role": "system", "content": _build_system_prompt(active_mode)}]
    
    if req.summary:
        msgs.append({"role": "system", "content": f"Recap of earlier conversation: {req.summary}"})
        
    if req.syllabus:
        where = f"The student is studying syllabus {req.syllabus}"
        if req.topic:
            where += f", topic: {req.topic}"
        msgs.append({"role": "system", "content": where + "."})
        
    if user and req.syllabus:
        try:
            progress_list = _udb.get_progress(user["id"], req.syllabus)
            if progress_list:
                confident_count = sum(1 for p in progress_list if p.get("status") == "confident")
                in_progress_count = sum(1 for p in progress_list if p.get("status") == "in_progress")
                prog_msg = f"Student progress on this syllabus: {confident_count} topics confident, {in_progress_count} in-progress."
                if req.topic:
                    active_progress = next((p for p in progress_list if p.get("topic") == req.topic), None)
                    if active_progress:
                        prog_msg += f" Current topic '{req.topic}' status is '{active_progress.get('status', 'not_started')}'."
                msgs.append({"role": "system", "content": prog_msg})
        except Exception:
            pass

    ctx = _topic_samples(req.syllabus, req.topic)
    if ctx:
        msgs.append({"role": "system",
                     "content": "Real Cambridge question stems on this topic, "
                                "for style reference only (do not copy):\n" + ctx})

    sliced_history = history[-6:]
    for h in sliced_history:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            msgs.append({"role": h["role"], "content": str(h["content"])[:4000]})

    def event_generator():
        nonlocal new_session_created
        accumulated_text = []
        prov_used = "unknown"
        
        try:
            if images_to_process:
                content_list = [{"type": "text", "text": (message or "Please review my work and tell me what I did wrong.")[:4000]}]
                for img in images_to_process:
                    data_uri = img if img.startswith("data:") else f"data:image/jpeg;base64,{img}"
                    content_list.append({"type": "image_url", "image_url": {"url": data_uri}})
                msgs.append({"role": "user", "content": content_list})
                stream_res, prov = _vision_chat_stream(msgs)
            else:
                msgs.append({"role": "user", "content": message[:4000]})
                stream_res, prov = _chat_stream(msgs)
                
            if not stream_res:
                yield f"data: {json.dumps({'error': 'No active LLM providers configured or responding'})}\n\n"
                return
                
            prov_used = prov
            for token, p_name in stream_res():
                accumulated_text.append(token)
                yield f"data: {json.dumps({'token': token})}\n\n"
                
        except Exception as e:
            yield f"data: {json.dumps({'error': f'Streaming error: {str(e)}'})}\n\n"
            return
            
        full_text = "".join(accumulated_text)
        clean_text = _strip_reasoning(full_text)
        clean_html = _clean_html(clean_text, strip_latex=False)
        
        new_summary = None
        if len(history) >= 12:
            try:
                recap_prompt = [
                    {"role": "system", "content": "Condense the following conversation history into a 2-3 sentence summary/recap of what has been discussed and explained so far, to serve as context for the continuation of the tutoring session. Be concise and factual."},
                ]
                if req.summary:
                    recap_prompt.append({"role": "system", "content": f"Prior recap: {req.summary}"})
                for h in history[:-6]:
                    recap_prompt.append({"role": h["role"], "content": h["content"]})
                
                summary_text, _ = _chat_complete(recap_prompt, max_tokens=150)
                if summary_text:
                    new_summary = summary_text.strip()
                    if user and session_id:
                        _udb.update_session_summary(session_id, new_summary)
            except Exception:
                pass

        if user and session_id:
            _udb.save_tutor_message(bot_msg_id, session_id, "assistant", clean_html, [], prov_used)
            
            if new_session_created or len(history) == 0:
                try:
                    title_prompt = [
                        {"role": "system", "content": "Generate a short, 3-5 word title summarizing the following student query and response. Do not use quotes or punctuation. Return ONLY the title. E.g. 'Electrolysis Revision'"},
                        {"role": "user", "content": f"Query: {message}\nResponse: {clean_text[:500]}"}
                    ]
                    title_text, _ = _chat_complete(title_prompt, max_tokens=15)
                    if title_text:
                        title = title_text.strip().replace('"', '').replace("'", "")
                        _udb.rename_tutor_session(session_id, user["id"], title[:50])
                except Exception:
                    pass

        final_meta = {
            "done": True,
            "html": clean_html,
            "provider": prov_used,
            "session_id": session_id,
            "mode": active_mode,
            "user_message_id": user_msg_id,
            "bot_message_id": bot_msg_id,
            "summary": new_summary or req.summary
        }
        yield f"data: {json.dumps(final_meta)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/transcribe")
async def transcribe_audio(audio: UploadFile = File(...), request: Request = None):
    """Convert student voice note to text via Groq Whisper."""
    import os
    import requests as _req

    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise HTTPException(503, "Voice transcription is not available — GROQ_API_KEY not set.")

    audio_bytes = await audio.read()
    if len(audio_bytes) > 25 * 1024 * 1024:
        raise HTTPException(413, "Audio file too large (max 25 MB).")
    if not audio_bytes:
        raise HTTPException(400, "Empty audio received.")

    model = os.environ.get("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")
    try:
        r = _req.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            files={"file": (audio.filename or "voice.webm", audio_bytes,
                            audio.content_type or "audio/webm")},
            data={"model": model, "response_format": "json"},
            timeout=30)
        if r.status_code != 200:
            raise HTTPException(503, f"Transcription failed (HTTP {r.status_code}).")
        return {"text": r.json().get("text", "").strip()}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, f"Transcription error: {exc}")


FORMULA_EXPLAIN_SYSTEM = """You are a Cambridge tutor at PrepWithTee explaining \
a formula to a student in a quick, focused overlay. Be direct and practical.

Reply with EXACTLY this structure using clean HTML (no markdown, no code fences):

<h3>What it means</h3>
<p>2-3 sentences in plain English: what the formula calculates and the physical/mathematical idea behind it.</p>

<h3>When to use it</h3>
<p>The exam trigger phrases that signal this formula is needed. Keep it to a short list using <strong> for each phrase.</p>

<h3>Worked example</h3>
<p>A realistic Cambridge-style exam question, then a clean step-by-step solution. Use numbers and units.</p>

Rules: no LaTeX, use plain maths (×, ÷, ², √, Δ). Under 280 words total."""


class ExplainFormulaReq(BaseModel):
    name: str
    expr: str | None = None
    syllabus: str | None = None
    vars: str | None = None


@app.post("/api/explain-formula")
def explain_formula(req: ExplainFormulaReq, request: Request):
    """AI explanation of a formula: plain-English meaning, when to use it, worked example."""
    client_ip = _client_ip(request)
    wait = _tutor_rate_limited(client_ip)
    if wait is not None:
        raise HTTPException(
            429, f"Rate limit — try again in {wait // 60 + 1} minutes.")

    name = (req.name or "").strip()[:200]
    if not name:
        raise HTTPException(400, "Formula name required.")

    prompt_parts = [f"Formula: {name}"]
    if req.expr:
        prompt_parts.append(f"Expression: {req.expr}")
    if req.vars:
        prompt_parts.append(f"Variables: {req.vars}")
    if req.syllabus:
        prompt_parts.append(f"Cambridge syllabus: {req.syllabus}")
    prompt_parts.append("Explain this formula for a Cambridge exam student.")

    msgs = [
        {"role": "system", "content": FORMULA_EXPLAIN_SYSTEM},
        {"role": "user", "content": "\n".join(prompt_parts)},
    ]
    text, prov = _chat_complete(msgs, max_tokens=600)
    if text is None:
        raise HTTPException(503, "AI service unavailable — set GROQ_API_KEY. (" + prov + ")")
    return {"html": _clean_html(text), "provider": prov}


class DemoBookingReq(BaseModel):
    parent_name: str
    student_name: str
    contact: str
    grade: str
    subjects: list[str]
    message: str | None = None


@app.post("/api/demo")
def book_demo(req: DemoBookingReq):
    import users_db as _udb
    _udb.save_lead({
        "parent_name": req.parent_name,
        "student_name": req.student_name,
        "contact": req.contact,
        "grade": req.grade,
        "subjects": ",".join(req.subjects),
        "message": req.message,
    })

    _notify(
        f"[PrepWithTee] New Demo Request — {req.student_name}",
        f"Parent: {req.parent_name}\nStudent: {req.student_name}\nContact: {req.contact}\nGrade: {req.grade}\nSubjects: {', '.join(req.subjects)}\nMessage: {req.message or '—'}",
        rows=[
            ("Parent", req.parent_name),
            ("Student", req.student_name),
            ("Contact", req.contact),
            ("Grade / Level", req.grade),
            ("Subjects", ", ".join(req.subjects)),
            ("Message", req.message or "—"),
        ],
    )
    return {"status": "success", "message": "Demo request received successfully!"}


# ---------------------------------------------------------------------------
# Resources / notes library.
#
# Filesystem-driven so the tutor never touches code to publish: drop files into
#   data/resources/<Category>/...
# and they appear on the site. An optional _meta.json in a category folder sets
# its title/description/subject/tint; otherwise those are derived from the
# folder name. Files render inline on the page (PDFs, images) exactly like the
# past-paper library, or download for other formats.
# ---------------------------------------------------------------------------
RESOURCES_DIR = ROOT / "data" / "resources"
RESOURCE_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".webp",
                 ".docx", ".pptx", ".xlsx", ".zip", ".txt"}
_INLINE_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
_MEDIA_TYPES = {".pdf": "application/pdf", ".png": "image/png",
                ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".webp": "image/webp", ".txt": "text/plain"}


def _nice_name(name: str) -> str:
    """Folder/file stem -> a readable title, keeping acronyms (IGCSE) intact."""
    return re.sub(r"[_\-]+", " ", Path(name).stem).strip()


def _natural_key(name: str) -> list:
    """Natural sort key: splits on digit runs so '10' sorts after '9', not after '1'."""
    return [int(p) if p.isdigit() else p.lower()
            for p in re.split(r"(\d+)", name)]


def _build_tree(path: Path, resources_root: Path) -> dict | None:
    """Return a recursive {type, name, children|...} node, or None if empty."""
    if path.is_file():
        if path.suffix.lower() not in RESOURCE_EXTS or path.name.startswith((".", "_")):
            return None
        return {
            "type": "file",
            "name": path.name,
            "title": _nice_name(path.name),
            "rel": path.relative_to(resources_root).as_posix(),
            "ext": path.suffix.lower().lstrip("."),
            "inline": path.suffix.lower() in _INLINE_EXTS,
            "size": path.stat().st_size,
        }
    if path.is_dir() and not path.name.startswith((".", "_")):
        # Dirs before files; within each group, natural (numeric-aware) alphabetical
        children = [
            n for n in (
                _build_tree(c, resources_root)
                for c in sorted(path.iterdir(),
                                key=lambda x: (x.is_file(), _natural_key(x.name)))
            )
            if n is not None
        ]
        if children:
            return {"type": "dir", "name": path.name, "children": children}
    return None


def _count_files(node: dict) -> int:
    if node["type"] == "file":
        return 1
    return sum(_count_files(c) for c in node.get("children", []))


@app.get("/api/resources")
def resources():
    """Every category with its recursive file tree."""
    if not RESOURCES_DIR.is_dir():
        return {"categories": []}
    cats = []
    for d in sorted(RESOURCES_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith((".", "_")):
            continue
        meta = {}
        mp = d / "_meta.json"
        if mp.exists():
            try:
                meta = json.loads(mp.read_text("utf-8"))
            except Exception:
                meta = {}
        tree = _build_tree(d, RESOURCES_DIR)
        if tree is None:
            continue
        cats.append({
            "name": meta.get("title", _nice_name(d.name)),
            "slug": d.name,
            "description": meta.get("description", ""),
            "subject": meta.get("subject", ""),
            "board": meta.get("board", ""),
            "icon": meta.get("icon", ""),
            "tint": meta.get("tint", ""),
            "count": _count_files(tree),
            "tree": tree,
        })
    return {"categories": cats}


@app.get("/api/resources/file")
def resource_file(rel: str):
    """Serve one resource. Resolve-and-check so `rel` can never escape the
    resources folder (e.g. ../../etc/passwd)."""
    base = RESOURCES_DIR.resolve()
    path = (RESOURCES_DIR / rel).resolve()
    if not str(path).startswith(str(base)) or not path.is_file():
        raise HTTPException(404, "no such resource")
    ext = path.suffix.lower()
    disp = "inline" if ext in _INLINE_EXTS else "attachment"
    return FileResponse(
        path, media_type=_MEDIA_TYPES.get(ext, "application/octet-stream"),
        headers={"Content-Disposition": f'{disp}; filename="{path.name}"'})


class FeedbackReq(BaseModel):
    rating: int | None = None       # 1–5 stars
    message: str
    name: str | None = None
    page: str | None = None         # which page the feedback came from
    type: str | None = None         # "feedback" or "issue"


# ---------------------------------------------------------------------------
# Shared email helper.
# ---------------------------------------------------------------------------
# Two transports, tried in order:
#
#   1. Resend (RESEND_API_KEY) — preferred. Mail goes out as
#      noreply@prepwithtee.com, DKIM-signed with d=prepwithtee.com, over a
#      domain whose sending reputation is ours to build.
#   2. Gmail SMTP (SMTP_USER + SMTP_PASS) — the original path, kept as a
#      fallback so a missing/expired API key degrades to working mail rather
#      than to silence.
#
# Why the move: sending student reminders from a free @gmail.com address is
# itself the spam signal. There is no domain reputation to accrue, Gmail's bulk
# sender rules treat consumer From: addresses poorly, and Outlook/Yahoo/school
# domains discount them hard. `Reply-To` still points at the tutor's inbox, so
# replies land where they always did.
#
# Missing config on both = silent skip (unchanged behaviour in development).
_RESEND_ENDPOINT = "https://api.resend.com/emails"


def _mail_from() -> str:
    """RFC 5322 From:. Must be a domain verified in the Resend dashboard."""
    return os.environ.get("MAIL_FROM", "PrepWithTee <noreply@prepwithtee.com>")


def _reply_to() -> str:
    return os.environ.get("NOTIFY_EMAIL", "nexgentutors6@gmail.com")


def _send_resend(to_addr: str, subject: str, body: str,
                 html_body: str | None, api_key: str) -> bool:
    """Hand the message to Resend's HTTP API. Returns True if accepted."""
    import requests
    payload = {
        "from": _mail_from(),
        "to": [to_addr],
        "subject": subject,
        "text": body,
        "reply_to": _reply_to(),
        # Resend generates its own Message-ID in the sending domain and applies
        # the DKIM signature, so neither is set here — a hand-rolled Message-ID
        # in the wrong domain is what filters read as forgery.
        "headers": {
            "List-Unsubscribe": f"<mailto:{_reply_to()}?subject=unsubscribe>",
            "Auto-Submitted": "auto-generated",
        },
    }
    if html_body:
        payload["html"] = html_body
    try:
        r = requests.post(
            _RESEND_ENDPOINT, json=payload, timeout=10,
            headers={"Authorization": f"Bearer {api_key}"})
    except Exception as exc:
        print(f"[mail] resend request failed: {exc}", flush=True)
        return False
    if r.status_code >= 300:
        # Surface the reason — an unverified domain and a bad key look identical
        # from the outside, and both are silent 4xx.
        print(f"[mail] resend rejected ({r.status_code}): {r.text[:300]}", flush=True)
        return False
    return True


def _notify(subject: str, body: str, rows: list | None = None,
            to: str | None = None, cta: tuple[str, str] | None = None,
            html_override: str | None = None) -> bool:
    """Send a notification email. Returns True if it actually went out.

    `to` defaults to the tutor's own inbox (form submissions); pass a student's
    address for homework reminders. `cta` is an optional (label, url) button.
    """
    resend_key = os.environ.get("RESEND_API_KEY")
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    if not (resend_key or (smtp_user and smtp_pass)):
        return False
    to_addr = to or _reply_to()

    html_body = html_override if html_override else None
    if not html_body and rows:
        rows_html = "".join(
            f'<tr>'
            f'<td style="padding:9px 12px 9px 0;color:#888;font-size:.8rem;width:130px;vertical-align:top;white-space:nowrap">{_esc(str(k))}</td>'
            f'<td style="padding:9px 0;font-size:.88rem;color:#1a1a2e;vertical-align:top">{_esc(str(v))}</td>'
            f'</tr>'
            for k, v in rows
        )
        title = subject.replace("[PrepWithTee] ", "")
        html_body = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f4f0ea;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td style="padding:32px 16px">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:500px;margin:0 auto">
  <tr><td style="background:#2E1B4A;border-radius:12px 12px 0 0;padding:22px 28px">
    <p style="color:#C9BDF0;font-size:.75rem;margin:0;letter-spacing:.06em;text-transform:uppercase">PrepWithTee Notification</p>
    <h1 style="color:#fff;font-size:1.05rem;margin:6px 0 0;font-weight:700">{_esc(title)}</h1>
  </td></tr>
  <tr><td style="background:#fff;padding:24px 28px 28px;border-radius:0 0 12px 12px;box-shadow:0 2px 16px rgba(0,0,0,.08)">
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border-top:1px solid #eee">
      {rows_html}
    </table>
    {f'''<p style="margin:22px 0 0;text-align:center">
      <a href="{_esc(cta[1])}" style="display:inline-block;background:#E8913A;color:#fff;
         text-decoration:none;font-weight:700;font-size:.9rem;padding:11px 26px;
         border-radius:10px">{_esc(cta[0])}</a></p>''' if cta else ''}
  </td></tr>
  <tr><td style="padding:14px 0;text-align:center;color:#bbb;font-size:.74rem">
    PrepWithTee &nbsp;·&nbsp; {_esc(_reply_to())}
  </td></tr>
</table></td></tr></table>
</body></html>"""

    # Preferred transport. Falls through to SMTP on failure so an expired key or
    # a Resend outage does not silently drop a student's homework reminder.
    if resend_key and _send_resend(to_addr, subject, body, html_body, resend_key):
        return True
    if not (smtp_user and smtp_pass):
        return False

    msg = MIMEMultipart("alternative")
    # Deliverability headers. Without these Gmail scored student reminders as
    # spam: a bare address with no display name, no Date, no Message-ID and no
    # unsubscribe path looks like bulk mail from a script — which it is, so it
    # has to say who it is and how to stop it.
    from email.utils import formataddr, formatdate, make_msgid
    msg["Subject"] = subject
    msg["From"] = formataddr(("PrepWithTee", smtp_user))
    msg["To"] = to_addr
    msg["Reply-To"] = _reply_to()
    msg["Date"] = formatdate(localtime=True)
    # Message-ID must be in the domain the mail is actually FROM. On this path
    # that is the Gmail account, NOT prepwithtee.com — claiming a domain the
    # message was not sent from is what filters read as forgery.
    msg["Message-ID"] = make_msgid(domain=smtp_user.rsplit("@", 1)[-1])
    msg["List-Unsubscribe"] = f"<mailto:{smtp_user}?subject=unsubscribe>"
    # NO List-Unsubscribe-Post here. RFC 8058 one-click requires an https URI in
    # List-Unsubscribe for the receiver to POST to; declaring it alongside a
    # mailto-only header is malformed, and Gmail/Yahoo check the pairing. Add it
    # back the day there is a real https unsubscribe endpoint to point at.
    msg["Auto-Submitted"] = "auto-generated"
    msg.attach(MIMEText(body, "plain", "utf-8"))
    if html_body:
        msg.attach(MIMEText(html_body, "html", "utf-8"))
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=8) as srv:
            srv.starttls()
            srv.login(smtp_user, smtp_pass)
            srv.send_message(msg)
        return True
    except Exception as exc:
        print(f"Email notification skipped: {exc}")
        return False


@app.post("/api/feedback")
def submit_feedback(req: FeedbackReq):
    msg = (req.message or "").strip()
    if not msg:
        raise HTTPException(400, "Message is required")
    if len(msg) > 2000:
        raise HTTPException(400, "Message too long")
    if req.rating is not None and not (1 <= req.rating <= 5):
        raise HTTPException(400, "Rating must be 1–5")

    import users_db as _udb
    fb_type = req.type or "feedback"
    _udb.save_feedback({
        "rating": req.rating,
        "message": msg,
        "name": (req.name or "").strip() or None,
        "page": req.page,
        "type": fb_type,
    })

    stars = f"{req.rating}/5 ★" if req.rating else "—"
    _notify(
        f"[PrepWithTee] New {fb_type.title()} — {req.page or 'site'}",
        f"Type:    {fb_type}\nStars:   {stars}\nName:    {req.name or '—'}\nPage:    {req.page or '—'}\n\n{msg}",
        rows=[
            ("Type", fb_type.title()),
            ("Stars", stars),
            ("Name", req.name or "—"),
            ("Page", req.page or "—"),
            ("Message", msg),
        ],
    )
    return {"status": "success"}


class SubjectRequestReq(BaseModel):
    subject: str
    board: str | None = None
    message: str | None = None


@app.post("/api/subject-request")
def subject_request(req: SubjectRequestReq):
    subj = (req.subject or "").strip()
    if not subj:
        raise HTTPException(400, "Subject name is required")
    if len(subj) > 200:
        raise HTTPException(400, "Subject name too long")

    import users_db as _udb
    _udb.save_subject_request({
        "subject": subj,
        "board": (req.board or "").strip() or None,
        "message": (req.message or "").strip() or None,
    })

    _notify(
        f"[PrepWithTee] Subject Request — {subj}",
        f"Subject: {subj}\nBoard:   {req.board or '—'}\n\n{req.message or '(no message)'}",
        rows=[
            ("Subject", subj),
            ("Board", req.board or "—"),
            ("Message", req.message or "—"),
        ],
    )
    return {"status": "success"}


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


@app.get("/admin")
def admin_redirect(key: str = ""):
    """Legacy entry point — the dashboard is now the static admin.html SPA."""
    return RedirectResponse(f"/admin.html?key={quote(key)}" if key else "/admin.html")


def _crop_files_for_key(q_key: str):
    """(debug_png, crop_pdf) Paths for a natural key like '0625_s25_11_q01'.

    The key IS the on-disk layout — 'data/debug/{paper_key}/{slug}.png' — so a
    caller that already has the key needs no database at all. That matters in
    bulk: the report builder used to re-query one question at a time, which
    against Supabase meant a fresh remote connection per crop.

    Both paths are containment-checked against their data/ roots; one that
    escapes comes back as None rather than raising, so callers treat it as
    absent.
    """
    paper_key, _, slug = q_key.rpartition("_")
    if not paper_key or not slug or "/" in q_key or "\\" in q_key:
        return None
    png_path = (ROOT / "data" / "debug" / paper_key / f"{slug}.png").resolve()
    crop_path = (ROOT / "data" / "crops" / paper_key / f"{slug}.pdf").resolve()
    if not str(png_path).startswith(str((ROOT / "data" / "debug").resolve())):
        png_path = None
    if not str(crop_path).startswith(str((ROOT / "data" / "crops").resolve())):
        crop_path = None
    return png_path, crop_path


def _question_crop_files(question_id: int):
    """(debug_png, crop_pdf) Paths for a question, or None if it doesn't exist.

    Shared by the preview endpoint and the AI explainer so they can never
    disagree about which image belongs to a question.
    """
    q_key = _question_key(question_id)
    return _crop_files_for_key(q_key) if q_key else None


def _png_bytes_for_key(q_key: str) -> bytes | None:
    """The question crop as PNG bytes, straight from the natural key."""
    files = _crop_files_for_key(q_key) if q_key else None
    if files is None:
        return None
    png_path, crop_path = files
    try:
        if png_path and png_path.exists():
            return png_path.read_bytes()
        if crop_path and crop_path.exists():
            import fitz
            with fitz.open(str(crop_path)) as doc:
                return doc[0].get_pixmap(dpi=150).tobytes("png")
    except Exception:
        return None
    return None


def _question_png_bytes(question_id: int) -> bytes | None:
    """The question crop as PNG bytes, for feeding to a vision model."""
    q_key = _question_key(question_id)
    return _png_bytes_for_key(q_key) if q_key else None


@app.get("/api/question/{question_id}/preview")
def question_preview(question_id: int):
    """Serve the question crop as a PNG — used by the lightbox in the preview panel.

    Tries the pre-rendered debug PNG first (fast); falls back to rendering the
    crop PDF on demand with PyMuPDF so the endpoint works even when debug PNGs
    were not synced to the server.
    """
    files = _question_crop_files(question_id)
    if files is None:
        raise HTTPException(404, "question not found")
    png_path, crop_path = files

    # Fast path: pre-rendered debug PNG
    if png_path and png_path.exists():
        return FileResponse(png_path, media_type="image/png",
                            headers={"Cache-Control": "public, max-age=86400"})

    # Fallback: render first page of crop PDF with PyMuPDF
    if not crop_path or not crop_path.exists():
        raise HTTPException(404, "preview image not available for this question")
    try:
        import fitz
        with fitz.open(str(crop_path)) as doc:
            img_bytes = doc[0].get_pixmap(dpi=150).tobytes("png")
        return Response(content=img_bytes, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=3600"})
    except Exception as exc:
        raise HTTPException(500, f"could not render preview: {exc}")


@app.get("/api/question/{question_id}/ms-preview")
def question_ms_preview(question_id: int):
    """Serve the official mark scheme crop for a question as a PNG.

    Progress Tracker reveals this after a student has answered a real past-paper
    question, so they compare against Cambridge's own marking points rather
    than something a model invented.
    """
    con = _con()
    con.row_factory = sqlite3.Row
    row = con.execute(
        """SELECT m.crop_path
           FROM questions q
           JOIN ms_entries m ON m.paper_id = (
               SELECT p2.id FROM papers p2
               JOIN papers p1 ON p1.id = q.paper_id
               WHERE p2.syllabus = p1.syllabus AND p2.year = p1.year
                 AND p2.session = p1.session AND p2.paper = p1.paper
                 AND p2.variant = p1.variant AND p2.kind = 'ms')
             AND m.question_number = q.number
             AND m.sub_part = q.sub_part
           WHERE q.id = ?""",
        (question_id,)).fetchone()
    con.close()
    if row is None or not row["crop_path"]:
        raise HTTPException(404, "no mark scheme linked to this question")

    # crop_path is stored repo-relative with Windows separators.
    crop = (ROOT / str(row["crop_path"]).replace("\\", "/")).resolve()
    safe = (ROOT / "data" / "crops").resolve()
    if not str(crop).startswith(str(safe)) or not crop.exists():
        raise HTTPException(404, "mark scheme crop not available")
    try:
        import fitz
        with fitz.open(str(crop)) as doc:
            img = doc[0].get_pixmap(dpi=150).tobytes("png")
        return Response(content=img, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})
    except Exception as exc:
        raise HTTPException(500, f"could not render mark scheme: {exc}")


_UPLOADS_DIR = ROOT / "data" / "uploads"
_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_UPLOADS_DIR), name="uploads")


# ── SEO: robots.txt + sitemap.xml ─────────────────────────────────────────────

_PUBLIC_PATHS = [
    "/", "/subjects.html", "/resources.html",
    "/pricing.html", "/teachers.html", "/tools.html",
    "/teacher-apply.html", "/contact.html", "/guide.html", "/blog",
    # Study tools — each has a distinct meta description and real student value
    "/mcq-solver.html", "/formulas.html", "/definitions.html",
    "/command-words.html", "/calculator.html", "/periodic-table.html",
    "/bases-logic.html", "/pseudocode.html", "/graph.html",
    "/grade-calculator.html", "/grade-trends.html", "/graphs-guide.html",
    "/islamiat-references.html",
]
_NOINDEX_PATHS = {
    "/admin.html", "/dashboard.html", "/login.html", "/profile.html",
    "/teacher-dashboard.html", "/parent-dashboard.html",
    "/messages.html", "/homework.html", "/set-password.html",
    "/reset-password.html", "/forgot-password.html",
    "/study.html", "/study-hub.html", "/quiz.html",
    "/flashcards.html", "/fc-progress.html",
    "/topical-progress.html", "/yearly-progress.html",
    "/achievements.html", "/notes.html", "/notes-view.html",
    "/analytics.html", "/calendar.html",
    # Redirect stubs — no content, should never be indexed
    "/library.html", "/revise.html", "/ask.html", "/walkthrough.html",
}


@app.get("/robots.txt", include_in_schema=False)
def robots_txt():
    origin = os.environ.get("SITE_ORIGIN", "https://prepwithtee.com").rstrip("/")
    disallow = "\n".join(f"Disallow: {p}" for p in sorted(_NOINDEX_PATHS))
    content = (
        f"User-agent: *\nAllow: /\n{disallow}\n\n"
        f"Sitemap: {origin}/sitemap.xml\n"
    )
    return Response(content=content, media_type="text/plain")


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap_xml():
    origin = os.environ.get("SITE_ORIGIN", "https://prepwithtee.com").rstrip("/")
    # Priority hints: homepage highest, topical papers second, then by traffic value
    _priority = {
        "/": "1.0",
        "/papers.html": "0.95",
        "/subjects.html": "0.90",
        "/resources.html": "0.85",
        "/mcq-solver.html": "0.85",
        "/pricing.html": "0.80",
        "/tools.html": "0.80",
        "/formulas.html": "0.80",
        "/blog": "0.80",
        "/teachers.html": "0.75",
        "/definitions.html": "0.75",
        "/grade-calculator.html": "0.70",
        "/grade-trends.html": "0.70",
    }
    entries = []
    for p in _PUBLIC_PATHS:
        pri = _priority.get(p, "0.60")
        freq = "weekly" if p in ("/", "/papers.html", "/blog", "/resources.html") else "monthly"
        entries.append(
            f"  <url><loc>{origin}{p}</loc>"
            f"<changefreq>{freq}</changefreq>"
            f"<priority>{pri}</priority></url>"
        )
    # Catalogue pages: boards, every subject, every chapter
    try:
        for p in _catalog_mod.sitemap_paths():
            depth = p.count("/")
            pri = {1: "0.95", 2: "0.90", 3: "0.85"}.get(depth, "0.70")
            entries.append(f"  <url><loc>{origin}{p}</loc>"
                           f"<changefreq>weekly</changefreq><priority>{pri}</priority></url>")
    except Exception:
        pass
    # Yearly papers (subject + year pages) and MCQ practice pages
    try:
        for p in _yearly_mod.sitemap_paths():
            pri = "0.80" if p.count("/") <= 3 else "0.70"
            entries.append(f"  <url><loc>{origin}{p}</loc>"
                           f"<changefreq>monthly</changefreq><priority>{pri}</priority></url>")
    except Exception:
        pass
    try:
        for post in _blog_mod.get_published_posts():
            lastmod = (post.get("updated_at") or post.get("published_at") or "")[:10]
            mod_tag = f"<lastmod>{lastmod}</lastmod>" if lastmod else ""
            entries.append(
                f'  <url><loc>{origin}/blog/{post["slug"]}</loc>'
                f'{mod_tag}<changefreq>monthly</changefreq>'
                f'<priority>0.7</priority></url>'
            )
    except Exception:
        pass
    # Add published course pages
    try:
        import users_db as _udb
        for course in _udb.get_all_courses(published_only=True):
            slug = course.get("slug")
            if slug:
                entries.append(
                    f"  <url><loc>{origin}/course.html?slug={slug}</loc>"
                    f"<changefreq>monthly</changefreq><priority>0.7</priority></url>"
                )
    except Exception:
        pass
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(entries)
        + "\n</urlset>"
    )
    return Response(content=xml, media_type="application/xml",
                    headers={"Cache-Control": "public, max-age=3600"})


# ── Quiz Mode: Past-Paper Theory Questions ───────────────────────────────────

@app.get("/api/quiz/pp-questions")
def quiz_pp_questions(
    syllabus: str = Query(""),
    topic: str = Query(""),
    count: int = Query(5),
    seed: int = Query(None),
):
    """Return real past-paper question texts for the quiz theory mode."""
    if not syllabus or not topic:
        return {"questions": []}
    import random as _random
    con = _con()
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """SELECT q.id, q.text, q.marks, q.number, q.sub_part,
                      p.syllabus, p.year, p.session, p.paper, p.variant
               FROM classifications c
               JOIN questions q ON q.id = c.question_id
               JOIN papers p ON p.id = q.paper_id
               WHERE p.syllabus = ? AND c.topic = ?
                 AND q.status IS NOT 'excluded'
                 AND q.text IS NOT NULL AND length(trim(q.text)) > 20""",
            (syllabus, topic),
        ).fetchall()
        pool = [dict(r) for r in rows]
        if seed is not None:
            _random.seed(seed)
        _random.shuffle(pool)
        _sess = {"s": "M/J", "w": "O/N", "m": "F/M"}
        questions = []
        for row in pool:
            text = (row["text"] or "").strip()
            if len(text) < 20:
                continue
            sess = _sess.get(row["session"], row["session"].upper())
            ref = f"{row['paper']}{row['variant']}/{sess}/{str(row['year'])[2:]}"
            ref += f" Q{row['number']}" + (f"({row['sub_part']})" if row["sub_part"] else "")
            questions.append({
                "id": row["id"],
                "text": text,
                "marks": row["marks"],
                "ref": ref,
                "topic": topic,
                "syllabus": syllabus,
            })
            if len(questions) >= count:
                break
        return {"questions": questions}
    finally:
        con.close()


class QuizEvalReq(BaseModel):
    question: str
    student_answer: str
    marks: int | None = None
    topic: str | None = None
    syllabus: str | None = None
    ref: str | None = None


@app.post("/api/quiz/eval-stream")
def quiz_eval_stream(req: QuizEvalReq, request: Request):
    """AI evaluation of a student's typed answer. Streams SSE."""
    user = _auth_mod.maybe_user(request.cookies.get("session"))
    if user:
        from access import check_quota
        check_quota(user, "ai_tutor")
    else:
        client_ip = _client_ip(request)
        wait = _tutor_rate_limited(client_ip)
        if wait is not None:
            raise HTTPException(429, "Rate limit exceeded.")

    marks_str = f" [{req.marks} mark{'s' if req.marks and req.marks != 1 else ''}]" if req.marks else ""
    topic_str = f" on **{req.topic}**" if req.topic else ""
    syllabus_str = f" ({req.syllabus})" if req.syllabus else ""
    ref_str = f" · {req.ref}" if req.ref else ""

    system = (
        "You are a Cambridge O-Level/IGCSE examiner providing mark-scheme-style feedback. "
        "Structure your response with these five markdown sections in order:\n\n"
        "## ✅ Strengths\n"
        "Bullet points of what the student got right or expressed well.\n\n"
        "## ⚠️ Missing Points\n"
        "Bullet points of key marking points that are absent from the answer.\n\n"
        "## ❌ Weaknesses\n"
        "Bullet points of errors, imprecision, or misconceptions. Write 'None' if there are none.\n\n"
        "## Suggested Mark\n"
        "State e.g. **2 / 3** with one sentence justification.\n\n"
        "## 📝 Model Answer\n"
        "A concise mark-scheme-quality answer. Use Cambridge command-word standards. "
        "Keep the entire response under 350 words."
    )
    user_msg = (
        f"Cambridge question{syllabus_str}{ref_str}{topic_str}{marks_str}:\n"
        f"{req.question}\n\n"
        f"Student's answer:\n{req.student_answer or '(no answer given)'}\n\n"
        "Please evaluate this answer."
    )
    msgs = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_msg},
    ]

    def event_generator():
        try:
            stream_res, _ = _chat_stream(msgs)
            if not stream_res:
                yield f"data: {json.dumps({'error': 'No AI providers configured'})}\n\n"
                return
            accumulated = []
            for token, _ in stream_res():
                accumulated.append(token)
                yield f"data: {json.dumps({'token': token})}\n\n"
            full = "".join(accumulated)
            html = _clean_html(_strip_reasoning(full), strip_latex=False)
            yield f"data: {json.dumps({'done': True, 'html': html})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static",
                           html=True), name="static")
