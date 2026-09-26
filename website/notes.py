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
NOTES_V = "20260926a"                     # bump with notes.css / notes-page.js
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


def _subject_card(code: str) -> str:
    s = SUBJECTS[code]
    n = _count(code)
    chs = len(index().get(code, {}))
    meta = (f"{n} note{'s' if n != 1 else ''} · {chs} chapter{'s' if chs != 1 else ''}"
            if n else "Notes coming soon")
    return f"""
    <a class="cat-subj cat-tone-{s['tone']} nt-card{' is-soon' if not n else ''}" href="{notes_url(code)}">
      <div class="cat-subj-top"><span class="cat-code">{code}</span>
        {'<span class="nt-badge">Notes</span>' if n else '<span class="nt-soon">Coming soon</span>'}</div>
      <h3>{_e(s['plain'])}</h3>
      <p class="cat-subj-meta">{meta}</p>
    </a>"""


def _board_grid(board: str) -> str:
    codes = [c for c, s in SUBJECTS.items() if s["board_slug"] == board]
    codes.sort(key=lambda c: -_count(c))
    return f'<div class="cat-grid">{"".join(_subject_card(c) for c in codes)}</div>'


# ── Pages ─────────────────────────────────────────────────────────────────────

@router.get("/notes", response_class=HTMLResponse)
def notes_hub(user: dict | None = Depends(_auth.maybe_user)):
    total = sum(_count(c) for c in SUBJECTS)
    sections = "".join(f'<h2 class="cat-group"><a href="/notes/{b}">{BOARD_SHORT[b]}</a></h2>{_board_grid(b)}'
                       for b in BOARD_SHORT)
    body = f"""
    <header class="cat-hero cat-hero-sm">
      <p class="cat-eyebrow">Revision notes</p>
      <h1>Cambridge revision notes, chapter by chapter</h1>
      <p class="cat-lede">Clear notes written against the official syllabus - definitions,
        worked examples, common mistakes - each one linked to the past-paper questions on the
        same chapter. {total} notes so far, with more added every week.</p>
    </header>
    {sections}"""
    return _page(title="Cambridge Revision Notes | O Level, IGCSE & A Level — PrepWithTee",
                 desc="Free Cambridge O Level, IGCSE and A Level revision notes, organised by syllabus "
                      "chapter, each linked to the matching past-paper questions.",
                 path="/notes", body=body, user=user, crumbs=[("Home", "/"), ("Notes", "/notes")])


@router.get("/notes/{board}", response_class=HTMLResponse)
def notes_board(board: str, user: dict | None = Depends(_auth.maybe_user)):
    if board not in BOARD_SHORT:
        raise HTTPException(404, "Unknown board")
    body = f"""
    <header class="cat-hero cat-hero-sm">
      <p class="cat-eyebrow">Revision notes · Cambridge {BOARD_SHORT[board]}</p>
      <h1>{BOARD_SHORT[board]} revision notes</h1>
      <p class="cat-lede">Pick a subject to see its syllabus chapters and the notes for each.</p>
    </header>
    {_board_grid(board)}"""
    return _page(title=f"Cambridge {BOARD_SHORT[board]} Revision Notes — PrepWithTee",
                 desc=f"Cambridge {BOARD_SHORT[board]} revision notes by syllabus chapter.",
                 path=f"/notes/{board}", body=body, user=user,
                 crumbs=[("Home", "/"), ("Notes", "/notes"), (BOARD_SHORT[board], f"/notes/{board}")])


def _subject_or_404(board: str, subject: str) -> dict:
    s = _catalog.find_subject(board, subject)
    if s is None:
        raise HTTPException(404, "Unknown subject")
    return s


