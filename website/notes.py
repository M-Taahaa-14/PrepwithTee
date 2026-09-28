"""Revision notes as server-rendered pages (P2-d).

    /notes                                          boards -> subjects
    /notes/{board}                                  one board's subjects
    /notes/{board}/{subject}                        chapters (grouped by paper where the
                                                    syllabus splits) with their notes
    /notes/{board}/{subject}/{chapter}              one chapter: outcomes, notes, subtopics
    /notes/{board}/{subject}/{chapter}/{note}       the note itself

Chapters are the SAME syllabus chapters as the topical builder (taxonomy/), so
every chapter and note links straight to "Practise this chapter". The full note
text is in the HTML, so search engines read it; KaTeX renders the maths.

Adding a note = drop a file in
    website/static/notes-content/{syllabus}/{chapter-slug}/{note-slug}.html
starting with an optional metadata comment:
    <!--note {"title": "Hooke's Law and springs", "order": 3,
              "subtopic": "Hooke's Law and spring constant", "tier": "Core"} -->
Optional: {chapter-slug}/_chapter.json (syllabus_ref, weighting, learning_outcomes)
and {syllabus}/_subject.json (description, study_guide). The pages pick new files
up on their own (the index is rebuilt when the folder changes).

Old URLs (note.html?code=..&ch=..&st=.., chapter.html, subject.html) 301 here
through notes-content/_redirects.json.
"""

import json
import re
import threading
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

import auth as _auth
import catalog as _catalog

router = APIRouter()

NOTES_DIR = Path(__file__).resolve().parent / "static" / "notes-content"
NOTES_V = "20260929a"                     # bump with notes.css / notes-page.js
_e = _catalog._e
SUBJECTS = _catalog.SUBJECTS
BOARD_SHORT = _catalog.BOARD_SHORT
_META_RE = re.compile(r"^\s*<!--note\s+(\{.*?\})\s*-->\s*", re.S)
_H2_RE = re.compile(r'<h2[^>]*\bid="([^"]+)"[^>]*>(.*?)</h2>', re.S)


# ── Index of the notes on disk ────────────────────────────────────────────────

_cache: dict = {"stamp": None, "index": {}}
_lock = threading.Lock()


def _stamp() -> tuple:
    """Changes whenever a note file is added, removed or edited."""
    if not NOTES_DIR.exists():
        return ()
    return tuple(sorted((str(p.relative_to(NOTES_DIR)), p.stat().st_mtime_ns)
                        for p in NOTES_DIR.glob("*/*/*.html")))


def _read_meta(path: Path) -> tuple[dict, str]:
    raw = path.read_text(encoding="utf-8")
    m = _META_RE.match(raw)
    meta = {}
    if m:
        try:
            meta = json.loads(m.group(1))
        except ValueError:
            meta = {}
        raw = raw[m.end():]
    return meta, raw


def index() -> dict[str, dict[str, list[dict]]]:
    """{syllabus: {chapter_slug: [note, ...]}} sorted by order, then title."""
    stamp = _stamp()
    with _lock:
        if _cache["stamp"] == stamp:
            return _cache["index"]
        out: dict[str, dict[str, list[dict]]] = {}
        for p in NOTES_DIR.glob("*/*/*.html"):
            code, ch = p.parent.parent.name, p.parent.name
            meta, body = _read_meta(p)
            words = len(re.sub(r"<[^>]+>", " ", body).split())
            out.setdefault(code, {}).setdefault(ch, []).append({
                "slug": p.stem, "chapter": ch, "path": p,
                "title": meta.get("title") or p.stem.replace("-", " ").capitalize(),
                "order": meta.get("order", 999), "subtopic": meta.get("subtopic"),
                "tier": meta.get("tier"), "minutes": max(1, round(words / 200))})
        for chs in out.values():
            for notes in chs.values():
                notes.sort(key=lambda n: (n["order"], n["title"]))
        _cache.update(stamp=stamp, index=out)
        return out


def _json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def subject_meta(code: str) -> dict:
    return _json(NOTES_DIR / code / "_subject.json")


def chapter_meta(code: str, ch_slug: str) -> dict:
    return _json(NOTES_DIR / code / ch_slug / "_chapter.json")


