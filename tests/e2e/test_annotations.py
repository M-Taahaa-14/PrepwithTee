"""Annotation tools on the yearly paper viewer, driven with a real pen pointer
(Chrome DevTools pen events, like a Wacom tablet): a long pen stroke never
scrolls the page, Select moves / deletes, text can be edited after placing it,
and the partial eraser cuts a stroke in two."""

import re
import sqlite3

from playwright.sync_api import expect

from tests.conftest import INDEX_DB


def _paper_id():
    con = sqlite3.connect(INDEX_DB)
    pid = con.execute("SELECT id FROM papers WHERE syllabus='5054' AND year=2019 AND session='s' "
                      "AND paper=2 AND variant='1' AND kind='qp'").fetchone()[0]
    con.close()
    return pid


def _pen(cdp, kind, x, y, pressure=0.6):
    cdp.send("Input.dispatchMouseEvent", {
        "type": kind, "x": x, "y": y, "button": "left", "buttons": 0 if kind == "mouseReleased" else 1,
        "clickCount": 1, "pointerType": "pen", "force": pressure})


def _stroke(cdp, pts):
    _pen(cdp, "mousePressed", *pts[0])
    for x, y in pts[1:]:
        _pen(cdp, "mouseMoved", x, y)
    _pen(cdp, "mouseReleased", *pts[-1])


def _strokes(student, pid, page="2"):
    return student.request.get(f"/api/annotations?doc=paper:{pid}").json()["pages"].get(page, [])


def test_pen_select_text_and_partial_eraser(student, shots):
    student.request.post("/api/enrollments", data={"syllabus": "5054"})
    pid = _paper_id()
    page = student.new_page()
    page.goto(f"/yearly/view/{pid}")
    # single view keeps the geometry simple
    split = page.get_by_role("button", name=re.compile("Side by side"))
    if split.get_attribute("aria-pressed") == "true":
        split.click()
    stage = page.locator("#pv-qp")
    expect(stage.locator(".vw-pg canvas").first).to_be_visible(timeout=30_000)
    stage.evaluate("s => s.scrollTop = s.querySelectorAll('.vw-pg')[1].offsetTop")
    page.wait_for_timeout(800)
    pg2 = stage.locator(".vw-pg").nth(1)
    box = pg2.bounding_box()
    cdp = page.context.new_cdp_session(page)

    # 1. a long downward pen stroke: drawn in full, the page does not move
    page.locator('.an-bar [data-tool="pen"]').click()
    top0 = stage.evaluate("s => s.scrollTop")
    x0, y0 = box["x"] + 120, box["y"] + 120
    _stroke(cdp, [(x0 + (i % 7), y0 + i * 6) for i in range(60)])
    assert stage.evaluate("s => s.scrollTop") == top0, "a pen stroke scrolled the page"
    page.wait_for_timeout(1200)
    s = _strokes(student, pid)
    assert len(s) == 1 and s[0]["t"] == "pen" and len(s[0]["pts"]) > 40

    # 2. select + drag moves it; Delete removes it
    page.locator('.an-bar [data-tool="select"]').click()
    _stroke(cdp, [(x0 + 3, y0 + 150), (x0 + 60, y0 + 150), (x0 + 120, y0 + 150)])
    page.wait_for_timeout(1200)
    moved = _strokes(student, pid)[0]["pts"][0][0]
    assert moved > s[0]["pts"][0][0] + 0.05, "select + drag did not move the stroke"
    expect(page.locator('.an-bar [data-an="delete"]')).to_be_visible()
    page.keyboard.press("Delete")
    page.wait_for_timeout(1200)
    assert _strokes(student, pid) == []

    # 3. text: place, then edit by double-clicking with Select
    page.locator('.an-bar [data-tool="text"]').click()
    tx, ty = box["x"] + 200, box["y"] + 400
    page.mouse.click(tx, ty)
    page.keyboard.type("v = u + at")
    page.keyboard.press("Enter")
    page.locator('.an-bar [data-tool="select"]').click()
    page.mouse.dblclick(tx + 10, ty + 6)
    ed = page.locator(".an-text")
    expect(ed).to_have_value("v = u + at")
    ed.fill("v = u + at  (a const.)")
    page.keyboard.press("Enter")
    page.wait_for_timeout(1200)
    texts = [x for x in _strokes(student, pid) if x["t"] == "text"]
    assert [t["txt"] for t in texts] == ["v = u + at  (a const.)"]

    # 4. partial eraser: a horizontal line cut in the middle becomes two strokes
    page.locator('.an-bar [data-tool="line"]').click()
    lx, ly = box["x"] + 100, box["y"] + 600
    page.mouse.move(lx, ly); page.mouse.down(); page.mouse.move(lx + 300, ly, steps=8); page.mouse.up()
    page.locator('.an-bar [data-tool="eraser"]').click()
    # the eraser's own options replace colour/thickness while it is on
    opts = page.locator(".an-eraseopts")
    expect(opts).to_be_visible()
    expect(page.locator(".an-bar .an-swatch")).to_be_hidden()
    opts.get_by_role("radio", name="Partial").click()
    opts.get_by_role("radio", name="Large eraser").click()
    expect(opts.get_by_role("radio", name="Large eraser")).to_have_attribute("aria-checked", "true")
    _stroke(cdp, [(lx + 150, ly - 25), (lx + 150, ly), (lx + 150, ly + 25)])
    page.wait_for_timeout(1200)
    lines = [x for x in _strokes(student, pid) if x["t"] != "text"]
    assert len(lines) == 2 and all(x.get("pts") for x in lines), lines
    page.screenshot(path=str(shots / "annotations.png"))

    # 5. whole-object mode removes a touched stroke entirely
    opts.get_by_role("radio", name="Whole object").click()
    _stroke(cdp, [(lx + 40, ly - 20), (lx + 40, ly), (lx + 40, ly + 20)])
    page.wait_for_timeout(1200)
    assert len([x for x in _strokes(student, pid) if x["t"] != "text"]) == 1
    page.locator('.an-bar [data-tool="pen"]').click()
    expect(opts).to_be_hidden()
    expect(page.locator(".an-bar .an-swatch")).to_be_visible()


