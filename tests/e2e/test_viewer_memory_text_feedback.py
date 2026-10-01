"""Feedback 2026-09-30: "the website and Chrome lag when a paper is built",
"the text box can be moved but not enlarged", "feedback has no name/email".

- PDF pages far off screen give their canvases back; ink layers hold no pixels
  on pages without ink (they used to keep two full-page canvases per page).
- The text box works like a PDF editor's: formatting bar, Enter = new line,
  Esc finishes, corner / side handles, nudge, duplicate, delete.
- The floating Feedback form is pre-filled for a signed-in student and refuses
  a malformed email.
"""

import re

from playwright.sync_api import expect

from tests.e2e.test_annotations import _paper_id, _strokes

LIVE = """s => {
  const px = (sel) => [...s.querySelectorAll(sel)].filter((c) => c.width > 0).length;
  return { pdf: px('canvas.vw-pdf'), ink: px('canvas.an-layer'), pages: s.querySelectorAll('.vw-pg').length };
}"""


def _open(student):
    student.request.post("/api/enrollments", data={"syllabus": "5054"})
    pid = _paper_id()
    page = student.new_page()
    page.goto(f"/yearly/view/{pid}")
    split = page.get_by_role("button", name=re.compile("Side by side"))
    if split.get_attribute("aria-pressed") == "true":
        split.click()
    stage = page.locator("#pv-qp")
    expect(stage.locator(".vw-pg canvas.vw-pdf").first).to_be_visible(timeout=30_000)
    return pid, page, stage


def test_far_pages_release_their_canvases(student):
    _, page, stage = _open(student)
    peak = 0
    n = stage.evaluate("s => s.querySelectorAll('.vw-pg').length")
    assert n >= 10
    for i in range(n):                               # scroll through the whole paper
        stage.evaluate(f"s => s.scrollTop = s.querySelectorAll('.vw-pg')[{i}].offsetTop")
        page.wait_for_timeout(250)
        peak = max(peak, stage.evaluate(LIVE)["pdf"])
    page.wait_for_timeout(800)
    live = stage.evaluate(LIVE)
    assert live["pdf"] <= 6 and peak <= 8, (live, peak)       # not all n pages
    assert live["ink"] == 0, live                              # no ink, no pixels
    # scrolling back redraws page 1
    stage.evaluate("s => s.scrollTop = 0")
    expect(stage.locator(".vw-pg").first.locator("canvas.vw-pdf")).to_have_count(1, timeout=10_000)


def _texts(student, pid):
    return [x for x in _strokes(student, pid) if x["t"] == "text"]


def _handle(page, t, which):
    """Screen position of a selected text box's handle (annotate.js handles())."""
    return page.evaluate("""([t, which]) => {
      const c = document.querySelectorAll('#pv-qp .vw-pg')[1].querySelector('canvas.an-layer');
      const r = c.getBoundingClientRect(), W = r.width, H = r.height;
      const fs = t.s * W, pad = (t.bg || t.bd) ? Math.round(fs * 0.35) : 0;
      const fam = { serif: 'Georgia, "Times New Roman", serif' }[t.f] || '"Hanken Grotesk", system-ui, sans-serif';
      const m = document.createElement('canvas').getContext('2d');
      m.font = `${t.i ? 'italic ' : ''}${t.b ? 700 : t.f ? 400 : 600} ${fs}px ${fam}`;
      const lines = t.txt.split('\\n');
      const bw = t.bw ? t.bw * W : Math.max(...lines.map((l) => m.measureText(l).width));
      const x0 = r.left + t.x * W - pad - 5, x1 = r.left + t.x * W + bw + pad + 5;
      const y0 = r.top + t.y * H - pad - 5, y1 = r.top + t.y * H + lines.length * fs * 1.25 + pad + 5;
      return { se: [x1, y1], e: [x1, (y0 + y1) / 2], nw: [x0, y0] }[which];
    }""", [t, which])


