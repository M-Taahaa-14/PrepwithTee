"""Resources: well-known teachers' PDF notes, books and worksheets (SSR).

    /resources                                   hub: what is here, how to use it, boards
    /resources/{board}                           one board's subjects
    /resources/{board}/{subject}                 one subject: collections (teacher / source)
    /resources/{board}/{subject}/{folder...}     one folder inside it
    /resources/library/{slug}[/{folder...}]      board-wide shelves (syllabuses, planners)
    /resources/view?f=<rel>                      in-site viewer (PDF.js, paper theme, annotations)

Resources are OTHER PEOPLE's material we curate (Sir Hamiz, Zainematics,
Mathlete by Saad, Save My Exams ...). PrepWithTee's own notes live under /notes;
the two sections say so and link to each other.

The folder is the content, exactly as for the old resources.html (see
data/resources/README.md): one top-level folder per subject ("IGCSE Physics
0625", code read from the name or _meta.json) or per shelf (no code). Files are
served by app.py's /api/resources/file. The old /resources.html 301s here.
"""

import hashlib
import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

import auth as _auth
import catalog as _catalog

router = APIRouter()

ROOT = Path(__file__).resolve().parent.parent
RES_DIR = ROOT / "data" / "resources"
RES_V = "20261005a"                        # bump with resource-viewer.js / catalog.css
EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".docx", ".pptx", ".xlsx", ".zip", ".txt"}
INLINE = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
_e = _catalog._e
SUBJECTS = _catalog.SUBJECTS
BOARD_SHORT = _catalog.BOARD_SHORT
_CODE_RE = re.compile(r"\b(\d{4})\b")
_KIND_ICON = {".pdf": "PDF", ".png": "IMG", ".jpg": "IMG", ".jpeg": "IMG", ".webp": "IMG",
              ".docx": "DOC", ".pptx": "PPT", ".xlsx": "XLS", ".zip": "ZIP", ".txt": "TXT"}


# ── Index (rebuilt at most once a minute) ────────────────────────────────────

_cache: dict = {"at": 0.0, "idx": None}
_lock = threading.Lock()


def _nice(name: str) -> str:
    return re.sub(r"\s{2,}", " ", re.sub(r"[_]+", " ", Path(name).stem)).strip()


def _natural(name: str) -> list:
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", name)]


def _slug(name: str) -> str:
    return _catalog.slugify(name) or "folder"


def _scan(path: Path) -> dict | None:
    """{name, title, slug, dirs:[...], files:[...], count} for a folder (None if empty)."""
    dirs, files = [], []
    try:
        kids = sorted(path.iterdir(), key=lambda x: (x.is_file(), _natural(x.name)))
    except OSError:
        return None
    for c in kids:
        if c.name.startswith((".", "_")):
            continue
        if c.is_dir():
            d = _scan(c)
            if d:
                dirs.append(d)
        elif c.suffix.lower() in EXTS:
            try:
                size = c.stat().st_size
            except OSError:
                continue
            files.append({"name": c.name, "title": _nice(c.name), "ext": c.suffix.lower(),
                          "rel": c.relative_to(RES_DIR).as_posix(), "size": size})
    count = len(files) + sum(d["count"] for d in dirs)
    if not count:
        return None
    # slugs unique among siblings
    seen: dict[str, int] = {}
    for d in dirs:
        base = _slug(d["name"])
        seen[base] = seen.get(base, 0) + 1
        d["slug"] = base if seen[base] == 1 else f"{base}-{seen[base]}"
    return {"name": path.name, "title": _nice(path.name) if path.is_dir() else path.name,
            "dirs": dirs, "files": files, "count": count}


