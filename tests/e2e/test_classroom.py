"""My classroom in a browser: what the teacher put in the folder shows up for the
student, "I've done this" moves it on, and the teacher sees it in /teach."""

from playwright.sync_api import expect

from tests.e2e.test_collab_live import _student_id, teacher  # noqa: F401  (fixture)


def test_student_classroom(student, teacher, shots):  # noqa: F811
    sid = _student_id(student)
    t = teacher.request
    t.post(f"/api/teach/students/{sid}/folder", data={"syllabus": "5054", "kind": "note", "title": "Before Thursday",
                                                      "body": "Read the pressure notes and try Q1-Q5", "due_at": "2030-01-10"})
    t.post(f"/api/teach/students/{sid}/folder", data={"syllabus": "5054", "kind": "link", "title": "Video: moments",
                                                      "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
    b = t.post(f"/api/teach/students/{sid}/boards", data={"syllabus": "5054", "title": "Lesson 1 - Pressure"}).json()
    t.post(f"/api/teach/students/{sid}/classes", data={"class_date": "2026-10-08", "syllabus": "5054",
                                                       "topic": "Pressure in liquids", "duration_min": 60})

    errors = []
    page = student.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("/classroom")
    page.wait_for_url("**/classroom/5054")
    expect(page.get_by_role("heading", name="Physics", exact=False).first).to_be_visible()
    expect(page.locator(".cr-teacher")).to_contain_text("Tariq Teacher")
    expect(page.locator('[data-col="todo"] .cr-item')).to_have_count(3)
    expect(page.locator(".cr-next h2")).to_have_text("Before Thursday")
    expect(page.locator(".cr-classes")).to_contain_text("Pressure in liquids")
    page.screenshot(path=str(shots / "classroom.png"), full_page=True)

    # filter chips
    page.locator('[data-show="board"]').click()
    expect(page.locator(".cr-item:visible")).to_have_count(1)
    page.locator('[data-show=""]').click()

    # done -> moves to the Done column, and the teacher's folder says so
    page.locator(".cr-item", has_text="Before Thursday").get_by_role("button", name="I've done this").click()
    expect(page.locator('[data-col="done"] .cr-item', has_text="Before Thursday")).to_be_visible()
    items = t.get(f"/api/teach/students/{sid}/folder").json()["items"]
    assert next(i for i in items if i["title"] == "Before Thursday")["status"] == "done"

    # opening the board moves it to In progress
    page.locator(".cr-item", has_text="Lesson 1").get_by_role("link", name="Open").click()
    page.wait_for_url(f"**/whiteboard/{b['board']['id']}")
    page.goto("/classroom/5054")
    expect(page.locator('[data-col="in_progress"] .cr-item', has_text="Lesson 1")).to_be_visible()

    # the bell
    n = student.request.get("/api/notifications").json()["notifications"]
    assert any(x["title"] == "From your teacher: Video: moments" for x in n)

    # dark
    page.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")
    page.screenshot(path=str(shots / "classroom_dark.png"), full_page=True)
    assert not errors, errors
