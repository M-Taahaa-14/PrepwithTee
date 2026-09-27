"""Capture the home-page hero demo ("PrepWithTee in 40 seconds") from the REAL site.

Drives a local server with a throwaway demo student, screenshots each scene and
records where the cursor should point / click (element centres, as fractions of
the screen) into website/static/demos/hero/timeline.json, which
static/demo-player.js plays inside the laptop on the home page. Title cards
(the "Not sure where to start?" opener and the "Talk to Tee" closer) are plain
steps with a `card` instead of a `shot`. Re-run after UI changes so the demo
never goes stale:

    .venv\\Scripts\\python scripts\\capture_demo_shots.py [--base http://localhost:8017]

Needs the local server (prepwithtee-local) with data/index.db and a few stored
explanations (paper 37 = 4024 w25 P11 has them). It asserts every cursor target
is on screen, so a UI change that moves something fails loudly here.
"""

import argparse
import json
import time
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "website" / "static" / "demos" / "hero"
SC_OUT = ROOT / "website" / "static" / "demos" / "showcase"   # the 4-step "how it works" section
W, H = 1280, 800
EXPLAIN_PAPER = 37                        # 4024 Oct/Nov 2025 Paper 11: explanations stored
WHATSAPP = "https://wa.me/923204884375?text=Hi%20Tee%21%20I%27d%20like%20some%20help%20with%20my%20Cambridge%20exams."

# Page furniture that isn't part of the product story.
HIDE = """.an-fab, .an-bar, #global-note-fab, .pwt-chatbot-fab, #pwt-chatbot-fab, .pwt-chatbot,
  [class*="feedback-tab"], [class*="fb-tab"], #fb-tab, .fb-btn, .pwt-dock, .pwt-dock-tab, .tools-dock-tab,
  .driver-popover, .driver-overlay, #pwt-help-btn, .pwt-onb, .onb-panel, .tour-btn, .toast,
  [class*="tools-hint"], .td-hint, #scratch-pen-fab, .sp-fab { display: none !important; }"""

INTRO = {"eyebrow": "PrepWithTee in 40 seconds", "title": "Not sure where to start?",
         "text": "We've got you. Here's how you go from \"where do I even begin?\" to a marked paper - "
                 "and who to talk to when you want a real person.", "tone": "intro"}
