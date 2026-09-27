"""Topical booklets built by the web builder, and the in-site viewer.

    GET  /api/topical/{syllabus}/tree     chapters + subtopics with counts per year/paper
    POST /api/booklets/count              exact pool size for a selection (live counter)
    POST /api/booklets                    pick + mix questions, start the build -> {id, url}
    GET  /api/booklets                    my recent booklets
    GET  /api/booklets/{id}               metadata + page map (for the viewer)
    GET  /api/booklets/{id}/status        {status, progress, stage} (the loader polls this)
    GET  /api/booklets/{id}/pdf           the PDF, inline (?download=1 to save;
                                          ?part=ms = a mock test's separate mark scheme)
    GET  /papers/view/{id}                the viewer page (noindex)

Rules (tutor, 2026-09-24): at most 4 chapters per booklet, any number of
subtopics inside them; questions from every picked chapter/subtopic, mixed
rather than grouped (selection.select_mixed); only enrolled students build.

Two kinds (tutor, 2026-09-27 - the old papers.html Test Builder moved here):
`booklet` = compose, mark scheme after each question (or none); `test` =
pipeline.testgen, exam-style cover and the mark scheme as a SEPARATE file
({id}_ms.pdf) that the viewer keeps locked until the student finishes.

Retention (tutor, 2026-09-27 - replaces the 2026-09-26 "rebuild on open"): a
built PDF is kept for 30 days after it was LAST OPENED (every open refreshes the
file's mtime), then sweep() deletes the file. The booklet row stays, so the
student's history (/my-papers) keeps it as a RECORD - title, chapters, date,
size - with a "Build it again" link, but the paper itself no longer opens.
Builds write to a temporary name and are swapped in atomically.

    GET  /my-papers                       the student's history (SSR, noindex)
    GET  /api/booklets/{id}/pdf?annotated=1   the PDF with their ink burnt in

The PDF is built by `python -m pipeline.compose --ids ...` in a worker thread,
exactly as /api/generate shells out: the CLI is the tested interface. Its
PROGRESS lines drive the loader. Status lives in the database, not in memory,
because gunicorn runs two workers and a poll can land on either.
"""

import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from typing import Literal

from pydantic import BaseModel, field_validator

import access as _access
import auth as _auth
import catalog as _catalog
import db as _db
import users_db as _udb
from selection import select_mixed

router = APIRouter()

ROOT = Path(__file__).resolve().parent.parent
BOOKLET_DIR = Path(os.environ.get("BOOKLET_DIR") or ROOT / "data" / "booklets")
MAX_CHAPTERS = 4
MAX_QUESTIONS = 80
BUILD_TIMEOUT_S = 600
VIEWER_V = "20260928a"          # bump with viewer.css / viewer.js / builder.js

RETENTION_DAYS = int(os.environ.get("BOOKLET_RETENTION_DAYS") or 30)
SWEEP_EVERY_S = 6 * 3600

_EXEC = ThreadPoolExecutor(max_workers=2, thread_name_prefix="booklet")


# ── Retention ─────────────────────────────────────────────────────────────────

def _pdf_paths(b: dict) -> list[Path]:
    paths = [BOOKLET_DIR / f"{b['id']}.pdf"]
    if (b.get("params_json") or {}).get("kind") == "test":
        paths.append(BOOKLET_DIR / f"{b['id']}_ms.pdf")
    return paths


def sweep(now: float | None = None, days: int | None = None) -> int:
    """Delete built PDFs (and page maps) not opened for `days`; returns how many."""
    cutoff = (now or time.time()) - (days if days is not None else RETENTION_DAYS) * 86400
    n = 0
    if not BOOKLET_DIR.exists():
        return 0
    for f in BOOKLET_DIR.iterdir():
        if f.suffix not in (".pdf", ".json") or ".tmp-" in f.name:
            continue
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                n += 1
        except OSError:
            pass                                   # already gone / in use: next sweep
    return n


def _sweeper() -> None:
    while True:
        time.sleep(SWEEP_EVERY_S)
        try:
            n = sweep()
            if n:
                print(f"[booklets] retention sweep removed {n} file(s)", flush=True)
        except Exception as exc:                   # never let the loop die
            print(f"[booklets] retention sweep failed: {exc}", flush=True)


