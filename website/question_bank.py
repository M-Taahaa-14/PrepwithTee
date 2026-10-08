"""Test builder v2: see the questions before the paper is built.

    POST /api/booklets/draft          propose a question list for a selection +
                                      targets (per-chapter MCQ/theory counts, a
                                      mark target, difficulty) -> cards
    POST /api/booklets/alternatives   candidates for Swap / Add (search, filters)
    GET  /api/question/{id}/thumb.png the top of a question's crop, for the cards
    PUT  /api/questions/{id}/rating   a teacher's difficulty rating (1-3 or null)

The draft lives in the browser; Build sends the exact ids
(booklets.BookletReq.ids). Difficulty comes ONLY from teachers' ratings for now
(tutor, 2026-10-08) - a teacher sees their own rating, everyone else the median
of all teachers' ratings; no rating = "unrated".
"""

import statistics
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, field_validator

import auth as _auth
import booklets as _b
import db as _db
import users_db as _udb
from pipeline import config as _pcfg
from selection import availability, default_plan, order_recent_first, sectioned, select_targeted

router = APIRouter()

ROOT = Path(__file__).resolve().parent.parent
THUMB_DIR = ROOT / "data" / "thumbs"
THUMB_WIDTHS = (240, 360, 480)
THUMB_MAX_PT = 330           # the card shows the top of a question, not all of it
ALT_PAGE = 24
DIFF_KEYS = {"1", "2", "3", "unrated"}


# ── Difficulty ────────────────────────────────────────────────────────────────

def _is_teacher(user: dict | None) -> bool:
    return bool(user) and user.get("role") in ("teacher", "admin")


def difficulty_map(ids, user: dict | None) -> dict[int, dict]:
    """{qid: {"value": 1-3|None, "mine": 1-3|None, "n": raters}}."""
    by_q: dict[int, list] = {}
    try:
        rows = _udb.get_question_ratings(list(ids))
    except Exception as exc:                 # migration 028 not applied yet: just unrated
        print(f"[question_bank] ratings unavailable: {exc}", flush=True)
        rows = []
    for r in rows:
        by_q.setdefault(int(r["question_id"]), []).append(r)
    out = {}
    me = user["id"] if user else None
    for q, rs in by_q.items():
        mine = next((int(r["difficulty"]) for r in rs if r["rater_id"] == me), None)
        med = round(statistics.median(int(r["difficulty"]) for r in rs))
        out[q] = {"value": mine if (mine and _is_teacher(user)) else med,
                  "mine": mine, "n": len(rs)}
    return out


def _diff_key(d: dict | None) -> str:
    return str(d["value"]) if d and d.get("value") else "unrated"


# ── Cards ─────────────────────────────────────────────────────────────────────

def card(q: dict, syllabus: str, diff: dict | None) -> dict:
    code = f"{q['paper']}{q['variant']}"
    return {
        "id": q["id"], "bucket": q["bucket"], "chapter": q["chapter"],
        "subtopic": q.get("subtopic"), "mcq": bool(q.get("mcq")), "marks": q.get("marks"),
        "year": q["year"], "session": q["session"], "paper": q["paper"], "variant": q["variant"],
        "ref": _pcfg.source_ref(syllabus, code, q["session"], q["year"], q["number"],
                                q.get("sub_part") or ""),
        "snippet": (q.get("text") or "")[:220],
        "difficulty": diff or {"value": None, "mine": None, "n": 0},
        "thumb": f"/api/question/{q['id']}/thumb.png?w=360",
    }


class Mix(BaseModel):
    mcq: int = 0
    theory: int = 0


class DraftReq(_b.Selection):
    max_questions: int = 20
    plan: dict[str, Mix] | None = None
    marks_target: int | None = None
    difficulty: list[str] | None = None
    locked: list[int] = []
    seed: int | None = None

    @field_validator("difficulty")
    @classmethod
    def _diff(cls, v):
        if v is not None and not set(v) <= DIFF_KEYS:
            raise ValueError("difficulty: 1, 2, 3 or unrated")
        return v

    @field_validator("marks_target")
    @classmethod
    def _marks(cls, v):
        if v is not None and not 1 <= v <= 1000:
            raise ValueError("mark target between 1 and 1000")
        return v

    @field_validator("max_questions")
    @classmethod
    def _maxq(cls, v):
        if not 1 <= v <= _b.MAX_QUESTIONS:
            raise ValueError(f"between 1 and {_b.MAX_QUESTIONS} questions")
        return v