def notes_url(code: str, ch: str | None = None, note: str | None = None) -> str:
    s = SUBJECTS[code]
    url = f"/notes/{s['board_slug']}/{s['slug']}"
    return url + (f"/{ch}" if ch else "") + (f"/{note}" if note else "")


def _practise(code: str, chapter_name: str) -> str:
    return f"{_catalog.subject_url(code)}?pick={quote(chapter_name)}#builder"


def _count(code: str) -> int:
    return sum(len(v) for v in index().get(code, {}).values())


def _ordered_notes(code: str) -> list[dict]:
    """Every note of a subject in syllabus-chapter order (for previous / next)."""
    chs = index().get(code, {})
    out = []
    for c in _catalog.chapters(code):
        out += chs.get(c["slug"], [])
    return out


# ── Shared page bits ──────────────────────────────────────────────────────────

def _page(*, title, desc, path, body, crumbs, user, noindex=False, ld=None, katex=False, note=False):
    state = _catalog._student_state(user)
    styles = [f"/notes.css?v={NOTES_V}"]
    scripts = [f"/notes-page.js?v={NOTES_V}"] if note else []
    html = _catalog._shell(title=title, desc=desc, path=path, body=body, crumbs=crumbs, state=state,
                           noindex=noindex, ld=ld, scripts=tuple(scripts), styles=tuple(styles))
    if katex:
        html = html.replace("</head>", '''  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
  <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
  <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"></script>
</head>''', 1)
    return _catalog._respond(html, bool(user))


def _picker(user: dict | None, board: str | None = None) -> str:
    """The shared board/subject picker (ui.picker): subjects with notes first."""
    import ui
    state = _catalog._student_state(user)
    boards = [board] if board else ui.board_order(state)
    tiles = {}
    for b in boards:
        codes = sorted(ui.codes_for(b, state), key=lambda c: (c not in state["enrolled"], -_count(c)))
        tiles[b] = []
        for c in codes:
            n = _count(c)
            chs = len(index().get(c, {}))
            if n:
                stats = [(str(n), "notes"), (str(chs), "chapters")]
                actions = [("Read notes", notes_url(c), "primary"),
                           ("Practise", _catalog.subject_url(c), "ghost")]
            else:
                stats = [("Soon", "notes"), (str(len(_catalog.chapters(c)) or "—"), "chapters")]
                actions = [("See chapters", notes_url(c), "primary")]
            tiles[b].append(ui.tile(code=c, url=notes_url(c), stats=stats, actions=actions, soon=not n,
                                    flag="on" if c in state["enrolled"] else ("soon" if not n else "")))

    def sub(b, n_tiles):
        have = sum(1 for c in ui.codes_for(b) if _count(c))
        return f"{n_tiles} subjects · {have} with notes"
    return ui.picker(tiles, state=state, subtitle=sub,
                     board_links="/notes/{board}" if board else None, active=board or "")


# ── Pages ─────────────────────────────────────────────────────────────────────

