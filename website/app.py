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

import json
import os
import random
import re
import shutil
import sqlite3
import smtplib
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator
from starlette.background import BackgroundTask

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "index.db"

# ── Dual-mode DB: psycopg2 (Supabase) or SQLite ────────────────────────────
from . import db as _db
_USE_PG = _db.USE_PG

def _con():
    """Open a pipeline DB connection.  Caller must call .close()."""
    return _db.plain_connect()
YEAR_MIN, YEAR_MAX = 2020, 2025

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
}

app = FastAPI(title="PrepWithTee")

from . import auth as _auth_mod, users as _users_mod
app.include_router(_auth_mod.router)
app.include_router(_users_mod.router)


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
# that was free; against Supabase every one is a network round-trip, which put
# the endpoint at ~20 s. The answer only changes when the pipeline reclassifies
# (an offline, manual step), so serve it from an in-process cache and let a
# restart or the TTL pick up new data.
_META_CACHE: dict = {"at": 0.0, "data": None}
_META_TTL_S = 600


@app.get("/api/meta")
def meta():
    now = time.time()
    if _META_CACHE["data"] is not None and now - _META_CACHE["at"] < _META_TTL_S:
        return _META_CACHE["data"]
    data = _build_meta()
    _META_CACHE.update(at=now, data=data)
    return data


@app.on_event("startup")
def _warm_meta_cache():
    """Build the meta cache off-thread so the first visitor never waits on it."""
    def build():
        try:
            _META_CACHE.update(at=time.time(), data=_build_meta())
        except Exception as exc:            # a cold cache is recoverable
            print(f"[meta] warm-up failed: {exc}", flush=True)
    threading.Thread(target=build, daemon=True).start()


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

        topics = []
        for t in tax["topics"]:
            total = pool.get(t["name"], 0)
            if not total:
                continue
            seen = per_paper.get(t["name"], {})
            allowed = t.get("papers")
            if allowed is not None:
                seen = {k: v for k, v in seen.items() if int(k) in allowed}
            # Build subtopic list from taxonomy (preserving order) with question counts
            raw_subs = t.get("subtopics", [])
            sc = subtopic_counts.get(t["name"], {})
            subtopics = [
                {"name": s["name"], "count": sc.get(s["name"], 0)}
                for s in raw_subs
            ] if raw_subs else []
            topics.append({"name": t["name"], "count": total,
                           "papers": seen, "subtopics": subtopics})

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

        out.append({"syllabus": syl, "subject": tax.get("subject", syl),
                    "short": short_of.get(syl, tax.get("subject", syl)),
                    "board": board_of.get(syl, "Other"),
                    "topics": topics, "components": components,
                    "sessions": avail_sessions,
                    "variants": avail_variants,
                    "year_min": syl_year_min, "year_max": syl_year_max})
    con.close()
    # Board order for the grouped picker (unknown boards fall to the end).
    board_order = [b for b, _ in BOARDS]
    return {"subjects": out, "board_order": board_order,
            "year_min": YEAR_MIN, "year_max": YEAR_MAX}


def _run(cmd: list[str]):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       timeout=300)
    if r.returncode != 0:
        tail = (r.stderr or r.stdout).strip().splitlines()[-1:]
        raise HTTPException(500, tail[0] if tail else "generation failed")


@app.post("/api/generate")
def generate(req: GenerateReq):
    if req.mode not in ("topical", "test"):
        raise HTTPException(400, "mode must be 'topical' or 'test'")
    if not req.topics:
        raise HTTPException(400, "pick at least one topic")

    tmp = Path(tempfile.mkdtemp(prefix="pwt_"))
    cleanup = BackgroundTask(shutil.rmtree, tmp, ignore_errors=True)
    slug = re.sub(r"[^a-z0-9]+", "-", "-".join(req.topics).lower()).strip("-")[:60]
    topics_arg = ",".join(req.topics)
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

    zpath = tmp / f"{stem}_{slug}_test.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(out, out.name)
        ms = out.with_name(out.stem + "_ms.pdf")
        z.write(ms, ms.name)
    return FileResponse(zpath, media_type="application/zip",
                        filename=zpath.name, background=cleanup)


