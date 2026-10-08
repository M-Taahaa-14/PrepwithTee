"""My classroom (/classroom): the student's side of the shared folder."""

import pytest

from tests.api.test_collab import _user


@pytest.fixture()
def cls(app):
    import teaching
    import users_db
    teaching.clear()
    s = _user(app, name="Sana Student")
    t = _user(app, "teacher", "Tariq Teacher")
    o = _user(app, name="Other Student")
    users_db.assign_teacher_student(t.uid, s.uid, "5054")
    teaching.clear()
    yield {"student": s, "teacher": t, "other": o}
    for c in (s, t, o):
        c.__exit__(None, None, None)


def _note(t, sid, title="Read pages 3-5", kind="note", **extra):
    r = t.post(f"/api/teach/students/{sid}/folder", json={"syllabus": "5054", "kind": kind, "title": title, **extra})
    assert r.status_code == 200, r.text
    return r.json()["item"]


def test_one_subject_goes_straight_to_it(cls):
    r = cls["student"].get("/classroom", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/classroom/5054"


def test_no_teacher_gets_the_classes_pitch(cls):
    r = cls["other"].get("/classroom")
    assert r.status_code == 200 and "Learn with a PrepWithTee teacher" in r.text
    assert cls["other"].get("/classroom/5054", follow_redirects=False).status_code == 302


def test_subject_page_shows_the_folder_but_not_private_notes(cls):
    s, t = cls["student"], cls["teacher"]
    _note(t, s.uid, "Before Thursday", body="Read the pressure notes")
    t.post(f"/api/teach/students/{s.uid}/notes", json={"body": "SECRET weak on indices", "syllabus": "5054"})
    r = s.get("/classroom/5054")
    assert r.status_code == 200
    assert "Before Thursday" in r.text and "Read the pressure notes" in r.text
    assert "SECRET" not in r.text
    assert "Tariq Teacher" in r.text and "Next up" in r.text


def test_mark_done_and_undo(cls):
    s, t = cls["student"], cls["teacher"]
    it = _note(t, s.uid)
    assert s.post(f"/api/classroom/items/{it['id']}/open").status_code == 200
    import teach_store
    assert teach_store.get_item(it["id"])["status"] == "in_progress"
    assert s.post(f"/api/classroom/items/{it['id']}/done").json()["status"] == "done"
    row = teach_store.get_item(it["id"])
    assert row["status"] == "done" and row["student_done_at"]
    # the teacher sees it waiting to be marked
    assert t.get("/api/teach/overview").json()["totals"]["to_mark"] == 0     # notes aren't marked work
    assert s.post(f"/api/classroom/items/{it['id']}/done?undo=1").json()["status"] == "in_progress"
    t.patch(f"/api/teach/folder/{it['id']}", json={"status": "marked"})
    assert s.post(f"/api/classroom/items/{it['id']}/done").status_code == 409


def test_items_are_private_to_their_student(cls):
    it = _note(cls["teacher"], cls["student"].uid)
    assert cls["other"].post(f"/api/classroom/items/{it['id']}/done").status_code == 404
    assert cls["other"].post(f"/api/classroom/items/{it['id']}/open").status_code == 404
    nid = cls["teacher"].post(f"/api/teach/students/{cls['student'].uid}/notes", json={"body": "x"}).json()["id"]
    assert cls["student"].post(f"/api/classroom/items/{nid}/done").status_code == 404


def test_feedback_shows_on_marked_items(cls):
    s, t = cls["student"], cls["teacher"]
    it = _note(t, s.uid, "Moments worksheet")
    import teach_store
    teach_store.set_feedback(it["id"], [{"marks": 7, "max_marks": 10, "comment": "Show the formula first"}], t.uid)
    t.patch(f"/api/teach/folder/{it['id']}", json={"status": "marked"})
    html = s.get("/classroom/5054").text
    assert "7 / 10" in html and "Show the formula first" in html


def test_bell_and_summary(cls):
    s, t = cls["student"], cls["teacher"]
    it = _note(t, s.uid, "Watch this", kind="link", url="https://example.com/v")
    n = s.get("/api/notifications").json()["notifications"]
    assert any(x["title"] == "From your teacher: Watch this" and x["href"] == "/classroom/5054" for x in n)
    t.patch(f"/api/teach/folder/{it['id']}", json={"status": "marked"})
    n = s.get("/api/notifications").json()["notifications"]
    assert any(x["title"] == "Marked: Watch this" for x in n)
    summ = s.get("/api/classroom").json()
    assert summ["subjects"][0]["syllabus"] == "5054" and summ["subjects"][0]["marked"] == 1


def test_login_needed(client):
    assert client.get("/classroom", follow_redirects=False).headers["location"].startswith("/login.html")