def index() -> dict:
    """{"subjects": {code: category}, "shelves": {slug: category}}. A category is a
    scanned folder plus its _meta.json fields (title, description, icon)."""
    with _lock:
        if _cache["idx"] is not None and time.time() - _cache["at"] < 60:
            return _cache["idx"]
        subjects, shelves = {}, {}
        if RES_DIR.is_dir():
            for d in sorted(RES_DIR.iterdir()):
                if not d.is_dir() or d.name.startswith((".", "_")):
                    continue
                tree = _scan(d)
                if not tree:
                    continue
                meta = {}
                try:
                    meta = json.loads((d / "_meta.json").read_text("utf-8"))
                except Exception:
                    pass
                tree["meta"] = meta
                m = _CODE_RE.search(d.name) or _CODE_RE.search(str(meta.get("subject", "")))
                if m and m.group(1) in SUBJECTS:
                    subjects[m.group(1)] = tree
                else:
                    tree["slug"] = _slug(d.name)
                    shelves[tree["slug"]] = tree
        _cache.update(at=time.time(), idx={"subjects": subjects, "shelves": shelves})
        return _cache["idx"]


def has_subject(code: str) -> bool:
    return code in index()["subjects"]


def subject_url(code: str) -> str:
    s = SUBJECTS[code]
    return f"/resources/{s['board_slug']}/{s['slug']}"


def view_url(rel: str) -> str:
    return f"/resources/view?f={quote(rel)}"


def doc_key(rel: str) -> str:
    """Annotation key for one resource file (mcq._DOC accepts res:<16 hex>)."""
    return "res:" + hashlib.sha1(rel.encode("utf-8")).hexdigest()[:16]


def _walk(tree: dict, parts: list[str]) -> tuple[dict, list[dict]]:
    """Follow folder slugs down the tree -> (folder, [ancestors incl. it])."""
    node, trail = tree, []
    for p in parts:
        node = next((d for d in node["dirs"] if d["slug"] == p), None)
        if node is None:
            raise HTTPException(404, "No such folder")
        trail.append(node)
    return node, trail


def _size(n: int) -> str:
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{max(1, round(n / 1024))} KB"


def _all_files(node: dict) -> list[dict]:
    return node["files"] + [f for d in node["dirs"] for f in _all_files(d)]


# ── Rendering ────────────────────────────────────────────────────────────────

def _file_rows(files: list[dict]) -> str:
    rows = []
    for f in files:
        kind = _KIND_ICON.get(f["ext"], "FILE")
        href = _file_href(f)
        rows.append(f'<li data-q="{_e(f["title"].lower())}"><a class="rs-file" href="{_e(href)}"{" download" if f["ext"] not in INLINE else ""}>'
                    f'<i class="rs-kind rs-kind-{kind.lower()}">{kind}</i>'
                    f'<span class="rs-file-name">{_e(f["title"])}</span>'
                    f'<small>{_size(f["size"])}</small></a></li>')
    return f'<ul class="rs-files">{"".join(rows)}</ul>' if rows else ""


def _file_href(f: dict) -> str:
    return view_url(f["rel"]) if f["ext"] in INLINE else f"/api/resources/file?rel={quote(f['rel'])}"


def _subtree(node: dict, url: str, path: list[str] | None = None) -> list[dict]:
    """Every folder and file BELOW `node` (not beside or above it), for the
    page search: a search inside a folder covers its subfolders too."""
    import ui
    path = path or []
    out = []
    for d in node["dirs"]:
        href = f"{url}/{d['slug']}"
        out.append(ui.deep_entry(d["title"], href, "Folder", path,
                                 extra=f"{d['count']} files"))
        out += _subtree(d, href, path + [d["title"]])
    for f in node["files"]:
        out.append(ui.deep_entry(f["title"], _file_href(f), _KIND_ICON.get(f["ext"], "FILE"), path,
                                 extra=f["ext"].lstrip("."), download=f["ext"] not in INLINE))
    return out


def _search(node: dict, url: str, placeholder: str, scope: str) -> str:
    import ui
    if not (node["dirs"] or len(node["files"]) > 6):
        return ""
    return ui.page_search(placeholder, ".rs-folder, .rs-files li", "section",
                          deep=_subtree(node, url), scope=scope)


_FOLDER_TONES = ["lav", "blue", "green", "orange", "pink", "teal", "yellow"]


