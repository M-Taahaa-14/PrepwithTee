"""Teaching phase 1, two browsers: a teacher and their student on the same
whiteboard and the same booklet. What one draws shows up for the other within
a couple of seconds, both see who is here, and "Hide other ink" hides it."""

import sqlite3
import uuid

import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import USERS_DB


def _student_id(ctx):
    return ctx.request.get("/auth/me?fresh=true").json()["id"]


@pytest.fixture()
def teacher(browser, base_url, student):
    """A teacher account linked (teacher_students) to the `student` fixture."""
    ctx = browser.new_context(viewport={"width": 1280, "height": 860}, base_url=base_url)
    email = f"e2e_t_{uuid.uuid4().hex[:8]}@test.local"
    pw = "Passw0rd!23"
    assert ctx.request.post("/auth/register", data={"email": email, "password": pw, "name": "Tariq Teacher"}).ok
    sid = _student_id(student)
    con = sqlite3.connect(USERS_DB)
    tid = con.execute("SELECT id FROM profiles WHERE email=?", (email,)).fetchone()[0]
    con.execute("UPDATE profiles SET role='teacher' WHERE id=?", (tid,))
    con.execute("INSERT INTO teacher_students (teacher_id, student_id, syllabus, status) VALUES (?,?,?, 'active')",
                (tid, sid, "5054"))
    con.commit()
    con.close()
    assert ctx.request.post("/auth/login", data={"email": email, "password": pw}).ok    # token with the new role
    ctx.add_init_script("localStorage.setItem('pwt-wn', JSON.stringify({'board-2026-10': 1, "
                        "'instagram-2026-10': 1, 'coach-rail': 1}))")
    ctx.tid = tid
    yield ctx
    ctx.close()


def _draw(page, box, dx=0):
    page.mouse.move(box["x"] + 80 + dx, box["y"] + 120)
    page.mouse.down()
    page.mouse.move(box["x"] + 260 + dx, box["y"] + 200, steps=10)
    page.mouse.up()


def _count(page, doc, pg):
    return page.evaluate(f"() => (window.pwtInk.page({doc!r}, {pg!r})?.strokes || []).length")


def test_whiteboard_live_between_teacher_and_student(student, teacher, shots):
    b = student.request.post("/api/wb/boards", data={"title": "Lesson 1"}).json()
    student.request.patch(f"/api/wb/boards/{b['id']}", data={"teacher_edit": True})
    pid = student.request.get(f"/api/wb/boards/{b['id']}").json()["pages"][0]["id"]
    doc = f"wb:{b['id']}"

    sp, tp = student.new_page(), teacher.new_page()
    for p in (sp, tp):
        p.goto(f"/whiteboard/{b['id']}")
        expect(p.locator(".wb-pg canvas.an-layer").first).to_be_attached(timeout=15_000)
    # both see each other
    expect(sp.locator(".collab-bar.has-company")).to_be_visible(timeout=15_000)
    expect(sp.locator(".collab-label")).to_contain_text("Tariq")
    expect(tp.locator(".collab-bar.has-company")).to_be_visible(timeout=15_000)

    # the teacher draws -> the student sees it
    tp.locator('.ink-rail [data-tool="pen"]').click()
    _draw(tp, tp.locator(".wb-pg").first.bounding_box())
    expect(tp.locator(".wb-status")).to_have_text("All changes saved", timeout=10_000)
    tp.wait_for_function(f"() => true")
    sp.wait_for_function(f"() => (window.pwtInk.page({doc!r}, {pid!r})?.strokes || []).length === 1", timeout=8_000)

    # the student draws too -> the teacher has both
    sp.locator('.ink-rail [data-tool="pen"]').click()
    _draw(sp, sp.locator(".wb-pg").first.bounding_box(), dx=200)
    tp.wait_for_function(f"() => (window.pwtInk.page({doc!r}, {pid!r})?.strokes || []).length === 2", timeout=8_000)
    sp.screenshot(path=str(shots / "collab_board_student.png"))

    # saved with authors
    objs = student.request.get(f"/api/wb/boards/{b['id']}").json()["pages"][0]["objects"]
    assert sorted(o["by"] for o in objs) == sorted([_student_id(student), teacher.tid])

    # hide the other person's ink: the student's page shows only their own
    sp.locator(".collab-hide").click()
    expect(sp.locator(".collab-hide")).to_have_attribute("aria-pressed", "true")
    assert _count(sp, doc, pid) == 2          # still there, just not drawn
    sp.locator(".collab-hide").click()


def test_booklet_shared_ink_live(student, teacher, shots):
    req = student.request
    req.post("/api/enrollments", data={"syllabus": "5054"})
    b = req.post("/api/booklets", data={
        "syllabus": "5054", "papers": [2], "year_from": 2019, "year_to": 2025,
        "picks": [{"chapter": "Pressure"}], "max_questions": 2}).json()
    sp = student.new_page()
    sp.goto(b["url"])
    expect(sp.locator(".vw-pg canvas").first).to_be_visible(timeout=90_000)
    # the student opens it up to their teacher
    sp.once("dialog", lambda d: d.accept())
    sp.get_by_role("button", name="Work on this with my teacher").click()
    sp.wait_for_load_state()
    expect(sp.locator(".collab-bar")).to_be_visible(timeout=60_000)
    expect(sp.locator(".vw-pg canvas.vw-pdf").first).to_be_visible(timeout=60_000)

    tp = teacher.new_page()
    tp.goto(b["url"])
    expect(tp.locator(".vw-pg canvas.vw-pdf").first).to_be_visible(timeout=60_000)
    expect(tp.locator(".collab-bar")).to_be_visible()
    expect(tp.locator(".collab-label")).to_contain_text("E2E is here", timeout=10_000)    # the student, live

    tp.locator('.ink-rail [data-tool="pen"]').click()
    _draw(tp, tp.locator(".vw-pg").first.bounding_box())
    doc = f"booklet:{b['id']}"
    tp.wait_for_function("() => true")
    # it reaches the server...
    for _ in range(40):
        pages = req.get(f"/api/collab?doc={doc}").json()["pages"]
        if pages:
            break
        tp.wait_for_timeout(250)
    assert pages, "teacher's stroke never saved"
    pg = int(next(iter(pages)))
    # ...and the student's open viewer, without a reload
    sp.wait_for_function(f"() => (window.pwtInk.page({doc!r}, {pg}) || window.pwtInk.page({doc!r}, '{pg}'))"
                         f"?.strokes.length === 1", timeout=10_000)
    expect(sp.locator(".collab-bar.has-company")).to_be_visible(timeout=10_000)
    sp.screenshot(path=str(shots / "collab_booklet_student.png"))
    tp.screenshot(path=str(shots / "collab_booklet_teacher.png"))
    # downloads with both people's ink
    r = req.get(f"/api/booklets/{b['id']}/pdf?annotated=1")
    assert r.ok and r.body()[:4] == b"%PDF"