@router.get("/notes", response_class=HTMLResponse)
def notes_hub(user: dict | None = Depends(_auth.maybe_user)):
    total = sum(_count(c) for c in SUBJECTS)
    import ui
    faq_html, faq_ld = ui.faq([
        ("Who writes PrepWithTee notes?",
         "Our tutors, point by point against the current Cambridge syllabus - the same chapters the "
         "topical past papers use, so a note always leads straight to real questions on it."),
        ("Where are other teachers' notes?",
         'In <a href="/resources">Resources</a>: PDF notes from well-known teachers, textbooks, solved '
         'worksheets, official syllabuses and study planners, sorted by subject.'),
        ("A chapter says Coming soon - what now?",
         'Use a teacher\'s notes from Resources for that chapter, then practise it with a topical paper. '
         'New notes are added every week.'),
    ])
    body = f"""
    <header class="cat-hero cat-hero-sm">
      <p class="cat-eyebrow">Revision notes</p>
      <h1>Cambridge revision notes, chapter by chapter</h1>
      <p class="cat-lede">Clear notes written against the official syllabus - definitions,
        worked examples, common mistakes - each one linked to the past-paper questions on the
        same chapter. {total} notes so far, with more added every week.</p>
      <div class="cat-actions"><a class="cat-btn" href="#boards">Find your subject</a>
        <a class="cat-btn cat-btn-ghost" href="/resources">Teachers' notes &amp; books</a></div>
    </header>
    {_picker(user)}
    <section class="ui-compare">
      <article class="is-here"><h3>{ui.icon("notes")} PrepWithTee notes <small>you are here</small></h3>
        <p>Written by us, chapter by chapter against the syllabus. Every note links to the past-paper
          questions on the same chapter.</p><a href="#boards">Browse notes {ui.icon("arrow")}</a></article>
      <article><h3>{ui.icon("resources")} Resources</h3><p>Famous teachers' PDF notes (Sir Hamiz,
        Zainematics, Mathlete by Saad ...), textbooks, solved worksheets, syllabuses and planners.</p>
        <a href="/resources">Open resources {ui.icon("arrow")}</a></article>
    </section>
    {ui.steps([
        ("Read one note", "Start with the chapter you are studying in class. Each note is 5-10 minutes."),
        ("Make it yours", "Use the pen to annotate, or save key lines to My notes and flashcards."),
        ("Practise straight away", "Every note ends with <b>Practise this chapter</b> - real past-paper questions."),
        ("Come back before the exam", "The chapter page lists what you need to know; tick it off."),
    ], "How to study with notes", "ui-steps-row")}
    {faq_html}"""
    return _page(title="Cambridge Revision Notes | O Level, IGCSE & A Level — PrepWithTee",
                 desc="Free Cambridge O Level, IGCSE and A Level revision notes, organised by syllabus "
                      "chapter, each linked to the matching past-paper questions.",
                 path="/notes", body=body, user=user, ld=[faq_ld], crumbs=[("Home", "/"), ("Notes", "/notes")])


@router.get("/notes/{board}", response_class=HTMLResponse)
def notes_board(board: str, user: dict | None = Depends(_auth.maybe_user)):
    if board not in BOARD_SHORT:
        raise HTTPException(404, "Unknown board")
    body = f"""
    <header class="cat-hero cat-hero-sm">
      <p class="cat-eyebrow">Revision notes · Cambridge {BOARD_SHORT[board]}</p>
      <h1>{BOARD_SHORT[board]} revision notes</h1>
      <p class="cat-lede">Pick a subject to see its syllabus chapters and the notes for each.</p>
      <div class="cat-actions"><a class="cat-btn cat-btn-ghost" href="/resources/{board}">{BOARD_SHORT[board]} teachers' notes &amp; books</a></div>
    </header>
    {_picker(user, board)}"""
    return _page(title=f"Cambridge {BOARD_SHORT[board]} Revision Notes — PrepWithTee",
                 desc=f"Cambridge {BOARD_SHORT[board]} revision notes by syllabus chapter.",
                 path=f"/notes/{board}", body=body, user=user,
                 crumbs=[("Home", "/"), ("Notes", "/notes"), (BOARD_SHORT[board], f"/notes/{board}")])


def _subject_or_404(board: str, subject: str) -> dict:
    s = _catalog.find_subject(board, subject)
    if s is None:
        raise HTTPException(404, "Unknown subject")
    return s


_CH_TONES = ["lav", "blue", "green", "orange", "pink", "teal", "yellow"]


def _chapter_card(code: str, ch: dict, n: int = 0) -> str:
    """One chapter on the subject page: numbered, colour-cycled, with its
    syllabus subtopics ALWAYS listed (tutor, 2026-09-28 - no click to expand)."""
    notes = index().get(code, {}).get(ch["slug"], [])
    covered = {x["subtopic"] for x in notes if x.get("subtopic")}
    subs = "".join(f'<li class="{"is-on" if x["name"] in covered else ""}">{_e(x["name"])}</li>'
                   for x in ch["subtopics"])
    note_links = "".join(
        f'<li><a href="{notes_url(code, ch["slug"], x["slug"])}">{_e(x["title"])}</a>'
        f'<span>{x["minutes"]} min</span></li>' for x in notes)
    tone = _CH_TONES[n % len(_CH_TONES)]
    badge = (f'<span class="nt-badge">{len(notes)} note{"s" if len(notes) != 1 else ""}</span>' if notes
             else '<span class="nt-soon">Coming soon</span>')
    return f"""
    <article class="nt-ch cat-tone-{tone}{' has-notes' if notes else ''}" id="ch-{ch['slug']}" data-q="{_e((ch['display'] + ' ' + ' '.join(x['name'] for x in ch['subtopics'])).lower())}">
      <header>
        <span class="nt-ch-num">{n + 1:02d}</span>
        <a class="nt-ch-name" href="{notes_url(code, ch['slug'])}">{_e(ch['display'])}</a>
        {badge}
      </header>
      {f'<ul class="nt-notes">{note_links}</ul>' if notes else ''}
      {f'<div class="nt-subs"><p>{len(ch["subtopics"])} syllabus subtopic{"s" if len(ch["subtopics"]) != 1 else ""}</p><ul>{subs}</ul></div>'
       if ch['subtopics'] else ''}
      <footer><a class="nt-read" href="{notes_url(code, ch['slug'])}">Open chapter</a>
        <a class="nt-practise" href="{_practise(code, ch['name'])}">Practise questions →</a></footer>
    </article>"""