if os.environ.get("APP_ENV") != "test":
    threading.Thread(target=_sweeper, name="booklet-sweep", daemon=True).start()


def expired(b: dict) -> bool:
    """Built, but the PDF was swept (not opened for RETENTION_DAYS): record only."""
    return b["status"] == "ready" and not all(p.exists() for p in _pdf_paths(b))


def available_until(b: dict) -> float | None:
    """When a ready booklet's PDF will be swept if it is not opened again."""
    try:
        return BOOKLET_DIR.joinpath(f"{b['id']}.pdf").stat().st_mtime + RETENTION_DAYS * 86400
    except OSError:
        return None


# ── Request models ────────────────────────────────────────────────────────────

class Pick(BaseModel):
    chapter: str
    subtopics: list[str] = []     # empty = the whole chapter


class Selection(BaseModel):
    syllabus: str
    picks: list[Pick]
    year_from: int = 2010
    year_to: int = 2026
    papers: list[int] | None = None

    @field_validator("syllabus")
    @classmethod
    def _syl(cls, v):
        if v not in _catalog.SUBJECTS:
            raise ValueError("unknown syllabus")
        return v

    @field_validator("picks")
    @classmethod
    def _picks(cls, v):
        chapters = [p.chapter for p in v]
        if not v:
            raise ValueError("pick at least one chapter")
        if len(set(chapters)) != len(chapters):
            raise ValueError("each chapter only once")
        if len(v) > MAX_CHAPTERS:
            raise ValueError(f"at most {MAX_CHAPTERS} chapters per paper")
        return v


class BookletReq(Selection):
    max_questions: int = 20
    include_ms: bool = True
    seed: int | None = None
    kind: Literal["booklet", "test"] = "booklet"

    @field_validator("max_questions")
    @classmethod
    def _maxq(cls, v):
        if not 1 <= v <= MAX_QUESTIONS:
            raise ValueError(f"between 1 and {MAX_QUESTIONS} questions")
        return v


# ── Access ────────────────────────────────────────────────────────────────────

def _staff(user: dict) -> bool:
    return user.get("role") in ("teacher", "admin")


def require_enrolled(user: dict, syllabus: str) -> None:
    """Enrolling is free, but it is what unlocks a subject's features."""
    if _staff(user):
        return
    if syllabus not in set(_udb.get_enrollments(user["id"])):
        s = _catalog.SUBJECTS[syllabus]
        raise HTTPException(403, {
            "code": "not_enrolled", "syllabus": syllabus,
            "message": f"Enrol in {s['plain']} ({syllabus}) - it's free - to build papers.",
            "url": _catalog.subject_url(syllabus)})


def _owned(booklet_id: str, user: dict) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,16}", booklet_id or ""):
        raise HTTPException(404, "Booklet not found")
    b = _udb.get_booklet(booklet_id)
    if b is None or (b["user_id"] != user["id"] and not _staff(user)):
        raise HTTPException(404, "Booklet not found")
    return b


# ── Pool ──────────────────────────────────────────────────────────────────────

def _validate_chapters(sel: Selection) -> dict[str, dict]:
    known = {c["name"]: c for c in _catalog.chapters(sel.syllabus)}
    for p in sel.picks:
        ch = known.get(p.chapter)
        if ch is None:
            raise HTTPException(422, f"Unknown chapter: {p.chapter}")
        subs = {s["name"] for s in ch["subtopics"]}
        bad = [s for s in p.subtopics if s not in subs]
        if bad:
            raise HTTPException(422, f"Unknown subtopic in {p.chapter}: {bad[0]}")
    return known


