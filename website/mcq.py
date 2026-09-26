"""MCQ practice sessions (P1-e) and page annotations (P2-a).

    GET  /api/mcq/topics?syllabus=           chapters with how many keyed MCQs each has
    POST /api/mcq/sessions                   start: a full past paper or a topical set
    GET  /api/mcq/sessions?syllabus=         my sessions (resume / history)
    GET  /api/mcq/sessions/{id}              questions + my answers (+ keys once revealed)
    PUT  /api/mcq/sessions/{id}/answer       save one answer / flag (live check -> result)
    PUT  /api/mcq/sessions/{id}/clock        time used so far, preferred view
    POST /api/mcq/sessions/{id}/submit       mark it, record paper progress, full review
    GET  /mcq/session/{id}                   the solver page (noindex)

    GET  /api/annotations?doc=               my drawings on one document, per page
    PUT  /api/annotations                    save one page

A session never sends the answer key up front: a letter is revealed for one
question when live check marks it, and for all of them after submit. With live
check on, a checked answer is locked - otherwise checking would be free guessing.
"""

import json
import re
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, field_validator

import auth as _auth
import catalog as _catalog
import db as _db
import users_db as _udb
from selection import select_mixed

router = APIRouter()

SESSION_V = "20260927l"      # bump with mcq-session.js/.css, mcq-setup.js, annotate.js
LETTERS = ("A", "B", "C", "D")
# Official durations (minutes) for the multiple-choice components.
EXAM_MINS = {("9702", 1): 75, ("5054", 1): 60, ("5070", 1): 60,
             ("0625", 1): 45, ("0625", 2): 45, ("0620", 1): 45, ("0620", 2): 45}
SESSION_NAMES = {"m": "Feb/March", "s": "May/June", "w": "Oct/Nov"}
SESSION_SHORT = {"m": "F/M", "s": "M/J", "w": "O/N"}
_ID = re.compile(r"^[A-Za-z0-9_-]{6,16}$")


def _mcq_papers(code: str) -> list[int]:
    from pipeline import config as _pcfg
    return sorted(p for s, p in _pcfg.MCQ_PAPERS if s == code)


def _staff(user: dict) -> bool:
    return user.get("role") in ("teacher", "admin")


def _require_enrolled(user: dict, code: str) -> None:
    import booklets as _booklets
    _booklets.require_enrolled(user, code)


def _exam_seconds(code: str, paper: int, n_questions: int | None = None) -> int:
    mins = EXAM_MINS.get((code, paper), 45)
    if n_questions is None:
        return mins * 60
    # Topical sets get the exam's own pace (a 40-question hour = 90 s each).
    return max(60, round(mins * 60 / 40 * n_questions))


# ── Question data ─────────────────────────────────────────────────────────────

def _keys(con, qids: list[int]) -> dict[int, str]:
    """Official answer letter per question, from its sitting's mark scheme."""
    if not qids:
        return {}
    ph = ",".join("?" for _ in qids)
    rows = con.execute(
        f"""SELECT q.id AS qid, m.answer
            FROM questions q
            JOIN papers p ON p.id = q.paper_id
            JOIN papers pm ON pm.syllabus = p.syllabus AND pm.year = p.year
                          AND pm.session = p.session AND pm.paper = p.paper
                          AND pm.variant = p.variant AND pm.kind = 'ms'
            JOIN ms_entries m ON m.paper_id = pm.id AND m.question_number = q.number
                             AND m.sub_part = q.sub_part
            WHERE q.id IN ({ph})""", qids).fetchall()
    return {r["qid"]: (r["answer"] or "").strip().upper() for r in rows
            if (r["answer"] or "").strip().upper() in LETTERS}


