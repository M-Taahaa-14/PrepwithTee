"""Stamp the shared site navbar and footer into every public static page.

Single source of truth: ``website/partials/nav.html`` (the full
``<header class="site-header"> … </header>`` block) and
``website/partials/footer.html`` (``<footer class="site-footer"> … </footer>``).
Edit those files, then run this script to propagate them to every page in
``website/static``:

    python sync_nav.py            # from the website/ directory
    python sync_nav.py --check    # report drift, change nothing (CI-friendly)

How it works
------------
On the first run each page still has a bare ``<header class="site-header">``
(or ``<footer class="site-footer">``) block; the script replaces it with the
canonical one wrapped in ``<!--NAV:START-->`` / ``<!--NAV:END-->`` (or
``<!--FOOT:START-->`` / ``<!--FOOT:END-->``) markers. On later runs it replaces
whatever sits between those markers, so re-running is idempotent.

Only pages that already carry a site header / footer are touched - the sidebar
surfaces (admin, messages, teacher dashboard) and the full-screen app pages use
a different shell and are skipped automatically. Links in both partials are
absolute, so one identical block works at any URL depth. Active-link
highlighting is applied at runtime by main.js. The server-rendered pages
(blog, /papers, /yearly, /mcq) read the same partials through blog._nav() and
blog._foot().
"""

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
PARTS = HERE / "partials"

BLOCKS = [
    # (partial, marker name, bare-block regex)
    ("nav.html", "NAV", re.compile(r'<header class="site-header">.*?</header>', re.S)),
    ("footer.html", "FOOT", re.compile(r'<footer class="site-footer".*?</footer>', re.S)),
]


# ── Breadcrumb bar ───────────────────────────────────────────────────────────
# Every static page gets a "← Back to <parent>" pill + breadcrumb trail right
# under the header (plus BreadcrumbList JSON-LD), stamped between CRUMB
# markers. The trail is (label, url) pairs AFTER "Home", ending with the page
# itself. Pages not listed (home, sign-in pages, the full-screen tutor) get no
# bar. The server-rendered sections build the same bar in catalog._shell().
_DASH = ("Dashboard", "/dashboard.html")
_TOOLS = ("Tools", "/tools.html")
_PAPERS = ("Past papers", "/papers")
_NOTES = ("Notes", "/notes")
_HUB = ("Study hub", "/study-hub.html")
CRUMBS: dict[str, list[tuple[str, str]]] = {
    "dashboard.html": [_DASH],
    "achievements.html": [_DASH, ("Achievements", "/achievements.html")],
    "analytics.html": [_DASH, ("Analytics", "/analytics.html")],
    "calendar.html": [_DASH, ("Calendar", "/calendar.html")],
    "homework.html": [_DASH, ("Homework", "/homework.html")],
    "profile.html": [_DASH, ("Profile", "/profile.html")],
    "notes.html": [_DASH, ("My notes", "/notes.html")],
    "study-hub.html": [_DASH, _HUB],
    "study.html": [_DASH, _HUB, ("Study session", "/study.html")],
    "quiz.html": [_DASH, _HUB, ("Quiz", "/quiz.html")],
    "flashcards.html": [_DASH, ("Flashcards", "/flashcards.html")],
    "fc-progress.html": [_DASH, ("Flashcards", "/flashcards.html"), ("Progress", "/fc-progress.html")],
    "topical-progress.html": [_PAPERS, ("Topical progress", "/topical-progress.html")],
    "yearly-progress.html": [_PAPERS, ("Yearly progress", "/yearly-progress.html")],
    "tools.html": [_TOOLS],
    "calculator.html": [_TOOLS, ("Calculator", "/calculator.html")],
    "graph.html": [_TOOLS, ("Graph plotter", "/graph.html")],
    "grade-calculator.html": [_TOOLS, ("Grade calculator", "/grade-calculator.html")],
    "grade-trends.html": [_TOOLS, ("Grade trends", "/grade-trends.html")],
    "bases-logic.html": [_TOOLS, ("Number bases & logic", "/bases-logic.html")],
    "pseudocode.html": [_TOOLS, ("Pseudocode runner", "/pseudocode.html")],
    "periodic-table.html": [_TOOLS, ("Periodic table", "/periodic-table.html")],
    "formulas.html": [_TOOLS, ("Formula sheets", "/formulas.html")],
    "command-words.html": [_TOOLS, ("Command words", "/command-words.html")],
    "graphs-guide.html": [_TOOLS, ("Graph guide", "/graphs-guide.html")],
    "definitions.html": [_NOTES, ("Definitions", "/definitions.html")],
    "islamiat-references.html": [_NOTES, ("Islamiyat references", "/islamiat-references.html")],
    "solver.html": [("AI Tutor", "/tutor.html"), ("Photo Solver", "/solver")],
    "subjects.html": [("Subjects", "/subjects.html")],
    "course.html": [("Subjects", "/subjects.html"), ("Course", "/course.html")],
    "guide.html": [("Guide", "/guide.html")],
    "walkthrough.html": [("Guide", "/guide.html"), ("Walkthrough", "/walkthrough.html")],
    "pricing.html": [("Pricing", "/pricing.html")],
    "teachers.html": [("Our teachers", "/teachers.html")],
    "teacher-apply.html": [("Our teachers", "/teachers.html"), ("Teach with us", "/teacher-apply.html")],
    "contact.html": [("Contact", "/contact.html")],
    "terms.html": [("Terms", "/terms.html")],
    "privacy.html": [("Privacy", "/privacy.html")],
}
# Dashboard section tabs (tutor, 2026-09-28: moving between the dashboard's own
# pages was hard). Stamped inside the CRUMB block of every page listed here;
# /my-papers (server-rendered) draws the same bar from ui.dash_tabs().
DASH_TABS = [
    ("Overview", "/dashboard.html", "📊"),
    ("Chapter progress", "/topical-progress.html", "📈"),
    ("Paper scores", "/yearly-progress.html", "🎯"),
    ("My papers", "/my-papers", "🗂️"),
    ("Homework", "/homework.html", "📝"),
    ("Calendar", "/calendar.html", "📅"),
    ("Analytics", "/analytics.html", "📉"),
    ("Achievements", "/achievements.html", "🏆"),
    ("Flashcards", "/fc-progress.html", "🃏"),
    ("Profile", "/profile.html", "👤"),
]
DASH_TAB_PAGES = {u.lstrip("/") for _n, u, _i in DASH_TABS if u.endswith(".html")}