def test_scratch_pen_on_every_other_page_is_never_saved(student, shots):
    page = student.new_page()
    puts = []
    page.on("request", lambda r: puts.append(r.url) if "/api/annotations" in r.url else None)
    for url in ("/tools.html", "/papers/igcse", "/yearly"):
        page.goto(url)
        expect(page.locator(".an-fab")).to_be_visible(timeout=10_000)
        assert page.locator(".an-bar").count() == 1, url
    # draw on /yearly, scroll: the ink moves with the page
    page.locator(".an-fab").click()
    page.locator('.an-bar [data-tool="pen"]').click()
    page.mouse.move(400, 500); page.mouse.down(); page.mouse.move(600, 520, steps=10); page.mouse.up()
    expect(page.locator(".an-saved")).to_contain_text("not saved")
    ink_at = lambda y: page.evaluate(
        f"(() => {{ const c = document.querySelector('.an-viewport canvas'); const d = devicePixelRatio;"
        f" return [...c.getContext('2d').getImageData(500 * d, {y} * d, 1, 1).data][3] > 0; }})()")
    assert ink_at(510)
    page.locator('.an-bar [data-tool="pointer"]').click()
    page.mouse.wheel(0, 200); page.wait_for_timeout(400)
    moved = page.evaluate("scrollY")
    assert moved > 0 and ink_at(round(510 - moved)) and not ink_at(510)
    page.screenshot(path=str(shots / "scratch_pen.png"))
    page.reload()
    expect(page.locator(".an-fab")).to_be_visible()
    assert not ink_at(510)
    assert puts == [], puts                                    # nothing ever sent

    # PDF viewers keep their own, saved annotator - only one bar
    student.request.post("/api/enrollments", data={"syllabus": "5054"})
    page.goto(f"/yearly/view/{_paper_id()}")
    expect(page.locator("#pv-qp .vw-pg canvas").first).to_be_visible(timeout=30_000)
    assert page.locator(".an-bar").count() == 1 and page.locator(".an-viewport").count() == 0