def _bucket_list(sel: _b.Selection, known: dict, avail: dict) -> list[dict]:
    """The picked chapters / subtopics in the order they were picked."""
    out = []
    for p in sel.picks:
        names = ([f"{p.chapter} › {s}" for s in p.subtopics] if p.subtopics else [p.chapter])
        for b in names:
            a = avail.get(b) or {"mcq": 0, "theory": 0, "mcq_marks": 0, "theory_marks": 0}
            out.append({"key": b, "chapter": p.chapter,
                        "label": known[p.chapter]["display"] + (b[len(p.chapter):] if b != p.chapter else ""),
                        **a})
    return out


@router.post("/api/booklets/draft")
def draft(req: DraftReq, user: dict = Depends(_auth.get_current_user)):
    """A proposed list for review. Cheap (no build, no quota)."""
    known = _b._validate_chapters(req)
    pool = _b.question_pool(req)
    diffs = difficulty_map([q["id"] for q in pool], user)
    avail = availability(pool)
    locked = set(req.locked)
    use = pool
    if req.difficulty:
        want = set(req.difficulty)
        use = [q for q in pool if q["id"] in locked or _diff_key(diffs.get(q["id"])) in want]
    plan = ({b: m.model_dump() for b, m in req.plan.items()} if req.plan is not None
            else default_plan(use, req.max_questions))
    chosen = select_targeted(use, plan, req.marks_target, req.max_questions,
                             req.seed, list(req.locked))
    chosen = sectioned(order_recent_first(chosen))[:_b.MAX_QUESTIONS]
    return {
        "questions": [card(q, req.syllabus, diffs.get(q["id"])) for q in chosen],
        "buckets": _bucket_list(req, known, avail),
        "plan": plan,
        "has_mcq": any(q["mcq"] for q in pool),
        "pool": len(pool),
        "rated": sum(1 for q in pool if q["id"] in diffs),
        "can_rate": _is_teacher(user),
    }


class AltReq(_b.Selection):
    bucket: str | None = None
    kind: Literal["mcq", "theory"] | None = None
    exclude: list[int] = []
    q: str = ""
    difficulty: list[str] | None = None
    sort: Literal["recent", "oldest", "marks_low", "marks_high"] = "recent"
    page: int = 0


@router.post("/api/booklets/alternatives")
def alternatives(req: AltReq, user: dict = Depends(_auth.get_current_user)):
    """Questions the user could swap in or add, one page at a time."""
    _b._validate_chapters(req)
    pool = _b.question_pool(req)
    ex = set(req.exclude)
    words = [w for w in req.q.lower().split() if w]
    rows = [q for q in pool if q["id"] not in ex
            and (not req.bucket or q["bucket"] == req.bucket)
            and (not req.kind or ("mcq" if q["mcq"] else "theory") == req.kind)
            and all(w in f"{q['text']} {q['subtopic'] or ''}".lower() for w in words)]
    diffs = difficulty_map([q["id"] for q in rows], user)
    if req.difficulty:
        want = set(req.difficulty)
        rows = [q for q in rows if _diff_key(diffs.get(q["id"])) in want]
    if req.sort in ("marks_low", "marks_high"):
        rows.sort(key=lambda q: q["marks"] or 0, reverse=req.sort == "marks_high")
    else:
        rows = order_recent_first(rows)
        if req.sort == "oldest":
            rows.reverse()
    page = max(0, req.page)
    chunk = rows[page * ALT_PAGE:(page + 1) * ALT_PAGE]
    return {"total": len(rows), "page": page, "per_page": ALT_PAGE,
            "questions": [card(q, req.syllabus, diffs.get(q["id"])) for q in chunk]}


# ── Ratings ───────────────────────────────────────────────────────────────────

class RatingReq(BaseModel):
    difficulty: int | None = None

    @field_validator("difficulty")
    @classmethod
    def _d(cls, v):
        if v is not None and v not in (1, 2, 3):
            raise ValueError("difficulty is 1 (easy), 2 (medium) or 3 (hard)")
        return v


@router.put("/api/questions/{question_id}/rating")
def rate(question_id: int, req: RatingReq, user: dict = Depends(_auth.get_current_user)):
    if not _is_teacher(user):
        raise HTTPException(403, "Only teachers can rate questions.")
    con = _db.plain_connect()
    try:
        ok = con.execute("SELECT 1 FROM questions WHERE id = ?", (question_id,)).fetchone()
    finally:
        con.close()
    if not ok:
        raise HTTPException(404, "No such question")
    _udb.set_question_rating(question_id, user["id"], req.difficulty)
    return {"id": question_id, "difficulty": difficulty_map([question_id], user).get(
        question_id, {"value": None, "mine": None, "n": 0})}


# ── Thumbnails ────────────────────────────────────────────────────────────────

CROPS = (ROOT / "data" / "crops").resolve()


