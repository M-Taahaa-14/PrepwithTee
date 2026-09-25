"""Boards, the subject catalogue, and the SEO pages built on them.

    /papers                                   board picker (logged-in -> their board)
    /papers/{board}                           subjects: yours first, the rest locked
    /papers/{board}/{subject}                 one subject: chapters + subtopics
    /papers/{board}/{subject}/{chapter}       one chapter

These are server-rendered so search engines read real text without running
JavaScript. Logged-out visitors (and Google) get description text and the
syllabus chapter names only - no question images (tutor's decision,
2026-09-24). A logged-in student sees the same page personalised: enrolled
subjects first, the rest behind a free one-click enrol.

    GET  /api/boards            every board with its subjects
    GET  /api/me/boards         the student's boards
    PUT  /api/me/boards         set them (multiple allowed)
    GET  /api/catalogue?board=  subjects for a board, with enrolled/locked flags

Question counts come from app.py's /api/meta cache, handed in through
set_meta_provider() so this module never imports app.py (which runs as
website.app and would be executed twice).
"""

import html as _html
import json
import os
import re
from pathlib import Path
from urllib.parse import quote, urlencode
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

import auth as _auth
import users_db as _udb

router = APIRouter()

SITE_ORIGIN = os.environ.get("SITE_ORIGIN", "https://prepwithtee.com").rstrip("/")
CSS_V = "20260927f"       # bump with catalog.css / catalog.js (immutable caching)
STYLES_V = "20260927f"    # the site-wide styles.css pin

# ── Registry ──────────────────────────────────────────────────────────────────
# Board and display name per syllabus. The single source of truth: app.py's
# library, meta and generator all read this list.
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

BOARD_SLUGS = {"Cambridge O Level": "o-level", "Cambridge IGCSE": "igcse",
               "Cambridge A Level": "a-level"}
BOARD_SHORT = {"o-level": "O Level", "igcse": "IGCSE", "a-level": "A Level"}
BOARD_BLURB = {
    "o-level": "Topical past papers for every Cambridge O Level subject we cover, "
               "sorted chapter by chapter with the official mark schemes.",
    "igcse": "Cambridge IGCSE topical past papers - every question sorted by "
             "syllabus chapter and subtopic, with official mark schemes.",
    "a-level": "Cambridge International AS & A Level topical past papers, split by "
               "component and chapter, with official mark schemes.",
}
# Paper components per syllabus: (short label, full title, level). The short label
# is what chips and filters show ("P3 · Pure 3"); the title heads a builder
# section; level is "AS"/"A2" for A Level components, "" otherwise. app.py's
# PAPER_LABELS and the yearly/builder pages all derive from this one table.
COMPONENTS: dict[str, dict[int, tuple[str, str, str]]] = {
    "9709": {1: ("Pure 1", "Pure Mathematics 1", "AS"),
             3: ("Pure 3", "Pure Mathematics 3", "A2"),
             4: ("Mechanics", "Mechanics", "AS"),
             5: ("Statistics", "Probability & Statistics 1", "AS")},
    "9702": {1: ("MCQ", "Multiple choice", "AS"),
             2: ("AS Structured", "AS structured questions", "AS"),
             4: ("A Level", "A Level structured questions", "A2"),
             5: ("Planning", "Planning, analysis & evaluation", "A2")},
    "9618": {1: ("Theory", "Theory fundamentals", "AS"),
             2: ("Problem-solving", "Problem-solving & programming", "AS"),
             3: ("Advanced Theory", "Advanced theory", "A2"),
             4: ("Practical", "Practical programming", "A2")},
    "0580": {2: ("Extended", "Extended · short answer", ""),
             4: ("Extended", "Extended · structured", "")},
    "4024": {1: ("Paper 1", "Paper 1", ""), 2: ("Paper 2", "Paper 2", "")},
    "0625": {1: ("MCQ Core", "Multiple choice (Core)", ""),
             2: ("MCQ Extended", "Multiple choice (Extended)", ""),
             4: ("Extended", "Theory (Extended)", "")},
    "5054": {1: ("MCQ", "Multiple choice", ""), 2: ("Theory", "Theory", "")},
    "5070": {1: ("MCQ", "Multiple choice", ""), 2: ("Theory", "Theory", "")},
    "0620": {1: ("MCQ Core", "Multiple choice (Core)", ""),
             2: ("MCQ Extended", "Multiple choice (Extended)", ""),
             3: ("Theory Core", "Theory (Core)", ""),
             4: ("Theory Extended", "Theory (Extended)", "")},
    "2210": {1: ("Theory", "Computer systems", ""),
             2: ("Problem-solving", "Algorithms, programming & logic", "")},
    "0478": {1: ("Theory", "Computer systems", ""),
             2: ("Problem-solving", "Algorithms, programming & logic", "")},
    # These two examine different content per component, so the labels are what
    # the student actually revises from, not just a paper number.
    "2058": {1: ("Qur'an & the Prophet", "The Qur'an and the life of the Prophet", ""),
             2: ("Hadith & the Caliphs", "Hadith, history and the Caliphs", "")},
    "2059": {1: ("History of Pakistan", "History and culture of Pakistan", ""),
             2: ("Environment of Pakistan", "The environment of Pakistan", "")},
}