def _folder_cards(dirs: list[dict], base: str) -> str:
    cards = []
    for i, d in enumerate(dirs):
        # search text = the folder and every file inside it, so "kinematics"
        # finds the teacher folder that holds a kinematics PDF
        q = " ".join([d["title"]] + [f["title"] for f in _all_files(d)]).lower()
        sub = f"{len(d['dirs'])} folders · " if d["dirs"] else ""
        preview = ", ".join(x["title"] for x in (d["dirs"][:3] or d["files"][:3]))
        cards.append(f'<a class="rs-folder cat-tone-{_FOLDER_TONES[i % len(_FOLDER_TONES)]}" '
                     f'href="{_e(base)}/{d["slug"]}" data-q="{_e(q[:4000])}">'
                     f'<span class="rs-folder-ic" aria-hidden="true"></span>'
                     f'<b>{_e(d["title"])}</b><small>{sub}{d["count"]} file{"s" if d["count"] != 1 else ""}</small>'
                     f'{f"<span class=rs-folder-peek>{_e(preview)}</span>" if preview else ""}</a>')
    return f'<div class="rs-folders">{"".join(cards)}</div>' if cards else ""


def _page(*, title, desc, path, body, crumbs, user, noindex=False, ld=None):
    state = _catalog._student_state(user)
    return _catalog._respond(_catalog._shell(title=title, desc=desc, path=path, body=body, crumbs=crumbs,
                                             state=state, noindex=noindex, ld=ld), bool(user))


def _picker(user: dict | None, board: str | None = None) -> str:
    """The shared board/subject picker (ui.picker) over subjects with resources."""
    import ui
    state = _catalog._student_state(user)
    idx = index()["subjects"]
    boards = [board] if board else ui.board_order(state)
    tiles = {}
    for b in boards:
        tiles[b] = []
        for c in ui.codes_for(b, state):
            if c not in idx:
                continue
            t = idx[c]
            tiles[b].append(ui.tile(
                code=c, url=subject_url(c), flag="on" if c in state["enrolled"] else "",
                stats=[(f'{t["count"]:,}', "files"), (str(len(t["dirs"])), "collections")],
                actions=[("Open resources", subject_url(c), "primary"),
                         ("Our notes", _notes_url(c), "ghost")]))
    return ui.picker(tiles, state=state, board_links="/resources/{board}" if board else None,
                     active=board or "", empty='<p class="cat-note">Nothing here yet.</p>')


def _notes_url(code: str) -> str:
    import notes
    return notes.notes_url(code)


def _shelf_cards() -> str:
    out = []
    for slug, t in index()["shelves"].items():
        m = t["meta"]
        out.append(f'<a class="rs-shelf" href="/resources/library/{slug}">'
                   f'<span class="rs-shelf-ic">{_e(m.get("icon") or "📚")}</span>'
                   f'<b>{_e(m.get("title") or t["title"])}</b>'
                   f'<span>{_e(m.get("description", ""))}</span><small>{t["count"]} files</small></a>')
    return f'<div class="rs-shelves">{"".join(out)}</div>' if out else ""


# ── Pages ─────────────────────────────────────────────────────────────────────

