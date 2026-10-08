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
CSS_V = "20261008b"       # bump with catalog.css / catalog.js (immutable caching)
STYLES_V = "20261006d"    # the site-wide styles.css pin

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
             5: ("Statistics", "Probability & Statistics 1", "AS"),
             6: ("Statistics (to 2019)", "Probability & Statistics 1 (Paper 6 until 2019)", "AS")},
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
             3: ("Extended (to 2015)", "Theory (Extended)", ""),
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


# Cambridge renumbered some papers when a syllabus changed; up to and including
# the given year the component meant something else.
OLD_COMPONENTS: dict[tuple[str, int], tuple[int, tuple[str, str, str]]] = {
    ("9709", 5): (2019, ("Mechanics 2", "Mechanics 2 (old syllabus, not in topicals)", "A2")),
    ("0625", 2): (2015, ("Theory Core", "Theory (Core)", "")),
    ("0620", 2): (2015, ("Theory Core", "Theory (Core)", "")),
    ("0620", 3): (2015, ("Theory Extended", "Theory (Extended)", "")),
}


def component(code: str, paper: int, year: int | None = None) -> dict:
    """{paper, short, label ("P3 · Pure 3"), title, level} for one component
    (as it was in `year`, when given - see OLD_COMPONENTS)."""
    short, title, level = COMPONENTS.get(code, {}).get(paper, (f"Paper {paper}", f"Paper {paper}", ""))
    old = OLD_COMPONENTS.get((code, paper))
    if year is not None and old and int(year) <= old[0]:
        short, title, level = old[1]
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
    def safe(fn, default):
        def run():
            try:
                return fn(user["id"])
            except Exception:
                return default
        return run
    # Two REST round-trips to Supabase: run them side by side.
    got = _udb.gather(boards=safe(_udb.get_boards, ([], None)),
                      enrolled=safe(_udb.get_enrollments, []))
    boards, primary = got["boards"]
    enrolled = set(got["enrolled"])
    if not boards and enrolled:
        # Not saved yet: infer from what they study so the page is still right.
        inferred = sorted({board_of(c) for c in enrolled if board_of(c)})
        return {"user": user, "boards": inferred, "primary": None,
                "enrolled": enrolled, "boards_inferred": True}
    return {"user": user, "boards": boards, "primary": primary, "enrolled": enrolled}


# ── JSON API ──────────────────────────────────────────────────────────────────