def component(code: str, paper: int) -> dict:
    """{paper, short, label ("P3 · Pure 3"), title, level} for one component."""
    short, title, level = COMPONENTS.get(code, {}).get(paper, (f"Paper {paper}", f"Paper {paper}", ""))
    return {"paper": paper, "short": short, "label": f"P{paper} · {short}",
            "title": title, "level": level}


PAPER_LABELS = {code: {p: component(code, p)["label"] for p in comps}
                for code, comps in COMPONENTS.items()}

# Pastel card pair per subject family (tokens from styles.css).
_FAMILY = [("math", "lav"), ("physic", "green"), ("chem", "orange"),
           ("computer", "pink"), ("islam", "teal"), ("pakistan", "yellow")]


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _plain(name: str) -> str:
    """'Mathematics (Syllabus D)' -> 'Mathematics' for slugs and headings."""
    return re.sub(r"\s*\(.*?\)", "", name).strip()


SUBJECTS: dict[str, dict] = {}
for _board, _subs in BOARDS:
    for _code, _name in _subs:
        SUBJECTS[_code] = {
            "code": _code, "name": _name, "plain": _plain(_name),
            "board": _board, "board_slug": BOARD_SLUGS[_board],
            "slug": f"{slugify(_plain(_name))}-{_code}",
            "tone": next((t for k, t in _FAMILY if k in _name.lower()), "blue"),
        }


def subject_url(code: str) -> str:
    s = SUBJECTS[code]
    return f"/papers/{s['board_slug']}/{s['slug']}"


def _yearly_url(code: str) -> str:
    import yearly                          # yearly imports this module
    return yearly.yearly_url(code)


def _mcq_url(code: str) -> str:
    import yearly
    return yearly.mcq_url(code)


def board_of(code: str) -> str | None:
    s = SUBJECTS.get(code)
    return s["board_slug"] if s else None


def find_subject(board_slug: str, subject_slug: str) -> dict | None:
    for s in SUBJECTS.values():
        if s["board_slug"] == board_slug and s["slug"] == subject_slug:
            return s
    return None


# ── Question counts (from app.py's meta cache) ────────────────────────────────
_meta_provider: Callable[[], dict] | None = None


def set_meta_provider(fn: Callable[[], dict]) -> None:
    global _meta_provider
    _meta_provider = fn


def _meta_for(code: str) -> dict | None:
    if _meta_provider is None:
        return None
    try:
        data = _meta_provider() or {}
    except Exception:
        return None
    return next((s for s in data.get("subjects", []) if s["syllabus"] == code), None)


def chapters(code: str) -> list[dict]:
    """[{name, display, slug, count, subtopics:[{name,count}]}] in syllabus order."""
    m = _meta_for(code)
    if m is None:
        return []
    out = []
    for t in m["topics"]:
        out.append({"name": t["name"], "display": t.get("display") or t["name"],
                    "slug": slugify(t["name"]), "count": t.get("count", 0),
                    "papers": t.get("paper_scope"),
                    "subtopics": [{"name": s["name"], "count": s.get("count", 0)}
                                  for s in t.get("subtopics", [])]})
    return out


