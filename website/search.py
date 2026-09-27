"""Site search: one small index the header search box (static/site-search.js)
filters in the browser.

    GET /api/search/index    [{t: title, s: subtitle, u: url, k: kind, q: extra words}]

It lists every page (explore.SECTIONS), every subject's section pages
(topical, by year, MCQ, mock test, notes, resources), every syllabus chapter
and every note. Nothing personal is in it, so it is cached publicly and in
process for 10 minutes. ~1-2k rows, ~100 KB before gzip - small enough that
typing never waits for the network.
"""

import threading
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

import catalog as _catalog

router = APIRouter()

_CACHE: dict = {"at": 0.0, "rows": None}
_TTL_S = 600
_LOCK = threading.Lock()


def build_index() -> list[dict]:
    import explore
    import notes
    import resources
    import ui
    rows: list[dict] = []
    for heading, _icon, items in explore.SECTIONS:
        for label, url, what, _acct in items:
            rows.append({"t": label, "s": what, "u": url, "k": "page", "q": heading.lower()})
    board_names = {"o-level": "o level olevel", "igcse": "igcse", "a-level": "a level alevel as"}
    for code, s in _catalog.SUBJECTS.items():
        board = _catalog.BOARD_SHORT[s["board_slug"]]
        words = f'{code} {s["name"]} {board_names[s["board_slug"]]}'.lower()
        for key, label, url, _ic in ui.subject_links(code):
            rows.append({"t": f'{s["plain"]} {code} · {label}', "s": f"Cambridge {board}",
                         "u": url, "k": "subject" if key == "topical" else key, "q": words})
        subj_url = _catalog.subject_url(code)
        for ch in _catalog.chapters(code):
            subs = " ".join(x["name"] for x in ch.get("subtopics", []))
            rows.append({"t": ch["display"], "s": f'{s["plain"]} {code} · chapter · {ch["count"]:,} questions',
                         "u": f'{subj_url}/{ch["slug"]}', "k": "chapter",
                         "q": f"{words} {subs}".lower()})
        for ch_slug, items in notes.index().get(code, {}).items():
            for n in items:
                rows.append({"t": n["title"], "s": f'{s["plain"]} {code} · note · {n["minutes"]} min read',
                             "u": notes.notes_url(code, ch_slug, n["slug"]), "k": "note",
                             "q": f'{words} {ch_slug.replace("-", " ")} {n.get("subtopic") or ""}'.lower()})
    for slug, t in resources.index()["shelves"].items():
        title = t["meta"].get("title") or t["title"]
        rows.append({"t": title, "s": "Resources shelf", "u": f"/resources/library/{slug}", "k": "resources",
                     "q": (t["meta"].get("description") or "").lower()})
    return rows


def index_rows() -> list[dict]:
    if _CACHE["rows"] is not None and time.time() - _CACHE["at"] < _TTL_S:
        return _CACHE["rows"]
    with _LOCK:
        if _CACHE["rows"] is None or time.time() - _CACHE["at"] >= _TTL_S:
            _CACHE.update(rows=build_index(), at=time.time())
    return _CACHE["rows"]


@router.get("/api/search/index")
def search_index():
    return JSONResponse(index_rows(), headers={"Cache-Control": "public, max-age=600"})