def _crop_path(question_id: int) -> Path | None:
    """data/crops/{paper_key}/q{NN}{sub}.pdf - the same layout app._crop_files_for_key reads."""
    con = _db.plain_connect()
    try:
        r = con.execute("""SELECT q.number, q.sub_part, p.syllabus, p.year, p.session, p.paper, p.variant
                           FROM questions q JOIN papers p ON p.id = q.paper_id WHERE q.id = ?""",
                        (question_id,)).fetchone()
    finally:
        con.close()
    if not r:
        return None
    key = _pcfg.paper_key(r["syllabus"], r["session"], r["year"], f"{r['paper']}{r['variant']}")
    crop = (CROPS / key / f"q{r['number']:02d}{r['sub_part'] or ''}.pdf").resolve()
    if not str(crop).startswith(str(CROPS)) or not crop.is_file():
        return None
    return crop


@router.get("/api/question/{question_id}/thumb.png")
def thumb(question_id: int, w: int = Query(360)):
    """The top of the question (first page, at most THUMB_MAX_PT tall), cached."""
    w = min(THUMB_WIDTHS, key=lambda x: abs(x - w))
    out = THUMB_DIR / f"{question_id}_{w}.png"
    if not out.exists():
        crop = _crop_path(question_id)
        if crop is None:
            raise HTTPException(404, "No crop for this question")
        import fitz
        with fitz.open(str(crop)) as doc:
            page = doc[0]
            r = page.rect
            clip = fitz.Rect(r.x0, r.y0, r.x1, min(r.y1, r.y0 + THUMB_MAX_PT))
            pix = page.get_pixmap(matrix=fitz.Matrix(w / r.width, w / r.width), clip=clip)
            THUMB_DIR.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(f".tmp{id(pix)}.png")
            pix.save(str(tmp))
            tmp.replace(out)
    return Response(out.read_bytes(), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})


PREVIEW_W = 900


@router.get("/api/question/{question_id}/preview.png")
def preview(question_id: int):
    """The whole question (every page of its crop, stacked) as one PNG."""
    out = THUMB_DIR / f"{question_id}_full.png"
    if not out.exists():
        crop = _crop_path(question_id)
        if crop is None:
            raise HTTPException(404, "No crop for this question")
        import fitz
        with fitz.open(str(crop)) as src:
            w = max(p.rect.width for p in src)
            h = sum(p.rect.height for p in src) + 12 * (src.page_count - 1)
            sheet = fitz.open()
            page = sheet.new_page(width=w, height=h)
            y = 0.0
            for i, p in enumerate(src):
                page.show_pdf_page(fitz.Rect(0, y, p.rect.width, y + p.rect.height), src, i)
                y += p.rect.height + 12
            pix = page.get_pixmap(matrix=fitz.Matrix(PREVIEW_W / w, PREVIEW_W / w))
            sheet.close()
        THUMB_DIR.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(f".tmp{id(pix)}.png")
        pix.save(str(tmp))
        tmp.replace(out)
    return Response(out.read_bytes(), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.get("/api/question/{question_id}/review")
def review(question_id: int, user: dict = Depends(_auth.get_current_user)):
    """What the preview drawer shows: the full question, and behind a toggle the
    official mark scheme (an MCQ's is just its letter)."""
    con = _db.plain_connect()
    try:
        q = con.execute("""SELECT q.number, q.sub_part, q.marks, q.text, p.syllabus, p.year,
                                  p.session, p.paper, p.variant
                           FROM questions q JOIN papers p ON p.id = q.paper_id
                           WHERE q.id = ?""", (question_id,)).fetchone()
        if not q:
            raise HTTPException(404, "No such question")
        answer = None
        mcq = _pcfg.is_mcq(q["syllabus"], q["paper"], q["year"])
        if mcq:
            r = con.execute("""SELECT m.answer FROM ms_entries m JOIN papers mp ON mp.id = m.paper_id
                               WHERE mp.kind = 'ms' AND mp.syllabus = ? AND mp.year = ? AND mp.session = ?
                                 AND mp.paper = ? AND mp.variant = ? AND m.question_number = ?""",
                            (q["syllabus"], q["year"], q["session"], q["paper"], q["variant"],
                             q["number"])).fetchone()
            answer = r["answer"] if r else None
    finally:
        con.close()
    return {"id": question_id, "mcq": mcq, "answer": answer,
            "image": f"/api/question/{question_id}/preview.png",
            "ms_image": None if mcq else f"/api/question/{question_id}/ms-preview",
            "ref": _pcfg.source_ref(q["syllabus"], f"{q['paper']}{q['variant']}", q["session"],
                                    q["year"], q["number"], q["sub_part"] or ""),
            "difficulty": difficulty_map([question_id], user).get(
                question_id, {"value": None, "mine": None, "n": 0}),
            "can_rate": _is_teacher(user)}