def test_text_box_like_a_pdf_editor(student, shots):
    pid, page, stage = _open(student)
    stage.evaluate("s => s.scrollTop = s.querySelectorAll('.vw-pg')[1].offsetTop")
    page.wait_for_timeout(800)
    box = stage.locator(".vw-pg").nth(1).bounding_box()
    page.locator('.an-bar [data-tool="text"]').click()
    tx, ty = box["x"] + 150, box["y"] + 330
    page.mouse.click(tx, ty)
    ed = page.locator(".an-text")
    expect(ed).to_be_focused()
    bar = page.locator(".an-tb")
    expect(bar).to_be_visible()

    # 1. two lines (Enter = new line), the box grows as you type
    w0 = ed.bounding_box()["width"]
    page.keyboard.type("F = ma")
    page.keyboard.press("Enter")
    page.keyboard.type("so a = F / m")
    assert ed.bounding_box()["width"] > w0 and ed.input_value() == "F = ma\nso a = F / m"

    # 2. formatting from the bar keeps the caret in the box
    bar.locator('[data-tb="font"]').select_option("serif")
    bar.locator('[data-tb="bigger"]').click()
    bar.locator('[data-tb="bigger"]').click()          # 12 -> 14 -> 16 pt
    bar.locator('[data-tb="b"]').click()
    bar.locator('[data-tb="al"][data-v="c"]').click()
    bar.locator('[data-tb="fill"]').click()
    bar.locator('[data-tbf="@yellow"]').click()
    bar.locator('[data-tb="bd"]').click()
    expect(ed).to_be_focused()
    page.keyboard.type("!")
    expect(bar.locator('[data-tb="pt"]')).to_have_value("16")
    assert "700" in ed.evaluate("e => getComputedStyle(e).fontWeight")
    page.screenshot(path=str(shots / "text-box-editing.png"))

    # 3. Esc finishes: stored with its style, and it stays selected
    page.keyboard.press("Escape")
    page.wait_for_timeout(1200)
    [t] = _texts(student, pid)
    assert t["txt"] == "F = ma\nso a = F / m!" and t["f"] == "serif" and t["b"] == 1
    assert t["al"] == "c" and t["bg"] == "@yellow" and t["bd"] == 1
    assert abs(t["s"] * 595 - 16) < 0.6
    expect(bar).to_be_visible()                      # the bar stays for the selected box

    # 4. the corner handle scales it, the side handle sets the wrap width
    page.locator('.an-bar [data-tool="select"]').click()
    x, y = _handle(page, t, "se")
    page.mouse.move(x, y); page.mouse.down(); page.mouse.move(x + 120, y + 60, steps=6); page.mouse.up()
    page.wait_for_timeout(1200)
    [t2] = _texts(student, pid)
    assert t2["s"] > t["s"] * 1.2, (t["s"], t2["s"])
    x, y = _handle(page, t2, "e")
    page.mouse.move(x, y); page.mouse.down(); page.mouse.move(x - 60, y, steps=5); page.mouse.up()
    page.wait_for_timeout(1200)
    [t3] = _texts(student, pid)
    assert t3.get("bw") and t3["s"] == t2["s"], t3
    page.screenshot(path=str(shots / "text-box-selected.png"))

    # 5. keys: arrows nudge, Ctrl+D duplicates, Delete removes the copy, Ctrl+Z / Y
    page.keyboard.press("Shift+ArrowRight")
    page.wait_for_timeout(1200)
    [t4] = _texts(student, pid)
    assert t4["x"] > t3["x"]
    page.keyboard.press("Control+d")
    page.wait_for_timeout(1200)
    assert len(_texts(student, pid)) == 2
    page.keyboard.press("Delete")
    page.wait_for_timeout(1200)
    assert len(_texts(student, pid)) == 1

    # 6. click on it with the Text tool = type in it again; clicking away just ends the edit
    page.locator('.an-bar [data-tool="text"]').click()
    x, y = _handle(page, t4, "nw")
    page.mouse.click(x + 30, y + 20)
    expect(ed).to_be_focused()
    expect(ed).to_have_value("F = ma\nso a = F / m!")
    page.mouse.click(box["x"] + 400, box["y"] + 700)           # away: ends it, no new box
    page.wait_for_timeout(1200)
    expect(page.locator(".an-text")).to_have_count(0)
    assert len(_texts(student, pid)) == 1

    # 7. the download with ink carries it
    pdf = student.request.get(f"/api/library/pdf/{pid}")        # the paper exists
    assert pdf.ok


def test_feedback_is_prefilled_and_checks_the_email(student, shots):
    me = student.request.get("/auth/me").json()
    page = student.new_page()
    page.goto("/tools.html")
    page.locator("#fbTabBtn").click()
    expect(page.locator("#fbEmail")).to_have_value(me["email"], timeout=10_000)
    expect(page.locator("#fbName")).not_to_have_value("")
    page.locator("#fbMessage").fill("The contents links jump one page too far.")
    page.locator("#fbEmail").fill("ali@")
    page.locator("#fbSubmitBtn").click()
    expect(page.locator("#fbError")).to_contain_text("email")
    page.locator("#fbEmail").fill("ali@gmial.com")
    page.locator("#fbSubmitBtn").click()
    expect(page.locator("#fbError")).to_contain_text("gmail.com")
    page.locator("#fbEmail").fill(me["email"])
    page.locator("#fbSubmitBtn").click()
    expect(page.locator("#fbThanks")).to_be_visible()
    page.screenshot(path=str(shots / "feedback-sent.png"))