def question_pool(sel: Selection) -> list[dict]:
    """Every question matching the selection, tagged with the bucket it counts
    towards: the subtopic when the student picked subtopics, else the chapter."""
    picks = {p.chapter: set(p.subtopics) for p in sel.picks}
    names = list(picks)
    ph = ",".join("?" for _ in names)
    papers = [int(p) for p in (sel.papers or [])]
    paper_clause = f" AND p.paper IN ({','.join('?' for _ in papers)})" if papers else ""
    con = _db.plain_connect()
    try:
        rows = con.execute(
            f"""SELECT q.id, q.marks, c.topic, c.secondary_topic, c.subtopic,
                       p.year, p.session, p.paper, p.variant
                FROM questions q
                JOIN classifications c ON c.question_id = q.id
                JOIN papers p ON p.id = q.paper_id
                WHERE p.syllabus = ? AND p.kind = 'qp'
                  AND p.year BETWEEN ? AND ?
                  AND q.status IS NOT 'excluded'
                  AND (c.topic IN ({ph}) OR c.secondary_topic IN ({ph}))""" + paper_clause,
            [sel.syllabus, sel.year_from, sel.year_to, *names, *names, *papers]).fetchall()
    finally:
        con.close()
    pool = []
    for r in rows:
        home = r["topic"] if r["topic"] in picks else r["secondary_topic"]
        subs = picks[home]
        if subs:
            # Subtopics belong to the primary chapter, so a question only
            # counts for a picked subtopic when that chapter is its home.
            if r["topic"] != home or r["subtopic"] not in subs:
                continue
            bucket = f"{home} › {r['subtopic']}"
        else:
            bucket = home
        pool.append({"id": r["id"], "bucket": bucket, "year": r["year"],
                     "marks": r["marks"], "chapter": home})
    return pool


# ── API ───────────────────────────────────────────────────────────────────────

@router.get("/api/topical/{syllabus}/tree")
def topical_tree(syllabus: str):
    if syllabus not in _catalog.SUBJECTS:
        raise HTTPException(404, "Unknown syllabus")
    meta = _catalog._meta_for(syllabus) or {}
    return {
        "syllabus": syllabus, "subject": _catalog.SUBJECTS[syllabus]["plain"],
        "year_min": meta.get("year_min"), "year_max": meta.get("year_max"),
        "components": [{**c, **_catalog.component(syllabus, c["paper"])}
                       for c in meta.get("components", [])],
        "groups": _catalog.paper_groups(syllabus),
        "max_chapters": MAX_CHAPTERS, "max_questions": MAX_QUESTIONS,
        "chapters": [
            {"name": t["name"], "display": t.get("display") or t["name"],
             "count": t.get("count", 0), "papers": t.get("paper_scope"),
             "counts_by_year": t.get("counts_by_year", {}),
             "paper_year": t.get("paper_year", {}),
             "subtopics": [{"name": s["name"], "count": s.get("count", 0),
                            "counts_by_year": s.get("counts_by_year", {})}
                           for s in t.get("subtopics", [])]}
            for t in meta.get("topics", [])],
    }


@router.post("/api/booklets/count")
def booklet_count(sel: Selection, user: dict = Depends(_auth.get_current_user)):
    _validate_chapters(sel)
    pool = question_pool(sel)
    per: dict[str, int] = {}
    for q in pool:
        per[q["bucket"]] = per.get(q["bucket"], 0) + 1
    return {"pool": len(pool), "marks": sum(q["marks"] or 0 for q in pool),
            "per_bucket": per}


@router.post("/api/booklets")
def create_booklet(req: BookletReq, user: dict = Depends(_auth.get_current_user)):
    require_enrolled(user, req.syllabus)
    known = _validate_chapters(req)
    _access.check_quota_gate(user, _event(req.kind))
    pool = question_pool(req)
    if not pool:
        raise HTTPException(400, "No questions match that selection. Widen the year "
                                 "range or paper filter, or pick different chapters.")
    seed = req.seed if req.seed is not None else secrets.randbits(31)
    chosen = select_mixed(pool, req.max_questions, seed)
    subj = _catalog.SUBJECTS[req.syllabus]
    title = (("Mock test: " if req.kind == "test" else "")
             + " · ".join(known[p.chapter]["display"] for p in req.picks)
             + f" — {subj['plain']} {req.syllabus}")
    booklet_id = secrets.token_urlsafe(6)
    _udb.create_booklet({
        "id": booklet_id, "user_id": user["id"], "syllabus": req.syllabus,
        "title": title, "seed": seed,
        "params_json": {**req.model_dump(), "total_marks": sum(q["marks"] or 0 for q in chosen)},
        "question_ids": [q["id"] for q in chosen], "status": "queued",
        "progress": 0, "stage": "Picking questions"})
    _EXEC.submit(_build, booklet_id, user)
    return {"id": booklet_id, "url": f"/papers/view/{booklet_id}",
            "questions": len(chosen), "title": title}


