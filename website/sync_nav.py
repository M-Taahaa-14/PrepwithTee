"""Stamp the shared site navbar into every public static page.

Single source of truth: ``website/partials/nav.html`` (the full
``<header class="site-header"> … </header>`` block). Edit that one file, then
run this script to propagate it to every page in ``website/static``:

    python sync_nav.py            # from the website/ directory
    python sync_nav.py --check    # report drift, change nothing (CI-friendly)

How it works
------------
On the first run each page still has a bare ``<header class="site-header">``
block; the script replaces it with the canonical nav wrapped in
``<!--NAV:START-->`` / ``<!--NAV:END-->`` markers. On later runs it replaces
whatever sits between those markers, so re-running is idempotent.

Only pages that already carry a ``<header class="site-header">`` are touched —
the sidebar surfaces (admin, messages, teacher dashboard) use a different shell
and are skipped automatically. Active-link highlighting is applied at runtime by
main.js (it matches each link's href against the URL), so one identical navbar
serves every page correctly.
"""

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
PARTIAL = HERE / "partials" / "nav.html"

_MARKER_RE = re.compile(r"<!--NAV:START.*?<!--NAV:END-->", re.S)
_HEADER_RE = re.compile(r'<header class="site-header">.*?</header>', re.S)
_START = ("<!--NAV:START — shared navbar. Do not edit here; "
          "edit website/partials/nav.html then run: python sync_nav.py -->")
_END = "<!--NAV:END-->"


def _block(nav: str) -> str:
    return f"{_START}\n{nav.strip()}\n{_END}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync the shared navbar into every static page.")
    ap.add_argument("--check", action="store_true",
                    help="report which pages are out of sync; write nothing")
    args = ap.parse_args()

    if not PARTIAL.is_file():
        print(f"ERROR: canonical nav not found at {PARTIAL}", file=sys.stderr)
        return 2

    nav = PARTIAL.read_text(encoding="utf-8")
    block = _block(nav)

    changed, skipped, stale = [], [], []
    for page in sorted(STATIC.glob("*.html")):
        src = page.read_text(encoding="utf-8")

        if _MARKER_RE.search(src):
            new = _MARKER_RE.sub(lambda _: block, src, count=1)
        elif _HEADER_RE.search(src):
            new = _HEADER_RE.sub(lambda _: block, src, count=1)
        else:
            skipped.append(page.name)          # no site-header (sidebar shells)
            continue

        if new != src:
            stale.append(page.name)
            if not args.check:
                page.write_text(new, encoding="utf-8")
                changed.append(page.name)

    if args.check:
        if stale:
            print(f"{len(stale)} page(s) out of sync: {', '.join(stale)}")
            return 1
        print(f"All {len(list(STATIC.glob('*.html'))) - len(skipped)} nav pages in sync.")
        return 0

    print(f"Updated {len(changed)} page(s).")
    if skipped:
        print(f"Skipped {len(skipped)} page(s) with no .site-header: {', '.join(skipped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
