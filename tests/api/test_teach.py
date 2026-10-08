"""Teaching console API (/api/teach): a teacher sees and works with their own
students only; things built for a student land in the shared folder."""

import uuid

import pytest

from tests.api.test_collab import _booklet, _pen, _user
from tests.conftest import needs_index_db


@pytest.fixture()
def cls(app):
    import teaching
    import users_db
    teaching.clear()
    s = _user(app, name="Sana Student")
    s.post("/api/enrollments", json={"syllabus": "5054"})
    t = _user(app, "teacher", "Tariq Teacher")
    o = _user(app, "teacher", "Other Teacher")
    u = _user(app, name="Not Assigned")
    users_db.assign_teacher_student(t.uid, s.uid, "5054")
    teaching.clear()
    yield {"student": s, "teacher": t, "other": o, "unassigned": u}
    for c in (s, t, o, u):
        c.__exit__(None, None, None)


def test_only_teachers_get_in_and_the_role_is_read_from_the_db(app, cls):
    assert cls["student"].get("/api/teach/me").status_code == 403
    # promoted after signing in: no new sign-in needed
    import users_db
    c = _user(app, name="Late Teacher")
    users_db.update_profile(c.uid, {"role": "teacher"})
    assert c.get("/api/teach/me").status_code == 200
    c.__exit__(None, None, None)


def test_students_are_only_mine(cls):
    t, o, s = cls["teacher"], cls["other"], cls["student"]
    rows = t.get("/api/teach/students").json()["students"]
    assert [r["id"] for r in rows] == [s.uid] and rows[0]["subjects"] == ["5054"]
    assert o.get("/api/teach/students").json()["students"] == []
    assert t.get(f"/api/teach/students/{s.uid}").status_code == 200
    assert o.get(f"/api/teach/students/{s.uid}").status_code == 404
    assert t.get(f"/api/teach/students/{cls['unassigned'].uid}").status_code == 404
    d = t.get(f"/api/teach/students/{s.uid}").json()
    assert d["taught"] == ["5054"] and d["profile"]["id"] == s.uid
    ov = t.get("/api/teach/overview").json()
    assert ov["totals"]["students"] == 1


def test_activity_hides_admin_only_events(cls):
    a = cls["teacher"].get(f"/api/teach/students/{cls['student'].uid}/activity").json()
    assert not {"payment", "email", "note"} & {e["type"] for e in a["events"]}
    assert "plan" not in a and "summary" in a


def test_folder_note_status_and_access(cls):
    t, o, s = cls["teacher"], cls["other"], cls["student"]
    r = t.post(f"/api/teach/students/{s.uid}/folder", json={"syllabus": "5054", "kind": "note",
                                                             "title": "Before Thursday", "body": "Read pages 3-5"})
    assert r.status_code == 200, r.text
    item = r.json()["item"]
    assert item["status"] == "todo" and item["meta"]["body"] == "Read pages 3-5"
    assert o.patch(f"/api/teach/folder/{item['id']}", json={"status": "done"}).status_code == 404
    assert t.patch(f"/api/teach/folder/{item['id']}", json={"status": "marked"}).json()["item"]["status"] == "marked"
    f = t.get(f"/api/teach/students/{s.uid}/folder", params={"syllabus": "5054"}).json()
    assert [i["title"] for i in f["items"]] == ["Before Thursday"] and f["counts"]["marked"] == 1
    assert t.post(f"/api/teach/students/{s.uid}/folder", json={"syllabus": "5054", "kind": "link", "title": "x",
                                                                "url": "javascript:alert(1)"}).status_code == 400
    assert o.get(f"/api/teach/students/{s.uid}/folder").status_code == 404
    assert t.delete(f"/api/teach/folder/{item['id']}").status_code == 200


def test_homework_and_classes_go_in_the_folder(cls):
    t, s = cls["teacher"], cls["student"]
    a = t.post(f"/api/teach/students/{s.uid}/assignments?notify=false",
               json={"title": "Pressure worksheet", "syllabus": "5054", "due_date": "2030-01-10"}).json()["assignment"]
    c = t.post(f"/api/teach/students/{s.uid}/classes", json={"class_date": "2026-10-09", "syllabus": "5054",
                                                             "topic": "Moments", "duration_min": 60})
    assert c.status_code == 200, c.text
    items = t.get(f"/api/teach/students/{s.uid}/folder").json()["items"]
    kinds = {i["kind"]: i for i in items}
    assert kinds["homework"]["title"] == "Pressure worksheet" and kinds["homework"]["due_at"] == "2030-01-10"
    assert kinds["class"]["title"] == "Moments" and kinds["class"]["status"] == "done"
    # marking the homework done marks its folder row
    t.patch(f"/api/teach/assignments/{a['id']}", json={"status": "done"})
    items = t.get(f"/api/teach/students/{s.uid}/folder").json()["items"]
    assert next(i for i in items if i["kind"] == "homework")["status"] == "marked"
    # another teacher can't touch it
    assert cls["other"].patch(f"/api/teach/assignments/{a['id']}", json={"status": "assigned"}).status_code == 404
    assert cls["other"].get("/api/teach/homework").json()["students"] == []
    hw = t.get("/api/teach/homework").json()
    assert [x["user_id"] for x in hw["students"]] == [s.uid]