def _question_meta(qids: list[int]) -> tuple[list[dict], dict[int, str]]:
    """[{qid, n, label, ref, topic, paper_id, page, y}] in session order + the keys."""
    if not qids:
        return [], {}
    ph = ",".join("?" for _ in qids)
    con = _db.plain_connect()
    try:
        rows = {r["id"]: dict(r) for r in con.execute(
            f"""SELECT q.id, q.number, q.sub_part, q.rects_json, q.paper_id, c.topic,
                       p.syllabus, p.year, p.session, p.paper, p.variant
                FROM questions q JOIN papers p ON p.id = q.paper_id
                LEFT JOIN classifications c ON c.question_id = q.id
                WHERE q.id IN ({ph})""", qids).fetchall()}
        keys = _keys(con, qids)
    finally:
        con.close()
    out = []
    for i, qid in enumerate(qids, 1):
        r = rows.get(qid)
        if not r:
            continue
        sub = r["sub_part"] or ""
        try:
            first = json.loads(r["rects_json"] or "[]")[0]
            page, y = int(first["page"]) + 1, round(float(first["y0"]), 1)
        except (ValueError, IndexError, KeyError, TypeError):
            page, y = 1, 0.0
        out.append({
            "qid": qid, "n": i, "number": r["number"],
            "label": f"Q{i}",
            "ref": (f"{r['syllabus']}/{r['paper']}{r['variant'] or ''}/"
                    f"{SESSION_SHORT.get(r['session'], r['session'])}/{r['year'] % 100:02d} "
                    f"Q{r['number']}{f'({sub})' if sub else ''}"),
            "topic": r["topic"] or "", "paper_id": r["paper_id"], "page": page, "y": y})
    return out, keys


def _paper_row(paper_id: int) -> dict | None:
    con = _db.plain_connect()
    try:
        r = con.execute("SELECT id, syllabus, year, session, paper, variant, kind "
                        "FROM papers WHERE id = ?", [paper_id]).fetchone()
        return dict(r) if r else None
    finally:
        con.close()


# ── Topics (for the setup screen) ─────────────────────────────────────────────

@router.get("/api/mcq/topics")
def mcq_topics(syllabus: str = Query(..., pattern=r"^[0-9A-Za-z]{4,6}$")):
    papers = _mcq_papers(syllabus)
    if not papers:
        raise HTTPException(404, "No multiple-choice papers for this subject")
    ph = ",".join("?" for _ in papers)
    con = _db.plain_connect()
    try:
        rows = con.execute(
            f"""SELECT c.topic, COUNT(DISTINCT q.id) AS n, MIN(p.year) AS y0, MAX(p.year) AS y1
                FROM questions q
                JOIN papers p ON p.id = q.paper_id
                JOIN classifications c ON c.question_id = q.id
                WHERE p.syllabus = ? AND p.kind = 'qp' AND p.paper IN ({ph})
                  AND q.status IS NOT 'excluded'
                GROUP BY c.topic""", [syllabus, *papers]).fetchall()
    finally:
        con.close()
    counts = {r["topic"]: dict(r) for r in rows}
    order = [c["name"] for c in _catalog.chapters(syllabus)]
    names = [t for t in order if t in counts] + sorted(t for t in counts if t not in order)
    return {"syllabus": syllabus, "papers": papers,
            "topics": [{"name": t, "count": counts[t]["n"]} for t in names],
            "year_min": min((r["y0"] for r in counts.values()), default=None),
            "year_max": max((r["y1"] for r in counts.values()), default=None)}


# ── Sessions ──────────────────────────────────────────────────────────────────

