"""The fx-991ES-style calculator, in a real browser.

- natural display: fractions, roots and powers typed into boxes; exact answers
  (5/6, √2/2) with S⇔D for the decimal; SHIFT = for the decimal straight away
- SOLVE, EQN (quadratic), STAT (1-variable), TABLE, BASE-N
- the physical keyboard
- memory + history per account: a guest's history merged at sign-up,
  STO / M+ / variables kept across a reload and on a second device
- the Tools tab on the paper viewers: calculator beside the paper, the right
  tools for the subject, and the calculator's keys do not trigger the
  annotation tools' shortcuts
"""

import re
import sqlite3
import uuid

from playwright.sync_api import expect

from tests.conftest import INDEX_DB


def k(page, *keys):
    for key in keys:
        page.locator(f'.cx-device [data-key="{key}"]').first.click()


def res(page):
    return page.locator(".cx-res").first


def paper(syl, year=2019):
    con = sqlite3.connect(INDEX_DB)
    pid = con.execute("SELECT id FROM papers WHERE syllabus=? AND year=? AND kind='qp' ORDER BY paper DESC LIMIT 1",
                      (syl, year)).fetchone()[0]
    con.close()
    return pid


def test_natural_display_exact_answers_and_modes(student, shots):
    page = student.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("/calculator.html")
    expect(page.locator(".cx-device")).to_be_visible()

    # ½ + ⅓ typed into fraction boxes -> 5/6 (stacked); S⇔D -> decimal
    k(page, "1", "frac", "2", "right", "add", "1", "frac", "3")
    expect(page.locator(".cx-in .cx-frac")).to_have_count(2)
    k(page, "eq")
    expect(res(page).locator(".cx-frac span").first).to_have_text("5")
    expect(res(page).locator(".cx-frac span").last).to_have_text("6")
    k(page, "sd")
    expect(res(page)).to_have_text("0.8333333333")
    page.locator(".cx-device").screenshot(path=str(shots / "calc-fraction.png"))

    # sin 45 -> √2/2 exactly; SHIFT = gives the decimal
    k(page, "ac", "sin", "4", "5", "eq")
    expect(res(page)).to_contain_text("√")
    k(page, "sin", "4", "5", "shift", "eq")
    expect(res(page)).to_have_text("0.7071067812")
    # an operator straight after an answer carries on from Ans
    k(page, "ac", "2", "eq", "mul", "3", "eq")
    expect(res(page)).to_have_text("6")

    # errors say what went wrong
    k(page, "ac", "1", "div", "0", "eq")
    expect(page.locator(".cx-err")).to_contain_text("Math ERROR")
    k(page, "ac")

    # SOLVE: X² − 2 = 0 from X = 1
    k(page, "alpha", "rp", "sq", "sub", "2", "shift", "calc")
    expect(page.locator(".cx-prompt")).to_contain_text("X =")
    k(page, "1", "eq")
    expect(page.locator(".cx-res-list")).to_contain_text("1.414213562")
    page.locator(".cx-device").screenshot(path=str(shots / "calc-solve.png"))

    # EQN: X² − 3X + 2 = 0 -> 2 and 1
    k(page, "ac", "mode")
    expect(page.locator(".cx-menu")).to_contain_text("EQN")
    k(page, "5", "3")
    k(page, "1", "eq", "neg", "3", "eq", "2", "eq", "eq")
    sols = page.locator(".cx-sols")
    expect(sols).to_contain_text("X1 =")
    expect(sols.locator("dd").nth(0)).to_have_text("2")
    expect(sols.locator("dd").nth(1)).to_have_text("1")
    page.locator(".cx-device").screenshot(path=str(shots / "calc-eqn.png"))

    # STAT: 1, 2, 3, 4, 10 -> mean 4
    k(page, "mode", "3", "1")
    for n in ("1", "2", "3", "4"):
        k(page, n, "eq")
    k(page, "1", "0", "eq", "ac")
    stats = page.locator(".cx-stats")
    expect(stats).to_contain_text("x̄")
    expect(stats.locator("div", has_text="x̄").locator("dd")).to_have_text("4")
    expect(stats.locator("div", has_text="med").locator("dd")).to_have_text("3")
    page.locator(".cx-device").screenshot(path=str(shots / "calc-stat.png"))

    # TABLE: f(X) = X², 1 to 5
    k(page, "mode", "7", "alpha", "rp", "sq", "eq", "eq", "eq", "eq")
    rows = page.locator(".cx-table tbody tr")
    expect(rows).to_have_count(5)
    expect(rows.nth(2).locator("td").last).to_have_text("9")

    # BASE-N: FF + 1 in hex = 100, and the other bases
    k(page, "ac", "mode", "4", "pow", "tan", "tan", "add", "1", "eq")
    expect(res(page)).to_have_text("100")
    expect(page.locator(".cx-bases")).to_contain_text("256")
    page.locator(".cx-device").screenshot(path=str(shots / "calc-base.png"))

    # back to COMP, then the keyboard: 2^10 = 1024, 3/4 is a fraction
    k(page, "mode", "1")
    page.locator(".cx-device").focus()
    page.keyboard.type("2^10")
    page.keyboard.press("Enter")
    expect(res(page)).to_have_text("1024")
    page.keyboard.press("Escape")
    page.keyboard.type("3/4")
    page.keyboard.press("ArrowRight")
    page.keyboard.type("+1")
    page.keyboard.press("Enter")
    expect(res(page).locator(".cx-frac span").first).to_have_text("7")
    assert not errors, errors