@router.get("/notes/{board}/{subject}", response_class=HTMLResponse)
def notes_subject(board: str, subject: str, user: dict | None = Depends(_auth.maybe_user)):
    s = _subject_or_404(board, subject)
    code = s["code"]
    chs = _catalog.chapters(code)
    by = {c["name"]: c for c in chs}
    groups = _catalog.paper_groups(code)
    order = {c["name"]: i for i, c in enumerate(chs)}
    if groups:
        tree = "".join(
            f'<section class="nt-group"><h2 class="cat-group">{_e(g["eyebrow"])} · {_e(g["title"])}'
            + (f' <span class="cat-level cat-level-{g["level"]}">{"AS Level" if g["level"] == "AS" else "A Level"}</span>'
               if g["level"] else "")
            + f'</h2><div class="nt-chs">{"".join(_chapter_card(code, by[n], order[n]) for n in g["chapters"] if n in by)}</div></section>'
            for g in groups)
    else:
        tree = f'<div class="nt-chs">{"".join(_chapter_card(code, c, i) for i, c in enumerate(chs))}</div>'
    meta = subject_meta(code)
    n = _count(code)
    covered = len(index().get(code, {}))
    lede = meta.get("description") or (
        f"Revision notes for Cambridge {BOARD_SHORT[board]} {s['plain']} ({code}), organised by the "
        f"official syllabus chapters.")
    guide = "".join(f"<li>{_e(x)}</li>" for x in meta.get("study_guide", []))
    first = next(iter(_ordered_notes(code)), None)
    import resources as _res
    import ui
    res_link = (f'<a class="cat-btn cat-btn-ghost" href="{_res.subject_url(code)}">Teachers\' notes &amp; books</a>'
                if _res.has_subject(code) else "")
    body = f"""
    {ui.subject_tabs(code, "notes")}
    <header class="cat-hero cat-hero-sm cat-tone-{s['tone']}">
      <p class="cat-eyebrow">Revision notes · Cambridge {BOARD_SHORT[board]} · {code}</p>
      <h1>{_e(s['plain'])} {code} revision notes</h1>
      <p class="cat-lede">{_e(lede)}</p>
      <dl class="cat-stats">
        <div><dt>Notes</dt><dd>{n}</dd></div>
        <div><dt>Chapters covered</dt><dd>{covered} / {len(chs)}</dd></div>
      </dl>
      <div class="cat-actions">
        {f'<a class="cat-btn" href="{notes_url(code, first["chapter"], first["slug"])}">Start reading</a>' if first else ''}
        {res_link}
      </div>
    </header>
    {f'<details class="nt-guide"><summary>How to use these notes</summary><ul>{guide}</ul></details>' if guide else ''}
    {ui.page_search("Search chapters and subtopics, e.g. " + (chs[0]["display"] if chs else "forces"), ".nt-ch")}
    <div class="nt-tree">{tree}</div>"""
    ld = [{"@context": "https://schema.org", "@type": "Course",
           "name": f"Cambridge {BOARD_SHORT[board]} {s['plain']} ({code}) revision notes",
           "description": lede[:300],
           "provider": {"@type": "Organization", "name": "PrepWithTee", "sameAs": _catalog.SITE_ORIGIN}}]
    return _page(title=f"{s['plain']} {code} Revision Notes | Cambridge {BOARD_SHORT[board]} — PrepWithTee",
                 desc=lede[:300], path=notes_url(code), body=body, user=user, ld=ld,
                 noindex=n == 0,
                 crumbs=[("Home", "/"), ("Notes", "/notes"), (BOARD_SHORT[board], f"/notes/{board}"),
                         (f"{s['plain']} {code}", notes_url(code))])