@router.get("/resources", response_class=HTMLResponse)
def resources_hub(user: dict | None = Depends(_auth.maybe_user)):
    import ui
    idx = index()
    total = sum(t["count"] for t in idx["subjects"].values()) + sum(t["count"] for t in idx["shelves"].values())
    faq_html, faq_ld = ui.faq([
        ("How are Resources different from PrepWithTee notes?",
         'PrepWithTee notes (<a href="/notes">/notes</a>) are written by us against the syllabus and link '
         'straight to past-paper practice. Resources are PDFs from well-known teachers and publishers that '
         'students already trust - kept in one place, sorted by subject.'),
        ("Can I write on the PDFs?",
         "Yes. Open any PDF and use the pen bar. Signed in, your ink is saved to your account; the dark-paper "
         "button turns the page black for night study."),
        ("Who made these notes?",
         "Each folder is named after its author or source (for example a teacher's name or a publisher). "
         "The notes remain their work; we only organise them."),
    ])
    body = f"""
    <header class="cat-hero cat-hero-sm cat-tone-teal">
      <p class="cat-eyebrow">Resources</p>
      <h1>Teachers' notes, books and worksheets - in one place</h1>
      <p class="cat-lede">The PDFs Cambridge students swap in WhatsApp groups, sorted properly: notes from
        well-known teachers, textbooks, solved worksheets, official syllabuses and study planners.
        {total:,} files, each one opens right here with a pen and a dark-paper mode.</p>
      <div class="cat-actions"><a class="cat-btn" href="#boards">Find your subject</a>
        <a class="cat-btn cat-btn-ghost" href="/notes">PrepWithTee notes</a></div>
    </header>
    {_picker(user)}
    <section class="ui-compare">
      <article><h3>{ui.icon("notes")} PrepWithTee notes</h3><p>Our own notes, written chapter by chapter
        against the official syllabus, each linked to its past-paper questions.</p>
        <a href="/notes">Open revision notes {ui.icon("arrow")}</a></article>
      <article class="is-here"><h3>{ui.icon("resources")} Resources <small>you are here</small></h3>
        <p>Other teachers' PDFs, books and worksheets. Great for a second explanation or extra questions.</p>
        <a href="#boards">Browse resources {ui.icon("arrow")}</a></article>
    </section>
    {ui.steps([
        ("Start from the syllabus", "Open the <b>Official Syllabuses</b> shelf and keep your subject's list of topics nearby."),
        ("Read one set of notes well", "Pick one teacher's notes per chapter rather than skimming five."),
        ("Practise straight after", 'Do a <a href="/papers/topical">topical paper</a> on the same chapter the same day.'),
    ], "How to use them", "ui-steps-row")}
    <section><h2 class="ui-h2">For every subject</h2>{_shelf_cards()}</section>
    {faq_html}"""
    return _page(title="Cambridge Notes & Resources - Teachers' PDF Notes, Books, Worksheets | PrepWithTee",
                 desc="Well-known teachers' notes, textbooks, solved worksheets, official syllabuses and "
                      "study planners for Cambridge O Level, IGCSE and A Level - sorted by subject.",
                 path="/resources", body=body, user=user, ld=[faq_ld],
                 crumbs=[("Home", "/"), ("Resources", "/resources")])


@router.get("/resources/view", response_class=HTMLResponse)
def resource_viewer(f: str, user: dict | None = Depends(_auth.maybe_user)):
    path = (RES_DIR / f).resolve()
    if not str(path).startswith(str(RES_DIR.resolve())) or not path.is_file() \
            or path.suffix.lower() not in EXTS:
        raise HTTPException(404, "No such resource")
    rel = path.relative_to(RES_DIR.resolve()).as_posix()
    file_url = f"/api/resources/file?rel={quote(rel)}"
    if path.suffix.lower() not in INLINE:
        return RedirectResponse(file_url, 302)
    # Where it lives, for the back button: the folder page it was listed on.
    idx = index()
    parts = rel.split("/")
    back, back_label = "/resources", "Resources"
    for code, tree in idx["subjects"].items():
        if tree["name"] == parts[0]:
            back, back_label = subject_url(code), f"{SUBJECTS[code]['plain']} {code} resources"
            node = tree
            for p in parts[1:-1]:
                node = next((d for d in node["dirs"] if d["name"] == p), None)
                if node is None:
                    break
                back = f"{back}/{node['slug']}"
                back_label = node["title"]
    for slug, tree in idx["shelves"].items():
        if tree["name"] == parts[0]:
            back, back_label = f"/resources/library/{slug}", tree["meta"].get("title") or tree["title"]
    state = {"title": _nice(path.name), "url": file_url, "rel": rel, "doc": doc_key(rel),
             "kind": "pdf" if path.suffix.lower() == ".pdf" else "img",
             "backUrl": back, "backLabel": back_label, "signedIn": bool(user),
             "filename": path.name}
    import blog as _blog
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="robots" content="noindex">
  <script>try{{var t=localStorage.getItem("theme")||"light";document.documentElement.setAttribute("data-theme",t);var p=localStorage.getItem("pwt-paper");if(p)document.documentElement.setAttribute("data-paper",p)}}catch(e){{}}</script>
  <title>{_e(state['title'])} - Resources - PrepWithTee</title>
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700;800&family=Hanken+Grotesk:wght@400;500;600;700&family=Playfair+Display:wght@700;800&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/styles.css?v={_catalog.STYLES_V}">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf_viewer.min.css">
  <link rel="stylesheet" href="/viewer.css?v={RES_V}">
  <link rel="stylesheet" href="/annotate.css?v={RES_V}">
