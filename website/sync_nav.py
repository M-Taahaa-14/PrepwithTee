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