@router.get("/api/booklets")
def my_booklets(user: dict = Depends(_auth.get_current_user)):
    return {"booklets": [
        {"id": b["id"], "title": b["title"], "syllabus": b["syllabus"],
         "status": b["status"], "created_at": b["created_at"], "kind": _kind(b),
         "questions": len(b.get("question_ids") or []), "url": f"/papers/view/{b['id']}",
         "available": not expired(b)}
        for b in _udb.list_booklets(user["id"])]}


@router.get("/api/booklets/{booklet_id}")
def booklet_detail(booklet_id: str, user: dict = Depends(_auth.get_current_user)):
    b = _owned(booklet_id, user)
    return {**{k: b.get(k) for k in ("id", "title", "syllabus", "status", "progress", "stage",
                                     "error", "params_json", "page_map_json", "created_at")},
            "kind": _kind(b)}


@router.get("/api/booklets/{booklet_id}/status")
def booklet_status(booklet_id: str, user: dict = Depends(_auth.get_current_user)):
    b = _owned(booklet_id, user)
    if expired(b):
        return {"status": "expired", "progress": 100, "stage": "Kept as a record",
                "error": f"This paper was last opened more than {RETENTION_DAYS} days ago, so its PDF "
                         "has been removed. It stays on My papers as a record."}
    return {"status": b["status"], "progress": b["progress"], "stage": b.get("stage"),
            "error": b.get("error")}


@router.get("/api/booklets/{booklet_id}/pdf")
def booklet_pdf(booklet_id: str, download: bool = False, part: str = "paper", annotated: bool = False,
                user: dict = Depends(_auth.get_current_user)):
    b = _owned(booklet_id, user)
    if b["status"] != "ready":
        raise HTTPException(409, "This booklet is still being built.")
    if part not in ("paper", "ms") or (part == "ms" and _kind(b) != "test"):
        raise HTTPException(404, "No such part")
    pdf = BOOKLET_DIR / (f"{booklet_id}_ms.pdf" if part == "ms" else f"{booklet_id}.pdf")
    if not pdf.exists():
        raise HTTPException(410, f"This paper was not opened for {RETENTION_DAYS} days, so its PDF has "
                                 "been removed. It stays on My papers as a record.")
    # "Last opened" - what retention counts from. At most once a day: touching the
    # file changes its ETag / Last-Modified, and PDF.js loads it in byte ranges, so
    # a touch mid-session made the browser stitch ranges of two "versions"
    # ("Bad end offset"). A day's granularity is plenty for a 30-day rule.
    try:
        if time.time() - pdf.stat().st_mtime > 86400:
            os.utime(pdf)
    except OSError:
        pass
    name = (re.sub(r"[^A-Za-z0-9]+", "-", b["title"] or booklet_id).strip("-")[:80]
            + ("-mark-scheme" if part == "ms" else "") + ("-annotated" if annotated else "") + ".pdf")
    if annotated:
        doc = f"booklet:{booklet_id}" + (":ms" if part == "ms" else "")
        pages = _udb.get_annotations(user["id"], doc)
        if pages:
            import annot_pdf
            from fastapi.responses import Response
            return Response(annot_pdf.burn(pdf, pages), media_type="application/pdf",
                            headers={"Content-Disposition": f'attachment; filename="{name}"',
                                     "Cache-Control": "private, no-store"})
    return FileResponse(pdf, media_type="application/pdf", filename=name,
                        content_disposition_type="attachment" if download or annotated else "inline",
                        headers={"Cache-Control": "private, max-age=3600"})


# ── Build job ─────────────────────────────────────────────────────────────────

_STAGES = {"contents": (90, "Building the clickable contents page"),
           "scheme": (70, "Writing the separate mark scheme"),
           "saving": (96, "Finishing your paper")}


def _kind(b: dict) -> str:
    return (b.get("params_json") or {}).get("kind") or "booklet"