</head>
<body class="vw-page">
{_blog._nav()}
<main id="vw" class="vw" data-state="loading"></main>
<script id="vw-state" type="application/json">{json.dumps(state)}</script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
<script src="/main.js?v=20261005a"></script>
<script type="module" src="/auth.js?v=20261005a"></script>
<script type="module" src="/resource-viewer.js?v={RES_V}"></script>
</body>
</html>""", headers={"Cache-Control": "private, no-store"})


@router.get("/resources/library/{slug}", response_class=HTMLResponse)
@router.get("/resources/library/{slug}/{folder:path}", response_class=HTMLResponse)
def shelf_page(slug: str, folder: str = "", user: dict | None = Depends(_auth.maybe_user)):
    tree = index()["shelves"].get(slug)
    if tree is None:
        raise HTTPException(404, "No such shelf")
    parts = [p for p in folder.split("/") if p]
    node, trail = _walk(tree, parts)
    title = tree["meta"].get("title") or tree["title"]
    base = f"/resources/library/{slug}"
    crumbs = [("Home", "/"), ("Resources", "/resources"), (title, base)]
    url = base
    for t in trail:
        url += f"/{t['slug']}"
        crumbs.append((t["title"], url))
    h1 = trail[-1]["title"] if trail else title
    body = f"""
    <header class="cat-hero cat-hero-sm cat-tone-blue">
      <p class="cat-eyebrow">Resources · {'Shelf' if not trail else _e(title)}</p>
      <h1>{_e(h1)}</h1>
      <p class="cat-lede">{_e(tree['meta'].get('description', '')) if not trail else f'{node["count"]} files'}</p>
    </header>
    {_search(node, url, "Search " + ("this folder and everything inside it" if trail else "this shelf"),
             f"“{h1}”")}
    <div data-ps-browse>
    {_folder_cards(node['dirs'], url)}
    {_file_rows(node['files'])}
    </div>"""
    return _page(title=f"{h1} - Resources | PrepWithTee", desc=tree["meta"].get("description", title)[:300],
                 path=url, body=body, user=user, crumbs=crumbs, noindex=bool(trail))


@router.get("/resources/{board}", response_class=HTMLResponse)
def resources_board(board: str, user: dict | None = Depends(_auth.maybe_user)):
    if board not in BOARD_SHORT:
        raise HTTPException(404, "Unknown board")
    body = f"""
    <header class="cat-hero cat-hero-sm cat-tone-teal">
      <p class="cat-eyebrow">Resources · Cambridge {BOARD_SHORT[board]}</p>
      <h1>{BOARD_SHORT[board]} notes, books and worksheets</h1>
      <p class="cat-lede">Pick a subject to see every teacher's notes, the books and the worksheets we hold for it.</p>
      <div class="cat-actions"><a class="cat-btn cat-btn-ghost" href="/notes/{board}">PrepWithTee {BOARD_SHORT[board]} notes</a></div>
    </header>
    {_picker(user, board)}
    <section><h2 class="ui-h2">For every subject</h2>{_shelf_cards()}</section>"""
    return _page(title=f"Cambridge {BOARD_SHORT[board]} Notes, Books & Worksheets - PrepWithTee",
                 desc=f"Teachers' notes, books and worksheets for Cambridge {BOARD_SHORT[board]} subjects.",
                 path=f"/resources/{board}", body=body, user=user,
                 crumbs=[("Home", "/"), ("Resources", "/resources"), (BOARD_SHORT[board], f"/resources/{board}")])


@router.get("/resources/{board}/{subject}", response_class=HTMLResponse)
@router.get("/resources/{board}/{subject}/{folder:path}", response_class=HTMLResponse)
def resources_subject(board: str, subject: str, folder: str = "",
                      user: dict | None = Depends(_auth.maybe_user)):
    import ui
    s = _catalog.find_subject(board, subject)
    tree = index()["subjects"].get(s["code"]) if s else None
    if s is None or tree is None:
        raise HTTPException(404, "No resources for that subject")
    code = s["code"]
    parts = [p for p in folder.split("/") if p]
    node, trail = _walk(tree, parts)
    base = subject_url(code)
    crumbs = [("Home", "/"), ("Resources", "/resources"), (BOARD_SHORT[board], f"/resources/{board}"),
              (f"{s['plain']} {code}", base)]
    url = base
    for t in trail:
        url += f"/{t['slug']}"
        crumbs.append((t["title"], url))
    if trail:
        h1, lede = trail[-1]["title"], (f"{node['count']} files from {trail[0]['title']}, for Cambridge "
                                        f"{BOARD_SHORT[board]} {s['plain']} ({code}).")
    else:
        h1 = f"{s['plain']} {code} notes & resources"
        lede = (f"{tree['count']} files for Cambridge {BOARD_SHORT[board]} {s['plain']} ({code}): "
                + ", ".join(d["title"] for d in tree["dirs"][:5])
                + (" and more." if len(tree["dirs"]) > 5 else "."))
    loose = ""
    if node["files"]:
        head = '<h2 class="ui-h2">Quick topic notes</h2>' if not trail else '<h2 class="ui-h2">Files</h2>'
        loose = head + _file_rows(node["files"])
    folders = ""
    if node["dirs"]:
        folders = ('<h2 class="ui-h2">' + ("Collections" if not trail else "Folders") + "</h2>"
                   + _folder_cards(node["dirs"], url))
    tip = "" if trail else ui.callout(
        f'Our own chapter-by-chapter {s["plain"]} notes are in <a href="/notes/{board}/{s["slug"]}">Notes</a>, '
        f'each linked to past-paper questions on the same chapter.', tone="blue", icon_name="notes")
    body = f"""
    {ui.subject_tabs(code, "resources")}
    <header class="cat-hero cat-hero-sm cat-tone-{s['tone']}">
      <p class="cat-eyebrow">Resources · Cambridge {BOARD_SHORT[board]} · {code}</p>
      <h1>{_e(h1)}</h1>
      <p class="cat-lede">{_e(lede)}</p>
    </header>
    {tip}
    {_search(node, url, "Search " + ("this folder and everything inside it" if trail
                                     else f"all {s['plain']} resources") + ", e.g. a teacher or topic",
             f"“{h1}”" if trail else f"{s['plain']} resources")}
    <div data-ps-browse>
    {folders}
    {loose}
    </div>"""
    return _page(title=(f"{h1} - {s['plain']} {code} Resources | PrepWithTee" if trail else
                        f"{s['plain']} {code} Notes, Books & Worksheets | Cambridge {BOARD_SHORT[board]} - PrepWithTee"),
                 desc=lede[:300], path=url, body=body, user=user, crumbs=crumbs, noindex=bool(trail))


@router.get("/resources.html", include_in_schema=False)
def legacy_resources():
    return RedirectResponse("/resources", 301)


def sitemap_paths() -> list[str]:
    idx = index()
    paths = ["/resources"] + [f"/resources/{b}" for b in BOARD_SHORT
                              if any(SUBJECTS[c]["board_slug"] == b for c in idx["subjects"])]
    paths += [subject_url(c) for c in idx["subjects"]]
    paths += [f"/resources/library/{s}" for s in idx["shelves"]]
    return paths


def sitemap_lastmod() -> dict[str, float]:
    """{url: newest file mtime} for the hub, boards, subjects and shelves."""
    def newest(node: dict) -> float:
        t = 0.0
        for f in _all_files(node):
            try:
                t = max(t, (RES_DIR / f["rel"]).stat().st_mtime)
            except OSError:
                pass
        return t

    idx = index()
    out: dict[str, float] = {}
    for code, tree in idx["subjects"].items():
        t = newest(tree)
        board = f"/resources/{SUBJECTS[code]['board_slug']}"
        out[subject_url(code)] = t
        out[board] = max(out.get(board, 0.0), t)
        out["/resources"] = max(out.get("/resources", 0.0), t)
    for slug, tree in idx["shelves"].items():
        t = newest(tree)
        out[f"/resources/library/{slug}"] = t
        out["/resources"] = max(out.get("/resources", 0.0), t)
    return {u: t for u, t in out.items() if t}
