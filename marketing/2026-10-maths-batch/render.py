"""Render every poster in posters.html to an HD PNG in png/.

    .venv\\Scripts\\python marketing\\2026-10-maths-batch\\render.py [--only 01]

Each <section class="p" id="..."> becomes png/<id>.png at 2x (feed posts
2160x2700, stories 2160x3840) - Instagram downscales to 1080 wide and keeps it sharp.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="render only ids containing this text")
    ap.add_argument("--scale", type=float, default=2.0)
    args = ap.parse_args()
    out = HERE / "png"
    out.mkdir(exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1200, "height": 2000},
                                device_scale_factor=args.scale)
        page.goto((HERE / "posters.html").as_uri(), wait_until="networkidle")
        page.evaluate("document.fonts.ready")
        missing = page.evaluate("""() => ['Playfair Display','Archivo','Hanken Grotesk']
            .filter(f => !document.fonts.check(`700 40px "${f}"`))""")
        if missing:
            raise SystemExit(f"fonts did not load: {missing}")
        for sec in page.query_selector_all("section.p"):
            pid = sec.get_attribute("id")
            if args.only and args.only not in pid:
                continue
            # flag any content spilling past the poster's inner frame
            over = sec.evaluate("""s => { const i = s.querySelector('.in').getBoundingClientRect();
                return [...s.querySelectorAll('.in *')].some(e => { const r = e.getBoundingClientRect();
                  return r.width && (r.bottom > i.bottom + 1 || r.right > i.right + 1); }); }""")
            sec.screenshot(path=str(out / f"{pid}.png"))
            print(f"{pid}.png{'   <-- OVERFLOW' if over else ''}")
        browser.close()


if __name__ == "__main__":
    main()