def _event(kind: str) -> str:
    """The quota a build counts against (tests keep the old Test Builder's)."""
    return "topic_test" if kind == "test" else "topical_paper"


def _build(booklet_id: str, user: dict, record: bool = True) -> None:
    """Run pipeline.compose for a booklet, streaming progress into its row."""
    b = _udb.get_booklet(booklet_id)
    if b is None:
        return
    params = b["params_json"] or {}
    BOOKLET_DIR.mkdir(parents=True, exist_ok=True)
    final = BOOKLET_DIR / f"{booklet_id}.pdf"
    final_ms = BOOKLET_DIR / f"{booklet_id}_ms.pdf"
    final_map = BOOKLET_DIR / f"{booklet_id}.json"
    tag = f".tmp-{os.getpid()}-{threading.get_ident()}"
    pdf = BOOKLET_DIR / f"{booklet_id}{tag}.pdf"            # written here, then swapped in
    pmap = BOOKLET_DIR / f"{booklet_id}{tag}.json"
    test = _kind(b) == "test"
    topics = "|".join(p["chapter"] for p in params.get("picks", []))
    ids = ",".join(str(i) for i in b["question_ids"])
    if test:
        cmd = [sys.executable, "-m", "pipeline.testgen", "--syllabus", b["syllabus"],
               "--topics", topics, "--ids", ids, "--out", str(pdf)]
    else:
        cmd = [sys.executable, "-m", "pipeline.compose", "--syllabus", b["syllabus"],
               "--topics", topics, "--ids", ids, "--out", str(pdf), "--page-map", str(pmap)]
        if not params.get("include_ms", True):
            cmd.append("--no-ms")
    span = 60 if test else 84                 # a test still has its mark scheme to write
    last = {"progress": -1, "stage": None}

    def push(progress: int, stage: str):
        if stage != last["stage"] or progress - last["progress"] >= 5:
            _udb.update_booklet(booklet_id, {"status": "building",
                                             "progress": progress, "stage": stage})
            last.update(progress=progress, stage=stage)

    push(4, "Cropping questions from the original papers")
    tail: list[str] = []
    try:
        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True,
                                env={**os.environ, "PWT_PROGRESS": "1"})
        timer = threading.Timer(BUILD_TIMEOUT_S, proc.kill)
        timer.start()
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line.startswith("PROGRESS "):
                    tail = (tail + [line])[-20:]
                    continue
                parts = line.split()
                if parts[1] == "question" and len(parts) == 4:
                    done, total = int(parts[2]), max(1, int(parts[3]))
                    push(4 + int(span * done / total),
                         f"Cropping questions from the original papers · {done}/{total}")
                elif parts[1] in _STAGES:
                    push(*_STAGES[parts[1]])
            rc = proc.wait()
        finally:
            timer.cancel()
        if rc != 0 or not pdf.exists():
            raise RuntimeError(" | ".join(tail[-3:]) or f"{cmd[2]} exited {rc}")
        page_map = json.loads(pmap.read_text("utf-8")) if pmap.exists() else None
        tmp_ms = pdf.with_name(pdf.stem + "_ms.pdf")          # testgen's companion file
        if test:
            os.replace(tmp_ms, final_ms)
        os.replace(pdf, final)
        if pmap.exists():
            os.replace(pmap, final_map)
        _udb.update_booklet(booklet_id, {"status": "ready", "progress": 100,
                                         "stage": "Ready", "page_map_json": page_map,
                                         "error": None})
        if record:
            _access.record_quota(user, _event(_kind(b)))   # only successful builds count
    except Exception as exc:                              # surface, never hang the loader
        print(f"[booklet {booklet_id}] build failed: {exc}", flush=True)
        for leftover in BOOKLET_DIR.glob(f"{booklet_id}{tag}*"):
            leftover.unlink(missing_ok=True)
        _udb.update_booklet(booklet_id, {"status": "failed", "stage": "Failed",
                                         "error": "We couldn't build this paper. "
                                                  "Please try again."})


# ── Viewer page ───────────────────────────────────────────────────────────────