def test_history_memory_and_variables_follow_the_account(browser, base_url, shots):
    email = f"e2e_{uuid.uuid4().hex[:8]}@test.local"
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, base_url=base_url)
    page = ctx.new_page()
    page.goto("/calculator.html")
    expect(page.locator(".cx-device")).to_be_visible()
    k(page, "7", "mul", "6", "eq")
    expect(page.locator(".calc-hist-a").first).to_have_text("= 42")
    expect(page.locator("[data-sync]")).to_contain_text("this device")

    # sign up in the same browser: the guest history is merged into the account
    assert ctx.request.post("/auth/register", data={"email": email, "password": "Passw0rd!23",
                                                    "name": "Calc Student"}).ok
    ctx.request.post("/api/me/setup", data={"name": "Calc Student", "phone": "+92 3001234567",
                                            "boards": ["o-level"]})      # the profile gate
    page.reload()
    expect(page.locator("[data-sync]")).to_contain_text("your account")
    expect(page.locator(".calc-hist-a").first).to_have_text("= 42")

    # 12 × 3 = 36, SHIFT RCL (STO) then (−) = store in A; M+
    k(page, "ac", "1", "2", "mul", "3", "eq", "shift", "rcl", "neg")
    expect(page.locator('[data-var="A"] span')).to_have_text("36")
    k(page, "mplus")
    expect(page.locator('[data-var="M"] span')).to_have_text("36")
    # A + 4 = 40, typed with ALPHA
    k(page, "ac", "alpha", "neg", "add", "4", "eq")
    expect(page.locator(".calc-hist-a").first).to_have_text("= 40")
    page.wait_for_timeout(800)                                      # state save is debounced
    page.screenshot(path=str(shots / "calculator.png"))

    page.reload()
    expect(page.locator(".calc-hist-a")).to_have_count(3)
    expect(page.locator('[data-var="A"] span')).to_have_text("36")
    expect(page.locator('[data-var="M"] span')).to_have_text("36")

    # a second device sees the same; M (ALPHA M+) recalls memory
    other = browser.new_context(viewport={"width": 1280, "height": 900}, base_url=base_url)
    assert other.request.post("/auth/login", data={"email": email, "password": "Passw0rd!23"}).ok
    p2 = other.new_page()
    p2.goto("/calculator.html")
    expect(p2.locator(".calc-hist-a").first).to_have_text("= 40")
    k(p2, "alpha", "mplus", "add", "1", "eq")
    expect(p2.locator(".calc-hist-a").first).to_have_text("= 37")

    # ↺ brings a calculation back to edit; clear history
    page.reload()
    page.locator("[data-hist-q]").last.click()
    expect(page.locator(".cx-in")).to_contain_text("7")
    expect(page.locator(".cx-in")).to_contain_text("6")
    page.once("dialog", lambda d: d.accept())
    page.locator("[data-clear]").click()
    expect(page.locator(".calc-hist-a")).to_have_count(0)
    other.close()
    ctx.close()


def test_tools_tab_on_a_paper(student, shots):
    student.request.post("/api/enrollments", data={"syllabus": "5054"})
    page = student.new_page()
    page.goto(f"/yearly/view/{paper('5054')}")
    expect(page.locator(".vw-pg canvas.vw-pdf").first).to_be_visible(timeout=30_000)
    tab = page.locator(".pwt-fab")
    expect(tab).to_be_visible()
    tab.click()
    panel = page.locator(".pwt-panel")
    expect(panel).to_be_visible()
    # physics: calculator first, no periodic table
    names = panel.locator(".pwt-tab-name").all_inner_texts()
    assert names[0] == "Calculator" and "Periodic table" not in names, names
    expect(panel.locator(".cx-device")).to_be_visible(timeout=10_000)
    # the paper moves over instead of being covered
    expect(page.locator("body")).to_have_class(re.compile("pwt-docked"))
    page.wait_for_timeout(600)                                      # the slide-in and the reflow
    vw, pb = page.locator("#vw").bounding_box(), panel.bounding_box()
    assert vw["x"] + vw["width"] <= pb["x"] + 2, (vw, pb)

    # typing goes to the calculator, not the annotation shortcuts (p = pen, e = eraser)
    panel.locator(".cx-device").click(position={"x": 60, "y": 20})
    page.keyboard.type("2+3")
    page.keyboard.press("Enter")
    expect(panel.locator(".cx-res")).to_have_text("5")
    page.keyboard.type("pe")
    expect(page.locator('.an-bar [data-tool="pen"]')).to_have_attribute("aria-pressed", "false")
    page.screenshot(path=str(shots / "tools-dock-paper.png"))
    # close: the paper takes the width back
    panel.locator("[data-close]").click()
    expect(page.locator("body")).not_to_have_class(re.compile("pwt-docked"))


def test_tools_tab_on_a_chemistry_paper_has_the_periodic_table(student, shots):
    page = student.new_page()
    page.goto(f"/yearly/view/{paper('0620')}")
    expect(page.locator(".vw-pg canvas.vw-pdf").first).to_be_visible(timeout=30_000)
    page.locator(".pwt-fab").click()
    panel = page.locator(".pwt-panel")
    panel.locator(".pwt-tab", has_text="Periodic table").click()
    expect(panel.locator(".pt-cell").first).to_be_visible(timeout=10_000)
    page.screenshot(path=str(shots / "tools-dock-periodic.png"))
