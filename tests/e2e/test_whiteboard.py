"""PrepWithTee Board end to end: dashboard -> template -> draw, rename, paper
pattern, paste an image, add a page, reload (everything kept), export, share
link opens read-only for a guest, infinite canvas zooms; the public page,
/features and the What's new spotlight."""

import re

from playwright.sync_api import expect


def _board(student, bid):
    return student.request.get(f"/api/wb/boards/{bid}").json()


def test_whiteboard_flow(student, shots, browser, base_url):
    page = student.new_page()
    page.add_init_script("localStorage.setItem('pwt-wn', JSON.stringify({'board-2026-10': 1, 'coach-rail': 1}))")
    page.goto("/whiteboard")
    expect(page.get_by_role("heading", name="My boards")).to_be_visible()
    expect(page.locator(".wbd-usage")).to_contain_text("0 of 3 boards")
    page.locator('[data-tpl="squared"]').click()
    page.wait_for_url(re.compile(r"/whiteboard/[A-Za-z0-9]+$"))
    bid = page.url.rsplit("/", 1)[1]
    pg = page.locator(".wb-pg").first
    expect(pg.locator("canvas.an-layer")).to_be_attached(timeout=15_000)
    expect(page.locator(".ink-rail")).to_be_visible()

    # rename
    title = page.locator(".wb-title")
    title.fill("Circle theorems")
    title.press("Enter")

    # draw a stroke with the pen
    page.locator('.ink-rail [data-tool="pen"]').click()
    b = pg.bounding_box()
    page.mouse.move(b["x"] + 100, b["y"] + 120)
    page.mouse.down()
    page.mouse.move(b["x"] + 300, b["y"] + 200, steps=12)
    page.mouse.up()
    expect(page.locator(".wb-status")).to_have_text("All changes saved", timeout=10_000)

    # paper: dotted on this page
    page.locator('[data-act="paper"]').click()
    page.locator('[data-pattern="dotted"]').click()
    page.locator(".wb-dlg [data-close]").first.click()

    # paste an image (Ctrl+V)
    page.evaluate("""async () => {
      const cv = document.createElement('canvas'); cv.width = 240; cv.height = 120;
      const c = cv.getContext('2d'); c.fillStyle = '#ddd6fe'; c.fillRect(0, 0, 240, 120);
      const blob = await new Promise(r => cv.toBlob(r, 'image/png'));
      const dt = new DataTransfer(); dt.items.add(new File([blob], 'x.png', {type: 'image/png'}));
      document.body.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true}));
    }""")
    page.wait_for_timeout(2500)

    # add a page
    page.locator(".wb-addpage").click()
    expect(page.locator(".wb-thumb")).to_have_count(2)
    page.wait_for_timeout(1500)
    page.screenshot(path=str(shots / "whiteboard_editor.png"))

    # instruments draw at full size on a board too (board.css once shrank every svg to 18 px)
    for kind in ("ruler", "protractor", "setsquare"):
        page.locator(f'.ink-rail [data-inst="{kind}"]').click()
        body = page.locator(f".an-inst-{kind} .an-inst-body").bounding_box()
        assert body and body["width"] > 250, (kind, body)
    # instruments are always true size: no size control, the ruler says its real length
    assert page.locator(".an-inst-size").count() == 0
    expect(page.locator(".an-inst-ruler .an-inst-unit")).to_have_text("15 cm")
    page.screenshot(path=str(shots / "whiteboard_instruments.png"))
    for kind in ("setsquare", "protractor"):
        page.locator(f'.ink-rail [data-inst="{kind}"]').click()
    page.locator('.ink-rail [data-inst="ruler"]').click()

    d = _board(student, bid)
    assert d["title"] == "Circle theorems"
    assert len(d["pages"]) == 2
    kinds = [o["t"] for o in d["pages"][0]["objects"]]
    assert "pen" in kinds and "img" in kinds, kinds
    assert d["pages"][0]["settings"].get("pattern") == "dotted"

    # reload: everything is still there
    page.reload()
    expect(page.locator(".wb-thumb")).to_have_count(2, timeout=15_000)
    expect(page.locator(".wb-title")).to_have_value("Circle theorems")

    # export
    r = student.request.get(f"/api/wb/boards/{bid}/export.pdf")
    assert r.ok and r.body()[:4] == b"%PDF"

    # share link: a guest sees it read-only, with no tools
    tok = student.request.post(f"/api/wb/boards/{bid}/shares", data={"role": "view"}).json()["token"]
    guest = browser.new_context(viewport={"width": 1280, "height": 860}, base_url=base_url)
    gp = guest.new_page()
    gp.goto(f"/whiteboard/s/{tok}")
    expect(gp.locator(".wb-badge")).to_contain_text("View only", timeout=15_000)
    expect(gp.locator(".ink-rail")).to_be_hidden()
    expect(gp.locator(".wb-thumb")).to_have_count(2)
    gp.screenshot(path=str(shots / "whiteboard_shared.png"))
    guest.close()

    # dashboard lists it
    page.goto("/whiteboard")
    expect(page.locator(".wbd-card")).to_have_count(1)
    expect(page.locator(".wbd-card h3")).to_have_text("Circle theorems")
    page.screenshot(path=str(shots / "whiteboard_dashboard.png"))


def test_infinite_canvas_zoom_and_draw(student, shots):
    bid = student.request.post("/api/wb/boards", data={"template": "chalk"}).json()["id"]
    page = student.new_page()
    page.add_init_script("localStorage.setItem('pwt-wn', JSON.stringify({'board-2026-10': 1}))")
    page.goto(f"/whiteboard/{bid}")
    inf = page.locator(".wb-inf")
    expect(inf.locator("canvas.an-layer")).to_be_attached(timeout=15_000)
    expect(page.locator(".wb-mini")).to_be_visible()
    pct = page.locator(".wb-zoompct")
    before = pct.inner_text()
    b = inf.bounding_box()
    page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
    page.keyboard.down("Control")
    page.mouse.wheel(0, -400)
    page.keyboard.up("Control")
    expect(pct).not_to_have_text(before)
    page.locator('.ink-rail [data-tool="pen"]').click()
    page.mouse.move(b["x"] + 200, b["y"] + 200)
    page.mouse.down()
    page.mouse.move(b["x"] + 420, b["y"] + 260, steps=10)
    page.mouse.up()
    page.wait_for_timeout(1800)
    page.screenshot(path=str(shots / "whiteboard_infinite.png"))
    objs = _board(student, bid)["pages"][0]["objects"]
    assert [o["t"] for o in objs] == ["pen"]


def test_public_page_features_and_spotlight(browser, base_url, shots):
    ctx = browser.new_context(viewport={"width": 1280, "height": 860}, base_url=base_url)
    page = ctx.new_page()
    page.goto("/whiteboard")
    expect(page.get_by_role("heading", level=1)).to_contain_text("whiteboard")
    page.goto("/features")
    expect(page.locator(".ft-card.is-new")).to_have_count(3)
    page.screenshot(path=str(shots / "features.png"), full_page=True)
    # the nav shows the whiteboard
    expect(page.locator(".nav-wb")).to_be_attached()
    # the spotlight: once, then never again
    page.goto("/tools.html")
    card = page.locator(".wn-card")
    expect(card).to_be_visible(timeout=8_000)
    page.screenshot(path=str(shots / "whats_new.png"))
    card.locator(".wn-x").click()
    page.reload()
    page.wait_for_timeout(3500)
    expect(page.locator(".wn-card")).to_have_count(0)
    ctx.close()