def test_homework_set_elsewhere_shows_in_the_folder(cls):
    import users_db
    users_db.create_assignment({"user_id": cls["student"].uid, "syllabus": "5054", "title": "Old homework",
                                "kind": "homework", "status": "assigned", "topics_json": "[]", "attachments_json": "[]"})
    items = cls["teacher"].get(f"/api/teach/students/{cls['student'].uid}/folder").json()["items"]
    v = next(i for i in items if i["title"] == "Old homework")
    assert v["meta"]["virtual"] and v["status"] == "todo"


def test_board_for_student(cls):
    t, s = cls["teacher"], cls["student"]
    r = t.post(f"/api/teach/students/{s.uid}/boards", json={"syllabus": "5054", "title": "Lesson 1"})
    assert r.status_code == 200, r.text
    bid = r.json()["board"]["id"]
    full = s.get(f"/api/wb/boards/{bid}").json()
    assert full["readonly"] is False                                   # the student owns it
    tb = t.get(f"/api/wb/boards/{bid}").json()
    assert tb["readonly"] is False and tb["collab"] is True            # and the teacher draws on it
    pid = tb["pages"][0]["id"]
    assert t.put(f"/api/wb/boards/{bid}/pages/{pid}", json={"objects": [_pen("a")], "version": 1}).status_code == 200
    # not counted against the student's free boards: they can still make all 3 of their own
    for _ in range(3):
        assert s.post("/api/wb/boards", json={"title": "mine"}).status_code == 200
    # opening it moves the folder row on
    s.get(f"/api/wb/boards/{bid}")
    item = next(i for i in t.get(f"/api/teach/students/{s.uid}/folder").json()["items"] if i["kind"] == "board")
    assert item["status"] == "in_progress" and item["student_opened_at"]
    assert cls["other"].post(f"/api/teach/students/{s.uid}/boards", json={"syllabus": "5054"}).status_code == 404


@needs_index_db
def test_booklet_for_student_is_theirs_shared_and_in_the_folder(cls):
    t, s = cls["teacher"], cls["student"]
    r = t.post(f"/api/teach/students/{s.uid}/booklets", json={
        "syllabus": "5054", "papers": [2], "year_from": 2018, "year_to": 2025,
        "picks": [{"chapter": "Pressure"}], "max_questions": 3, "due_date": "2030-02-01"})
    assert r.status_code == 200, r.text
    bid = r.json()["id"]
    import users_db
    b = users_db.get_booklet(bid)
    assert b["user_id"] == s.uid and b["params_json"]["collab"] and b["params_json"]["set_by_id"] == t.uid
    item = r.json()["item"]
    assert item["kind"] == "booklet" and item["chapters"] == ["Pressure"] and item["due_at"] == "2030-02-01"
    # another teacher may not build for my student, nor for a subject I don't teach them
    assert cls["other"].post(f"/api/teach/students/{s.uid}/booklets", json={
        "syllabus": "5054", "picks": [{"chapter": "Pressure"}]}).status_code == 404
    assert t.post(f"/api/teach/students/{s.uid}/booklets", json={
        "syllabus": "0625", "picks": [{"chapter": "Pressure"}]}).status_code == 404


def test_teacher_set_mock_test_keeps_the_mark_scheme_until_finish(cls):
    import teach_store
    import users_db
    s, t = cls["student"], cls["teacher"]
    bid = uuid.uuid4().hex[:10]
    users_db.create_booklet({"id": bid, "user_id": s.uid, "syllabus": "5054", "title": "Mock",
                             "params_json": {"kind": "test", "collab": True, "set_by_id": t.uid},
                             "question_ids": [1], "status": "ready", "progress": 100})
    teach_store.add_item({"student_id": s.uid, "teacher_id": t.uid, "syllabus": "5054", "kind": "test",
                          "ref_id": bid, "title": "Mock"})
    d = s.get(f"/api/booklets/{bid}").json()
    assert d["role"] == "shared" and d["ms_open"] is False and d["collab"] is True
    assert s.get(f"/api/booklets/{bid}/pdf?part=ms").status_code == 403
    assert t.get(f"/api/booklets/{bid}").json()["role"] == "staff"           # the teacher always can
    assert s.post(f"/api/booklets/{bid}/finish").json()["ms_open"] is True
    item = teach_store.item_for("test", bid)
    assert item["status"] == "done" and item["student_done_at"]


def test_private_notes(cls):
    t, s = cls["teacher"], cls["student"]
    t.post(f"/api/teach/students/{s.uid}/notes", json={"body": "Weak on indices", "syllabus": "5054"})
    assert [n["body"] for n in t.get(f"/api/teach/students/{s.uid}/notes").json()["notes"]] == ["Weak on indices"]
    # never in the folder
    assert all(i["kind"] != "tnote" for i in t.get(f"/api/teach/students/{s.uid}/folder").json()["items"])
    assert cls["other"].get(f"/api/teach/students/{s.uid}/notes").status_code == 404


def test_progress_and_papers_scoped(cls):
    t, s, o = cls["teacher"], cls["student"], cls["other"]
    body = {"syllabus": "5054", "topic": "Pressure", "status": "learning"}
    assert t.post(f"/api/teach/students/{s.uid}/progress", json=body).status_code == 200
    assert o.post(f"/api/teach/students/{s.uid}/progress", json=body).status_code == 404
    assert t.get("/api/teach/subjects").json()["subject_options"][0]["code"] == "5054"


def test_old_teacher_dashboard_redirects(client):
    r = client.get("/teacher-dashboard.html", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "/teach"
    assert client.get("/teach").status_code == 200