def test_ruler_snaps_strokes_and_protractor_measures(student, shots):
    student.request.post("/api/enrollments", data={"syllabus": "5054"})
    pid = _paper_id()
    page = student.new_page()
    page.goto(f"/yearly/view/{pid}")
    split = page.get_by_role("button", name=re.compile("Side by side"))
    if split.get_attribute("aria-pressed") == "true":
        split.click()
    stage = page.locator("#pv-qp")
    expect(stage.locator(".vw-pg canvas").first).to_be_visible(timeout=30_000)
    page.wait_for_timeout(600)

    # ruler: on the page, at the paper's real scale (15 cm of an A4 width)
    page.locator('.an-bar [data-inst="ruler"]').click()
    ruler = page.locator(".an-inst-ruler")
    expect(ruler).to_be_visible()
    pg_w = stage.locator(".vw-pg").first.bounding_box()["width"]
    svg_w = float(ruler.locator("svg").get_attribute("width"))
    assert abs((svg_w - 12) - pg_w * 150 / 210) < 2

    # rotate it with the handle to about -30° (handle dragged down-right)
    rb = ruler.bounding_box()
    cx, cy = rb["x"] + rb["width"] / 2, rb["y"] + rb["height"] / 2
    h = ruler.locator(".an-inst-rot").bounding_box()
    page.mouse.move(h["x"] + 10, h["y"] + 10); page.mouse.down()
    import math
    r = 200
    page.mouse.move(cx + r * math.cos(math.radians(30)), cy + r * math.sin(math.radians(30)), steps=8)
    page.mouse.up()
    expect(ruler.locator(".an-inst-deg")).to_have_text("-30°")

    # a wobbly pen stroke started on the ruler's edge comes out perfectly straight
    page.locator('.an-bar [data-tool="pen"]').click()
    cdp = page.context.new_cdp_session(page)
    ux, uy = math.cos(math.radians(30)), math.sin(math.radians(30))     # along the ruler (screen)
    nx, ny = -uy, ux                                                      # across it
    half = ruler.locator("svg").evaluate("s => s.getAttribute('height')")
    edge = float(half) / 2 + 3
    pts = [(cx + nx * edge + ux * t + (4 if i % 2 else -4) * nx,
            cy + ny * edge + uy * t + (4 if i % 2 else -4) * ny) for i, t in enumerate(range(-120, 121, 12))]
    _stroke(cdp, pts)
    page.wait_for_timeout(1200)
    s = [x for x in _strokes(student, pid, page=str(stage.evaluate(
        "s => [...s.querySelectorAll('.vw-pg')].findIndex(p => p.querySelector('.an-inst')) + 1")))
         if x["t"] == "pen"][-1]
    box = stage.locator(".vw-pg").first.bounding_box()
    xy = [(p[0] * box["width"], p[1] * box["height"]) for p in s["pts"]]
    (x0, y0), (x1, y1) = xy[0], xy[-1]
    L = math.hypot(x1 - x0, y1 - y0)
    dev = max(abs((x - x0) * (y1 - y0) - (y - y0) * (x1 - x0)) / L for x, y in xy)
    assert L > 200 and dev < 1.0, (L, dev)                     # straight to within a pixel
    assert abs(math.degrees(math.atan2(y1 - y0, x1 - x0)) - 30) < 1.5

    # protractor: 0-180 both ways; the × puts instruments away
    page.locator('.an-bar [data-inst="protractor"]').click()
    prot = page.locator(".an-inst-protractor")
    expect(prot).to_be_visible()
    labels = prot.locator("text").evaluate_all("ts => ts.map(t => t.textContent)")
    assert "0" in labels and "90" in labels and "180" in labels
    page.screenshot(path=str(shots / "instruments.png"))
    prot.locator(".an-inst-x").click()
    ruler.locator(".an-inst-x").click()
    expect(page.locator(".an-inst")).to_have_count(0)
    expect(page.locator('.an-bar [data-inst="ruler"]')).to_have_attribute("aria-pressed", "false")
