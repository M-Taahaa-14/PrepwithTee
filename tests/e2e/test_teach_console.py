"""Teaching console (/teach) in a browser: Today, a student's page, the shared
folder (note, whiteboard, topical booklet), progress tab, light + dark."""

import re

from playwright.sync_api import expect

from tests.e2e.test_collab_live import teacher  # noqa: F401  (fixture)


def test_teach_console_walkthrough(student, teacher, shots):  # noqa: F811
    errors = []
    page = teacher.new_page()
    page.on("pageerror", lambda e: errors.append(f"{e} {e.stack}"))
    page.goto("/teach")
    expect(page.locator("#app")).to_be_visible(timeout=15_000)
    expect(page.get_by_role("heading", name=re.compile("Good (morning|afternoon|evening)"))).to_be_visible()
    expect(page.locator(".stu-card")).to_have_count(1)
    page.screenshot(path=str(shots / "teach_today.png"))

    page.locator(".stu-card").first.click()
    expect(page.locator(".profile-head h1")).to_have_text("E2E Student")
    expect(page.locator(".folder-cols")).to_be_visible()

    # a note for the student
    page.locator("[data-new]").click()
    page.locator('[data-make="note"]').click()
    page.locator(".modal [name=t]").fill("Before Thursday")
    page.locator(".modal [name=b]").fill("Read the pressure notes")
    page.locator(".modal button[type=submit]").click()
    expect(page.locator(".fi-title", has_text="Before Thursday")).to_be_visible()

    # a whiteboard (opens in a new tab)
    page.locator("[data-new]").click()
    page.locator('[data-make="board"]').click()
    page.locator(".modal [name=t]").fill("Lesson 1")
    with teacher.expect_page() as pop:
        page.locator(".modal button[type=submit]").click()
    board = pop.value
    expect(board.locator(".wb-pg canvas.an-layer").first).to_be_attached(timeout=15_000)
    expect(board.locator(".ink-rail")).to_be_visible()                 # the teacher can draw
    board.close()
    page.reload()
    expect(page.locator(".fi-title", has_text="Lesson 1")).to_be_visible(timeout=10_000)

    # a topical booklet
    page.locator("[data-new]").click()
    page.locator('[data-make="booklet"]').click()
    page.locator(".modal [data-ch] .chip").first.click()
    expect(page.locator(".modal [data-pool]")).to_contain_text("matching questions", timeout=10_000)
    page.locator(".modal [name=n]").fill("3")
    page.locator(".modal button[type=submit]").click()
    expect(page.locator(".fi-booklet")).to_have_count(1, timeout=15_000)
    page.screenshot(path=str(shots / "teach_folder.png"), full_page=True)

    # the student owns it and sees it shared
    items = teacher.request.get(f"/api/teach/students/{student.request.get('/auth/me?fresh=true').json()['id']}/folder").json()["items"]
    bid = next(i["ref_id"] for i in items if i["kind"] == "booklet")
    d = student.request.get(f"/api/booklets/{bid}").json()
    assert d["role"] == "owner" and d["collab"] is True

    # progress & marks + overview tabs render
    page.get_by_role("tab", name="Progress & marks").click()
    expect(page.locator("[data-manage]")).to_be_visible()
    page.get_by_role("tab", name="Overview").click()
    expect(page.locator(".stat-tiles")).to_be_visible()

    # dark mode
    page.locator("#theme-btn").click()
    page.get_by_role("tab", name="Folder").click()
    expect(page.locator(".folder-cols")).to_be_visible()
    page.screenshot(path=str(shots / "teach_folder_dark.png"), full_page=True)
    page.locator("#theme-btn").click()

    # other sections open
    for sec, text in (("students", "My students"), ("homework", "Homework"), ("groups", "Groups"),
                      ("messages", "Messages"), ("settings", "Settings")):
        page.goto(f"/teach#/{sec}")
        expect(page.get_by_role("heading", name=text, exact=True)).to_be_visible(timeout=10_000)
    assert not errors, errors


def test_students_get_the_gate(student):
    page = student.new_page()
    page.goto("/teach")
    expect(page.locator("#gate")).to_be_visible(timeout=10_000)
    expect(page.locator("#gate-note")).to_contain_text("isn't a teacher account")