def _chapter_or_404(code: str, chapter: str) -> dict:
    ch = next((c for c in _catalog.chapters(code) if c["slug"] == chapter), None)
    if ch is None:
        raise HTTPException(404, "Unknown chapter")
    return ch


@router.get("/notes/{board}/{subject}/{chapter}", response_class=HTMLResponse)
def notes_chapter(board: str, subject: str, chapter: str, user: dict | None = Depends(_auth.maybe_user)):
    s = _subject_or_404(board, subject)
    code = s["code"]
    ch = _chapter_or_404(code, chapter)
    notes = index().get(code, {}).get(chapter, [])
    meta = chapter_meta(code, chapter)
    covered = {n["subtopic"] for n in notes if n.get("subtopic")}
    outcomes = "".join(f"<li>{_e(x)}</li>" for x in meta.get("learning_outcomes", []))
    cards = "".join(f"""
      <a class="nt-note-card" href="{notes_url(code, chapter, n['slug'])}">
        <b>{_e(n['title'])}</b>
        <span>{_e(n['subtopic'] or '')}{' · ' if n.get('subtopic') else ''}{n['minutes']} min read</span>
      </a>""" for n in notes)
    subs = "".join(f'<li class="{"is-on" if x["name"] in covered else ""}">{_e(x["name"])}</li>'
                   for x in ch["subtopics"])
    chs = _catalog.chapters(code)
    i = next(k for k, c in enumerate(chs) if c["slug"] == chapter)
    prev_c, next_c = (chs[i - 1] if i else None), (chs[i + 1] if i + 1 < len(chs) else None)
    facts = "".join(f"<div><dt>{k}</dt><dd>{_e(meta[f])}</dd></div>" for k, f in
                    (("Syllabus", "syllabus_ref"), ("Weighting", "weighting"), ("Tier", "tier_split")) if meta.get(f))
    lede = (f"{len(notes)} revision note{'s' if len(notes) != 1 else ''} on {ch['display']} for Cambridge "
            f"{BOARD_SHORT[board]} {s['plain']} ({code})" if notes else
            f"Notes on {ch['display']} for Cambridge {BOARD_SHORT[board]} {s['plain']} ({code}) are coming soon")
    import ui
    soon = ui.callout("Our notes for this chapter are being written. Meanwhile, read a teacher's notes in "
                      '<a href="/resources">Resources</a> and practise its past-paper questions.',
                      tone="blue", icon_name="notes")
    body = f"""
    {ui.subject_tabs(code, "notes")}
    <header class="cat-hero cat-hero-sm cat-tone-{s['tone']}">
      <p class="cat-eyebrow">{_e(s['plain'])} {code} · Chapter {i + 1} of {len(chs)}</p>
      <h1>{_e(ch['display'])}</h1>
      <p class="cat-lede">{_e(lede)}. {ch['count']:,} past-paper questions on this chapter to practise.</p>
      {f'<dl class="cat-stats">{facts}</dl>' if facts else ''}
      <div class="cat-actions"><a class="cat-btn" href="{_practise(code, ch['name'])}">Practise this chapter</a>
        <a class="cat-btn cat-btn-ghost" href="{notes_url(code)}">All {_e(s['plain'])} notes</a></div>
    </header>
    {f'<h2 class="cat-group">Notes</h2><div class="nt-note-cards">{cards}</div>' if notes else
     soon}
    {f'<h2 class="cat-group">What you need to know</h2><ul class="nt-outcomes">{outcomes}</ul>' if outcomes else ''}
    {f'<h2 class="cat-group">Syllabus subtopics</h2><ul class="nt-sublist">{subs}</ul>' if subs else ''}
    <nav class="nt-pn">
      {f'<a href="{notes_url(code, prev_c["slug"])}">← {_e(prev_c["display"])}</a>' if prev_c else '<span></span>'}
      {f'<a href="{notes_url(code, next_c["slug"])}">{_e(next_c["display"])} →</a>' if next_c else '<span></span>'}
    </nav>"""
    return _page(title=f"{ch['display']} — {s['plain']} {code} Revision Notes | PrepWithTee",
                 desc=lede[:300], path=notes_url(code, chapter), body=body, user=user, noindex=not notes,
                 crumbs=[("Home", "/"), ("Notes", "/notes"), (BOARD_SHORT[board], f"/notes/{board}"),
                         (f"{s['plain']} {code}", notes_url(code)), (ch["display"], notes_url(code, chapter))])