@router.get("/api/boards")
def api_boards():
    import ui
    return {"boards": [
        {"slug": BOARD_SLUGS[b], "name": b, "short": BOARD_SHORT[BOARD_SLUGS[b]],
         "subjects": [{"code": c, "name": n, "plain": SUBJECTS[c]["plain"], "slug": SUBJECTS[c]["slug"],
                       "tone": SUBJECTS[c]["tone"], "url": subject_url(c),
                       # every section page of the subject (profile subject cards)
                       "links": [{"key": k, "label": label, "url": url}
                                 for k, label, url, _ic in ui.subject_links(c)]}
                      for c, n in subs]}
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
    back = ""
    if len(crumbs) > 2:
        import ui
        back = ui.back_link(crumbs[-2][1], crumbs[-2][0])
    needs_boards = bool(state["user"]) and (not state["boards"] or state.get("boards_inferred"))
    page_state = {"signedIn": bool(state["user"]), "boards": state["boards"],
                  "needsBoards": needs_boards,
                  "student": bool(state["user"]) and state["user"].get("role", "student") == "student",
                  "enrolled": sorted(state["enrolled"]),
                  "boardNames": BOARD_SHORT}
    robots = '<meta name="robots" content="noindex">' if noindex else ""
    import og_image                           # per-section/board/subject share image
    og_img = og_image.og_url(path)
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
  <meta property="og:site_name" content="PrepWithTee">
  <meta name="twitter:card" content="{'summary' if og_img.endswith('/logo.png') else 'summary_large_image'}">
  <meta name="theme-color" content="#4C2E72" media="(prefers-color-scheme: light)">
  <meta name="theme-color" content="#0f1117" media="(prefers-color-scheme: dark)">
  <meta property="og:title" content="{_e(title)}">
  <meta property="og:description" content="{_e(desc)}">
  <meta property="og:url" content="{_e(canonical)}">
  <meta property="og:image" content="{_e(og_img)}">
  <meta name="twitter:image" content="{_e(og_img)}">
  {ld_html}
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700;800;900&family=Hanken+Grotesk:wght@400;500;600;700;800&family=Playfair+Display:ital,wght@0,600;0,700;0,800;1,600&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/styles.css?v={STYLES_V}">
  <link rel="stylesheet" href="/catalog.css?v={CSS_V}">
  {''.join(f'<link rel="stylesheet" href="{href}">' for href in styles)}
</head>
<body class="cat-page">
{_blog._nav()}
<main class="cat-wrap" id="main">
  <div class="cat-topline">{back}<nav class="cat-crumbs" aria-label="Breadcrumb">{crumb_html}</nav></div>
  {body}
</main>
{_blog._foot()}
<script id="cat-state" type="application/json">{json.dumps(page_state)}</script>
<script src="/main.js?v=20261005a"></script>
<script src="/tools-core.js?v=20261005a"></script>
<script src="/tools-nav.js?v=20260811d"></script>
<script type="module" src="/auth.js?v=20261005c"></script>
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


# ── Pages ─────────────────────────────────────────────────────────────────────
#
#   /papers                 the past-papers hub: what each mode is, when to use
#                           it, a revision plan, boards, FAQ (never redirects)
#   /papers/topical         topical: how the builder works + every subject
#   /papers/mock-tests      mock tests: how they work + every subject
#   /papers/{board}         topical subjects for one board
#   /papers/{board}/{subject}[/{chapter}]   the builder / one chapter
#
# Subject-level pages carry ui.subject_tabs so a student can hop between the
# topical, yearly, MCQ, mock-test, notes and resources pages of one subject.

def _board_order(state: dict) -> list[str]:
    mine = state["boards"] or []
    return mine + [b for b in BOARD_SHORT if b not in mine]


def _subjects_of(board: str) -> list[str]:
    return [c for c, s in SUBJECTS.items() if s["board_slug"] == board]


def topical_tile(code: str, state: dict, test: bool = False) -> str:
    import ui
    st = subject_stats(code)
    url = subject_url(code) + ("?mode=test#builder" if test else "")
    enrolled = code in state["enrolled"]
    locked = bool(state["user"]) and not enrolled
    if enrolled:
        flag = "on"
        actions = [("Mock test" if test else "Topical booklet", url, "primary"),
                   ("By year", _yearly_url(code), "ghost")]
    elif locked:
        flag = "lock"
        actions = [("Enrol free", None, "gold", f'data-enrol="{code}"'), ("Preview", url, "ghost")]
    else:
        flag = ""
        actions = [("Mock tests" if test else "See chapters", url, "primary"),
                   ("By year", _yearly_url(code), "ghost")]
    import notes as _notes
    more = ([("MCQ", _mcq_url(code))] if st["has_mcq"] else []) + [("Notes", _notes.notes_url(code))]
    if test:
        more.insert(0, ("Topical", subject_url(code)))
    return ui.tile(code=code, url=url, flag=flag, actions=actions, more=more,
                   stats=[(str(st["chapters"]), "chapters"), (f'{st["questions"]:,}', "questions")],
                   years=_years(st))


def _topical_picker(state: dict, test: bool = False, board: str | None = None) -> str:
    """The shared picker (ui.picker) for topical / mock tests."""
    import ui
    boards = [board] if board else ui.board_order(state)

    def sub(b, n):
        mine = sum(1 for c in _subjects_of(b) if c in state["enrolled"])
        return f"{n} subjects" + (f" · you study {mine}" if mine else "")
    return ui.picker({b: [topical_tile(c, state, test) for c in ui.codes_for(b, state)] for b in boards},
                     state=state, subtitle=sub,
                     board_links=("/papers/{board}" if board else None), active=board or "")


def _recent_booklets(state: dict, n: int = 3) -> list[dict]:
    if not state["user"]:
        return []
    try:
        return _udb.list_booklets(state["user"]["id"], n)
    except Exception:
        return []


def _continue_block(state: dict) -> str:
    """Signed-in students: their subjects with one-click links, and recent papers."""
    if not state["user"]:
        return ""
    import ui
    mine = [c for c in SUBJECTS if c in state["enrolled"]]
    if not mine:
        return ui.callout(
            'You have not enrolled in a subject yet. Enrolling is free - open any subject below and '
            'press <b>Enrol free</b> to unlock its topical papers, mock tests, MCQ practice and progress '
            'tracking.', tone="blue", icon_name="user")
    # the student's boards first (their order), then any other board they study on
    order = ui.board_order(state)
    mine.sort(key=lambda c: order.index(SUBJECTS[c]["board_slug"]))
    rows = []
    for c in mine:
        s = SUBJECTS[c]
        links = "".join(f'<a class="sec-{k}" href="{_e(url)}">{ui.icon(ic)}{_e(label)}</a>'
                        for k, label, url, ic in ui.subject_links(c))
        rows.append(f'<article class="ui-mine cat-tone-{s["tone"]}" data-board="{s["board_slug"]}">'
                    f'<header><span class="cat-code">{c}</span>'
                    f'<b>{_e(s["plain"])}</b><small>{BOARD_SHORT[s["board_slug"]]}</small></header>'
                    f'<nav>{links}</nav></article>')
    # Board filter first (tutor, 2026-09-28): only when they study on 2+ boards.
    boards = [b for b in order if any(SUBJECTS[c]["board_slug"] == b for c in mine)]
    filt = ""
    if len(boards) > 1:
        filt = ('<nav class="pk-tabs ui-bf" data-bf aria-label="Filter your subjects by board">'
                '<button class="pk-tab is-on" type="button" data-bf-board="" aria-pressed="true">All boards '
                f'<b>{len(mine)}</b></button>'
                + "".join(f'<button class="pk-tab pk-b-{b}" type="button" data-bf-board="{b}" aria-pressed="false">'
                          f'<i></i>{BOARD_SHORT[b]} <b>{sum(1 for c in mine if SUBJECTS[c]["board_slug"] == b)}</b></button>'
                          for b in boards)
                + "</nav>")
    recent = _recent_booklets(state)
    rec = ""
    if recent:
        items = "".join(
            f'<li><a href="/papers/view/{_e(b["id"])}">{ui.icon("test" if (b.get("params_json") or {}).get("kind") == "test" else "topical")}'
            f'<span>{_e(b["title"] or "Topical paper")}</span></a></li>' for b in recent)
        rec = (f'<div class="ui-recent"><h3>Papers you built recently</h3><ul>{items}</ul>'
               f'<a class="ui-more" href="/my-papers">All my papers {ui.icon("arrow")}</a></div>')
    return (f'<section class="ui-continue"><h2 class="ui-h2">Your subjects</h2>{filt}'
            f'<div class="ui-continue-grid"><div class="ui-mine-list">{"".join(rows)}</div>{rec}</div></section>')


def _mode_cards(state: dict) -> str:
    import ui
    tq = sum(subject_stats(c)["questions"] for c in SUBJECTS)
    cards = [
        ui.mode_card(key="topical", title="Topical papers", url="/papers/topical", tone="lav",
                     blurb="Pick up to four chapters (and any subtopics) and get a booklet of real "
                           "Cambridge questions on just those topics, with the mark scheme after each.",
                     best="learning a chapter, or fixing a weak topic", cta="Build a topical paper",
                     meta=f"{tq:,} questions sorted by chapter"),
        ui.mode_card(key="yearly", title="Papers by year", url="/yearly", tone="blue",
                     blurb="Every question paper, mark scheme and insert, sitting by sitting. Opens "
                           "straight away - no account needed - with the mark scheme side by side.",
                     best="exam practice under real timing", cta="Browse by year",
                     meta="May/June, Oct/Nov and Feb/March · every variant"),
        ui.mode_card(key="mcq", title="MCQ practice", url="/mcq", tone="orange",
                     blurb="Multiple-choice papers one question at a time or as a full timed paper, "
                           "marked instantly against the official answer key.",
                     best="Paper 1 speed and accuracy", cta="Practise MCQs",
                     meta="Instant marking · timed or relaxed"),
        ui.mode_card(key="test", title="Mock tests", url="/papers/mock-tests", tone="green",
                     blurb="A timed, exam-style test from the chapters you choose. The mark scheme is "
                           "a separate file that unlocks when you press Finish.",
                     best="checking a topic is really exam-ready", cta="Make a mock test",
                     meta="About 1 minute per mark"),
    ]
    history = ""
    if state["user"]:
        history = (f'<a class="ui-mode ui-mode-slim" href="/my-papers">'
                   f'<span class="ui-mode-ic">{ui.icon("history")}</span><span class="ui-mode-body">'
                   f'<b class="ui-mode-title">My papers</b><span class="ui-mode-blurb">Every topical '
                   f'booklet and mock test you have built, with your annotations.</span></span>'
                   f'<span class="ui-mode-cta">Open {ui.icon("arrow")}</span></a>')
    return f'<div class="ui-modes">{"".join(cards)}</div>{history}'


_PLAN = [
    ("Learn the chapter", 'Read the <a href="/notes">revision notes</a> for it, or your teacher\'s '
                          'notes in <a href="/resources">Resources</a>. Keep the syllabus points in view.'),
    ("Practise it topically", 'Build a <a href="/papers/topical">topical paper</a> on that chapter. '
                              'Answer in full, then mark yourself with the official scheme after each question.'),
    ("Fix what you missed", "Open <b>Explain</b> or <b>Guide me</b> on any question you dropped marks on, "
                            "and redo it a few days later."),
    ("Prove it under time", 'Sit a <a href="/papers/mock-tests">mock test</a> on the chapter, then '
                            'full <a href="/yearly">papers by year</a> once most chapters are done.'),
]

_WHICH = [
    ("I have just finished a chapter in class", "Topical paper on that chapter, mark scheme on."),
    ("I keep losing marks on one topic", "Topical paper on the subtopic only, then a mock test a week later."),
    ("My exam is in 6-8 weeks", "One full paper by year every few days, timed, marked honestly."),
    ("I need Paper 1 speed", "MCQ practice as a full timed paper, then review every wrong option."),
    ("I want to know if I am exam-ready", "Mock test on 3-4 chapters, then compare with the grade thresholds."),
]


def _which_block() -> str:
    rows = "".join(f'<li><b>{_e(a)}</b><span>{_e(b)}</span></li>' for a, b in _WHICH)
    return f'<section class="ui-which"><h2 class="ui-h2">Which one should I use?</h2><ul>{rows}</ul></section>'


def _board_cards() -> str:
    import ui
    cards = []
    for board, subs in BOARDS:
        b = BOARD_SLUGS[board]
        names = ", ".join(_plain(n) for _c, n in subs)
        total = sum(subject_stats(c)["questions"] for c, _n in subs)
        cards.append(f"""
        <article class="cat-board pk-b-{b}">
          <span class="pk-bmark" aria-hidden="true">{ui.BOARD_THEME[b][0]}</span>
          <span class="cat-board-eyebrow">Cambridge</span>
          <h3><a href="/papers/{b}">{BOARD_SHORT[b]}</a></h3>
          <p>{_e(names)}</p>
          <span class="cat-board-count">{total:,} topical questions</span>
          <nav class="cat-board-links"><a href="/papers/{b}">Topical</a><a href="/yearly/{b}">By year</a>
            <a href="/notes/{b}">Notes</a><a href="/resources/{b}">Resources</a></nav>
        </article>""")
    return f'<section class="cat-boards">{"".join(cards)}</section>'


@router.get("/papers", response_class=HTMLResponse)
def page_hub(mode: str = "", user: dict | None = Depends(_auth.maybe_user)):
    if mode == "test":
        return RedirectResponse("/papers/mock-tests", 301)
    import ui
    state = _student_state(user)
    tq = sum(subject_stats(c)["questions"] for c in SUBJECTS)
    faq_html, faq_ld = ui.faq([
        ("Are these the real Cambridge questions?",
         "Yes. Every question is cropped straight from the original Cambridge PDF - diagrams, graphs and "
         "answer lines exactly as printed - and paired with the official mark scheme."),
        ("Do I need an account?",
         "Papers by year open without one. A free account lets you build topical papers and mock tests, "
         "practise MCQs, save your annotations and track progress for the subjects you enrol in."),
        ("How long are my topical papers kept?",
         'Each paper you build stays ready to open for 30 days after you last opened it, with your '
         'annotations. After that it stays on <a href="/my-papers">My papers</a> as a record of what you '
         'practised.'),
        ("What is the difference between a topical paper and a mock test?",
         "A topical paper shows the mark scheme right after every question so you learn as you go. A mock "
         "test is timed and exam-styled; its mark scheme is a separate file that unlocks when you finish."),
        ("Which years are covered?",
         "Most subjects go back to 2010-2015 and run to the latest session, with every variant of May/June, "
         "Oct/Nov and Feb/March."),
    ])
    body = f"""
    <header class="ui-hero">
      <div class="ui-hero-text">
        <p class="cat-eyebrow">Past papers</p>
        <h1>Every Cambridge past paper - by topic, by year, or as a test.</h1>
        <p class="cat-lede">Real questions cropped from the original papers, always with the official mark
          scheme. Choose how you want to practise below; if you are not sure, the revision plan further
          down tells you what to do and when.</p>
        <div class="cat-actions">
          <a class="cat-btn" href="/papers/topical">Build a topical paper</a>
          <a class="cat-btn cat-btn-ghost" href="/yearly">Browse papers by year</a>
        </div>
      </div>
      <dl class="ui-hero-stats">
        <div><dt>Topical questions</dt><dd>{tq:,}</dd></div>
        <div><dt>Subjects</dt><dd>{len(SUBJECTS)}</dd></div>
        <div><dt>Boards</dt><dd>O Level · IGCSE · A Level</dd></div>
      </dl>
    </header>
    {_continue_block(state)}
    <section><h2 class="ui-h2">Choose how to practise</h2>{_mode_cards(state)}</section>
    {ui.steps(_PLAN, "A revision plan that works", "ui-plan")}
    <section><h2 class="ui-h2">Pick your board</h2>{_board_cards()}</section>
    {_which_block()}
    {faq_html}"""
    ld = [faq_ld, {"@context": "https://schema.org", "@type": "CollectionPage",
                   "name": "Cambridge past papers", "url": f"{SITE_ORIGIN}/papers",
                   "description": "Topical, yearly, MCQ and mock-test practice from real Cambridge papers."}]
    return _respond(_shell(
        title="Cambridge Past Papers - Topical, Yearly, MCQ & Mock Tests | PrepWithTee",
        desc="Cambridge O Level, IGCSE and A Level past papers four ways: topical by chapter, full papers "
             "by year, instantly marked MCQs and timed mock tests - all with official mark schemes.",
        path="/papers", body=body, crumbs=[("Home", "/"), ("Past papers", "/papers")],
        state=state, ld=ld), bool(user))


@router.get("/papers/topical", response_class=HTMLResponse)
def page_topical(user: dict | None = Depends(_auth.maybe_user)):
    import ui
    state = _student_state(user)
    body = f"""
    <header class="cat-hero cat-hero-sm">
      <p class="cat-eyebrow">Topical past papers</p>
      <h1>Past-paper questions, sorted by chapter</h1>
      <p class="cat-lede">Every question from every paper we hold is tagged to its syllabus chapter and
        subtopic. Choose up to four chapters, narrow the years or papers if you like, and get one
        booklet - newest papers first, original questions, official mark scheme after each.</p>
    </header>
    {_topical_picker(state)}
    {ui.steps([
        ("Open your subject", "Pick a subject above. Enrolling is free and unlocks the builder."),
        ("Choose chapters", "Tick up to four chapters, or tap subtopic chips to take just part of one."),
        ("Filter (optional)", "Limit the years, the paper (e.g. Paper 2 only) and the number of questions."),
        ("Open and practise", "Your booklet opens in the viewer in a few seconds: write on it, check the mark "
                              "scheme, ask for an explanation, or download the PDF."),
    ], "How it works", "ui-steps-row")}
    {ui.callout('Built papers are listed on <a href="/my-papers">My papers</a> and stay ready to open for 30 '
                'days after you last opened them.', tone="blue", icon_name="history") if state["user"] else ''}"""
    return _respond(_shell(
        title="Topical Past Papers by Chapter | Cambridge O Level, IGCSE & A Level - PrepWithTee",
        desc="Build topical past papers from real Cambridge questions: pick chapters and subtopics, filter by "
             "year and paper, and get the official mark scheme after every question.",
        path="/papers/topical", body=body, state=state,
        crumbs=[("Home", "/"), ("Past papers", "/papers"), ("Topical", "/papers/topical")]), bool(user))


@router.get("/papers/mock-tests", response_class=HTMLResponse)
def page_mock_tests(user: dict | None = Depends(_auth.maybe_user)):
    import ui
    state = _student_state(user)
    body = f"""
    <header class="cat-hero cat-hero-sm cat-tone-green">
      <p class="cat-eyebrow">Mock tests</p>
      <h1>Exam-style tests from real Cambridge questions</h1>
      <p class="cat-lede">Choose the chapters, the number of questions or marks, and sit it like the real
        thing: an exam cover, a countdown at about a minute per mark, and a mark scheme that stays locked
        until you press <b>Finish test</b>.</p>
    </header>
    {_topical_picker(state, test=True)}
    {ui.steps([
        ("Pick a subject", "Open a subject above and switch the builder to <b>Mock test</b>."),
        ("Choose what it covers", "Up to four chapters, any subtopics, the years and papers to draw from."),
        ("Sit it timed", "Start the timer, write your answers on the paper or on your own sheet."),
        ("Finish and mark", "Press Finish to unlock the mark scheme, mark honestly, and note the topics to redo."),
    ], "How a mock test works", "ui-steps-row")}
"""
    return _respond(_shell(
        title="Cambridge Mock Tests from Past Papers | O Level, IGCSE & A Level - PrepWithTee",
        desc="Timed, exam-style Cambridge mock tests built from real past-paper questions on the chapters you "
             "choose, with a separate mark scheme that unlocks when you finish.",
        path="/papers/mock-tests", body=body, state=state,
        crumbs=[("Home", "/"), ("Past papers", "/papers"), ("Mock tests", "/papers/mock-tests")]), bool(user))


@router.get("/papers/{board}", response_class=HTMLResponse)
def page_board(board: str, mode: str = "", user: dict | None = Depends(_auth.maybe_user)):
    if board not in BOARD_SHORT:
        raise HTTPException(404, "Unknown board")
    if mode == "test":
        return RedirectResponse(f"/papers/mock-tests#{board}", 301)
    state = _student_state(user)
    codes = _subjects_of(board)
    note = ("" if state["user"] else
            '<p class="cat-note">Enrolling is free. <a href="/login.html?signup=1&amp;next=/papers/'
            f'{board}">Create an account</a> to unlock topical papers, mock tests, MCQ practice '
            'and progress tracking for each subject. Papers by year open without an account.</p>')
    if state["user"]:
        note = ('<p class="cat-note">Enrolling is free and unlocks everything for that subject: '
                'topical papers, mock tests, MCQ practice, AI help and progress tracking.</p>')
    body = f"""
    <header class="cat-hero cat-hero-sm">
      <p class="cat-eyebrow">Cambridge {BOARD_SHORT[board]} · Topical</p>
      <h1>{BOARD_SHORT[board]} topical past papers</h1>
      <p class="cat-lede">{_e(BOARD_BLURB[board])}</p>
      <div class="cat-actions"><a class="cat-btn cat-btn-ghost" href="/yearly/{board}">{BOARD_SHORT[board]} papers by year</a>
        <a class="cat-btn cat-btn-ghost" href="/notes/{board}">{BOARD_SHORT[board]} notes</a></div>
    </header>
    {_topical_picker(state, board=board)}
    {note}"""
    ld = [{"@context": "https://schema.org", "@type": "ItemList",
           "itemListElement": [{"@type": "ListItem", "position": i + 1,
                                "name": f"{SUBJECTS[c]['plain']} {c}",
                                "url": f"{SITE_ORIGIN}{subject_url(c)}"}
                               for i, c in enumerate(codes)]}]
    return _respond(_shell(
        title=f"Cambridge {BOARD_SHORT[board]} Topical Past Papers - PrepWithTee",
        desc=BOARD_BLURB[board], path=f"/papers/{board}", body=body, state=state, ld=ld,
        crumbs=[("Home", "/"), ("Past papers", "/papers"), ("Topical", "/papers/topical"),
                (BOARD_SHORT[board], f"/papers/{board}")]), bool(user))


def _subject_or_404(board: str, subject: str) -> dict:
    s = find_subject(board, subject)
    if s is None:
        raise HTTPException(404, "Unknown subject")
    return s


def _subject_actions(s: dict, state: dict, chapter: str | None = None, test: bool = False) -> str:
    code = s["code"]
    if not state["user"]:
        nxt = subject_url(code)
        return (f'<a class="cat-btn cat-btn-gold" href="/login.html?signup=1&amp;next={nxt}">'
                f'Create a free account to build papers</a>'
                f'<a class="cat-btn cat-btn-ghost" href="{_yearly_url(code)}">Papers by year (no account)</a>')
    if code not in state["enrolled"] and state["user"].get("role") not in ("teacher", "admin"):
        return (f'<button class="cat-btn cat-btn-gold" type="button" data-enrol="{code}">'
                f'🔒 Enrol free to unlock {_e(s["plain"])}</button>')
    if chapter:
        return (f'<a class="cat-btn" href="{subject_url(code)}?pick={_e(quote(chapter))}#builder">'
                f'Practise this chapter</a>'
                f'<a class="cat-btn cat-btn-ghost" href="{subject_url(code)}?mode=test&amp;pick={_e(quote(chapter))}#builder">'
                f'Mock test on it</a>')
    return (f'<a class="cat-btn" href="#builder">{"Build a mock test" if test else "Build a topical booklet"}</a>'
            f'<a class="cat-btn cat-btn-ghost" href="/topical-progress.html?syllabus={code}">My progress</a>'
            f'<a class="cat-btn cat-btn-ghost" href="/my-papers?syllabus={code}">Papers I built</a>')


@router.get("/papers/{board}/{subject}", response_class=HTMLResponse)
def page_subject(board: str, subject: str, mode: str = "",
                 user: dict | None = Depends(_auth.maybe_user)):
    import ui
    s = _subject_or_404(board, subject)
    state = _student_state(user)
    test = mode == "test"
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
    how = "" if not can_build else ui.steps([
        ("Choose chapters", "Up to four, from any paper. Tap subtopic chips to take only part of a chapter."),
        ("Set the filters", "Years, paper and how many questions - the live count shows what is available."),
        ("Build", "Practice booklet = mark scheme after each question. Mock test = timed, scheme unlocks at the end."),
    ], "", "ui-steps-row ui-steps-mini")
    body = f"""
    {ui.subject_tabs(code, "test" if test else "topical")}
    <header class="cat-hero cat-hero-sm cat-tone-{s['tone']}">
      <p class="cat-eyebrow">Cambridge {BOARD_SHORT[board]} · {code} · {"Mock test" if test else "Topical"}</p>
      <h1>{_e(s['plain'])} {"mock tests" if test else "topical past papers"}</h1>
      <p class="cat-lede">{_e(lede)}</p>
      <dl class="cat-stats">
        <div><dt>Questions</dt><dd>{st['questions']:,}</dd></div>
        <div><dt>Chapters</dt><dd>{st['chapters']}</dd></div>
        <div><dt>Years</dt><dd>{yrs or '–'}</dd></div>
      </dl>
      <div class="cat-actions">{_subject_actions(s, state, test=test)}</div>
    </header>
    {how}
    {builder}"""
    ld = [{"@context": "https://schema.org", "@type": "Course",
           "name": f"Cambridge {BOARD_SHORT[board]} {s['plain']} ({code}) topical past papers",
           "description": lede, "courseCode": code,
           "educationalLevel": f"Cambridge {BOARD_SHORT[board]}",
           "hasCourseInstance": {"@type": "CourseInstance", "courseMode": "online",
                                 "courseWorkload": "PT1H"},
           "offers": {"@type": "Offer", "price": 0, "priceCurrency": "USD", "category": "Free"},
           "provider": {"@type": "Organization", "name": "PrepWithTee", "sameAs": SITE_ORIGIN}}]
    return _respond(_shell(
        title=f"{s['plain']} {code} Topical Past Papers | Cambridge {BOARD_SHORT[board]} - PrepWithTee",
        desc=lede[:300], path=base, body=body, state=state, ld=ld,
        scripts=(f"/builder.js?v={CSS_V}",) if can_build else (),
        styles=(f"/builder.css?v={CSS_V}",) if can_build else (),
        crumbs=[("Home", "/"), ("Past papers", "/papers"), ("Topical", "/papers/topical"),
                (BOARD_SHORT[board], f"/papers/{board}"), (f"{s['plain']} {code}", base)]),
        bool(user))


@router.get("/papers/{board}/{subject}/{chapter}", response_class=HTMLResponse)
def page_chapter(board: str, subject: str, chapter: str,
                 user: dict | None = Depends(_auth.maybe_user)):
    import notes as _notes
    import ui
    s = _subject_or_404(board, subject)
    ch = next((c for c in chapters(s["code"]) if c["slug"] == chapter), None)
    if ch is None:
        raise HTTPException(404, "Unknown chapter")
    state = _student_state(user)
    code, base = s["code"], subject_url(s["code"])
    subs = "".join(
        f'<li><span>{_e(x["name"])}</span><span class="cat-ch-count">{x["count"]:,} questions</span></li>'
        for x in ch["subtopics"])
    lede = (f"{ch['count']:,} Cambridge {BOARD_SHORT[board]} {s['plain']} ({code}) past-paper "
            f"questions on {ch['display']}"
            + (f", across {len(ch['subtopics'])} subtopics" if ch["subtopics"] else "")
            + ", with official mark schemes.")
    has_notes = bool(_notes.index().get(code, {}).get(ch["slug"]))
    all_chs = chapters(code)
    i = next((k for k, c in enumerate(all_chs) if c["slug"] == ch["slug"]), 0)
    prev_c = all_chs[i - 1] if i > 0 else None
    next_c = all_chs[i + 1] if i + 1 < len(all_chs) else None
    pn = ('<nav class="ui-pn">'
          + (f'<a href="{base}/{prev_c["slug"]}"><small>Previous chapter</small>{_e(prev_c["display"])}</a>'
             if prev_c else "<span></span>")
          + (f'<a class="ui-pn-next" href="{base}/{next_c["slug"]}"><small>Next chapter</small>{_e(next_c["display"])}</a>'
             if next_c else "<span></span>")
          + "</nav>")
    body = f"""
    {ui.subject_tabs(code, "topical")}
    <header class="cat-hero cat-hero-sm cat-tone-{s['tone']}">
      <p class="cat-eyebrow">{_e(s['plain'])} {code} · Chapter {i + 1} of {len(all_chs)}</p>
      <h1>{_e(ch['display'])}</h1>
      <p class="cat-lede">{_e(lede)}</p>
      <div class="cat-actions">{_subject_actions(s, state, ch['name'])}
        {f'<a class="cat-btn cat-btn-ghost" href="{_notes.notes_url(code, ch["slug"])}">Read the notes</a>' if has_notes else ''}</div>
    </header>
    {f'<h2 class="cat-group">Subtopics</h2><ul class="cat-sublist">{subs}</ul>' if subs else ''}
    {pn}"""
    return _respond(_shell(
        title=f"{ch['display']} - {s['plain']} {code} Topical Questions | PrepWithTee",
        desc=lede[:300], path=f"{base}/{ch['slug']}", body=body, state=state,
        crumbs=[("Home", "/"), ("Past papers", "/papers"), ("Topical", "/papers/topical"),
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
    return RedirectResponse("/papers/mock-tests" if test else "/papers", 301)


def sitemap_paths() -> list[str]:
    """Every public catalogue URL, for app.py's sitemap.xml."""
    paths = ["/papers", "/papers/topical", "/papers/mock-tests"] + [f"/papers/{b}" for b in BOARD_SHORT]
    for code in SUBJECTS:
        base = subject_url(code)
        paths.append(base)
        paths += [f"{base}/{c['slug']}" for c in chapters(code)]
    return paths
