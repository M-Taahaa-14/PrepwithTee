"""Admin console v2 in a real browser: sign-in gate, overview, the students
table (sort, filter, select, bulk bar), a student's profile and notes, the
command palette, and both themes. Screenshots go to e2e-shots/admin-*.png."""

def test_gate_for_signed_out(browser, base_url, shots):
    ctx = browser.new_context(base_url=base_url)
    page = ctx.new_page()
    page.goto("/admin")
    page.get_by_text("Continue with Google").wait_for()
    assert page.locator("#app").is_hidden()
    ctx.close()


def test_students_table_and_profile(admin_page, shots):
    page = admin_page
    page.goto("/admin#/students?sort=name&dir=asc")
    page.locator(".dt tbody tr.click").first.wait_for()
    names = page.locator(".dt tbody .who b").all_inner_texts()
    assert [n.lower() for n in names] == sorted(n.lower() for n in names)

    # sort by clicking a header; the URL keeps the state
    page.get_by_role("button", name="Booklets").click()
    page.wait_for_function("location.hash.includes('sort=booklets')")
    page.wait_for_timeout(500)

    # filter through a select; the hash follows
    page.locator("[data-filter=plan]").select_option("free")
    page.wait_for_function("location.hash.includes('plan=free')")
    page.wait_for_timeout(400)
    assert page.locator(".dt tbody .pill", has_text="Free").count() >= 1

    # selecting rows shows the bulk bar
    page.locator("[data-row]").nth(0).check()
    page.locator("[data-row]").nth(1).check()
    assert page.locator("[data-bulk]").inner_text().startswith("2 selected")
    page.screenshot(path=str(shots / "admin-students.png"), full_page=False)

    # search box keeps focus and caret while the table refreshes
    box = page.locator("input.search")
    box.click()
    box.type("e2e", delay=60)
    page.wait_for_timeout(600)
    assert box.input_value() == "e2e"
    assert page.evaluate("document.activeElement.classList.contains('search')")

    # open a student
    page.locator(".dt tbody tr.click").first.click()
    page.wait_for_function("location.hash.startsWith('#/student/')")
    page.locator(".stat-tiles").wait_for()
    page.get_by_role("tab", name="Notes").click()
    page.locator("#note-body").fill("E2E note")
    page.get_by_role("button", name="Add note").click()
    page.locator(".event .txt", has_text="E2E note").wait_for()
    page.screenshot(path=str(shots / "admin-student.png"))
    page.locator("[data-del-note]").first.click()
    page.locator(".modal button[type=submit]").click()
    page.locator(".event .txt", has_text="E2E note").wait_for(state="detached")


def test_palette_and_themes(admin_page, shots):
    page = admin_page
    page.goto("/admin#/overview")
    page.locator(".kpis").wait_for()
    page.keyboard.press("Control+k")
    page.locator("#pal-q").fill("expiring")
    page.keyboard.press("Enter")
    page.wait_for_function("location.hash.includes('expiring=7')")
    for theme in ("light", "dark"):
        page.evaluate(f"localStorage.setItem('theme', '{theme}'); location.hash = '#/overview'")
        page.reload()                         # a hash-only goto would not re-read the theme
        page.locator(".kpis").wait_for()
        bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
        assert bg == ("rgb(18, 19, 23)" if theme == "dark" else "rgb(246, 247, 251)")   # graphite / cool white
        page.screenshot(path=str(shots / f"admin-overview-{theme}.png"))


def test_phone_has_no_sideways_scroll(admin_page):
    page = admin_page
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto("/admin#/students")
    page.locator(".dt tbody tr").first.wait_for()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