class StartReq(BaseModel):
    syllabus: str
    paper_id: int | None = None          # a full past paper ...
    topics: list[str] = []               # ... or a topical set
    count: int = 20
    year_from: int = 2010
    year_to: int = 2026
    papers: list[int] | None = None      # which MCQ components (e.g. 0625 P1 / P2)
    mode: str = "paper"                  # "paper" | "single"
    live_check: bool = False
    timer: str = "official"              # "official" | "none" | "custom"
    minutes: int | None = None
    seed: int | None = None

    @field_validator("syllabus")
    @classmethod
    def _syl(cls, v):
        if v not in _catalog.SUBJECTS:
            raise ValueError("unknown syllabus")
        return v

    @field_validator("mode")
    @classmethod
    def _mode(cls, v):
        if v not in ("paper", "single"):
            raise ValueError("mode must be paper or single")
        return v

    @field_validator("timer")
    @classmethod
    def _timer(cls, v):
        if v not in ("official", "none", "custom"):
            raise ValueError("timer must be official, none or custom")
        return v

    @field_validator("count")
    @classmethod
    def _count(cls, v):
        return max(5, min(60, v))


def _title(code: str, p: dict | None = None, topics: list[str] | None = None, n: int = 0) -> str:
    s = _catalog.SUBJECTS[code]
    if p:
        return (f"{s['plain']} {code}/{p['paper']}{p['variant'] or ''} · "
                f"{SESSION_NAMES.get(p['session'], p['session'])} {p['year']}")
    shown = ", ".join(topics[:2]) + (f" +{len(topics) - 2}" if len(topics) > 2 else "")
    return f"{s['plain']} {code} · {shown} · {n} questions"


def _topical_pool(req: StartReq) -> list[dict]:
    papers = [p for p in (req.papers or _mcq_papers(req.syllabus)) if p in _mcq_papers(req.syllabus)]
    if not papers:
        raise HTTPException(422, "Pick at least one multiple-choice paper")
    tph = ",".join("?" for _ in req.topics)
    pph = ",".join("?" for _ in papers)
    con = _db.plain_connect()
    try:
        rows = [dict(r) for r in con.execute(
            f"""SELECT q.id, c.topic, p.year FROM questions q
                JOIN papers p ON p.id = q.paper_id
                JOIN classifications c ON c.question_id = q.id
                WHERE p.syllabus = ? AND p.kind = 'qp' AND p.paper IN ({pph})
                  AND p.year BETWEEN ? AND ? AND q.status IS NOT 'excluded'
                  AND c.topic IN ({tph})""",
            [req.syllabus, *papers, req.year_from, req.year_to, *req.topics]).fetchall()]
        keyed = _keys(con, [r["id"] for r in rows])
    finally:
        con.close()
    # Only questions with an official key can be marked.
    return [{"id": r["id"], "bucket": r["topic"], "year": r["year"]} for r in rows if r["id"] in keyed]


@router.post("/api/mcq/sessions")
def start_session(req: StartReq, user: dict = Depends(_auth.get_current_user)):
    code = req.syllabus
    if not _mcq_papers(code):
        raise HTTPException(404, "No multiple-choice papers for this subject")
    _require_enrolled(user, code)
    if req.paper_id is not None:
        p = _paper_row(req.paper_id)
        if not p or p["syllabus"] != code or p["kind"] != "qp" or p["paper"] not in _mcq_papers(code):
            raise HTTPException(404, "That is not a multiple-choice paper for this subject")
        con = _db.plain_connect()
        try:
            qids = [r["id"] for r in con.execute(
                "SELECT id FROM questions WHERE paper_id = ? AND status IS NOT 'excluded' "
                "ORDER BY number, sub_part", [p["id"]]).fetchall()]
            keyed = _keys(con, qids)
        finally:
            con.close()
        if not qids:
            raise HTTPException(404, "This paper has no questions yet")
        if not keyed:
            raise HTTPException(422, "The answer key for this paper isn't available yet")
        kind, title, limit = "paper", _title(code, p), _exam_seconds(code, p["paper"])
    else:
        topics = [t for t in dict.fromkeys(req.topics) if t]
        if not topics:
            raise HTTPException(422, "Pick at least one chapter")
        req.topics = topics
        pool = _topical_pool(req)
        if not pool:
            raise HTTPException(422, "No marked multiple-choice questions match those filters")
        seed = req.seed if req.seed is not None else secrets.randbelow(2**31)
        qids = [q["id"] for q in select_mixed(pool, req.count, seed)]
        p = None
        kind, title = "topical", _title(code, None, topics, len(qids))
        limit = _exam_seconds(code, (req.papers or _mcq_papers(code))[0], len(qids))
    if req.timer == "none":
        limit = None
    elif req.timer == "custom":
        limit = max(1, min(240, req.minutes or 0)) * 60 if req.minutes else limit
    sid = secrets.token_urlsafe(6)
    _udb.create_mcq_session({
        "id": sid, "user_id": user["id"], "syllabus": code, "kind": kind,
        "paper_id": p["id"] if p else None, "title": title, "question_ids": qids,
        "settings": {"mode": req.mode, "live_check": bool(req.live_check),
                     "time_limit_s": limit, "timer": req.timer},
        "answers": {}, "status": "active", "elapsed_s": 0, "total": len(qids)})
    return {"id": sid, "url": f"/mcq/session/{sid}", "title": title}


