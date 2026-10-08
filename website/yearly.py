"""Yearly past papers and MCQ practice as their own pages (P1-d).

    /yearly                                   boards -> subjects
    /yearly/{board}                           one board's subjects
    /yearly/{board}/{subject}                 every sitting, newest first (SEO text)
    /yearly/{board}/{subject}/{year}          one year
    /yearly/view/{paper_id}                   the paper viewer (open to everyone; noindex)
    /mcq, /mcq/{board}/{subject}              MCQ practice landing pages

The viewer shows the question paper, mark scheme and insert of one sitting in
the same PDF.js viewer as topical booklets (pdf-pane.js), side by side on wide
screens, with Explain / Guide me / Mark scheme chips on every question - the
question rows and their positions (questions.rects_json) already exist for
each paper. The old ?tab=yearly|mcq URLs and library.html 301 here.

Yearly papers need NO account and NO enrolment (tutor, 2026-09-27): the viewer
opens for anyone. Signing in only adds saved annotations, "Mark done" and
marks - paper-viewer.js hides those for guests.
"""

import json
import re
import threading
import time
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

import auth as _auth
import catalog as _catalog
import db as _db
import users_db as _udb

router = APIRouter()

VIEWER_V = "20261006a"      # bump with paper-viewer.js / yearly.css / pdf-pane.js
SESSION_NAMES = {"m": "Feb/March", "s": "May/June", "w": "Oct/Nov"}
SESSION_SHORT = {"m": "F/M", "s": "M/J", "w": "O/N"}
SESSION_ORDER = {"m": 0, "s": 1, "w": 2}                # calendar order in a year
KINDS = {"qp": "Question paper", "ms": "Mark scheme", "in": "Insert"}

_e = _catalog._e
SUBJECTS = _catalog.SUBJECTS
BOARD_SHORT = _catalog.BOARD_SHORT


def yearly_url(code: str, year: int | None = None) -> str:
    s = SUBJECTS[code]
    return f"/yearly/{s['board_slug']}/{s['slug']}" + (f"/{year}" if year else "")


def mcq_url(code: str) -> str:
    s = SUBJECTS[code]
    return f"/mcq/{s['board_slug']}/{s['slug']}"


def is_mcq(code: str, paper: int, year: int | None = None) -> bool:
    from pipeline import config as _pcfg
    return _pcfg.is_mcq(code, paper, year)


def mcq_codes() -> list[str]:
    from pipeline import config as _pcfg
    return [c for c in SUBJECTS if any(s == c for s, _p in _pcfg.MCQ_PAPERS)]


# ── Data ──────────────────────────────────────────────────────────────────────

def sittings(code: str, year: int | None = None) -> list[dict]:
    """One entry per sitting (year, session, paper, variant) with its files,
    newest year first, sessions in calendar order, then paper/variant."""
    con = _db.plain_connect()
    try:
        rows = con.execute(
            "SELECT id, year, session, paper, variant, kind, filename FROM papers "
            "WHERE syllabus = ?" + (" AND year = ?" if year else ""),
            [code, year] if year else [code]).fetchall()
    finally:
        con.close()
    out: dict[tuple, dict] = {}
    for r in rows:
        key = (r["year"], r["session"], r["paper"], r["variant"] or "")
        e = out.setdefault(key, {"year": r["year"], "session": r["session"],
                                 "paper": r["paper"], "variant": r["variant"] or "",
                                 "code": f"{r['paper']}{r['variant'] or ''}", "files": {}})
        e["files"][r["kind"]] = {"id": r["id"], "filename": r["filename"]}
    return sorted(out.values(), key=lambda e: (-e["year"], SESSION_ORDER.get(e["session"], 9),
                                              e["paper"], e["variant"]))


_YEARS_CACHE: dict = {"at": 0.0, "data": {}}
_YEARS_TTL_S = 600
_YEARS_LOCK = threading.Lock()


def _all_years() -> dict[str, list[tuple[int, int, int]]]:
    """{syllabus: [(year, paper, question papers)]} for the whole archive,
    in ONE query, cached for 10 min. Every picker, subject tab row and hub asks
    for this per subject; one query each made /yearly take 14 s on production."""
    if time.time() - _YEARS_CACHE["at"] < _YEARS_TTL_S:
        return _YEARS_CACHE["data"]
    with _YEARS_LOCK:
        if time.time() - _YEARS_CACHE["at"] < _YEARS_TTL_S:
            return _YEARS_CACHE["data"]
        con = _db.plain_connect()
        try:
            rows = con.execute(
                "SELECT syllabus, year, paper, COUNT(*) AS n FROM papers WHERE kind = 'qp' "
                "GROUP BY syllabus, year, paper").fetchall()
        finally:
            con.close()
        data: dict[str, list[tuple[int, int, int]]] = {}
        for r in rows:
            data.setdefault(r["syllabus"], []).append((int(r["year"]), int(r["paper"]), int(r["n"])))
        _YEARS_CACHE.update(at=time.time(), data=data)
        return data