OUTRO = {"eyebrow": "Want a real person?", "title": "Learn one‑on‑one with Tee.",
         "text": "O Level, IGCSE and A Level - in Lahore and online. Message Tee on WhatsApp, "
                 "or book a free demo lesson.", "tone": "tee",
         "buttons": [{"label": "WhatsApp Tee", "href": WHATSAPP, "kind": "primary"},
                     {"label": "Book a free demo", "href": "#contact", "kind": "gold"}]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8017")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.jpg"):
        old.unlink()
    steps = [{"card": INTRO, "caption": "Not sure where to start? We've got you.",
              "chapter": "Start", "cursor": None, "click": False, "zoom": None, "dur": 4200}]

    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": W, "height": H}, base_url=args.base,
                            device_scale_factor=1, color_scheme="light")
        ctx.add_init_script("try{localStorage.setItem('theme','light');localStorage.setItem('pwt-onboarding-done','1');"
                            "['pwtour_seen_dashboard','pwtour_seen_profile'].forEach(k=>localStorage.setItem(k,'1'))}catch(e){}")
        req = ctx.request
        email = f"demo_{uuid.uuid4().hex[:8]}@test.local"
        assert req.post("/auth/register", data={"email": email, "password": "Passw0rd!23",
                                                "name": "Ayesha Khan"}).ok
        req.put("/api/me/boards", data={"boards": ["igcse", "o-level"]})
        for s in ("0625", "4024"):
            req.post("/api/enrollments", data={"syllabus": s})
        req.post("/api/profile", data={"grade": "IGCSE", "phone": "+92 3001234567"})
        req.post("/api/time-spent", data={"seconds": 120})
        page = ctx.new_page()

        def shot(name, caption, chapter, target=None, click=False, zoom=None, dur=3200):
            page.add_style_tag(content=HIDE)
            page.wait_for_timeout(500)
            path = OUT / f"{len(steps):02d}-{name}.jpg"
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

        # 1 - pick a board on the topical picker
        page.goto("/papers/topical")
        page.evaluate("document.querySelector('[data-pk]').scrollIntoView({block:'start'}); window.scrollBy(0,-90)")
        page.wait_for_timeout(300)
        tab = '.pk-tab[data-pk-board="igcse"]'
        shot("board", "Pick your board - O Level, IGCSE or A Level.", "Pick", target=tab, click=True)
        page.locator(tab).click()
        page.wait_for_timeout(400)
        btn = '.pk-board[data-pk-board="igcse"] .pk-tile:has-text("Physics") .pk-btn:has-text("Topical booklet")'
        page.evaluate("""(sel) => { const el = document.querySelector(sel);
          window.scrollBy(0, el.getBoundingClientRect().top - 330); }""",
                      '.pk-board[data-pk-board="igcse"] .pk-grid')
        page.wait_for_timeout(300)
        shot("subject", "Choose your subject. Enrolling is free.", "Pick", target=btn, click=True,
             zoom={"s": 1.12})

        # 2 - builder: tick a chapter, then build
        page.goto("/papers/igcse/physics-0625#builder")
        page.locator(".bld-ch").first.wait_for()
        page.evaluate("document.getElementById('builder').scrollIntoView({block:'start'})")
        page.wait_for_timeout(300)
        forces = '.bld-ch:has(label:text-is("Forces")) input[type=checkbox]'
        page.locator(forces).scroll_into_view_if_needed()
        shot("chapters", "Tick the chapters you're stuck on - or just a few subtopics.", "Build",
             target=forces, click=True)
        page.locator(forces).check()
        page.locator(".bld-pool").filter(has_text="available").wait_for()
        shot("picked", "Hit Build. Every question is a real Cambridge one.", "Build",
             target=".bld-go", click=True, zoom={"s": 1.3})

        # 3 - the booklet
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
        shot("booklet", "Your booklet is ready in seconds - newest papers first.", "Practise", dur=2800)
        page.evaluate("""() => { const st = document.getElementById('vw-stage');
          const pg = st.querySelectorAll('.vw-pg')[2]; st.scrollTop = pg.offsetTop - 16; }""")
        page.wait_for_timeout(2500)
        shot("question", "The official mark scheme follows every question.", "Practise",
             target=".vw-chips button", zoom={"x": 0.5, "y": 0.42, "s": 1.12})

        # 4 - explanation on a past paper
        page.goto(f"/yearly/view/{EXPLAIN_PAPER}")
        page.locator("#pv-qp .vw-pg canvas").first.wait_for(timeout=60_000)
        split = page.get_by_role("button", name="Side by side")
        if split.count() and split.get_attribute("aria-pressed") == "true":
            split.click()
        page.wait_for_timeout(1200)
        page.evaluate("""() => { const st = document.getElementById('pv-qp');
          const c = st.querySelector('.vw-chips');
          st.scrollTop += c.getBoundingClientRect().top - st.getBoundingClientRect().top - 140; }""")
        page.wait_for_timeout(2500)
        explain = page.locator("#pv-qp .vw-chips").first.get_by_role("button", name="Explain")
        shot("explain-chip", "Stuck? One tap for a step-by-step explanation.", "Learn",
             target=explain, click=True, zoom={"s": 1.15})
        explain.click()
        page.locator(".vw-panel .ai-body").wait_for(timeout=30_000)
        page.wait_for_function("""() => { const b = document.querySelector('.vw-panel .ai-body');
          return b && b.innerText.length > 80 && !/Loading the worked solution/.test(b.innerText); }""",
                               timeout=40_000)
        page.wait_for_timeout(1500)
        shot("explain", "Every explanation is checked against the official mark scheme.", "Learn",
             zoom={"x": 0.78, "y": 0.5, "s": 1.2}, dur=4000)

        # 5 - marks & grade, then the dashboard
        page.get_by_role("button", name="Marks & grades").click()
        panel = page.locator(".vw-panel")
        panel.get_by_label("Your mark").fill("62")
        panel.get_by_label("Out of").fill("80")
        panel.get_by_role("button", name="Save").click()
        page.locator(".pv-result-card").wait_for()
        page.wait_for_timeout(800)
        shot("marks", "Sit full papers too - log your mark and see your grade.", "Track",
             target=".pv-result-card", zoom={"x": 0.8, "y": 0.35, "s": 1.25})

        page.goto("/dashboard.html")
        page.wait_for_timeout(1500)
        go = page.get_by_role("button", name="Let's go!")
        if go.count():
            go.first.click()
            page.wait_for_timeout(500)
        page.locator("#hub-streak-num").wait_for()
        page.wait_for_timeout(1200)
        shot("dashboard", "Your dashboard keeps your streak, progress and homework in one place.", "Track",
             target="#hub-streak-num", zoom={"s": 1.1}, dur=3800)

        # extra stills for the home page's 4-step showcase (not part of the hero video)
        SC_OUT.mkdir(parents=True, exist_ok=True)

        def still(name):
            page.add_style_tag(content=HIDE)
            page.wait_for_timeout(600)
            page.screenshot(path=str(SC_OUT / f"{name}.jpg"), type="jpeg", quality=78)
            print(f"showcase/{name}.jpg")

        page.goto("/notes/igcse/physics-0625/forces/hookes-law")
        page.wait_for_timeout(1500)
        still("notes")
        page.goto("/topical-progress.html?syllabus=0625")
        page.locator(".topic-row").first.wait_for(timeout=15_000)
        rows = page.locator(".topic-row")
        for k, status in enumerate(("confident", "confident", "learning", "confident", "learning")):
            rows.nth(k).locator(f'.status-btn[data-status="{status}"]').first.click()
            page.wait_for_timeout(250)
        page.wait_for_timeout(800)
        still("progress")
        b.close()
        import shutil
        for src, dst in (("03-chapters.jpg", "papers.jpg"), ("08-explain.jpg", "ai.jpg")):
            shutil.copyfile(OUT / src, SC_OUT / dst)

    steps.append({"card": OUTRO, "caption": "Want a real person? Learn one-on-one with Tee.",
                  "chapter": "Ask Tee", "cursor": None, "click": False, "zoom": None, "dur": 6500})
    (OUT / "timeline.json").write_text(json.dumps(
        {"title": "PrepWithTee in 40 seconds", "w": W, "h": H, "steps": steps}, indent=2), encoding="utf-8")
    total = sum(f.stat().st_size for f in OUT.glob("*.jpg")) // 1024
    print(f"{len(steps)} steps, {total} KB of screenshots -> {OUT}")


if __name__ == "__main__":
    main()