def _owned(sid: str, user: dict) -> dict:
    if not _ID.match(sid or ""):
        raise HTTPException(404, "Session not found")
    s = _udb.get_mcq_session(sid)
    if not s or (s["user_id"] != user["id"] and not _staff(user)):
        raise HTTPException(404, "Session not found")
    return s


def _summary(s: dict) -> dict:
    ans = s.get("answers") or {}
    return {"id": s["id"], "title": s["title"], "kind": s["kind"], "syllabus": s["syllabus"],
            "status": s["status"], "score": s.get("score"), "total": s.get("total"),
            "answered": sum(1 for a in ans.values() if a.get("a")),
            "count": len(s.get("question_ids") or []),
            "mode": (s.get("settings") or {}).get("mode", "paper"),
            "updated_at": s.get("updated_at"), "url": f"/mcq/session/{s['id']}"}


@router.get("/api/mcq/sessions")
def list_sessions(syllabus: str | None = None, user: dict = Depends(_auth.get_current_user)):
    return {"sessions": [_summary(s) for s in _udb.list_mcq_sessions(user["id"], syllabus)]}


def _payload(s: dict) -> dict:
    qs, keys = _question_meta(s["question_ids"])
    answers = s.get("answers") or {}
    submitted = s["status"] == "submitted"
    for q in qs:
        a = answers.get(str(q["qid"])) or {}
        q["answer"] = a.get("a")
        q["flagged"] = bool(a.get("f"))
        q["time_s"] = a.get("t") or 0
        q["has_key"] = q["qid"] in keys
        if submitted or a.get("checked"):
            q["key"] = keys.get(q["qid"])
            q["correct"] = bool(q["answer"]) and q["answer"] == q["key"]
    st = s.get("settings") or {}
    out = {**_summary(s), "settings": st, "elapsed_s": s.get("elapsed_s") or 0,
           "time_limit_s": st.get("time_limit_s"), "questions": qs,
           "paper_id": s.get("paper_id"), "created_at": s.get("created_at"),
           "submitted_at": s.get("submitted_at")}
    if s.get("paper_id"):
        out["pdf_url"] = f"/api/library/pdf/{s['paper_id']}"
    if submitted:
        out["review"] = _review(qs)
    return out


def _review(qs: list[dict]) -> dict:
    by_topic: dict[str, dict] = {}
    for q in qs:
        t = by_topic.setdefault(q["topic"] or "Other", {"topic": q["topic"] or "Other",
                                                       "right": 0, "total": 0})
        if q.get("key"):
            t["total"] += 1
            t["right"] += 1 if q.get("correct") else 0
    marked = [q for q in qs if q.get("key")]
    return {"right": sum(1 for q in marked if q["correct"]),
            "wrong": sum(1 for q in marked if q["answer"] and not q["correct"]),
            "blank": sum(1 for q in marked if not q["answer"]),
            "unmarked": len(qs) - len(marked),
            "topics": sorted(by_topic.values(), key=lambda t: (t["right"] / max(1, t["total"]),
                                                                t["topic"]))}