SESSION_NAMES = {"s": "May/June", "w": "Oct/Nov", "m": "Feb/March"}

# Board and display name per syllabus. Not every syllabus has a taxonomy file
# (0478 has none yet), so the library cannot rely on taxonomy["subject"] alone
# — without this, 0478 rendered as "0478 — 0478".
BOARDS = [
    ("Cambridge O Level", [
        ("4024", "Mathematics (Syllabus D)"),
        ("5054", "Physics"),
        ("5070", "Chemistry"),
        ("2210", "Computer Science"),
        ("2058", "Islamiyat"),
        ("2059", "Pakistan Studies"),
    ]),
    ("Cambridge IGCSE", [
        ("0580", "Mathematics"),
        ("0625", "Physics"),
        ("0620", "Chemistry"),
        ("0478", "Computer Science"),
    ]),
    ("Cambridge A Level", [
        ("9709", "Mathematics"),
        ("9702", "Physics"),
        ("9618", "Computer Science"),
    ]),
]


@app.get("/api/library")
def library(syllabus: str | None = None, year: int | None = None):
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


@app.get("/api/library/pdf/{paper_id}")
def library_pdf(paper_id: int):
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
    html, provider = _vision_complete(SOLVER_SYSTEM, prompt, media_type, b64)
    if html is None:
        print(f"[solve] no vision provider answered: {provider}", flush=True)
        raise HTTPException(
            503, "The photo solver is unavailable right now — try again shortly, "
                 "or send the photo to us on WhatsApp.")
    return {"html": _clean_html(html), "provider": provider}


# Vision providers, tried in order. Anthropic reads handwriting and diagrams
# best, so it leads when its key is set. Groq is deliberately absent: it serves
# text and audio models only, so a photo request there is a guaranteed 404.
# Free vision model ids churn, so each is overridable without a code change.
VISION_PROVIDERS = [
    {"name": "openrouter", "env": "OPENROUTER_API_KEY",
     "url": "https://openrouter.ai/api/v1/chat/completions",
     "model": os.environ.get("OPENROUTER_VISION_MODEL",
                             "meta-llama/llama-3.2-11b-vision-instruct:free")},
    {"name": "gemini", "env": "GEMINI_API_KEY",
     "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
     "model": os.environ.get("GEMINI_VISION_MODEL", "gemini-2.0-flash")},
]


def _vision_complete(system: str, prompt: str, media_type: str, b64: str):
    """Image + prompt -> text. Returns (text, provider) or (None, diagnostic)."""
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
    for p in VISION_PROVIDERS:
        pkey = os.environ.get(p["env"])
        if not pkey:
            continue
        try:
            r = requests.post(
                p["url"], timeout=90,
                headers={"Authorization": f"Bearer {pkey}",
                         "Content-Type": "application/json"},
                json={"model": p["model"], "max_tokens": 2000, "temperature": 0.3,
                      "messages": [
                          {"role": "system", "content": system},
                          {"role": "user", "content": [
                              {"type": "text", "text": prompt},
                              {"type": "image_url",
                               "image_url": {"url": data_url}},
                          ]},
                      ]})
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
     "model": "llama-3.3-70b-versatile"},
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

TUTOR_SYSTEM = """You are the study assistant at PrepWithTee, a Cambridge \
tutoring service (O Level, IGCSE and A Level). You help students practise and \
understand their syllabus.

Decide what the student wants:
- If they ask for practice/exam questions on a topic, WRITE original \
Cambridge-style questions numbered Q1, Q2, ..., each ending with its mark \
allocation like [3]. Match Cambridge command words (State, Explain, Calculate, \
Describe, Show that). Put a single "Answers" section at the very END with brief \
worked answers, so the student can attempt them first.
- If they ask a doubt or to explain a concept, explain it step by step in plain \
language, then give one short worked example.

Output clean, minimal HTML only: <h3> for section titles, <p> for prose, \
<ol><li> for numbered questions, <div class="step"> for working steps, \
<strong> for emphasis. No markdown, no code fences, no <html>/<body> wrapper.

Stay strictly within the Cambridge syllabus level the student names. Never \
invent facts or fabricate that something is on the syllabus. If a request is \
off-topic for their course, say so briefly and steer back."""

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
            r = requests.post(
                p["url"], timeout=45,
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json={"model": p["model"], "messages": messages,
                      "max_tokens": max_tokens, "temperature": 0.45})
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"], p["name"]
            errors.append(f'{p["name"]} HTTP {r.status_code}')
        except Exception as exc:                       # network / timeout
            errors.append(f'{p["name"]}: {exc}')
    return None, ("; ".join(errors) if errors else "no provider configured")


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