def _chapter_card(code: str, ch: dict) -> str:
    notes = index().get(code, {}).get(ch["slug"], [])
    covered = {n["subtopic"] for n in notes if n.get("subtopic")}
    subs = "".join(f'<li class="{"is-on" if x["name"] in covered else ""}">{_e(x["name"])}</li>'
                   for x in ch["subtopics"])
    note_links = "".join(
        f'<li><a href="{notes_url(code, ch["slug"], n["slug"])}">{_e(n["title"])}</a>'
        f'<span>{n["minutes"]} min</span></li>' for n in notes)
    return f"""
    <article class="nt-ch{' has-notes' if notes else ''}" id="ch-{ch['slug']}">
      <header>
        <a class="nt-ch-name" href="{notes_url(code, ch['slug'])}">{_e(ch['display'])}</a>
        {f'<span class="nt-badge">{len(notes)} note{"s" if len(notes) != 1 else ""}</span>' if notes
         else '<span class="nt-soon">Coming soon</span>'}
      </header>
      {f'<ul class="nt-notes">{note_links}</ul>' if notes else ''}
      {f'<details class="nt-subs"><summary>{len(ch["subtopics"])} syllabus subtopics</summary><ul>{subs}</ul></details>'
       if ch['subtopics'] else ''}
      <a class="nt-practise" href="{_practise(code, ch['name'])}">Practise this chapter →</a>
    </article>"""


@router.get("/notes/{board}/{subject}", response_class=HTMLResponse)
def notes_subject(board: str, subject: str, user: dict | None = Depends(_auth.maybe_user)):
    s = _subject_or_404(board, subject)
    code = s["code"]
    chs = _catalog.chapters(code)
    by = {c["name"]: c for c in chs}
    groups = _catalog.paper_groups(code)
    if groups:
        tree = "".join(
            f'<section class="nt-group"><h2 class="cat-group">{_e(g["eyebrow"])} · {_e(g["title"])}'
            + (f' <span class="cat-level cat-level-{g["level"]}">{"AS Level" if g["level"] == "AS" else "A Level"}</span>'
               if g["level"] else "")
            + f'</h2><div class="nt-chs">{"".join(_chapter_card(code, by[n]) for n in g["chapters"] if n in by)}</div></section>'
            for g in groups)
    else:
        tree = f'<div class="nt-chs">{"".join(_chapter_card(code, c) for c in chs)}</div>'
    meta = subject_meta(code)
    n = _count(code)
    covered = len(index().get(code, {}))
    lede = meta.get("description") or (
        f"Revision notes for Cambridge {BOARD_SHORT[board]} {s['plain']} ({code}), organised by the "
        f"official syllabus chapters.")
    guide = "".join(f"<li>{_e(x)}</li>" for x in meta.get("study_guide", []))
    first = next(iter(_ordered_notes(code)), None)
    body = f"""
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
        <a class="cat-btn cat-btn-ghost" href="{_catalog.subject_url(code)}">Topical past papers</a>
      </div>
    </header>
    {f'<details class="nt-guide"><summary>How to use these notes</summary><ul>{guide}</ul></details>' if guide else ''}
    {tree}"""
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
    body = f"""
    <header class="cat-hero cat-hero-sm cat-tone-{s['tone']}">
      <p class="cat-eyebrow">{_e(s['plain'])} {code} · Chapter</p>
      <h1>{_e(ch['display'])}</h1>
      <p class="cat-lede">{_e(lede)}. {ch['count']:,} past-paper questions on this chapter to practise.</p>
      {f'<dl class="cat-stats">{facts}</dl>' if facts else ''}
      <div class="cat-actions"><a class="cat-btn" href="{_practise(code, ch['name'])}">Practise this chapter</a>
        <a class="cat-btn cat-btn-ghost" href="{notes_url(code)}">All {_e(s['plain'])} notes</a></div>
    </header>
    {f'<h2 class="cat-group">Notes</h2><div class="nt-note-cards">{cards}</div>' if notes else
     '<p class="nt-empty">Notes for this chapter are being written. Meanwhile, practise its past-paper questions.</p>'}
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