@router.get("/notes/{board}/{subject}/{chapter}/{note}", response_class=HTMLResponse)
def notes_note(board: str, subject: str, chapter: str, note: str,
               user: dict | None = Depends(_auth.maybe_user)):
    s = _subject_or_404(board, subject)
    code = s["code"]
    ch = _chapter_or_404(code, chapter)
    notes = index().get(code, {}).get(chapter, [])
    n = next((x for x in notes if x["slug"] == note), None)
    if n is None:
        raise HTTPException(404, "Note not found")
    _meta, content = _read_meta(n["path"])
    toc = "".join(f'<li><a href="#{_e(i)}">{re.sub(r"<[^>]+>", "", t)}</a></li>' for i, t in _H2_RE.findall(content))
    seq = _ordered_notes(code)
    k = next(j for j, x in enumerate(seq) if x["slug"] == note and x["chapter"] == chapter)
    prev_n, next_n = (seq[k - 1] if k else None), (seq[k + 1] if k + 1 < len(seq) else None)
    by = {c["slug"]: c for c in _catalog.chapters(code)}
    def side_item(c: str) -> str:
        here = c == chapter
        inner = ""
        if here:
            inner = "<ul>" + "".join(
                f'<li><a class="{"is-here" if x["slug"] == note else ""}" '
                f'href="{notes_url(code, c, x["slug"])}" data-note="{code}/{c}/{x["slug"]}">{_e(x["title"])}</a></li>'
                for x in index()[code][c]) + "</ul>"
        return (f'<li class="{"is-here" if here else ""}"><a href="{notes_url(code, c)}">'
                f'{_e(by[c]["display"])}</a>{inner}</li>')
    side_chs = "".join(side_item(c["slug"]) for c in _catalog.chapters(code)
                       if c["slug"] in index().get(code, {}))
    plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", content)).strip()
    desc = f"{n['title']} — {ch['display']}, Cambridge {BOARD_SHORT[board]} {s['plain']} ({code}). {plain[:180]}"
    body = f"""
    <div class="nt-layout">
      <aside class="nt-side" id="nt-side" aria-label="{_e(s['plain'])} notes">
        <p class="nt-side-head">{_e(s['plain'])} {code}</p>
        <ul class="nt-side-list">{side_chs}</ul>
      </aside>
      <article class="nt-article" data-note="{code}/{chapter}/{note}">
        <header class="nt-head">
          <p class="cat-eyebrow">{_e(ch['display'])}</p>
          <h1>{_e(n['title'])}</h1>
          <p class="nt-meta">{f'<span class="nt-chip">{_e(n["subtopic"])}</span>' if n.get('subtopic') else ''}
            {f'<span class="nt-chip nt-tier">{_e(n["tier"])}</span>' if n.get('tier') else ''}
            <span>{n['minutes']} min read</span></p>
          {f'<nav class="nt-toc" aria-label="On this page"><b>On this page</b><ol>{toc}</ol></nav>' if toc else ''}
        </header>
        <div class="nt-body note-body">{content}</div>
        <aside class="nt-cta">
          <div><b>Test yourself on {_e(ch['display'])}</b>
            <span>{ch['count']:,} real Cambridge past-paper questions, with mark schemes.</span></div>
          <a class="cat-btn" href="{_practise(code, ch['name'])}">Practise this chapter →</a>
        </aside>
        <nav class="nt-pn">
          {f'<a href="{notes_url(code, prev_n["chapter"], prev_n["slug"])}"><small>Previous</small>{_e(prev_n["title"])}</a>' if prev_n else '<span></span>'}
          {f'<a class="nt-next" href="{notes_url(code, next_n["chapter"], next_n["slug"])}"><small>Next</small>{_e(next_n["title"])}</a>' if next_n else '<span></span>'}
        </nav>
      </article>
    </div>
    <button type="button" class="nt-side-btn" data-nt-side aria-controls="nt-side" aria-expanded="false">☰ Notes</button>
    <div class="nt-progress" aria-hidden="true"><i></i></div>"""
    ld = [{"@context": "https://schema.org", "@type": "Article", "headline": n["title"],
           "about": f"{ch['display']} — Cambridge {BOARD_SHORT[board]} {s['plain']} ({code})",
           "educationalLevel": f"Cambridge {BOARD_SHORT[board]}", "inLanguage": "en",
           "author": {"@type": "Organization", "name": "PrepWithTee"},
           "publisher": {"@type": "Organization", "name": "PrepWithTee", "sameAs": _catalog.SITE_ORIGIN},
           "mainEntityOfPage": f"{_catalog.SITE_ORIGIN}{notes_url(code, chapter, note)}"}]
    return _page(title=f"{n['title']} — {s['plain']} {code} Notes | PrepWithTee", desc=desc[:300],
                 path=notes_url(code, chapter, note), body=body, user=user, ld=ld, katex=True, note=True,
                 crumbs=[("Home", "/"), ("Notes", "/notes"), (BOARD_SHORT[board], f"/notes/{board}"),
                         (f"{s['plain']} {code}", notes_url(code)), (ch["display"], notes_url(code, chapter)),
                         (n["title"], notes_url(code, chapter, note))])