def subject_years(code: str) -> list[tuple[int, int]]:
    """[(year, question papers)] newest first."""
    per: dict[int, int] = {}
    for y, _p, n in _all_years().get(code, []):
        per[y] = per.get(y, 0) + n
    return sorted(per.items(), reverse=True)


def mcq_years(code: str) -> list[tuple[int, int]]:
    """[(year, multiple-choice question papers)] newest first."""
    per: dict[int, int] = {}
    for y, p, n in _all_years().get(code, []):
        if is_mcq(code, p, y):
            per[y] = per.get(y, 0) + n
    return sorted(per.items(), reverse=True)


def _paper_row(paper_id: int) -> dict | None:
    con = _db.plain_connect()
    try:
        r = con.execute("SELECT id, syllabus, year, session, paper, variant, kind, filename "
                        "FROM papers WHERE id = ?", [paper_id]).fetchone()
        return dict(r) if r else None
    finally:
        con.close()


def _sitting_files(p: dict) -> dict:
    con = _db.plain_connect()
    try:
        rows = con.execute(
            "SELECT id, kind, filename, page_count FROM papers WHERE syllabus = ? AND year = ? "
            "AND session = ? AND paper = ? AND variant = ?",
            [p["syllabus"], p["year"], p["session"], p["paper"], p["variant"] or ""]).fetchall()
    finally:
        con.close()
    return {r["kind"]: {"id": r["id"], "filename": r["filename"],
                        "url": f"/api/library/pdf/{r['id']}"} for r in rows}


def source_ref(p: dict, number: int, sub: str = "") -> str:
    return (f"{p['syllabus']}/{p['paper']}{p['variant'] or ''}/"
            f"{SESSION_SHORT.get(p['session'], p['session'])}/{p['year'] % 100:02d} "
            f"Q{number}{f'({sub})' if sub else ''}")


def page_map(p: dict, qp_id: int | None, ms_id: int | None) -> tuple[list, dict, int]:
    """Chips for the question paper ([{seq, qid, label, ref, topic, page, y}]),
    where each question's mark scheme starts ({"3|b": {page, y}}), and the
    paper's total marks (for the marks box)."""
    questions, ms_at, total = [], {}, 0
    con = _db.plain_connect()
    try:
        if qp_id:
            rows = con.execute(
                """SELECT q.id, q.number, q.sub_part, q.rects_json, q.marks, c.topic
                   FROM questions q LEFT JOIN classifications c ON c.question_id = q.id
                   WHERE q.paper_id = ? AND q.status IS NOT 'excluded'
                   ORDER BY q.number, q.sub_part""", [qp_id]).fetchall()
            for r in rows:
                try:
                    first = json.loads(r["rects_json"] or "[]")[0]
                except (ValueError, IndexError):
                    continue
                total += r["marks"] or 0
                sub = r["sub_part"] or ""
                questions.append({
                    "seq": len(questions) + 1, "qid": r["id"],
                    "label": f"Q{r['number']}{f'({sub})' if sub else ''}",
                    "number": r["number"], "sub": sub,
                    "ref": source_ref(p, r["number"], sub), "topic": r["topic"] or "",
                    "page": int(first["page"]) + 1, "y": round(float(first["y0"]), 1)})
        if ms_id:
            for r in con.execute("SELECT question_number, sub_part, rects_json FROM ms_entries "
                                 "WHERE paper_id = ?", [ms_id]).fetchall():
                try:
                    first = json.loads(r["rects_json"] or "[]")[0]
                except (ValueError, IndexError):
                    continue
                ms_at[f"{r['question_number']}|{r['sub_part'] or ''}"] = {
                    "page": int(first["page"]) + 1, "y": round(float(first["y0"]), 1)}
    finally:
        con.close()
    return questions, ms_at, total


def _staff(user: dict | None) -> bool:
    return bool(user) and user.get("role") in ("teacher", "admin")


# ── Shared bits ───────────────────────────────────────────────────────────────

def _subject_or_404(board: str, subject: str) -> dict:
    s = _catalog.find_subject(board, subject)
    if s is None:
        raise HTTPException(404, "Unknown subject")
    return s


def _sitting_title(code: str, e: dict) -> str:
    v = f" variant {e['variant']}" if e["variant"] else ""
    return (f"{SUBJECTS[code]['plain']} {code}/{e['code']} · "
            f"{SESSION_NAMES.get(e['session'], e['session'])} {e['year']} · Paper {e['paper']}{v}")