def _clean_html(text: str) -> str:
    """Models sometimes wrap output in ```html fences or emit a little markdown.
    Strip the fences; if it clearly isn't HTML, do a minimal markdown pass."""
    t = text.strip()
    t = re.sub(r"^```(?:html)?\s*|\s*```$", "", t).strip()
    # Every student-facing answer goes through here, so this is the one place
    # LaTeX has to be normalised for the tutor, the solver and the quiz alike.
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


@app.post("/api/ask")
def ask(req: AskReq, request: Request):
    """Chat: generate practice questions or explain a doubt (Groq + fallbacks)."""
    client_ip = _client_ip(request)
    wait = _tutor_rate_limited(client_ip)
    if wait is not None:
        raise HTTPException(
            429, f"That's {TUTOR_LIMIT} questions this hour — take a short break "
                 f"and try again in {wait // 60 + 1} minutes.")

    message = (req.message or "").strip()
    if not message:
        raise HTTPException(400, "Type what you'd like to practise or ask.")

    msgs = [{"role": "system", "content": TUTOR_SYSTEM}]
    if req.syllabus:
        where = f"The student is studying syllabus {req.syllabus}"
        if req.topic:
            where += f", topic: {req.topic}"
        msgs.append({"role": "system", "content": where + "."})
    ctx = _topic_samples(req.syllabus, req.topic)
    if ctx:
        msgs.append({"role": "system",
                     "content": "Real Cambridge question stems on this topic, "
                                "for style reference only (do not copy):\n" + ctx})
    for h in (req.history or [])[-6:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            msgs.append({"role": h["role"], "content": str(h["content"])[:4000]})
    msgs.append({"role": "user", "content": message[:4000]})

    text, prov = _chat_complete(msgs)
    if text is None:
        raise HTTPException(
            503, "The question generator is not switched on yet — set "
                 "GROQ_API_KEY on the server and restart. (" + prov + ")")
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
    leads_db = ROOT / "data" / "leads.db"
    leads_db.parent.mkdir(parents=True, exist_ok=True)
    
    # Save to SQLite
    import sqlite3
    conn = sqlite3.connect(leads_db)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_name TEXT,
            student_name TEXT,
            contact TEXT,
            grade TEXT,
            subjects TEXT,
            message TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        INSERT INTO leads (parent_name, student_name, contact, grade, subjects, message)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (req.parent_name, req.student_name, req.contact, req.grade, ",".join(req.subjects), req.message))
    conn.commit()
    conn.close()

    # Append to log file (capped at 1 MB to prevent unbounded growth)
    leads_txt = ROOT / "data" / "leads.txt"
    if not leads_txt.exists() or leads_txt.stat().st_size < 1_000_000:
        with open(leads_txt, "a", encoding="utf-8") as f:
            f.write(f"New Booking: Parent={req.parent_name}, Student={req.student_name}, Contact={req.contact}, Grade={req.grade}, Subjects={req.subjects}, Msg={req.message}\n")

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


ADMIN_KEY = os.environ.get("ADMIN_KEY", "prepwithtee-admin-2026")

# ---------------------------------------------------------------------------
# Shared email helper — fires only when SMTP_USER + SMTP_PASS are configured.
# Set those env vars on the server to activate; missing vars = silent skip.
# ---------------------------------------------------------------------------
def _notify(subject: str, body: str, rows: list | None = None) -> None:
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    if not (smtp_user and smtp_pass):
        return
    to_addr = os.environ.get("NOTIFY_EMAIL", "nexgentutors6@gmail.com")

    html_body = None
    if rows:
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
  </td></tr>
  <tr><td style="padding:14px 0;text-align:center;color:#bbb;font-size:.74rem">
    PrepWithTee &nbsp;·&nbsp; nexgentutors6@gmail.com
  </td></tr>
