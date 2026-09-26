"""Capture the landing-page demo ("How PrepWithTee works") from the REAL site.

Drives a local server with a throwaway demo student, screenshots each scene and
records where the cursor should point / click (element centres, as fractions of
the screen) into website/static/demos/how-it-works/timeline.json, which
static/demo-player.js plays. Re-run after UI changes so the demo never goes stale:

    .venv\\Scripts\\python scripts\\capture_demo_shots.py [--base http://localhost:8017]

Needs the local server (prepwithtee-local) with data/index.db and a few stored
explanations (paper 37 = 4024 w25 P11 has them).
"""

import argparse
import json
import time
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "website" / "static" / "demos" / "how-it-works"
W, H = 1280, 800
EXPLAIN_PAPER = 37                        # 4024 Oct/Nov 2025 Paper 11: explanations stored

# Page furniture that isn't part of the product story.
HIDE = """.an-fab, .an-bar, #global-note-fab, .pwt-chatbot-fab, #pwt-chatbot-fab, .pwt-chatbot,
  [class*="feedback-tab"], [class*="fb-tab"], #fb-tab, .fb-btn, .pwt-dock, .pwt-dock-tab, .tools-dock-tab,
  .driver-popover, .driver-overlay, #pwt-help-btn, .pwt-onb, .onb-panel, .tour-btn, .toast
  { display: none !important; }"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8017")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    steps = []

    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": W, "height": H}, base_url=args.base,
                            device_scale_factor=1, color_scheme="light")
        ctx.add_init_script("try{localStorage.setItem('theme','light');localStorage.setItem('pwt-onboarding-done','1')}catch(e){}")
        req = ctx.request
        email = f"demo_{uuid.uuid4().hex[:8]}@test.local"
        assert req.post("/auth/register", data={"email": email, "password": "Passw0rd!23",
                                                "name": "Ayesha Khan"}).ok
        req.put("/api/me/boards", data={"boards": ["igcse", "o-level"]})
        for s in ("0625", "4024"):
            req.post("/api/enrollments", data={"syllabus": s})
        page = ctx.new_page()

        def shot(name, caption, chapter, target=None, click=False, zoom=None, dur=3200):
            page.add_style_tag(content=HIDE)
            page.wait_for_timeout(500)
            path = OUT / f"{len(steps) + 1:02d}-{name}.jpg"
            page.screenshot(path=str(path), type="jpeg", quality=78)
            cur = None
            if target is not None:
                loc = page.locator(target) if isinstance(target, str) else target
                box = loc.first.bounding_box()
                cur = [round((box["x"] + box["width"] / 2) / W, 4), round((box["y"] + box["height"] / 2) / H, 4)]
                assert 0 <= cur[0] <= 1 and 0 <= cur[1] <= 1, f"{target} is off screen: {cur}"
                if zoom:        # zoom about the cursor, so the thing being clicked stays in frame
                    zoom = {"x": cur[0], "y": cur[1], "s": zoom["s"]}
            steps.append({"shot": path.name, "caption": caption, "chapter": chapter, "cursor": cur,
                          "click": click, "zoom": zoom, "dur": dur})
            print(f"{path.name}  {caption}")

        # 1 - board page
        page.goto("/papers/igcse")
        shot("board", "Pick your board and enrol in your subjects — free.", "Choose",
             target='.cat-subj:has-text("Physics") .cat-btn:has-text("Topical")', click=True)

        # 2 - builder: tick a chapter (before + after)
        page.goto("/papers/igcse/physics-0625#builder")
        page.locator(".bld-ch").first.wait_for()
        page.evaluate("document.getElementById('builder').scrollIntoView({block:'start'})")
        page.wait_for_timeout(300)
        forces = '.bld-ch:has(label:text-is("Forces")) input[type=checkbox]'
        page.locator(forces).scroll_into_view_if_needed()
        shot("chapters", "Tick the chapters you need — or just a few subtopics.", "Build",
             target=forces, click=True)
        page.locator(forces).check()
        page.locator(".bld-pool").filter(has_text="available").wait_for()
        shot("picked", "Mix up to four chapters. Every question is a real Cambridge one.", "Build",
             target=".bld-go", click=True, zoom={"x": 0.83, "y": 0.45, "s": 1.35})

        # 3 - build and open the booklet
        r = req.post("/api/booklets", data={"syllabus": "0625", "picks": [{"chapter": "Forces"}],
                                            "papers": [4], "max_questions": 6, "year_from": 2019,
                                            "year_to": 2025, "seed": 7})
        bid = r.json()["id"]
        for _ in range(120):
            if req.get(f"/api/booklets/{bid}/status").json()["status"] in ("ready", "failed"):
                break
            time.sleep(1)
        page.goto(f"/papers/view/{bid}")
        page.locator(".vw-pg canvas").first.wait_for(timeout=60_000)
        page.wait_for_timeout(1500)
        shot("booklet", "Your paper is built in seconds - a proper booklet with a cover and contents.",
             "Practise", dur=2600)
        # then a question page: the stage scrolls, not the window
        page.evaluate("""() => { const st = document.getElementById('vw-stage');
          const pg = st.querySelectorAll('.vw-pg')[2]; st.scrollTop = pg.offsetTop - 16; }""")
        page.wait_for_timeout(2500)
        shot("question", "Real Cambridge questions, with the official mark scheme after each one.", "Practise",
             target=".vw-chips button", zoom={"x": 0.5, "y": 0.42, "s": 1.12})

        # 4 - explanation on a past paper
        page.goto(f"/yearly/view/{EXPLAIN_PAPER}")
        page.locator("#pv-qp .vw-pg canvas").first.wait_for(timeout=60_000)
        split = page.get_by_role("button", name="Side by side")
        if split.count() and split.get_attribute("aria-pressed") == "true":
            split.click()
        page.wait_for_timeout(1200)
        # the stage scrolls, not the window: bring question 1's chips into view
        page.evaluate("""() => { const st = document.getElementById('pv-qp');
          const c = st.querySelector('.vw-chips');
          st.scrollTop += c.getBoundingClientRect().top - st.getBoundingClientRect().top - 140; }""")
        page.wait_for_timeout(2500)
        explain = page.locator("#pv-qp .vw-chips").first.get_by_role("button", name="Explain")
        shot("explain-chip", "Stuck? Ask for a step-by-step explanation.", "Understand",
             target=explain, click=True, zoom={"s": 1.15})
        explain.click()
        page.locator(".vw-panel .ai-body").wait_for(timeout=30_000)
        page.wait_for_function("""() => { const b = document.querySelector('.vw-panel .ai-body');
          return b && b.innerText.length > 80 && !/Loading the worked solution/.test(b.innerText); }""",
                               timeout=40_000)
        page.wait_for_timeout(1500)
        shot("explain", "Every explanation is checked against the official mark scheme.", "Understand",
             zoom={"x": 0.78, "y": 0.5, "s": 1.2}, dur=4200)

        # 5 - marks & grade
        page.get_by_role("button", name="Marks & grades").click()
        panel = page.locator(".vw-panel")
        panel.get_by_label("Your mark").fill("62")
        panel.get_by_label("Out of").fill("80")
        panel.get_by_role("button", name="Save").click()
        page.locator(".pv-result-card").wait_for()
        page.wait_for_timeout(800)
        shot("marks", "Log your mark — see your grade on Cambridge's own thresholds.", "Track",
             target=".pv-result-card", zoom={"x": 0.8, "y": 0.35, "s": 1.25})

        # 6 - progress on the yearly grid
        page.goto("/yearly/o-level/mathematics-4024/2025")
        page.locator(".yr-tile.is-done").first.wait_for(timeout=10_000)
        page.locator(".yr-tile.is-done").first.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        shot("progress", "Every paper you finish is ticked off, with your score.", "Track",
             target=".yr-tile.is-done", zoom={"x": 0.5, "y": 0.5, "s": 1.15}, dur=3800)
        b.close()

    (OUT / "timeline.json").write_text(json.dumps(
        {"title": "How PrepWithTee works", "w": W, "h": H, "steps": steps}, indent=2), encoding="utf-8")
    total = sum(f.stat().st_size for f in OUT.glob("*.jpg")) // 1024
    print(f"{len(steps)} steps, {total} KB of screenshots -> {OUT}")


if __name__ == "__main__":
    main()