@router.get("/api/mcq/sessions/{sid}")
def get_session(sid: str, user: dict = Depends(_auth.get_current_user)):
    return _payload(_owned(sid, user))


class AnswerReq(BaseModel):
    qid: int
    answer: str | None = None
    flagged: bool | None = None
    time_s: int | None = None            # seconds spent on this question so far
    only_flag: bool = False              # change the flag and nothing else

    @field_validator("answer")
    @classmethod
    def _letter(cls, v):
        if v is None or v == "":
            return None
        v = v.strip().upper()
        if v not in LETTERS:
            raise ValueError("answer must be A, B, C or D")
        return v


@router.put("/api/mcq/sessions/{sid}/answer")
def save_answer(sid: str, req: AnswerReq, user: dict = Depends(_auth.get_current_user)):
    s = _owned(sid, user)
    if s["status"] != "active":
        raise HTTPException(409, "This session has been submitted")
    if req.qid not in s["question_ids"]:
        raise HTTPException(404, "That question isn't in this session")
    answers = dict(s.get("answers") or {})
    a = dict(answers.get(str(req.qid)) or {})
    live = bool((s.get("settings") or {}).get("live_check"))
    if req.flagged is not None:
        a["f"] = bool(req.flagged)
    if req.time_s is not None:
        a["t"] = max(0, min(24 * 3600, int(req.time_s)))
    result = {}
    if not req.only_flag:
        if live and a.get("checked") and req.answer != a.get("a"):
            raise HTTPException(409, "Checked answers are locked in live-check mode")
        a["a"] = req.answer
        if live and req.answer:
            con = _db.plain_connect()
            try:
                key = _keys(con, [req.qid]).get(req.qid)
            finally:
                con.close()
            if key:
                a["checked"] = True
                result = {"key": key, "correct": req.answer == key}
    answers[str(req.qid)] = a
    _udb.update_mcq_session(sid, {"answers": answers})
    return {"ok": True, **result}


class ClockReq(BaseModel):
    elapsed_s: int
    mode: str | None = None


@router.put("/api/mcq/sessions/{sid}/clock")
def save_clock(sid: str, req: ClockReq, user: dict = Depends(_auth.get_current_user)):
    s = _owned(sid, user)
    if s["status"] != "active":
        return {"ok": True}
    fields: dict = {"elapsed_s": max(int(s.get("elapsed_s") or 0), max(0, min(10 * 3600, req.elapsed_s)))}
    if req.mode in ("paper", "single"):
        fields["settings"] = {**(s.get("settings") or {}), "mode": req.mode}
    _udb.update_mcq_session(sid, fields)
    return {"ok": True}


@router.post("/api/mcq/sessions/{sid}/submit")
def submit_session(sid: str, user: dict = Depends(_auth.get_current_user)):
    s = _owned(sid, user)
    if s["status"] == "submitted":
        return _payload(s)
    qs, keys = _question_meta(s["question_ids"])
    answers = s.get("answers") or {}
    score = sum(1 for q in qs if keys.get(q["qid"])
                and (answers.get(str(q["qid"])) or {}).get("a") == keys[q["qid"]])
    total = sum(1 for q in qs if keys.get(q["qid"]))
    now = datetime.now(timezone.utc).isoformat()
    _udb.update_mcq_session(sid, {"status": "submitted", "score": score, "total": total,
                                  "submitted_at": now})
    if s["kind"] == "paper" and s.get("paper_id"):
        p = _paper_row(s["paper_id"])
        if p:
            try:
                _udb.upsert_paper_progress(user["id"], p["syllabus"], p["year"], p["session"],
                                           p["paper"], p["variant"] or "", "confident",
                                           score=score, max_score=total,
                                           note="MCQ practice", set_by="student")
            except Exception as exc:                       # progress is a bonus, never fatal
                print(f"[mcq {sid}] paper progress not saved: {exc}", flush=True)
    return _payload(_udb.get_mcq_session(sid))