def dash_tabs_html(current: str) -> str:
    tabs = []
    for name, url, ic in DASH_TABS:
        on = url == current
        cur = ' aria-current="page"' if on else ""
        tabs.append(f'<a class="dtab{" is-on" if on else ""}" href="{url}"{cur}>'
                    f'<span aria-hidden="true">{ic}</span>{_esc(name)}</a>')
    return ('<nav class="dtabs" aria-label="Dashboard sections"><div class="container dtabs-in">'
            + "".join(tabs) + "</div></nav>")


SITE = "https://prepwithtee.com"
_CRUMB_RE = re.compile(r"<!--CRUMB:START.*?<!--CRUMB:END-->\n?", re.S)
# the single-link bars this replaces: <div class="page-back-bar"><a ...>Dashboard</a></div>
_OLD_BACK_RE = re.compile(r'\s*<div class="page-back-bar">\s*<a[^>]*>.*?</a>\s*</div>[ \t]*\n?', re.S)


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")


def crumb_block(page: str) -> str | None:
    trail = CRUMBS.get(page)
    if not trail:
        return None
    full = [("Home", "/")] + trail
    parent = full[-2]
    links = " ".join(
        (f'<a href="{u}">{_esc(n)}</a><span aria-hidden="true">›</span>' if i < len(full) - 1
         else f'<span aria-current="page">{_esc(n)}</span>')
        for i, (n, u) in enumerate(full))
    ld = json.dumps({"@context": "https://schema.org", "@type": "BreadcrumbList",
                     "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n,
                                          "item": f"{SITE}{u}"} for i, (n, u) in enumerate(full)]},
                    ensure_ascii=False)
    return ("<!--CRUMB:START — breadcrumb bar. Do not edit here; edit CRUMBS in website/sync_nav.py "
            "then run: python sync_nav.py -->\n"
            '<div class="pg-crumbbar"><div class="container pg-crumbbar-in">'
            f'<a class="pg-back" href="{parent[1]}"><svg viewBox="0 0 24 24" aria-hidden="true">'
            '<path d="M15 5l-7 7 7 7"/></svg><span>' + _esc(parent[0]) + "</span></a>"
            f'<nav class="pg-crumbs" aria-label="Breadcrumb">{links}</nav></div></div>\n'
            + (dash_tabs_html("/" + page) + "\n" if page in DASH_TAB_PAGES else "")
            + f'<script type="application/ld+json">{ld}</script>\n'
            "<!--CRUMB:END-->\n")


def stamp_crumbs(page: str, html: str) -> str:
    """Put (or refresh) the bar right after the navbar, dropping any old back bar."""
    html = _CRUMB_RE.sub("", html)
    block = crumb_block(page)
    end = html.find("<!--NAV:END-->")
    if end < 0:
        return html
    end += len("<!--NAV:END-->")
    nl = html.find("\n", end)
    end = nl + 1 if nl >= 0 else end
    rest = html[end:]
    m = _OLD_BACK_RE.match(rest)
    if m and block:
        rest = rest[m.end():]
    return html[:end] + (block or "") + rest


def _markers(name: str, partial: str):
    start = (f"<!--{name}:START — shared {'navbar' if name == 'NAV' else 'footer'}. Do not edit here; "
             f"edit website/partials/{partial} then run: python sync_nav.py -->")
    return start, f"<!--{name}:END-->", re.compile(rf"<!--{name}:START.*?<!--{name}:END-->", re.S)


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync the shared navbar + footer into every static page.")
    ap.add_argument("--check", action="store_true",
                    help="report which pages are out of sync; write nothing")
    args = ap.parse_args()

    blocks = []
    for partial, name, bare in BLOCKS:
        path = PARTS / partial
        if not path.is_file():
            print(f"ERROR: canonical {partial} not found at {path}", file=sys.stderr)
            return 2
        start, end, marker_re = _markers(name, partial)
        blocks.append((f"{start}\n{path.read_text(encoding='utf-8-sig').strip()}\n{end}", marker_re, bare))

    changed, stale = [], []
    pages = sorted(STATIC.glob("*.html"))
    for page in pages:
        src = page.read_text(encoding="utf-8")
        new = src
        for block, marker_re, bare in blocks:
            if marker_re.search(new):
                new = marker_re.sub(lambda _: block, new, count=1)
            elif bare.search(new):
                new = bare.sub(lambda _: block, new, count=1)
        new = stamp_crumbs(page.name, new)
        if new != src:
            stale.append(page.name)
            if not args.check:
                page.write_text(new, encoding="utf-8")
                changed.append(page.name)

    if args.check:
        if stale:
            print(f"{len(stale)} page(s) out of sync: {', '.join(stale)}")
            return 1
        print(f"All {len(pages)} pages in sync.")
        return 0
    print(f"Updated {len(changed)} page(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