def _sitting_rows(code: str, items: list[dict]) -> str:
    rows = []
    for e in items:
        files = e["files"]
        main = files.get("qp") or files.get("ms") or files.get("in")
        if not main:
            continue
        mcq = is_mcq(code, e["paper"], e["year"])
        # Fixed slots (QP · MS · Practise · Insert) so the buttons line up down a
        # column; an absent file leaves its slot empty rather than shifting the rest,
        # and inserts come last because most papers have none.
        empty = '<span class="yr-file yr-none" aria-hidden="true"></span>'

        def doc(k, lab, title):
            return (f'<a class="yr-file yr-{k}" href="/yearly/view/{main["id"]}?doc={k}" '
                    f'title="{title}">{lab}</a>') if k in files else empty
        slots = [doc("qp", "QP", "Question paper"), doc("ms", "MS", "Mark scheme"),
                 (f'<a class="yr-file yr-practise" href="{mcq_url(code)}?paper={files["qp"]["id"]}#start" '
                  f'title="Practise it in the MCQ solver" aria-label="Practise this paper">▶</a>'
                  if mcq and "qp" in files else empty),
                 doc("in", "IN", "Insert")]
        rows.append(f"""
          <li class="yr-row" data-key="{e['year']}|{e['session']}|{e['paper']}|{_e(e['variant'])}">
            <a class="yr-main" href="/yearly/view/{main['id']}">
              <span class="yr-name"><b>Paper {e['code']}</b>{'<em class="yr-mcq">MCQ</em>' if mcq else ''}</span>
              <span class="yr-code">{code}/{e['code']} · {SESSION_SHORT.get(e['session'], '')} {e['year']}</span>
            </a>
            <span class="yr-files">{''.join(slots)}</span>
            <span class="yr-done" aria-hidden="true"></span>
          </li>""")
    return "".join(rows)


def _tile(code: str, e: dict) -> str:
    """One sitting as a compact tile: variant code, then QP / MS / Insert links and,
    for a multiple-choice paper, a Practise button that opens the MCQ solver."""
    files = e["files"]
    main = files.get("qp") or files.get("ms") or files.get("in")
    if not main:
        return ""
    mcq = is_mcq(code, e["paper"], e["year"])
    links = [f'<a class="yr-f yr-f-{k}" href="/yearly/view/{main["id"]}?doc={k}" title="{KINDS[k]}">{lab}</a>'
             for k, lab in (("qp", "QP"), ("ms", "MS"), ("in", "Insert")) if k in files]
    if mcq and "qp" in files:
        links.append(f'<a class="yr-f yr-f-go" href="{mcq_url(code)}?paper={files["qp"]["id"]}#start" '
                     f'title="Practise in the MCQ solver" aria-label="Practise {code}/{e["code"]} as MCQ">▶ Practise</a>')
    sess = SESSION_SHORT.get(e["session"], e["session"])
    return f"""
          <div class="yr-tile" data-key="{e['year']}|{e['session']}|{e['paper']}|{_e(e['variant'])}"
               data-find="{code}/{e['code']} {e['code']} {sess} {SESSION_NAMES.get(e['session'], '')} {e['year']} p{e['paper']}">
            <a class="yr-tile-main" href="/yearly/view/{main['id']}" title="{_e(_sitting_title(code, e))}">
              <b>{e['code']}</b><span>{code}/{e['code']} · {sess} {e['year']}</span>
            </a>
            <div class="yr-tile-files">{''.join(links)}</div>
            <span class="yr-done" aria-hidden="true"></span>
          </div>"""


def _year_block(code: str, year: int, items: list[dict], open_: bool) -> str:
    """A year as a grid: one row per paper component, one column per session."""
    sessions = sorted({e["session"] for e in items}, key=lambda x: SESSION_ORDER.get(x, 9))
    papers = sorted({e["paper"] for e in items})
    cell: dict[tuple, list] = {}
    for e in items:
        cell.setdefault((e["paper"], e["session"]), []).append(e)
    head = "".join(f'<div class="yr-mh" data-sess="{x}">{SESSION_NAMES.get(x, x)}</div>' for x in sessions)
    rows = []
    for pno in papers:
        c = _catalog.component(code, pno, year)
        lvl = f'<i class="yr-level yr-level-{c["level"]}">{c["level"]}</i>' if c["level"] else ""
        cells = "".join(
            f'<div class="yr-cell" data-sess="{x}" data-label="{SESSION_NAMES.get(x, x)}">'
            + ("".join(_tile(code, e) for e in cell.get((pno, x), []))
               or '<span class="yr-nil" aria-label="No paper">—</span>')
            + "</div>" for x in sessions)
        rows.append(f'<div class="yr-mrow" data-comp="{pno}"><div class="yr-comp">'
                    f'<b>Paper {pno}</b><span>{_e(c["title"])}</span>{lvl}</div>{cells}</div>')
    n = sum(1 for e in items if e["files"])
    return f"""
    <details class="yr-year" id="y{year}"{' open' if open_ else ''}>
      <summary><h2>{year}</h2><span class="yr-year-n">{n} papers</span>
        <span class="yr-year-done" hidden></span>
        <a class="yr-yearlink" href="{yearly_url(code, year)}">Only {year} →</a></summary>
      <div class="yr-matrix" style="--sessions:{len(sessions)}">
        <div class="yr-mhead"><div class="yr-mh yr-mh-comp">Paper</div>{head}</div>
        {''.join(rows)}
      </div>
    </details>"""