# ── Page ──────────────────────────────────────────────────────────────────────

@router.get("/mcq/session/{sid}", response_class=HTMLResponse)
def session_page(sid: str, user: dict | None = Depends(_auth.maybe_user)):
    if user is None:
        return RedirectResponse(f"/login.html?next=/mcq/session/{sid}", 302)
    s = _owned(sid, user)
    import blog as _blog
    import yearly as _yearly
    esc = _catalog._e
    subj = _catalog.SUBJECTS.get(s["syllabus"])
    state = {"id": s["id"], "title": s["title"],
             "backUrl": _yearly.mcq_url(s["syllabus"]) if subj else "/mcq"}
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="robots" content="noindex">
  <script>try{{var t=localStorage.getItem("theme")||"light";document.documentElement.setAttribute("data-theme",t)}}catch(e){{}}</script>
  <title>{esc(s['title'] or 'MCQ practice')} — PrepWithTee</title>
  <link rel="icon" href="/logo.png">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700;800&family=Hanken+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@500;700&family=Playfair+Display:wght@700;800&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/styles.css?v={_catalog.STYLES_V}">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf_viewer.min.css">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.css">
  <link rel="stylesheet" href="/viewer.css?v={SESSION_V}">
  <link rel="stylesheet" href="/ai-panel.css?v={SESSION_V}">
  <link rel="stylesheet" href="/annotate.css?v={SESSION_V}">
  <link rel="stylesheet" href="/mcq-session.css?v={SESSION_V}">
</head>
<body class="vw-page mq-page">
{_blog._nav()}
<main id="mq" class="vw mq" data-state="loading">
  <section class="vw-load"><div class="vw-load-card"><p class="vw-eyebrow">MCQ practice</p>
    <h1>{esc(s['title'] or '')}</h1></div></section>
</main>
<script id="mq-state" type="application/json">{json.dumps(state)}</script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.1.6/purify.min.js"></script>
<script src="/main.js?v=20260927k"></script>
<script type="module" src="/auth.js?v=20260927k"></script>
<script type="module" src="/mcq-session.js?v={SESSION_V}"></script>
</body>
</html>""", headers={"Cache-Control": "private, no-store"})


@router.get("/mcq-solver.html", include_in_schema=False)
def legacy_solver(syllabus: str = ""):
    import yearly as _yearly
    return RedirectResponse(_yearly.legacy_target("mcq", syllabus), 301)


# ── Annotations ───────────────────────────────────────────────────────────────

_DOC = re.compile(r"^(paper:\d{1,10}|booklet:[A-Za-z0-9_-]{6,16}|mcq:[A-Za-z0-9_-]{6,16}:q\d{1,10})$")


def _doc_or_400(doc: str) -> str:
    if not _DOC.match(doc or ""):
        raise HTTPException(400, "Unknown document")
    return doc


@router.get("/api/annotations")
def get_annotations(doc: str, user: dict = Depends(_auth.get_current_user)):
    return {"doc": _doc_or_400(doc),
            "pages": {str(k): v for k, v in _udb.get_annotations(user["id"], doc).items()}}


class AnnotReq(BaseModel):
    doc: str
    page: int
    strokes: list[dict]

    @field_validator("page")
    @classmethod
    def _page(cls, v):
        if not 0 <= v < 1000:
            raise ValueError("page out of range")
        return v

    @field_validator("strokes")
    @classmethod
    def _strokes(cls, v):
        if len(v) > 3000 or len(json.dumps(v)) > 600_000:
            raise ValueError("too much ink on one page")
        return v


@router.put("/api/annotations")
def put_annotations(req: AnnotReq, user: dict = Depends(_auth.get_current_user)):
    _udb.set_annotations(user["id"], _doc_or_400(req.doc), req.page, req.strokes)
    return {"ok": True}
