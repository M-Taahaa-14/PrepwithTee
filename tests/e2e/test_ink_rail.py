"""The left annotation rail on a paper viewer: pinned it moves the paper over,
unpinned it tucks into a tab; any colour by hex; the compass draws a saved arc;
a sticker is saved; the coach mark points students at the new tools once."""

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


def _open(student):
    student.request.post("/api/enrollments", data={"syllabus": "5054"})
    pid = _paper_id()
    page = student.new_page()
    page.goto(f"/yearly/view/{pid}")
    page.evaluate("localStorage.setItem('pwt-wn', '{}')")          # show the coach mark
    page.reload()
    split = page.get_by_role("button", name=re.compile("Side by side"))
    if split.get_attribute("aria-pressed") == "true":
        split.click()
    stage = page.locator("#pv-qp")
    expect(stage.locator(".vw-pg canvas").first).to_be_visible(timeout=30_000)
    page.wait_for_timeout(600)
    return page, pid, stage


def _ink(student, pid):
    pages = student.request.get(f"/api/annotations?doc=paper:{pid}").json()["pages"]
    return [o for v in pages.values() for o in v]


def test_rail_pin_colour_compass_sticker(student, shots):
    page, pid, stage = _open(student)
    rail = page.locator(".ink-rail")
    expect(rail).to_be_visible()
    # coach mark, once
    coach = page.locator(".wn-coach")
    expect(coach).to_be_visible(timeout=8_000)
    page.screenshot(path=str(shots / "rail_coach.png"))
    coach.get_by_role("button", name="Got it").click()

    # pinned on a wide screen: the paper moves over
    assert page.evaluate("document.body.classList.contains('ink-pinned')")
    # unpin, click the page: the rail tucks into the tab
    page.locator('.ink-rail [data-an="pin"]').click()
    page.mouse.click(700, 300)
    expect(page.locator(".an-tab")).to_be_visible()
    expect(rail).to_be_hidden()
    page.locator(".an-tab").click()
    expect(rail).to_be_visible()
    page.locator('.ink-rail [data-an="pin"]').click()             # pin again
    page.wait_for_timeout(800)                                     # the paper refits to the pinned rail

    # any colour by hex
    page.locator(".ink-rail .ink-allc").click()
    hexbox = page.locator(".ink-cp-hex")
    hexbox.fill("#ff6600")
    hexbox.press("Enter")
    page.keyboard.press("Escape")

    # compass: open, turn the top -> an arc in that colour, saved
    page.locator('.ink-rail [data-inst="compass"]').click()
    hinge = page.locator('.an-compass [data-k="hinge"]').bounding_box()
    needle = page.locator('.an-compass [data-k="needle"]').bounding_box()
    hx, hy = hinge["x"] + hinge["width"] / 2, hinge["y"] + hinge["height"] / 2
    cx = needle["x"] + needle["width"] / 2
    page.mouse.move(hx, hy)
    page.mouse.down()
    page.mouse.move(cx - 120, hy + 10, steps=12)
    page.mouse.up()
    expect(page.locator(".an-cmp-r")).to_contain_text("4.0 cm")
    page.wait_for_timeout(1500)
    arcs = [o for o in _ink(student, pid) if o["t"] == "arc"]
    assert len(arcs) == 1 and arcs[0]["c"] == "#ff6600" and abs(arcs[0]["sw"]) > 0.3, arcs
    assert abs(arcs[0]["r"] - 40 / 210) < 0.002                      # 4 cm on an A4 width
    page.screenshot(path=str(shots / "rail_compass.png"))
    page.locator(".an-compass .an-inst-x").click()

    # a sticker
    page.locator('.ink-rail [data-tool="sticker"]').click()
    if not page.locator('.ink-fly[data-kind="stickers"]').is_visible():
        page.locator('.ink-rail [data-tool="sticker"]').click()
    page.locator('.ink-fly [data-stk="good_work"]').click()
    pg = stage.locator(".vw-pg").first.bounding_box()
    page.mouse.click(pg["x"] + pg["width"] * 0.6, pg["y"] + 300)
    page.wait_for_timeout(1500)
    stk = [o for o in _ink(student, pid) if o["t"] == "stk"]
    assert [s["k"] for s in stk] == ["good_work"]
    page.screenshot(path=str(shots / "rail_sticker.png"))

    # the coach mark does not come back
    page.reload()
    expect(stage.locator(".vw-pg canvas").first).to_be_visible(timeout=30_000)
    page.wait_for_timeout(2500)
    expect(page.locator(".wn-coach")).to_have_count(0)


def test_set_square_draws_perpendicular_lines(student, shots):
    import math
    page, pid, stage = _open(student)
    page.keyboard.press("Escape")
    page.locator(".wn-coach [data-ok]").first.click() if page.locator(".wn-coach").count() else None
    page.locator('.ink-rail [data-inst="setsquare"]').click()
    sq = page.locator(".an-inst-setsquare")
    expect(sq).to_be_visible()
    expect(sq.locator(".an-inst-unit")).to_have_text("45°")
    sq.locator(".an-inst-opt").click()
    expect(sq.locator(".an-inst-unit")).to_have_text("30° · 60°")
    page.locator('.ink-rail [data-tool="pen"]').click()
    cdp = page.context.new_cdp_session(page)

    def stroke(pts):
        def ev(kind, x, y):
            cdp.send("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left",
                     "buttons": 0 if kind == "mouseReleased" else 1, "clickCount": 1,
                     "pointerType": "pen", "force": 0.6})
        ev("mousePressed", *pts[0])
        for x, y in pts[1:]:
            ev("mouseMoved", x, y)
        ev("mouseReleased", *pts[-1])

    # the right-angle corner and the two legs, in screen px (not rotated: base along +x, upright up)
    corner = sq.evaluate("""el => { const r = el.getBoundingClientRect(); const o = el.style.transformOrigin.split(' ');
        return [r.left + parseFloat(o[0]), r.top + parseFloat(o[1])]; }""")
    cx, cy = corner
    # wobbly stroke along the base (just below it) and up the upright (just left of it)
    stroke([(cx + 20 + i * 12, cy + 4 + (3 if i % 2 else -3)) for i in range(15)])
    stroke([(cx - 4 + (3 if i % 2 else -3), cy - 20 - i * 8) for i in range(10)])
    page.wait_for_timeout(1500)
    pens = [o for o in _ink(student, pid) if o["t"] == "pen"][-2:]
    assert len(pens) == 2
    box = stage.locator(".vw-pg").first.bounding_box()

    def angle(s):
        (x0, y0), (x1, y1) = s["pts"][0][:2], s["pts"][-1][:2]
        return math.degrees(math.atan2((y1 - y0) * box["height"], (x1 - x0) * box["width"]))
    a, b = angle(pens[0]), angle(pens[1])
    assert abs(a) < 1, a                                   # along the base: horizontal
    assert abs(abs(a - b) - 90) < 1, (a, b)                # the two legs: perpendicular
    page.screenshot(path=str(shots / "rail_setsquare.png"))