def _tiles(board: str, kind: str, state: dict) -> list[str]:
    """Picker tiles (ui.tile) for one board: every subject with papers by year,
    or with multiple-choice papers (kind="mcq")."""
    import ui
    out = []
    for c in ui.codes_for(board, state):
        if kind == "mcq" and c not in mcq_codes():
            continue
        yrs = mcq_years(c) if kind == "mcq" else subject_years(c)
        if not yrs:
            continue
        n = sum(n for _y, n in yrs)
        url = yearly_url(c) if kind == "yearly" else mcq_url(c)
        mine = c in state["enrolled"]
        if kind == "yearly":
            actions = [("Open papers", url, "primary"), ("Latest year", yearly_url(c, yrs[0][0]), "ghost")]
            stats = [(f"{n:,}", "papers"), (str(len(yrs)), "years")]
        else:
            actions = [("Practise MCQs", url, "primary"), ("Papers by year", yearly_url(c), "ghost")]
            stats = [(f"{n:,}", "MCQ papers"), (str(len(yrs)), "years")]
        out.append(ui.tile(code=c, url=url, stats=stats, actions=actions, flag="on" if mine else "",
                           years=f"{yrs[-1][0]}–{yrs[0][0]}"))
    return out


def _picker(kind: str, state: dict, board: str | None = None) -> str:
    import ui
    boards = [board] if board else ui.board_order(state)
    base = "/yearly/{board}" if kind == "yearly" else None
    return ui.picker({b: _tiles(b, kind, state) for b in boards}, state=state,
                     board_links=base if board else None, active=board or "")


def _page(*, title, desc, path, body, crumbs, user, noindex=False, ld=None, scripts=()):
    state = _catalog._student_state(user)
    html = _catalog._shell(title=title, desc=desc, path=path, body=body, crumbs=crumbs,
                           state=state, noindex=noindex, ld=ld, scripts=scripts)
    html = html.replace("</head>", f'  <link rel="stylesheet" href="/yearly.css?v={VIEWER_V}">\n</head>', 1)
    return _catalog._respond(html, bool(user))


# ── Yearly pages ──────────────────────────────────────────────────────────────

def _how_codes() -> str:
    """How to read a Cambridge paper code - the thing every new student asks."""
    import ui
    return ui.steps([
        ("Session", "<b>M/J</b> = May/June, <b>O/N</b> = Oct/Nov, <b>F/M</b> = Feb/March (sat in Pakistan and India)."),
        ("Paper and variant", "<b>22</b> = Paper 2, variant 2. Variants are different papers of the same "
                              "difficulty, sat in different time zones - all are worth doing."),
        ("QP, MS, Insert", "Question paper, its mark scheme, and the insert (source booklet) if the paper had one."),
    ], "Reading a paper code", "ui-steps-row")


def _mcq_how() -> str:
    import ui
    return ui.steps([
        ("Choose a subject", "Above - every subject with a multiple-choice paper."),
        ("Full paper or topics", "Sit a real paper against the official time, or a set from chosen chapters."),
        ("Check as you go, or at the end", "Live check reveals each answer as you lock it in."),
        ("Review", "Every wrong option explained, so the same trap does not get you twice."),
    ], "How MCQ practice works", "ui-steps-row")

@router.get("/yearly", response_class=HTMLResponse)
def yearly_hub(user: dict | None = Depends(_auth.maybe_user)):
    state = _catalog._student_state(user)
    body = f"""
    <header class="cat-hero cat-hero-sm">
      <p class="cat-eyebrow">Yearly past papers</p>
      <h1>Cambridge past papers by year</h1>
      <p class="cat-lede">Every question paper, mark scheme and insert we hold, sitting by
        sitting. Open one to read the paper with its mark scheme side by side, and ask for a
        worked explanation of any question. <b>No account needed.</b></p>
    </header>
    {_picker("yearly", state)}
    {_how_codes()}"""
    return _page(title="Cambridge Past Papers by Year | O Level, IGCSE & A Level — PrepWithTee",
                 desc="Cambridge O Level, IGCSE and A Level past papers by year and session, "
                      "with mark schemes and inserts.",
                 path="/yearly", body=body, user=user,
                 crumbs=[("Home", "/"), ("Past papers", "/papers"), ("By year", "/yearly")])


_KEY_RE = re.compile(r"^(\d{4})_([msw])(\d{2})_(?:qp_|ms_)?(\d)(\d?)$")