def paper_groups(code: str) -> list[dict]:
    """Chapters grouped by the paper(s) that examine them, for subjects whose
    components cover different content (A Level Maths/Physics/CS, O Level and
    IGCSE CS, Islamiyat, Pakistan Studies). [] when every chapter is examined on
    every paper - then one flat list is the right view.

    [{key, papers, title, eyebrow, level, chapters:[name]}], in paper order.
    Components with an identical chapter set share one group (9702 P1 + P2)."""
    m = _meta_for(code)
    if not m or not m.get("split_by_paper"):
        return []
    out = []
    for g in m.get("paper_groups", []):
        papers = g["papers"]
        comps = [component(code, p) for p in papers]
        levels = sorted({c["level"] for c in comps if c["level"]})
        level = levels[0] if len(levels) == 1 else ""
        if len(papers) == 1:
            eyebrow, title = f"Paper {papers[0]}", comps[0]["title"]
        else:
            eyebrow = "Papers " + " & ".join(str(p) for p in papers)
            title = {"AS": "AS Level content", "A2": "A Level (A2) content"}.get(
                level, " / ".join(c["title"] for c in comps))
        out.append({"key": "-".join(map(str, papers)), "papers": papers, "title": title,
                    "eyebrow": eyebrow, "level": level, "chapters": g["topics"],
                    "components": [c["title"] for c in comps]})
    return out


def subject_stats(code: str) -> dict:
    m = _meta_for(code)
    if m is None:
        return {"questions": 0, "chapters": 0, "year_min": None, "year_max": None,
                "has_mcq": False}
    comps = {c["label"] for c in m.get("components", [])}
    return {"questions": sum(t.get("count", 0) for t in m["topics"]),
            "chapters": len(m["topics"]),
            "year_min": m.get("year_min"), "year_max": m.get("year_max"),
            "has_mcq": any("MCQ" in c for c in comps)}


# ── Student state ─────────────────────────────────────────────────────────────

def _student_state(user: dict | None) -> dict:
    """Boards + enrolled syllabuses for the signed-in user (empty when anonymous)."""
    if not user:
        return {"user": None, "boards": [], "primary": None, "enrolled": set()}
    try:
        boards, primary = _udb.get_boards(user["id"])
    except Exception:
        boards, primary = [], None
    try:
        enrolled = set(_udb.get_enrollments(user["id"]))
    except Exception:
        enrolled = set()
    if not boards and enrolled:
        # Not saved yet: infer from what they study so the page is still right.
        inferred = sorted({board_of(c) for c in enrolled if board_of(c)})
        return {"user": user, "boards": inferred, "primary": None,
                "enrolled": enrolled, "boards_inferred": True}
    return {"user": user, "boards": boards, "primary": primary, "enrolled": enrolled}


# ── JSON API ──────────────────────────────────────────────────────────────────

@router.get("/api/boards")
def api_boards():
    return {"boards": [
        {"slug": BOARD_SLUGS[b], "name": b, "short": BOARD_SHORT[BOARD_SLUGS[b]],
         "subjects": [{"code": c, "name": n, "slug": SUBJECTS[c]["slug"],
                       "url": subject_url(c)} for c, n in subs]}
        for b, subs in BOARDS]}


@router.get("/api/me/boards")
def api_my_boards(user: dict = Depends(_auth.get_current_user)):
    st = _student_state(user)
    return {"boards": st["boards"], "primary": st["primary"],
            "saved": not st.get("boards_inferred", False) and bool(st["boards"])}


class BoardsReq(BaseModel):
    boards: list[str]
    primary: str | None = None


@router.put("/api/me/boards")
def api_set_boards(req: BoardsReq, user: dict = Depends(_auth.get_current_user)):
    boards = [b for b in dict.fromkeys(req.boards) if b in BOARD_SHORT]
    if not boards:
        raise HTTPException(422, "Pick at least one board")
    primary = req.primary if req.primary in boards else boards[0]
    _udb.set_boards(user["id"], boards, primary)
    return {"boards": boards, "primary": primary}


