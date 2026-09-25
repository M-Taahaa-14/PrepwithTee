"""Graph plotter (P2-b) in a real browser: the new parser, friendly errors,
the last good graph kept while typing, implicit equations (a circle)."""

import re

from playwright.sync_api import expect

INK = """([hex, alpha]) => {
  const c = document.querySelector('[data-canvas]');
  const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
  const mix = (v) => alpha * v + (1 - alpha) * 255;          // drawn over white
  const r = mix(parseInt(hex.slice(1, 3), 16)), g = mix(parseInt(hex.slice(3, 5), 16)), b = mix(parseInt(hex.slice(5, 7), 16));
  let n = 0;
  for (let i = 0; i < d.length; i += 4)
    if (Math.abs(d[i] - r) < 40 && Math.abs(d[i + 1] - g) < 40 && Math.abs(d[i + 2] - b) < 40) n++;
  return n;
}"""
FIRST = "#6366f1"


def _open(browser, base_url):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, base_url=base_url)
    page = ctx.new_page()
    page.goto("/graph.html")
    expect(page.locator(".gp2-inp").first).to_be_visible(timeout=15_000)
    return ctx, page


def test_parser_errors_and_last_good_graph(browser, base_url, shots):
    ctx, page = _open(browser, base_url)
    inp = page.locator(".gp2-inp").first
    inp.fill("-x^2 + 4")                                    # was a JS SyntaxError before
    row = page.locator(".gp2-expr").first
    expect(row).not_to_have_class(re.compile("gp2-bad"))
    expect(row.locator(".gp2-type")).to_have_text("y =")
    good = page.evaluate(INK, [FIRST, 1])
    assert good > 200

    inp.fill("-x^2 + sin(")                                 # half-typed
    expect(row).to_have_class(re.compile("gp2-bad"))
    expect(row.locator(".gp2-errtxt")).to_contain_text("Missing ')' to close 'sin('")
    expect(row.locator(".gp2-errtxt")).to_contain_text("showing your last graph")
    assert page.evaluate(INK, [FIRST, 0.3]) > 50            # faded, but still there
    expect(inp).to_be_focused()                             # typing was never interrupted

    inp.fill("q + 1")
    expect(row.locator(".gp2-errtxt")).to_contain_text("use x")
    inp.fill("sin x + x(x-1)")                              # was ReferenceError / TypeError
    expect(row).not_to_have_class(re.compile("gp2-bad"))
    page.screenshot(path=str(shots / "graph_explicit.png"))
    ctx.close()


def test_circle_and_vertical_line(browser, base_url, shots):
    ctx, page = _open(browser, base_url)
    inp = page.locator(".gp2-inp").first
    inp.fill("x^2 + y^2 = 25")
    row = page.locator(".gp2-expr").first
    expect(row.locator(".gp2-type")).to_have_text("⤳")
    assert page.evaluate(INK, [FIRST, 1]) > 300                  # the circle is drawn
    box = page.evaluate("""() => {
      const c = document.querySelector('[data-canvas]');
      const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
      let x0 = 1e9, x1 = -1, y0 = 1e9, y1 = -1;
      for (let y = 0; y < c.height; y++) for (let x = 0; x < c.width; x++) {
        const i = (y * c.width + x) * 4;
        if (Math.abs(d[i] - 99) < 40 && Math.abs(d[i + 1] - 102) < 40 && Math.abs(d[i + 2] - 241) < 40) {
          x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y);
        }
      }
      return [x1 - x0, y1 - y0];
    }""")
    assert abs(box[0] - box[1]) <= max(6, 0.04 * box[0]), f"circle drawn as {box}"    # equal axes
    page.locator("[data-add]").click()
    second = page.locator(".gp2-inp").nth(1)
    second.fill("x = 3")
    expect(page.locator(".gp2-expr").nth(1).locator(".gp2-type")).to_have_text("x =")
    page.locator("[data-add]").click()
    page.locator(".gp2-inp").nth(2).fill("y < x")
    expect(page.locator(".gp2-expr").nth(2).locator(".gp2-errtxt")).to_contain_text("coming soon")
    page.screenshot(path=str(shots / "graph_circle.png"))
    ctx.close()


def test_presets_and_keyboard(browser, base_url):
    ctx, page = _open(browser, base_url)
    page.locator("[data-clear-all]").click()
    page.get_by_role("button", name="log₂x").click()
    expect(page.locator(".gp2-inp").first).to_have_value("log_2(x)")
    expect(page.locator(".gp2-expr").first).not_to_have_class(re.compile("gp2-bad"))
    page.locator("[data-kb-toggle]").click()
    inp = page.locator(".gp2-inp").first
    inp.fill("")
    inp.focus()
    for key in ("|x|", "x", "|x|"):
        page.locator(f'.gp2-kb-btn[data-ins="{"|" if key == "|x|" else key}"]').click()
    expect(inp).to_have_value("|x|")
    expect(page.locator(".gp2-expr").first).not_to_have_class(re.compile("gp2-bad"))
    ctx.close()