def find_paper(syllabus: str, year: int, session: str, paper: int, variant: str = "") -> int | None:
    """The question paper's id for one sitting (falls back to its mark scheme)."""
    con = _db.plain_connect()
    try:
        rows = con.execute(
            "SELECT id, kind FROM papers WHERE syllabus = ? AND year = ? AND session = ? "
            "AND paper = ? AND COALESCE(variant, '') = ?",
            [syllabus, year, session, paper, variant or ""]).fetchall()
    finally:
        con.close()
    by_kind = {r["kind"]: r["id"] for r in rows}
    return by_kind.get("qp") or by_kind.get("ms")


@router.get("/yearly/open", include_in_schema=False)
def yearly_open(syllabus: str = "", year: int = 0, session: str = "", paper: int = 0,
                variant: str = "", key: str = ""):
    """Resolve a sitting (fields, or a paper key like 5054_s23_22) to its viewer.
    Used by the progress pages and by old /papers.html deep links."""
    m = _KEY_RE.match(key.strip())
    if m:
        syllabus, session = m.group(1), m.group(2)
        year, paper, variant = 2000 + int(m.group(3)), int(m.group(4)), m.group(5)
    if syllabus not in SUBJECTS:
        return RedirectResponse("/yearly", 302)
    pid = find_paper(syllabus, year, session, paper, variant) if year and paper else None
    return RedirectResponse(f"/yearly/view/{pid}" if pid else yearly_url(syllabus, year or None), 302)


@router.get("/yearly/view/{paper_id}", response_class=HTMLResponse)
def yearly_viewer(paper_id: int, doc: str = "qp", user: dict | None = Depends(_auth.maybe_user)):
    p = _paper_row(paper_id)
    if p is None or p["syllabus"] not in SUBJECTS:
        raise HTTPException(404, "Paper not found")
    code = p["syllabus"]
    s = SUBJECTS[code]
    files = _sitting_files(p)
    qp, ms = files.get("qp"), files.get("ms")
    questions, ms_at, total = page_map(p, qp and qp["id"], ms and ms["id"])
    e = {"year": p["year"], "session": p["session"], "paper": p["paper"],
         "variant": p["variant"] or "", "code": f"{p['paper']}{p['variant'] or ''}"}
    title = _sitting_title(code, e)
    import ui as _ui
    _dock = _ui.tools_dock(code)
    state = {"title": title, "short": f"{code}/{e['code']} {SESSION_SHORT.get(p['session'], '')} {p['year']}",
             "syllabus": code, "year": p["year"], "session": p["session"], "paper": p["paper"],
             "variant": e["variant"], "sessionName": SESSION_NAMES.get(p["session"], p["session"]),
             "files": files, "doc": doc if doc in files else next(iter(files), "qp"),
             "questions": questions, "msAt": ms_at, "totalMarks": total,
             "mcq": is_mcq(code, p["paper"], p["year"]), "backUrl": yearly_url(code, p["year"]),
             "subjectName": s["plain"], "labels": KINDS, "signedIn": bool(user),
             "loginUrl": f"/login.html?next=/yearly/view/{paper_id}"}
    import blog as _blog
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="robots" content="noindex">
  <script>try{{var t=localStorage.getItem("theme")||"light";document.documentElement.setAttribute("data-theme",t);var p=localStorage.getItem("pwt-paper");if(p)document.documentElement.setAttribute("data-paper",p)}}catch(e){{}}</script>
  <title>{_e(title)} — PrepWithTee</title>
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700;800&family=Hanken+Grotesk:wght@400;500;600;700&family=Playfair+Display:wght@700;800&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/styles.css?v={_catalog.STYLES_V}">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf_viewer.min.css">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.css">
  <link rel="stylesheet" href="/viewer.css?v={VIEWER_V}">
  <link rel="stylesheet" href="/ai-panel.css?v={VIEWER_V}">
  <link rel="stylesheet" href="/annotate.css?v={VIEWER_V}">
  <link rel="stylesheet" href="/yearly.css?v={VIEWER_V}">
</head>
<body class="vw-page"{_dock[0]}>
{_blog._nav()}
<main id="vw" class="vw" data-state="loading">
  <section class="vw-load"><div class="vw-load-card"><p class="vw-eyebrow">Opening</p>
    <h1>{_e(title)}</h1></div></section>