@router.get("/api/catalogue")
def api_catalogue(board: str, user: dict | None = Depends(_auth.maybe_user)):
    if board not in BOARD_SHORT:
        raise HTTPException(404, "Unknown board")
    st = _student_state(user)
    subs = []
    for code, s in SUBJECTS.items():
        if s["board_slug"] != board:
            continue
        stats = subject_stats(code)
        subs.append({"code": code, "name": s["name"], "slug": s["slug"],
                     "url": subject_url(code), "enrolled": code in st["enrolled"],
                     "locked": code not in st["enrolled"], **stats})
    subs.sort(key=lambda x: (not x["enrolled"]))
    return {"board": board, "name": BOARD_SHORT[board], "subjects": subs,
            "signed_in": bool(user)}


# ── HTML shell ────────────────────────────────────────────────────────────────

def _e(s) -> str:
    return _html.escape(str(s), quote=True)


def _shell(*, title: str, desc: str, path: str, body: str, crumbs: list[tuple[str, str]],
           state: dict, noindex: bool = False, ld: list | None = None,
           scripts: tuple[str, ...] = (), styles: tuple[str, ...] = ()) -> str:
    import blog as _blog                      # shared navbar + footer
    canonical = f"{SITE_ORIGIN}{path}"
    crumb_ld = {"@context": "https://schema.org", "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": i + 1, "name": n,
                     "item": f"{SITE_ORIGIN}{u}"} for i, (n, u) in enumerate(crumbs)]}
    blocks = [crumb_ld] + (ld or [])
    ld_html = "".join(f'<script type="application/ld+json">{json.dumps(b, ensure_ascii=False)}</script>'
                      for b in blocks)
    crumb_html = " <span aria-hidden=\"true\">›</span> ".join(
        f'<a href="{_e(u)}">{_e(n)}</a>' if i < len(crumbs) - 1 else f"<span>{_e(n)}</span>"
        for i, (n, u) in enumerate(crumbs))
    needs_boards = bool(state["user"]) and (not state["boards"] or state.get("boards_inferred"))
    page_state = {"signedIn": bool(state["user"]), "boards": state["boards"],
                  "needsBoards": needs_boards,
                  "enrolled": sorted(state["enrolled"]),
                  "boardNames": BOARD_SHORT}
    robots = '<meta name="robots" content="noindex">' if noindex else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <script>try{{var t=localStorage.getItem("theme")||"light";document.documentElement.setAttribute("data-theme",t)}}catch(e){{}}</script>
  <title>{_e(title)}</title>
  <meta name="description" content="{_e(desc)}">
  <link rel="canonical" href="{_e(canonical)}">
  {robots}
  <meta property="og:type" content="website">
  <meta property="og:title" content="{_e(title)}">
  <meta property="og:description" content="{_e(desc)}">
  <meta property="og:url" content="{_e(canonical)}">
  <meta property="og:image" content="{SITE_ORIGIN}/logo.png">
  {ld_html}
  <link rel="icon" href="/logo.png">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700;800;900&family=Hanken+Grotesk:wght@400;500;600;700;800&family=Playfair+Display:ital,wght@0,600;0,700;0,800;1,600&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/styles.css?v={STYLES_V}">
  <link rel="stylesheet" href="/catalog.css?v={CSS_V}">
  {''.join(f'<link rel="stylesheet" href="{href}">' for href in styles)}
</head>
<body class="cat-page">
{_blog._nav()}
<main class="cat-wrap">
  <nav class="cat-crumbs" aria-label="Breadcrumb">{crumb_html}</nav>
  {body}
