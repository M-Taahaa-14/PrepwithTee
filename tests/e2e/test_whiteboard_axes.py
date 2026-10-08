"""Graph with axes paper on the Board: template -> Paper dialog -> ranges and box
values saved on the page; a bad range shows a message and saves nothing."""

import re

from playwright.sync_api import expect


def test_graph_with_axes(student, shots):
    page = student.new_page()
    page.goto("/whiteboard")
    page.locator('[data-tpl="axes"]').click()
    page.wait_for_url(re.compile(r"/whiteboard/[A-Za-z0-9]+$"))
    bid = page.url.rsplit("/", 1)[1]
    expect(page.locator(".wb-pg canvas.an-layer").first).to_be_attached(timeout=15_000)
    board = student.request.get(f"/api/wb/boards/{bid}").json()
    assert board["settings"]["pattern"] == "axes"
    assert board["settings"]["ax"]["x0"] == -5

    page.locator('[data-act="paper"]').click()
    box = page.locator(".wb-axes")
    expect(box).to_be_visible()

    # a backwards range: message, nothing saved
    box.locator('[name="x1"]').fill("-9")
    box.locator('[name="x1"]').press("Enter")
    expect(box.locator(".wb-axes-err")).to_contain_text("smaller to bigger")

    # the trig preset: 0..360 in 30s, -2..2 in 0.5s, free scale
    box.locator('[data-axpreset="trig"]').click()
    expect(box.locator(".wb-axes-err")).to_have_text("")
    page.wait_for_timeout(800)
    pg = student.request.get(f"/api/wb/boards/{bid}").json()["pages"][0]
    ax = pg["settings"]["ax"]
    assert (ax["x0"], ax["x1"], ax["dx"], ax["y0"], ax["y1"], ax["dy"], ax["eq"]) == (0, 360, 30, -2, 2, 0.5, False)

    # small squares per big square
    box.locator('[name="sub"]').select_option("10")
    page.wait_for_timeout(800)
    assert student.request.get(f"/api/wb/boards/{bid}").json()["pages"][0]["settings"]["ax"]["sub"] == 10
    page.locator(".wb-dlg [data-close]").first.click()
    page.wait_for_timeout(600)
    page.screenshot(path=str(shots / "whiteboard-axes.png"))

    # other patterns hide the axes form
    page.locator('[data-act="paper"]').click()
    page.locator('[data-pattern="lined"]').click()
    expect(page.locator(".wb-axes")).to_be_hidden()