# ── Old URLs ──────────────────────────────────────────────────────────────────

def _redirects() -> dict:
    return _json(NOTES_DIR / "_redirects.json")


@router.get("/note.html", include_in_schema=False)
def legacy_note(code: str = "", ch: str = "", st: str = ""):
    if code not in SUBJECTS:
        return RedirectResponse("/notes", 301)
    new = _redirects().get(code, {}).get("notes", {}).get(f"{ch}/{st}")
    if new:
        c, n = new.split("/", 1)
        return RedirectResponse(notes_url(code, c, n), 301)
    c = _redirects().get(code, {}).get("chapters", {}).get(ch)
    return RedirectResponse(notes_url(code, c) if c else notes_url(code), 301)


@router.get("/chapter.html", include_in_schema=False)
def legacy_chapter(code: str = "", ch: str = ""):
    if code not in SUBJECTS:
        return RedirectResponse("/notes", 301)
    c = _redirects().get(code, {}).get("chapters", {}).get(ch)
    return RedirectResponse(notes_url(code, c) if c else notes_url(code), 301)


@router.get("/notes-view.html", include_in_schema=False)
def legacy_notes_view():
    """The old interactive-notes hub, superseded by /notes (2026-09-27)."""
    return RedirectResponse("/notes", 301)


@router.get("/subject.html", include_in_schema=False)
def legacy_subject(code: str = ""):
    return RedirectResponse(notes_url(code) if code in SUBJECTS else "/notes", 301)


def sitemap_paths() -> list[str]:
    """Only pages with real notes (empty 'coming soon' pages are noindex)."""
    paths = ["/notes"] + [f"/notes/{b}" for b in BOARD_SHORT]
    for code, chs in index().items():
        if code not in SUBJECTS:
            continue
        paths.append(notes_url(code))
        for ch, notes in chs.items():
            paths.append(notes_url(code, ch))
            paths += [notes_url(code, ch, n["slug"]) for n in notes]
    return paths


def sitemap_lastmod() -> dict[str, float]:
    """{url: newest file mtime} for every sitemap page - a note's own file, a
    chapter/subject/board/hub the newest note (or _chapter/_subject.json) under it."""
    out: dict[str, float] = {}

    def bump(url: str, t: float) -> None:
        out[url] = max(out.get(url, 0.0), t)

    def mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    for code, chs in index().items():
        if code not in SUBJECTS:
            continue
        up = [notes_url(code), f"/notes/{SUBJECTS[code]['board_slug']}", "/notes"]
        for u in up:
            bump(u, mtime(NOTES_DIR / code / "_subject.json"))
        for ch, notes in chs.items():
            t_ch = mtime(NOTES_DIR / code / ch / "_chapter.json")
            for n in notes:
                t = mtime(n["path"])
                out[notes_url(code, ch, n["slug"])] = t
                t_ch = max(t_ch, t)
            for u in [notes_url(code, ch)] + up:
                bump(u, t_ch)
    return {u: t for u, t in out.items() if t}