</main>
{_blog._foot()}
<script id="cat-state" type="application/json">{json.dumps(page_state)}</script>
<script src="/main.js?v=20260924a"></script>
<script src="/tools-core.js?v=20260927b"></script>
<script src="/tools-nav.js?v=20260811d"></script>
<script type="module" src="/auth.js?v=20260927b"></script>
<script type="module" src="/catalog.js?v={CSS_V}"></script>
{''.join(f'<script type="module" src="{src}"></script>' for src in scripts)}
</body>
</html>"""


def _respond(html: str, signed_in: bool) -> HTMLResponse:
    # Personalised pages must never be cached by a shared cache.
    cc = "private, no-store" if signed_in else "public, max-age=300"
    return HTMLResponse(html, headers={"Cache-Control": cc})


def _years(stats: dict) -> str:
    y0, y1 = stats.get("year_min"), stats.get("year_max")
    return f"{y0}–{y1}" if y0 and y1 else ""


def _subject_card(code: str, state: dict, test: bool = False) -> str:
    s = SUBJECTS[code]
    st = subject_stats(code)
    enrolled = code in state["enrolled"]
    url = subject_url(code) + ("?mode=test#builder" if test else "")
    meta = f'{st["chapters"]} chapters · {st["questions"]:,} questions'
    yrs = _years(st)
    if enrolled and test:
        actions = f'<a class="cat-btn" href="{url}">Build a mock test</a>'
        badge = '<span class="cat-badge cat-badge-on">Enrolled</span>'
    elif enrolled:
        actions = (f'<a class="cat-btn" href="{url}">Topical</a>'
                   f'<a class="cat-btn cat-btn-ghost" href="{_yearly_url(code)}">Yearly</a>'
                   + (f'<a class="cat-btn cat-btn-ghost" href="{_mcq_url(code)}">MCQ</a>'
                      if st["has_mcq"] else ""))
        badge = '<span class="cat-badge cat-badge-on">Enrolled</span>'
    else:
        actions = (f'<button class="cat-btn cat-btn-gold" type="button" data-enrol="{code}">'
                   f'Enrol free</button><a class="cat-btn cat-btn-ghost" href="{url}">Preview</a>')
        badge = '<span class="cat-badge" aria-label="Not enrolled">🔒</span>'
    return f"""
    <article class="cat-subj cat-tone-{s['tone']}{' is-enrolled' if enrolled else ' is-locked'}">
      <div class="cat-subj-top"><span class="cat-code">{code}</span>{badge}</div>
      <h3><a href="{url}">{_e(s['plain'])}</a></h3>
      <p class="cat-subj-meta">{meta}{f' · {yrs}' if yrs else ''}</p>
      <div class="cat-subj-actions">{actions}</div>
    </article>"""


def _board_tabs(active: str, state: dict, q: str = "") -> str:
    mine = state["boards"] or []
    order = mine + [b for b in BOARD_SHORT if b not in mine] if state["user"] else list(BOARD_SHORT)
    tabs = []
    for b in order:
        cls = "cat-tab" + (" is-active" if b == active else "") + (" is-mine" if b in mine else "")
        current = ' aria-current="page"' if b == active else ""
        tabs.append(f'<a class="{cls}" href="/papers/{b}{q}"{current}>{BOARD_SHORT[b]}</a>')
    if state["user"]:
        tabs.append('<button class="cat-tab cat-tab-add" type="button" data-open-boards>'
                    'Edit my boards</button>')
    return f'<nav class="cat-tabs" aria-label="Boards">{"".join(tabs)}</nav>'


# ── Pages ─────────────────────────────────────────────────────────────────────

@router.get("/papers", response_class=HTMLResponse)
def page_hub(mode: str = "", user: dict | None = Depends(_auth.maybe_user)):
    state = _student_state(user)
    q = "?mode=test" if mode == "test" else ""
    if state["user"] and state["boards"] and not state.get("boards_inferred"):
        return RedirectResponse(f"/papers/{state['primary'] or state['boards'][0]}{q}", 302)
    cards = []
    for board, subs in BOARDS:
        b = BOARD_SLUGS[board]
        names = ", ".join(_plain(n) for _c, n in subs)
        total = sum(subject_stats(c)["questions"] for c, _n in subs)
        cards.append(f"""
        <a class="cat-board" href="/papers/{b}{q}">
          <span class="cat-board-eyebrow">Cambridge</span>
          <h2>{BOARD_SHORT[b]}</h2>
          <p>{_e(names)}</p>
          <span class="cat-board-count">{total:,} topical questions →</span>
        </a>""")
    hero = ("""
    <header class="cat-hero">
      <p class="cat-eyebrow">Mock tests</p>
      <h1>Exam-style tests from real Cambridge questions.</h1>
      <p class="cat-lede">Pick your board and subject, choose up to four chapters, and get a
        timed test with an exam cover - the mark scheme comes as a separate file you unlock
        when you finish.</p>
    </header>""" if q else """
    <header class="cat-hero">
      <p class="cat-eyebrow">Topical past papers</p>
      <h1>Every Cambridge past-paper question, sorted by chapter.</h1>
      <p class="cat-lede">Pick your board, enrol in your subjects for free, then build a
        paper from up to four chapters. Questions are cropped straight from the original
        papers, with the official mark scheme alongside.</p>
    </header>""")
    body = f"""{hero}
    <section class="cat-boards">{''.join(cards)}</section>"""
    return _respond(_shell(
        title="Cambridge Topical Past Papers | O Level, IGCSE & A Level — PrepWithTee",
        desc="Free topical past papers for Cambridge O Level, IGCSE and A Level: every "
             "question sorted by syllabus chapter and subtopic, with official mark schemes.",
        path="/papers", body=body, crumbs=[("Home", "/"), ("Past papers", "/papers")],
        state=state), bool(user))


@router.get("/papers/{board}", response_class=HTMLResponse)
def page_board(board: str, mode: str = "", user: dict | None = Depends(_auth.maybe_user)):
    if board not in BOARD_SHORT:
        raise HTTPException(404, "Unknown board")
    state = _student_state(user)
    test = mode == "test"
    codes = [c for c, s in SUBJECTS.items() if s["board_slug"] == board]
    mine = [c for c in codes if c in state["enrolled"]]
    rest = [c for c in codes if c not in state["enrolled"]]
    sections = []
    if mine:
        sections.append(f'<h2 class="cat-group">Your subjects <span>{len(mine)}</span></h2>'
                        f'<div class="cat-grid">{"".join(_subject_card(c, state, test) for c in mine)}</div>')
    label = f"All {BOARD_SHORT[board]} subjects" if mine or not state["user"] else "Choose your subjects"
    sections.append(f'<h2 class="cat-group">{label}</h2>'
                    f'<div class="cat-grid">{"".join(_subject_card(c, state, test) for c in rest)}</div>')
    note = ("" if state["user"] else
            '<p class="cat-note">Enrolling is free. <a href="/login.html?signup=1&amp;next=/papers/'
            f'{board}">Create an account</a> to unlock topical papers, yearly papers, MCQ practice '
            'and progress tracking for each subject.</p>')
    if state["user"]:
        note = ('<p class="cat-note">Enrolling is free and unlocks everything for that subject: '
                'topical and yearly papers, MCQ practice, AI help and progress tracking.</p>')
    body = f"""
    <header class="cat-hero cat-hero-sm">
      <p class="cat-eyebrow">Cambridge {BOARD_SHORT[board]}{' · Mock tests' if test else ''}</p>
      <h1>{BOARD_SHORT[board]} {'mock tests' if test else 'topical past papers'}</h1>
      <p class="cat-lede">{_e(BOARD_BLURB[board])}</p>
    </header>
    {_board_tabs(board, state, "?mode=test" if test else "")}
    {''.join(sections)}
    {note}"""
    ld = [{"@context": "https://schema.org", "@type": "ItemList",
           "itemListElement": [{"@type": "ListItem", "position": i + 1,
                                "name": f"{SUBJECTS[c]['plain']} {c}",
                                "url": f"{SITE_ORIGIN}{subject_url(c)}"}
                               for i, c in enumerate(codes)]}]
    return _respond(_shell(
        title=f"Cambridge {BOARD_SHORT[board]} Topical Past Papers — PrepWithTee",
        desc=BOARD_BLURB[board], path=f"/papers/{board}", body=body, state=state, ld=ld,
        crumbs=[("Home", "/"), ("Past papers", "/papers"),
                (BOARD_SHORT[board], f"/papers/{board}")]), bool(user))


def _subject_or_404(board: str, subject: str) -> dict:
    s = find_subject(board, subject)
    if s is None:
        raise HTTPException(404, "Unknown subject")
    return s


def _subject_actions(s: dict, state: dict, chapter: str | None = None) -> str:
    code = s["code"]
    if not state["user"]:
        nxt = subject_url(code)
        return (f'<a class="cat-btn cat-btn-gold" href="/login.html?signup=1&amp;next={nxt}">'
                f'Create a free account to build papers</a>')
    if code not in state["enrolled"]:
        return (f'<button class="cat-btn cat-btn-gold" type="button" data-enrol="{code}">'
                f'🔒 Enrol free to unlock {_e(s["plain"])}</button>')
    st = subject_stats(code)
    build = (f"{subject_url(code)}?pick={_e(quote(chapter))}#builder" if chapter
             else "#builder")
    return (f'<a class="cat-btn" href="{build}">Build a topical paper</a>'
            f'<a class="cat-btn cat-btn-ghost" href="{_yearly_url(code)}">Yearly papers</a>'
            + (f'<a class="cat-btn cat-btn-ghost" href="{_mcq_url(code)}">MCQ practice</a>'
               if st["has_mcq"] else "")
            + f'<a class="cat-btn cat-btn-ghost" href="/topical-progress.html?syllabus={code}">My progress</a>')


@router.get("/papers/{board}/{subject}", response_class=HTMLResponse)
def page_subject(board: str, subject: str, user: dict | None = Depends(_auth.maybe_user)):
    s = _subject_or_404(board, subject)
    state = _student_state(user)
    code, st = s["code"], subject_stats(s["code"])
    chs = chapters(code)
    base = subject_url(code)
    def ch_item(ch):
        subs = "".join(f"<li>{_e(x['name'])}</li>" for x in ch["subtopics"])
        return f"""
        <li class="cat-ch">
          <a class="cat-ch-head" href="{base}/{ch['slug']}">
            <span class="cat-ch-name">{_e(ch['display'])}</span>
            <span class="cat-ch-count">{ch['count']:,} questions</span>
          </a>
          {f'<ul class="cat-subs">{subs}</ul>' if subs else ''}
        </li>"""
    by_name = {c["name"]: c for c in chs}
    groups = paper_groups(code)
    if groups:
        static_list = "".join(
            f'<section class="cat-pgroup"><h2 class="cat-group">{_e(g["eyebrow"])} · {_e(g["title"])}'
            + (f' <span class="cat-level cat-level-{g["level"]}">{"AS Level" if g["level"] == "AS" else "A Level"}</span>'
               if g["level"] else "")
            + f'</h2><ol class="cat-chapters">{"".join(ch_item(by_name[n]) for n in g["chapters"] if n in by_name)}</ol></section>'
            for g in groups)
    else:
        static_list = (f'<h2 class="cat-group">Syllabus chapters</h2>'
                       f'<ol class="cat-chapters">{"".join(ch_item(c) for c in chs)}</ol>')
    can_build = bool(state["user"]) and (
        code in state["enrolled"] or state["user"].get("role") in ("teacher", "admin"))
    builder = (f'<section id="builder" class="bld" data-syllabus="{code}" aria-label="Paper builder">'
               f'<noscript>{static_list}</noscript></section>' if can_build else static_list)
    yrs = _years(st)
    lede = (f"Every Cambridge {BOARD_SHORT[board]} {s['plain']} ({code}) past-paper question"
            f"{f' from {yrs}' if yrs else ''}, sorted into {st['chapters']} syllabus chapters"
            f" and their subtopics, with the official mark schemes.")
    body = f"""
    <header class="cat-hero cat-hero-sm cat-tone-{s['tone']}">
      <p class="cat-eyebrow">Cambridge {BOARD_SHORT[board]} · {code}</p>
      <h1>{_e(s['plain'])} topical past papers</h1>
      <p class="cat-lede">{_e(lede)}</p>
      <dl class="cat-stats">
        <div><dt>Questions</dt><dd>{st['questions']:,}</dd></div>
        <div><dt>Chapters</dt><dd>{st['chapters']}</dd></div>
        <div><dt>Years</dt><dd>{yrs or '–'}</dd></div>
      </dl>
      <div class="cat-actions">{_subject_actions(s, state)}</div>
    </header>
    {builder}"""
    ld = [{"@context": "https://schema.org", "@type": "Course",
           "name": f"Cambridge {BOARD_SHORT[board]} {s['plain']} ({code}) topical past papers",
           "description": lede,
           "provider": {"@type": "Organization", "name": "PrepWithTee", "sameAs": SITE_ORIGIN}}]
    return _respond(_shell(
        title=f"{s['plain']} {code} Topical Past Papers | Cambridge {BOARD_SHORT[board]} — PrepWithTee",
        desc=lede[:300], path=base, body=body, state=state, ld=ld,
        scripts=(f"/builder.js?v={CSS_V}",) if can_build else (),
        styles=(f"/builder.css?v={CSS_V}",) if can_build else (),
        crumbs=[("Home", "/"), ("Past papers", "/papers"),
                (BOARD_SHORT[board], f"/papers/{board}"), (f"{s['plain']} {code}", base)]),
        bool(user))


@router.get("/papers/{board}/{subject}/{chapter}", response_class=HTMLResponse)
def page_chapter(board: str, subject: str, chapter: str,
                 user: dict | None = Depends(_auth.maybe_user)):
    s = _subject_or_404(board, subject)
    ch = next((c for c in chapters(s["code"]) if c["slug"] == chapter), None)
    if ch is None:
        raise HTTPException(404, "Unknown chapter")
    state = _student_state(user)
    code, base = s["code"], subject_url(s["code"])
    subs = "".join(
        f'<li><span>{_e(x["name"])}</span><span class="cat-ch-count">{x["count"]:,}</span></li>'
        for x in ch["subtopics"])
    lede = (f"{ch['count']:,} Cambridge {BOARD_SHORT[board]} {s['plain']} ({code}) past-paper "
            f"questions on {ch['display']}"
            + (f", across {len(ch['subtopics'])} subtopics" if ch["subtopics"] else "")
            + ", with official mark schemes.")
    body = f"""
    <header class="cat-hero cat-hero-sm cat-tone-{s['tone']}">
      <p class="cat-eyebrow">{_e(s['plain'])} {code} · Chapter</p>
      <h1>{_e(ch['display'])}</h1>
      <p class="cat-lede">{_e(lede)}</p>
      <div class="cat-actions">{_subject_actions(s, state, ch['name'])}</div>
    </header>
    {f'<h2 class="cat-group">Subtopics</h2><ul class="cat-sublist">{subs}</ul>' if subs else ''}
    <p class="cat-note"><a href="{base}">← All {_e(s['plain'])} chapters</a></p>"""
    return _respond(_shell(
        title=f"{ch['display']} — {s['plain']} {code} Topical Questions | PrepWithTee",
        desc=lede[:300], path=f"{base}/{ch['slug']}", body=body, state=state,
        crumbs=[("Home", "/"), ("Past papers", "/papers"),
                (BOARD_SHORT[board], f"/papers/{board}"), (f"{s['plain']} {code}", base),
                (ch["display"], f"{base}/{ch['slug']}")]), bool(user))


@router.get("/papers.html", include_in_schema=False)
def legacy_papers(tab: str = "", mode: str = "", syllabus: str = "", s: str = "",
                  topics: str = "", topic: str = "", key: str = "", year: int = 0,
                  session: str = "", paper: int = 0, variant: str = ""):
    """The old single-page builder, retired 2026-09-27. Every old link moves for
    good (301): topical -> /papers/{board}/{subject} (?pick= the first chapter),
    the Test Builder -> the same builder with ?mode=test, yearly/library ->
    /yearly (a specific sitting -> its viewer), MCQ -> /mcq."""
    import yearly as _yearly
    syllabus = syllabus or s
    if key or (tab == "yearly" and year and paper):
        q = {"key": key} if key else {"syllabus": syllabus, "year": year, "session": session,
                                        "paper": paper, "variant": variant}
        return RedirectResponse("/yearly/open?" + urlencode(q), 301)
    moved = _yearly.legacy_target(tab, syllabus)
    if moved:
        return RedirectResponse(moved, 301)
    test = "mode=test" if mode == "test" else ""
    if syllabus in SUBJECTS:
        first = next((t.strip() for t in re.split(r"[,|]", topics or topic) if t.strip()), "")
        query = "&".join(x for x in (f"pick={quote(first)}" if first else "", test) if x)
        return RedirectResponse(f"{subject_url(syllabus)}{'?' + query if query else ''}#builder", 301)
    return RedirectResponse("/papers" + (f"?{test}" if test else ""), 301)


def sitemap_paths() -> list[str]:
    """Every public catalogue URL, for app.py's sitemap.xml."""
    paths = ["/papers"] + [f"/papers/{b}" for b in BOARD_SHORT]
    for code in SUBJECTS:
        base = subject_url(code)
        paths.append(base)
        paths += [f"{base}/{c['slug']}" for c in chapters(code)]
    return paths