</main>
<script id="vw-state" type="application/json">{json.dumps(state)}</script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.1.6/purify.min.js"></script>
<script src="/main.js?v=20261005a"></script>
<script type="module" src="/auth.js?v=20261005c"></script>
<script type="module" src="/paper-viewer.js?v={VIEWER_V}"></script>
{_dock[1]}
</body>
</html>""", headers={"Cache-Control": "private, no-store" if user else "public, max-age=300"})


@router.get("/yearly/{board}", response_class=HTMLResponse)
def yearly_board(board: str, user: dict | None = Depends(_auth.maybe_user)):
    if board not in BOARD_SHORT:
        raise HTTPException(404, "Unknown board")
    state = _catalog._student_state(user)
    body = f"""
    <header class="cat-hero cat-hero-sm">
      <p class="cat-eyebrow">Cambridge {BOARD_SHORT[board]}</p>
      <h1>{BOARD_SHORT[board]} past papers by year</h1>
      <p class="cat-lede">Question papers, mark schemes and inserts for every Cambridge
        {BOARD_SHORT[board]} subject we cover, sitting by sitting.</p>
    </header>
    {_picker("yearly", state, board)}"""
    return _page(title=f"Cambridge {BOARD_SHORT[board]} Past Papers by Year — PrepWithTee",
                 desc=f"Cambridge {BOARD_SHORT[board]} past papers by year, with mark schemes.",
                 path=f"/yearly/{board}", body=body, user=user,
                 crumbs=[("Home", "/"), ("Past papers", "/papers"), ("By year", "/yearly"),
                         (BOARD_SHORT[board], f"/yearly/{board}")])


def _subject_page(board: str, subject: str, year: int | None, user: dict | None):
    s = _subject_or_404(board, subject)
    code = s["code"]
    items = sittings(code, year)
    if not items:
        raise HTTPException(404, "No papers for that year" if year else "No papers yet")
    years = subject_years(code)
    by_year: dict[int, list] = {}
    for e in items:
        by_year.setdefault(e["year"], []).append(e)
    blocks = "".join(_year_block(code, y, by_year[y], open_=(year is not None or i < 3))
                     for i, y in enumerate(sorted(by_year, reverse=True)))
    base = yearly_url(code)
    span = f"{years[-1][0]}–{years[0][0]}" if years else ""
    nqp = sum(n for _y, n in years)
    if year:
        ys = [y for y, _n in years]
        i = ys.index(year) if year in ys else -1
        newer = ys[i - 1] if i > 0 else None
        older = ys[i + 1] if 0 <= i < len(ys) - 1 else None
        jump = (f'<nav class="yr-pn">'
                + (f'<a href="{yearly_url(code, older)}">← {older}</a>' if older else "<span></span>")
                + f'<a href="{base}">All years</a>'
                + (f'<a href="{yearly_url(code, newer)}">{newer} →</a>' if newer else "<span></span>")
                + "</nav>")
        h1 = f"{s['plain']} {code} past papers {year}"
        lede = (f"Every Cambridge {BOARD_SHORT[board]} {s['plain']} ({code}) paper from {year}: "
                f"{len(items)} sittings across "
                f"{', '.join(SESSION_NAMES[x] for x in sorted({e['session'] for e in items}, key=SESSION_ORDER.get))}"
                f", each with its mark scheme.")
    else:
        jump = ('<nav class="yr-jump" aria-label="Jump to a year">'
                + "".join(f'<a href="#y{y}">{y}</a>' for y, _n in years) + "</nav>")
        h1 = f"{s['plain']} {code} past papers"
        lede = (f"{nqp:,} Cambridge {BOARD_SHORT[board]} {s['plain']} ({code}) question papers"
                f"{f' from {span}' if span else ''}, with mark schemes and inserts - "
                f"May/June, Oct/Nov and Feb/March, every variant.")
    first = next((e for e in items if "qp" in e["files"]), None)
    actions = ([f'<a class="cat-btn" href="/yearly/view/{first["files"]["qp"]["id"]}">Open the latest paper</a>']
               if first else [])
    if user:
        actions.append(f'<a class="cat-btn cat-btn-ghost" href="/yearly-progress.html?syllabus={code}">My progress</a>')
    import ui
    enrol = ""
    if not user:
        enrol = ui.callout(
            f'Every paper opens straight away - no account needed. <a href="/login.html?signup=1&amp;next={base}">'
            f'A free account</a> also saves your pen marks, ticks off the papers you have done and records '
            f'your marks against the grade thresholds.', tone="blue", icon_name="user")
    comps = sorted({e["paper"] for e in items})
    sessions = sorted({e["session"] for e in items}, key=lambda x: SESSION_ORDER.get(x, 9))
    comp_chips = "".join(
        f'<button type="button" class="yr-chip" data-comp="{pno}" aria-pressed="false" title="{_e(c["title"])}">'
        f'P{pno} <span>{_e(c["short"])}</span>'
        + (f'<i class="yr-level yr-level-{c["level"]}">{c["level"]}</i>' if c["level"] else "") + "</button>"
        for pno in comps for c in [_catalog.component(code, pno)]) if len(comps) > 1 else ""
    sess_chips = "".join(
        f'<button type="button" class="yr-chip" data-sess="{x}" aria-pressed="false">{SESSION_NAMES.get(x, x)}</button>'
        for x in sessions) if len(sessions) > 1 else ""
    rail = "" if year else (
        '<nav class="yr-rail" aria-label="Years"><p>Years</p>'
        + "".join(f'<a href="#y{y}"><b>{y}</b><span data-rail="{y}">{n}</span></a>' for y, n in years)
        + "</nav>")
    stats = (f'<dl class="cat-stats"><div><dt>Question papers</dt><dd>{(len(items) if year else nqp):,}</dd></div>'
             f'<div><dt>{"Year" if year else "Years"}</dt><dd>{year or span}</dd></div>'
             f'<div><dt>Sessions</dt><dd>{len(sessions)}</dd></div></dl>')
    body = f"""
    {ui.subject_tabs(code, "yearly")}
    <header class="cat-hero cat-hero-sm cat-tone-{s['tone']}">
      <p class="cat-eyebrow">Cambridge {BOARD_SHORT[board]} · {code} · Yearly</p>
      <h1>{_e(h1)}</h1>
      <p class="cat-lede">{_e(lede)}</p>
      {stats}
      <div class="cat-actions">{''.join(actions)}</div>
    </header>
    {enrol}
    {jump if year else ''}
    <div class="yr-bar" role="toolbar" aria-label="Filter papers">
      {f'<div class="yr-chips" data-group="comp"><button type="button" class="yr-chip" data-comp="" aria-pressed="true">All papers</button>{comp_chips}</div>' if comp_chips else ''}
      <div class="yr-bar-end">
      {f'<div class="yr-chips" data-group="sess"><button type="button" class="yr-chip" data-sess="" aria-pressed="true">All sessions</button>{sess_chips}</div>' if sess_chips else ''}
      <label class="yr-filter"><span class="sr-only">Search papers</span>
        <svg viewBox="0 0 20 20" width="15" height="15" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M13 13l4 4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
        <input type="search" placeholder="Search: 42, M/J, 2019…" data-yr-filter autocomplete="off"></label>
      </div>
    </div>
    <div class="yr-layout{' has-rail' if rail else ''}">
      {rail}
      <div class="yr-years" data-syllabus="{code}">{blocks}</div>
    </div>
    <p class="yr-none-found" hidden>No papers match those filters.</p>"""
    crumbs = [("Home", "/"), ("Past papers", "/papers"), ("By year", "/yearly"),
              (BOARD_SHORT[board], f"/yearly/{board}"), (f"{s['plain']} {code}", base)]
    body += ui.steps([
        ("Sit it timed", "Open the question paper, set a timer for the official time, and answer on paper."),
        ("Mark it honestly", "Switch on <b>Side by side</b>: the mark scheme follows the question you are on."),
        ("Log your score", "Add your marks - we compare them with that sitting's grade thresholds."),
        ("Go back to topics", 'Any chapter you lost marks on: build a <a href="' + _catalog.subject_url(code)
         + '">topical paper</a> on it.'),
    ], "How to use a past paper", "ui-steps-row ui-steps-after")
    if year:
        crumbs.append((str(year), yearly_url(code, year)))
    return _page(
        title=(f"{s['plain']} {code} Past Papers {year} | Cambridge {BOARD_SHORT[board]} — PrepWithTee"
               if year else
               f"{s['plain']} {code} Past Papers by Year | Cambridge {BOARD_SHORT[board]} — PrepWithTee"),
        desc=lede[:300], path=yearly_url(code, year), body=body, user=user, crumbs=crumbs,
        scripts=(f"/yearly.js?v={VIEWER_V}",))


@router.get("/yearly/{board}/{subject}", response_class=HTMLResponse)
def yearly_subject(board: str, subject: str, user: dict | None = Depends(_auth.maybe_user)):
    return _subject_page(board, subject, None, user)


@router.get("/yearly/{board}/{subject}/{year}", response_class=HTMLResponse)
def yearly_year(board: str, subject: str, year: int, user: dict | None = Depends(_auth.maybe_user)):
    return _subject_page(board, subject, year, user)


# ── MCQ pages ─────────────────────────────────────────────────────────────────

@router.get("/mcq", response_class=HTMLResponse)
def mcq_hub(user: dict | None = Depends(_auth.maybe_user)):
    state = _catalog._student_state(user)
    body = f"""
    <header class="cat-hero cat-hero-sm">
      <p class="cat-eyebrow">MCQ practice</p>
      <h1>Cambridge multiple-choice practice</h1>
      <p class="cat-lede">Real Cambridge multiple-choice questions, one at a time or as a
        full timed paper, marked instantly against the official answer key - with an
        explanation of why each wrong option is wrong.</p>
    </header>
    {_picker("mcq", state)}
    {_mcq_how()}"""
    return _page(title="Cambridge MCQ Past Paper Practice | O Level, IGCSE & A Level — PrepWithTee",
                 desc="Practise Cambridge multiple-choice past-paper questions, marked instantly "
                      "against the official answer keys.",
                 path="/mcq", body=body, user=user,
                 crumbs=[("Home", "/"), ("Past papers", "/papers"), ("MCQ practice", "/mcq")])


@router.get("/mcq/{board}/{subject}", response_class=HTMLResponse)
def mcq_subject(board: str, subject: str, user: dict | None = Depends(_auth.maybe_user)):
    s = _subject_or_404(board, subject)
    code = s["code"]
    if code not in mcq_codes():
        raise HTTPException(404, "No multiple-choice papers for this subject")
    papers = [e for e in sittings(code) if is_mcq(code, e["paper"], e["year"]) and "qp" in e["files"]]
    if not papers:
        raise HTTPException(404, "No multiple-choice papers yet")
    span = f"{papers[-1]['year']}–{papers[0]['year']}"
    state = _catalog._student_state(user)
    can = bool(user) and (code in state["enrolled"] or _staff(user))
    if can:
        start = (f'<a class="cat-btn" href="#start">⚡ Start practice</a>'
                 f'<a class="cat-btn cat-btn-ghost" href="{yearly_url(code)}">Full papers by year</a>')
    elif user:
        start = f'<button class="cat-btn cat-btn-gold" type="button" data-enrol="{code}">🔒 Enrol free to practise</button>'
    else:
        start = (f'<a class="cat-btn cat-btn-gold" href="/login.html?signup=1&amp;next={mcq_url(code)}">'
                 f'Create a free account to practise</a>')
    recent = _sitting_rows(code, papers[:12])
    lede = (f"{len(papers):,} Cambridge {BOARD_SHORT[board]} {s['plain']} ({code}) multiple-choice "
            f"papers from {span}. Practise question by question or sit a whole paper against the "
            f"clock, with every answer checked against the official key.")
    import ui
    body = f"""
    {ui.subject_tabs(code, "mcq")}
    <header class="cat-hero cat-hero-sm cat-tone-{s['tone']}">
      <p class="cat-eyebrow">Cambridge {BOARD_SHORT[board]} · {code} · MCQ</p>
      <h1>{_e(s['plain'])} {code} MCQ practice</h1>
      <p class="cat-lede">{_e(lede)}</p>
      <div class="cat-actions">{start}</div>
    </header>
    {f'<section class="mqs" id="start"><h2 class="cat-group">Start practice</h2><div id="mq-setup" data-syllabus="{code}"><noscript>Turn on JavaScript to practise.</noscript></div></section>' if can else ''}
    <ul class="yr-feats">
      <li><b>Instant marking</b><span>Every answer checked against the official Cambridge key.</span></li>
      <li><b>Why, not just what</b><span>Each option explained, including the tempting wrong ones.</span></li>
      <li><b>Timed or relaxed</b><span>Race the clock or take a full paper at exam pace.</span></li>
    </ul>
    <h2 class="cat-group">Latest multiple-choice papers</h2>
    <ul class="yr-list yr-list-flat">{recent}</ul>
    <p class="cat-note"><a href="{yearly_url(code)}">All {_e(s['plain'])} papers by year →</a></p>"""
    return _page(title=f"{s['plain']} {code} MCQ Practice | Cambridge {BOARD_SHORT[board]} — PrepWithTee",
                 desc=lede[:300], path=mcq_url(code), body=body, user=user,
                 scripts=(f"/yearly.js?v={VIEWER_V}",) + ((f"/mcq-setup.js?v={VIEWER_V}",) if can else ()),
                 crumbs=[("Home", "/"), ("Past papers", "/papers"), ("MCQ practice", "/mcq"),
                         (f"{s['plain']} {code}", mcq_url(code))])


# ── Old URLs ──────────────────────────────────────────────────────────────────

def legacy_target(tab: str, syllabus: str) -> str | None:
    """Where an old /papers.html?tab=... link now lives (None = not a moved tab)."""
    if tab == "yearly":
        return yearly_url(syllabus) if syllabus in SUBJECTS else "/yearly"
    if tab == "mcq":
        return mcq_url(syllabus) if syllabus in mcq_codes() else "/mcq"
    return None


@router.get("/library.html", include_in_schema=False)
def legacy_library(syllabus: str = ""):
    return RedirectResponse(legacy_target("yearly", syllabus), 301)


def sitemap_paths() -> list[str]:
    paths = ["/yearly"] + [f"/yearly/{b}" for b in BOARD_SHORT] + ["/mcq"]
    for code in SUBJECTS:
        years = subject_years(code)
        if not years:
            continue
        paths.append(yearly_url(code))
        paths += [yearly_url(code, y) for y, _n in years]
        if code in mcq_codes():
            paths.append(mcq_url(code))
    return paths