@router.get("/papers/view/{booklet_id}", response_class=HTMLResponse)
def viewer_page(booklet_id: str, user: dict | None = Depends(_auth.maybe_user)):
    if user is None:
        return RedirectResponse(f"/login.html?next=/papers/view/{booklet_id}", 302)
    b = _owned(booklet_id, user)
    if expired(b):
        return _record_page(b, user)
    import blog as _blog
    esc = _catalog._e
    subj = _catalog.SUBJECTS.get(b["syllabus"], {})
    state = {"id": b["id"], "title": b["title"], "syllabus": b["syllabus"], "kind": _kind(b),
             "totalMarks": (b.get("params_json") or {}).get("total_marks"),
             "subjectUrl": _catalog.subject_url(b["syllabus"]) if subj else "/papers"}
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="robots" content="noindex">
  <script>try{{var t=localStorage.getItem("theme")||"light";document.documentElement.setAttribute("data-theme",t);var p=localStorage.getItem("pwt-paper");if(p)document.documentElement.setAttribute("data-paper",p)}}catch(e){{}}</script>
  <title>{esc(b['title'] or 'Topical paper')} — PrepWithTee</title>
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700;800&family=Hanken+Grotesk:wght@400;500;600;700&family=Playfair+Display:wght@700;800&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/styles.css?v={_catalog.STYLES_V}">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf_viewer.min.css">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.css">
  <link rel="stylesheet" href="/viewer.css?v={VIEWER_V}">
  <link rel="stylesheet" href="/ai-panel.css?v={VIEWER_V}">
  <link rel="stylesheet" href="/annotate.css?v={VIEWER_V}">