</table></td></tr></table>
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to_addr
    msg.attach(MIMEText(body, "plain", "utf-8"))
    if html_body:
        msg.attach(MIMEText(html_body, "html", "utf-8"))
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=8) as srv:
            srv.starttls()
            srv.login(smtp_user, smtp_pass)
            srv.send_message(msg)
    except Exception as exc:
        print(f"Email notification skipped: {exc}")


@app.post("/api/feedback")
def submit_feedback(req: FeedbackReq):
    msg = (req.message or "").strip()
    if not msg:
        raise HTTPException(400, "Message is required")
    if len(msg) > 2000:
        raise HTTPException(400, "Message too long")
    if req.rating is not None and not (1 <= req.rating <= 5):
        raise HTTPException(400, "Rating must be 1–5")

    fb_db = ROOT / "data" / "feedback.db"
    fb_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(fb_db)
    conn.execute("""CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rating INTEGER, message TEXT, name TEXT, page TEXT, type TEXT,
        ts DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    try:
        conn.execute("ALTER TABLE feedback ADD COLUMN type TEXT")
    except Exception:
        pass
    fb_type = req.type or "feedback"
    conn.execute(
        "INSERT INTO feedback (rating, message, name, page, type) VALUES (?,?,?,?,?)",
        (req.rating, msg, (req.name or "").strip() or None, req.page, fb_type))
    conn.commit()
    conn.close()

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

    sr_db = ROOT / "data" / "subject_requests.db"
    sr_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(sr_db)
    conn.execute("""CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject TEXT, board TEXT, message TEXT,
        ts DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute(
        "INSERT INTO requests (subject, board, message) VALUES (?,?,?)",
        (subj, (req.board or "").strip() or None, (req.message or "").strip() or None))
    conn.commit()
    conn.close()

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


# ---------------------------------------------------------------------------
# Admin dashboard  —  /admin?key=<ADMIN_KEY>
# ---------------------------------------------------------------------------
def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

import re as _re

def _wa_href(contact: str) -> str | None:
    digits = _re.sub(r"\D", "", contact or "")
    if not (7 <= len(digits) <= 15):
        return None
    if digits.startswith("0"):
        digits = "92" + digits[1:]
    elif not digits.startswith("92") and len(digits) <= 11:
        digits = "92" + digits
    return f"https://wa.me/{digits}"

def _admin_rows(rows, cols: list[tuple[str, str]], today: str) -> str:
    if not rows:
        return ""
    trs = ""
    for row in rows:
        keys = row.keys()
        cells = ""
        is_today = False
        for label, key in cols:
            if key == "__ts__":
                val = str(row["timestamp"] if "timestamp" in keys else (row["ts"] if "ts" in keys else ""))
                is_today = val.startswith(today)
                disp = val[11:16] if is_today else val[:10]
                badge = '<span class="today-pill">Today</span>' if is_today else ""
                cells += f'<td class="ts">{_esc(disp)}{badge}</td>'
            elif key == "__type__":
                t = str(row["type"] if "type" in keys else "feedback") or "feedback"
                cls = "badge-issue" if t == "issue" else "badge-ok"
                icon = "🔧" if t == "issue" else "💬"
                cells += f'<td><span class="badge {cls}">{icon} {_esc(t)}</span></td>'
            elif key == "__stars__":
                r = row["rating"] if "rating" in keys else None
                stars = ("★" * int(r) + "☆" * (5 - int(r))) if r else "—"
                cls = "stars-hi" if r and int(r) >= 4 else ("stars-lo" if r and int(r) <= 2 else "")
                cells += f'<td class="{cls}">{stars}</td>'
            elif key == "__contact__":
                val = str(row["contact"] if "contact" in keys else "") or "—"
                wa = _wa_href(val)
                wa_btn = f' <a class="wa-btn" href="{wa}" target="_blank" rel="noopener">WhatsApp ↗</a>' if wa else ""
                cells += f'<td>{_esc(val)}{wa_btn}</td>'
            else:
                val = str(row[key] if key in keys else "") or "—"
                cells += f'<td class="msg-cell">{_esc(val)}</td>'
        row_cls = "row-today" if is_today else ""
        trs += f'<tr class="{row_cls}">{cells}</tr>'
    return trs


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(key: str = ""):
    if key != ADMIN_KEY:
        return HTMLResponse(
            "<!DOCTYPE html><html><body style='font-family:sans-serif;padding:48px;background:#f4f0ea'>"
            "<h2 style='color:#2E1B4A'>Access denied</h2>"
            "<p style='margin-top:8px;color:#666'>Append <code>?key=YOUR_KEY</code> to the URL.</p>"
            "</body></html>", status_code=403)

    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _load(db_path, query):
        if not db_path.exists():
            return []
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        rows = c.execute(query).fetchall()
        c.close()
        return rows

    leads    = _load(ROOT / "data" / "leads.db",    "SELECT * FROM leads ORDER BY timestamp DESC")
    feedback = _load(ROOT / "data" / "feedback.db", "SELECT * FROM feedback ORDER BY ts DESC")
    subj_req = _load(ROOT / "data" / "subject_requests.db", "SELECT * FROM requests ORDER BY ts DESC")

    n_d, n_f, n_s = len(leads), len(feedback), len(subj_req)
    total = n_d + n_f + n_s

    demo_cols = [("Time","__ts__"),("Parent","parent_name"),("Student","student_name"),
                 ("Contact","__contact__"),("Grade","grade"),("Subjects","subjects"),("Note","message")]
    fb_cols   = [("Time","__ts__"),("Type","__type__"),("Stars","__stars__"),
                 ("Name","name"),("Page","page"),("Message","message")]
    sr_cols   = [("Time","__ts__"),("Subject","subject"),("Board","board"),("Message","message")]

    def _tbl(rows, cols, empty):
        if not rows:
            return f'<div class="empty-state"><span>📭</span><p>{empty}</p></div>'
        ths = "".join(f"<th>{c[0]}</th>" for c in cols)
        trs = _admin_rows(rows, cols, today)
        return f'<div class="tbl-wrap"><table><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table></div>'

    demo_tbl = _tbl(leads,    demo_cols, "No demo requests yet — they'll appear here once students book.")
    fb_tbl   = _tbl(feedback, fb_cols,   "No feedback or issues submitted yet.")
    sr_tbl   = _tbl(subj_req, sr_cols,   "No subject requests yet.")

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin — PrepWithTee</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#F4F0EA;color:#1A1A2E;min-height:100vh}}

/* ── Header ── */
.adm-header{{
  background:#2E1B4A;color:#fff;
  padding:0 28px;height:60px;
  display:flex;align-items:center;gap:14px;
  position:sticky;top:0;z-index:10;
  box-shadow:0 2px 12px rgba(0,0,0,.25);
}}
.adm-logo{{font-size:1.05rem;font-weight:800;letter-spacing:-.01em;color:#fff}}
.adm-logo span{{color:#C9BDF0}}
.adm-bell{{
  margin-left:auto;position:relative;cursor:pointer;
  background:rgba(255,255,255,.12);border:none;color:#fff;
  width:38px;height:38px;border-radius:50%;font-size:1.1rem;
  display:flex;align-items:center;justify-content:center;
  transition:background .15s;
}}
.adm-bell:hover{{background:rgba(255,255,255,.22)}}
.bell-badge{{
  position:absolute;top:-2px;right:-2px;
  background:#E8913A;color:#fff;font-size:.6rem;font-weight:800;
  min-width:16px;height:16px;border-radius:8px;
  display:flex;align-items:center;justify-content:center;padding:0 3px;
  border:2px solid #2E1B4A;
}}
.adm-refresh{{
  background:rgba(255,255,255,.1);border:none;color:rgba(255,255,255,.7);
  padding:6px 14px;border-radius:8px;font-size:.8rem;cursor:pointer;
  font-family:inherit;transition:background .14s;
}}
.adm-refresh:hover{{background:rgba(255,255,255,.18);color:#fff}}

/* ── Stat cards ── */
.adm-cards{{display:flex;gap:14px;padding:24px 28px 0;flex-wrap:wrap}}
.adm-card{{
  flex:1;min-width:160px;border-radius:16px;padding:18px 20px;
  display:flex;align-items:center;gap:14px;
}}
.adm-card.lav{{background:#E4DEF9;}}
.adm-card.grn{{background:#D4F0E0;}}
.adm-card.org{{background:#FBE2CC;}}
.card-icon{{font-size:1.6rem;line-height:1}}
.card-body b{{display:block;font-size:1.75rem;font-weight:800;line-height:1}}
.adm-card.lav .card-body b{{color:#4A2E8F}}
.adm-card.grn .card-body b{{color:#16704A}}
.adm-card.org .card-body b{{color:#B0541C}}
.card-body span{{font-size:.75rem;font-weight:600;opacity:.7;text-transform:uppercase;letter-spacing:.04em}}

/* ── Tabs ── */
.adm-tabs{{
  display:flex;gap:2px;padding:20px 28px 0;
}}
.adm-tab{{
  padding:10px 20px;cursor:pointer;font-weight:600;font-size:.87rem;
  color:#888;border-radius:10px 10px 0 0;border:1.5px solid transparent;
  border-bottom:none;background:transparent;
  user-select:none;transition:all .15s;position:relative;top:1px;
}}
.adm-tab:hover{{color:#2E1B4A;background:rgba(255,255,255,.5)}}
.adm-tab.active{{
  color:#2E1B4A;background:#fff;
  border-color:#E8DFCE;
}}
.adm-tab-count{{
  display:inline-flex;align-items:center;justify-content:center;
  background:rgba(76,46,114,.12);color:#4A2E8F;
  font-size:.7rem;font-weight:800;border-radius:10px;
  padding:1px 6px;margin-left:5px;
}}

/* ── Content panel ── */
.adm-panel{{
  background:#fff;border:1.5px solid #E8DFCE;border-radius:0 12px 12px 12px;
  margin:0 28px 28px;overflow:hidden;
}}
.adm-section{{display:none}}
.adm-section.active{{display:block}}
.tbl-wrap{{overflow-x:auto}}

/* ── Table ── */
table{{width:100%;border-collapse:collapse;font-size:.84rem}}
th{{
  background:#FAF7F2;text-align:left;padding:10px 16px;
  font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;color:#888;
  white-space:nowrap;border-bottom:1.5px solid #E8DFCE;font-weight:700;
}}
td{{
  padding:10px 16px;border-bottom:1px solid #F0EAE0;
  vertical-align:top;max-width:260px;word-break:break-word;
}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:#FDFAF6}}
tr.row-today td{{background:#FEFBF4}}

/* ── Cell variants ── */
.ts{{color:#aaa;font-size:.78rem;white-space:nowrap;padding-right:6px}}
.today-pill{{
  display:inline-block;margin-left:6px;
  background:#FBE2CC;color:#B0541C;
  font-size:.65rem;font-weight:700;padding:1px 6px;border-radius:8px;
  vertical-align:middle;text-transform:uppercase;letter-spacing:.03em;
}}
.msg-cell{{color:#444;max-width:300px}}
.badge{{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:20px;font-size:.74rem;font-weight:700}}
.badge-ok{{background:#D4F0E0;color:#16704A}}
.badge-issue{{background:#FBDCE8;color:#B0326E}}
.stars-hi{{color:#E8913A;font-size:.9rem;letter-spacing:1px}}
.stars-lo{{color:#aaa;font-size:.9rem;letter-spacing:1px}}
.wa-btn{{
  display:inline-flex;align-items:center;gap:4px;
  margin-left:7px;padding:2px 8px;
  background:#D4F0E0;color:#16704A;border-radius:8px;
  font-size:.72rem;font-weight:700;text-decoration:none;
  transition:background .12s;
}}
.wa-btn:hover{{background:#A9E0C3}}
.wa-btn::before{{content:"💬";font-size:.75rem}}

/* ── Empty state ── */
.empty-state{{
  padding:56px 24px;text-align:center;color:#bbb;
}}
.empty-state span{{display:block;font-size:2rem;margin-bottom:10px}}
.empty-state p{{font-size:.9rem}}
</style>
</head>
<body>

<header class="adm-header">
  <div class="adm-logo">PrepWith<span>Tee</span></div>
  <span style="color:rgba(255,255,255,.35);font-size:.85rem">Admin</span>
  <button class="adm-refresh" onclick="location.reload()">↻ Refresh</button>
  <button class="adm-bell" title="Total submissions">
    🔔
    <span class="bell-badge">{total}</span>
  </button>
</header>

<div class="adm-cards">
  <div class="adm-card lav">
    <span class="card-icon">📋</span>
    <div class="card-body"><b>{n_d}</b><span>Demo Requests</span></div>
  </div>
  <div class="adm-card grn">
    <span class="card-icon">💬</span>
    <div class="card-body"><b>{n_f}</b><span>Feedback &amp; Issues</span></div>
  </div>
  <div class="adm-card org">
    <span class="card-icon">📚</span>
    <div class="card-body"><b>{n_s}</b><span>Subject Requests</span></div>
  </div>
</div>

<div class="adm-tabs">
  <div class="adm-tab active" onclick="show(this,'sec-demo')">
    Demo Requests<span class="adm-tab-count">{n_d}</span>
  </div>
  <div class="adm-tab" onclick="show(this,'sec-fb')">
    Feedback &amp; Issues<span class="adm-tab-count">{n_f}</span>
  </div>
  <div class="adm-tab" onclick="show(this,'sec-sr')">
    Subject Requests<span class="adm-tab-count">{n_s}</span>
  </div>
</div>

<div class="adm-panel">
  <div class="adm-section active" id="sec-demo">{demo_tbl}</div>
  <div class="adm-section" id="sec-fb">{fb_tbl}</div>
  <div class="adm-section" id="sec-sr">{sr_tbl}</div>
</div>

<script>
function show(tab, secId) {{
  document.querySelectorAll('.adm-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.adm-section').forEach(s => s.classList.remove('active'));
  tab.classList.add('active');
  document.getElementById(secId).classList.add('active');
}}
</script>
</body></html>"""
    return HTMLResponse(html)


@app.get("/api/question/{question_id}/preview")
def question_preview(question_id: int):
    """Serve the question crop as a PNG — used by the lightbox in the preview panel.

    Tries the pre-rendered debug PNG first (fast); falls back to rendering the
    crop PDF on demand with PyMuPDF so the endpoint works even when debug PNGs
    were not synced to the server.
    """
    con = _con()
    con.row_factory = sqlite3.Row
    row = con.execute(
        """SELECT q.number, q.sub_part, p.syllabus, p.year, p.session, p.paper, p.variant
           FROM questions q
           JOIN papers p ON p.id = q.paper_id
           WHERE q.id = ?""",
        (question_id,)).fetchone()
    con.close()
    if row is None:
        raise HTTPException(404, "question not found")

    key = (f"{row['syllabus']}_{row['session']}{row['year'] % 100:02d}"
           f"_{row['paper']}{row['variant']}")
    slug = f"q{row['number']:02d}" + (row["sub_part"] or "")

    # Fast path: pre-rendered debug PNG
    png_path = (ROOT / "data" / "debug" / key / f"{slug}.png").resolve()
    safe_debug = (ROOT / "data" / "debug").resolve()
    if str(png_path).startswith(str(safe_debug)) and png_path.exists():
        return FileResponse(png_path, media_type="image/png",
                            headers={"Cache-Control": "public, max-age=86400"})

    # Fallback: render first page of crop PDF with PyMuPDF
    crop_path = (ROOT / "data" / "crops" / key / f"{slug}.pdf").resolve()
    safe_crops = (ROOT / "data" / "crops").resolve()
    if not str(crop_path).startswith(str(safe_crops)) or not crop_path.exists():
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

    Revision mode reveals this after a student has answered a real past-paper
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


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static",
                           html=True), name="static")