</head>
<body class="vw-page">
{_blog._nav()}
<main id="vw" class="vw" data-state="loading"></main>
<script id="vw-state" type="application/json">{json.dumps(state)}</script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.1.6/purify.min.js"></script>
<script src="/main.js?v=20260928a"></script>
<script type="module" src="/auth.js?v=20260927k"></script>
<script type="module" src="/viewer.js?v={VIEWER_V}"></script>
</body>
</html>""", headers={"Cache-Control": "private, no-store"})


# ── My papers (history) ───────────────────────────────────────────────────────

def _rebuild_url(b: dict) -> str:
    """The builder, pre-ticked with the same chapters (and mode)."""
    from urllib.parse import urlencode
    params = b.get("params_json") or {}
    q = [("pick", p["chapter"]) for p in params.get("picks", []) if p.get("chapter")]
    if _kind(b) == "test":
        q.append(("mode", "test"))
    base = _catalog.subject_url(b["syllabus"]) if b["syllabus"] in _catalog.SUBJECTS else "/papers/topical"
    return f"{base}?{urlencode(q)}#builder" if q else f"{base}#builder"


def _date(ts) -> str:
    from datetime import datetime
    try:
        d = (datetime.fromtimestamp(ts) if isinstance(ts, (int, float))
             else datetime.fromisoformat(str(ts).replace("Z", "+00:00")))
        return f"{d.day} {d.strftime('%b %Y')}"
    except Exception:
        return str(ts or "")[:10]


def _paper_card(b: dict, inked: set[str]) -> str:
    import ui
    esc = _catalog._e
    params = b.get("params_json") or {}
    test = _kind(b) == "test"
    subj = _catalog.SUBJECTS.get(b["syllabus"], {})
    chapters = [p["chapter"] for p in params.get("picks", []) if p.get("chapter")]
    n = len(b.get("question_ids") or [])
    marks = params.get("total_marks")
    years = (f"{params.get('year_from')}–{params.get('year_to')}"
             if params.get("year_from") and params.get("year_to") else "")
    has_ink = f"booklet:{b['id']}" in inked or f"booklet:{b['id']}:ms" in inked
    gone = expired(b)
    if b["status"] in ("queued", "building"):
        badge, state = '<span class="mp-badge mp-building">Building…</span>', "building"
    elif b["status"] == "failed":
        badge, state = '<span class="mp-badge mp-failed">Failed</span>', "failed"
    elif gone:
        badge, state = '<span class="mp-badge mp-record">Record only</span>', "record"
    else:
        until = available_until(b)
        badge = f'<span class="mp-badge mp-ready">Ready{f" · until {_date(until)}" if until else ""}</span>'
        state = "ready"
    acts = []
    bid = esc(b["id"])
    if state in ("ready", "building"):
        acts.append(f'<a class="cat-btn" href="/papers/view/{bid}">Open</a>')
    if state == "ready":
        acts.append(f'<a class="cat-btn cat-btn-ghost" href="/api/booklets/{bid}/pdf?download=1">'
                    f'{ui.icon("download")} PDF</a>')
        if has_ink:
            acts.append(f'<a class="cat-btn cat-btn-ghost" href="/api/booklets/{bid}/pdf?annotated=1" '
                        f'title="The PDF with your pen, highlighter and text marks">'
                        f'{ui.icon("download")} With my annotations</a>')
        if test:
            acts.append(f'<a class="cat-btn cat-btn-ghost" href="/api/booklets/{bid}/pdf?part=ms&amp;'
                        f'{"annotated=1" if has_ink else "download=1"}">{ui.icon("download")} Mark scheme</a>')
    acts.append(f'<a class="cat-btn cat-btn-ghost" href="{esc(_rebuild_url(b))}">Build it again</a>')
    meta = " · ".join(x for x in (f"{n} questions", f"{marks} marks" if marks else "", years,
                                   "annotated" if has_ink else "") if x)
    return f"""
    <article class="mp-card is-{state} cat-tone-{subj.get('tone', 'blue')}" data-syllabus="{esc(b['syllabus'])}"
             data-kind="{'test' if test else 'booklet'}">
      <div class="mp-ic">{ui.icon("test" if test else "topical")}</div>
      <div class="mp-body">
        <p class="mp-top"><span class="cat-code">{esc(b['syllabus'])}</span>
          <span class="mp-kind">{'Mock test' if test else 'Topical paper'}</span>{badge}</p>
        <h3>{esc(' · '.join(chapters) or b['title'] or 'Topical paper')}</h3>
        <p class="mp-meta">{esc(subj.get('plain', ''))} · built {_date(b.get('created_at'))} · {esc(meta)}</p>
        <div class="mp-acts">{''.join(acts)}</div>
      </div>
    </article>"""


_FILTER_JS = """
<script>
(function () {
  var f = { syl: document.querySelector("[data-mp-syl][aria-pressed=true]")?.dataset.mpSyl || "", kind: "" };
  function apply() {
    var shown = 0;
    document.querySelectorAll(".mp-card").forEach(function (c) {
      var ok = (!f.syl || c.dataset.syllabus === f.syl) && (!f.kind || c.dataset.kind === f.kind);
      c.hidden = !ok; if (ok) shown++;
    });
    document.querySelectorAll(".mp-sec").forEach(function (s) {
      s.hidden = !s.querySelector(".mp-card:not([hidden])");
    });
    var none = document.querySelector(".mp-none");
    if (none) none.hidden = shown > 0;
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-mp-syl],[data-mp-kind]"); if (!b) return;
    if (b.hasAttribute("data-mp-syl")) f.syl = b.dataset.mpSyl; else f.kind = b.dataset.mpKind;
    b.parentNode.querySelectorAll("button").forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
    apply();
  });
  apply();
})();
</script>"""


@router.get("/my-papers", response_class=HTMLResponse)
def my_papers_page(syllabus: str = "", user: dict | None = Depends(_auth.maybe_user)):
    if user is None:
        return RedirectResponse("/login.html?next=/my-papers", 302)
    esc = _catalog._e
    state = _catalog._student_state(user)
    rows = _udb.list_booklets(user["id"], 300)
    try:
        inked = _udb.annotated_docs(user["id"], "booklet:")
    except Exception:
        inked = set()
    codes = sorted({b["syllabus"] for b in rows})
    live = [b for b in rows if not expired(b)]
    old = [b for b in rows if expired(b)]
    chips = "".join(
        f'<button type="button" class="yr-chip" data-mp-syl="{esc(c)}" aria-pressed="{str(c == syllabus).lower()}">'
        f'{esc(c)} <span>{esc(_catalog.SUBJECTS.get(c, {}).get("plain", ""))}</span></button>' for c in codes)
    bar = (f'<div class="yr-bar mp-bar" role="toolbar" aria-label="Filter papers">'
           f'<div class="yr-chips"><button type="button" class="yr-chip" data-mp-syl="" '
           f'aria-pressed="{str(syllabus not in codes).lower()}">All subjects</button>{chips}</div>'
           f'<div class="yr-chips"><button type="button" class="yr-chip" data-mp-kind="" aria-pressed="true">All</button>'
           f'<button type="button" class="yr-chip" data-mp-kind="booklet" aria-pressed="false">Topical</button>'
           f'<button type="button" class="yr-chip" data-mp-kind="test" aria-pressed="false">Mock tests</button></div>'
           f'</div>') if rows else ""
    empty = ("" if rows else
             '<div class="ui-empty"><h2>No papers yet</h2><p>Topical papers and mock tests you build appear '
             'here, together with your annotations. Build your first one from a subject page.</p>'
             '<div class="cat-actions"><a class="cat-btn" href="/papers/topical">Build a topical paper</a>'
             '<a class="cat-btn cat-btn-ghost" href="/papers/mock-tests">Make a mock test</a></div></div>')
    sec_live = (f'<section class="mp-sec"><h2 class="ui-h2">Ready to open</h2><div class="mp-list">'
                f'{"".join(_paper_card(b, inked) for b in live)}</div></section>') if live else ""
    sec_old = (f'<section class="mp-sec"><h2 class="ui-h2">Older - kept as a record</h2>'
               f'<p class="cat-note mp-note">Not opened for {RETENTION_DAYS} days, so the PDF was removed.</p>'
               f'<div class="mp-list">{"".join(_paper_card(b, inked) for b in old)}</div></section>') if old else ""
    body = f"""
    <header class="cat-hero cat-hero-sm">
      <p class="cat-eyebrow">My papers</p>
      <h1>Papers you have built</h1>
      <p class="cat-lede">Every topical paper and mock test you have made. A paper stays ready to open - with
        your pen and highlighter marks - for {RETENTION_DAYS} days after you last opened it. After that it is
        kept here as a record, and <b>Build it again</b> makes a fresh one on the same chapters.</p>
      <dl class="cat-stats"><div><dt>Built</dt><dd>{len(rows)}</dd></div>
        <div><dt>Ready to open</dt><dd>{len(live)}</dd></div>
        <div><dt>Records</dt><dd>{len(old)}</dd></div></dl>
      <div class="cat-actions"><a class="cat-btn" href="/papers/topical">New topical paper</a>
        <a class="cat-btn cat-btn-ghost" href="/papers/mock-tests">New mock test</a></div>
    </header>
    {bar}
    {empty}
    {sec_live}
    {sec_old}
    <p class="cat-note mp-none" hidden>Nothing matches those filters.</p>
    {_FILTER_JS}"""
    html = _catalog._shell(title="My papers - PrepWithTee", desc="Topical papers and mock tests you built.",
                           path="/my-papers", body=body, state=state, noindex=True,
                           crumbs=[("Home", "/"), ("Past papers", "/papers"), ("My papers", "/my-papers")])
    html = html.replace("</head>", f'  <link rel="stylesheet" href="/yearly.css?v={VIEWER_V}">\n</head>', 1)
    return HTMLResponse(html, headers={"Cache-Control": "private, no-store"})


def _record_page(b: dict, user: dict) -> HTMLResponse:
    state = _catalog._student_state(user)
    body = f"""
    <header class="cat-hero cat-hero-sm">
      <p class="cat-eyebrow">Kept as a record</p>
      <h1>This paper is no longer stored</h1>
      <p class="cat-lede">It was last opened more than {RETENTION_DAYS} days ago, so its PDF was removed. The
        record stays on My papers - build it again for a fresh copy on the same chapters.</p>
    </header>
    <div class="mp-list">{_paper_card(b, set())}</div>"""
    return HTMLResponse(_catalog._shell(
        title="Paper record - PrepWithTee", desc="", path=f"/papers/view/{b['id']}", body=body,
        state=state, noindex=True,
        crumbs=[("Home", "/"), ("Past papers", "/papers"), ("My papers", "/my-papers"),
                ("Record", f"/papers/view/{b['id']}")]),
        headers={"Cache-Control": "private, no-store"})
