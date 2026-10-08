"""Teaching phase 1: who may open whose things, shared ink on collaborative
booklets (optimistic saves, authorship, polling), whiteboard members, and the
message link rule."""

import uuid

import pytest
from fastapi.testclient import TestClient


def _user(app, role="student", name="Test User"):
    """A logged-in TestClient for a brand-new account with `role`."""
    c = TestClient(app)
    c.__enter__()
    email = f"c_{uuid.uuid4().hex[:10]}@test.local"
    r = c.post("/auth/register", json={"email": email, "password": "Passw0rd!23", "name": name, "role": "student"})
    assert r.status_code == 200, r.text
    uid = r.json()["id"] if "id" in r.json() else r.json()["user"]["id"]
    if role != "student":
        import users_db
        users_db.update_profile(uid, {"role": role})
        c.post("/auth/login", json={"email": email, "password": "Passw0rd!23"})   # fresh token, new role
    c.uid = uid
    return c


@pytest.fixture()
def people(app):
    import teaching
    import users_db
    teaching.clear()
    student = _user(app, name="Sana Student")
    teacher = _user(app, "teacher", "Tariq Teacher")
    other_t = _user(app, "teacher", "Other Teacher")
    stranger = _user(app, name="Some Stranger")
    admin = _user(app, "admin", "Ada Admin")
    users_db.assign_teacher_student(teacher.uid, student.uid, "5054")
    teaching.clear()
    yield {"student": student, "teacher": teacher, "other": other_t, "stranger": stranger, "admin": admin}
    for c in (student, teacher, other_t, stranger, admin):
        c.__exit__(None, None, None)


def _booklet(owner_id, collab=True):
    import users_db
    bid = uuid.uuid4().hex[:10]
    users_db.create_booklet({"id": bid, "user_id": owner_id, "syllabus": "5054", "title": "Motion",
                             "params_json": {"kind": "booklet", "collab": collab}, "question_ids": [1, 2],
                             "status": "ready", "progress": 100})
    return bid


def _pen(oid, x=0.1):
    return {"id": oid, "t": "pen", "c": "@blue", "w": 2, "pts": [[x, 0.1], [x + 0.1, 0.2]]}


# ── booklet access ───────────────────────────────────────────────────────────

def test_only_the_students_own_teacher_can_open_their_booklet(people):
    bid = _booklet(people["student"].uid, collab=False)
    assert people["student"].get(f"/api/booklets/{bid}").status_code == 200
    assert people["teacher"].get(f"/api/booklets/{bid}").status_code == 200
    assert people["admin"].get(f"/api/booklets/{bid}").status_code == 200
    # any teacher used to get in; now only the linked one
    assert people["other"].get(f"/api/booklets/{bid}").status_code == 404
    assert people["stranger"].get(f"/api/booklets/{bid}").status_code == 404


def test_detail_says_collab_for_both_sides(people):
    bid = _booklet(people["student"].uid)
    for who in ("student", "teacher"):
        d = people[who].get(f"/api/booklets/{bid}").json()
        assert d["collab"] is True and d["me"] == people[who].uid


# ── shared ink ───────────────────────────────────────────────────────────────

def test_shared_ink_round_trip_and_authorship(people):
    s, t = people["student"], people["teacher"]
    doc = f"booklet:{_booklet(s.uid)}"
    r = s.put("/api/collab", json={"doc": doc, "page": 0, "objects": [_pen("a")], "version": 0})
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 1
    got = t.get("/api/collab", params={"doc": doc}).json()
    assert got["pages"]["0"]["objects"][0]["by"] == s.uid
    # the teacher adds a stroke on top: the student's keeps its author
    r = t.put("/api/collab", json={"doc": doc, "page": 0, "objects": got["pages"]["0"]["objects"] + [_pen("b", .5)],
                                   "version": 1})
    assert r.status_code == 200
    objs = {o["id"]: o["by"] for o in s.get("/api/collab", params={"doc": doc}).json()["pages"]["0"]["objects"]}
    assert objs == {"a": s.uid, "b": t.uid}


def test_stale_save_is_a_409_with_the_current_page(people):
    s, t = people["student"], people["teacher"]
    doc = f"booklet:{_booklet(s.uid)}"
    s.put("/api/collab", json={"doc": doc, "page": 2, "objects": [_pen("a")], "version": 0})
    t.put("/api/collab", json={"doc": doc, "page": 2, "objects": [_pen("a"), _pen("b")], "version": 1})
    r = s.put("/api/collab", json={"doc": doc, "page": 2, "objects": [_pen("a"), _pen("c")], "version": 1})
    assert r.status_code == 409
    d = r.json()
    assert d["code"] == "stale" and d["version"] == 2 and {o["id"] for o in d["objects"]} == {"a", "b"}
    # first save on a page that someone else created meanwhile is stale too
    r = s.put("/api/collab", json={"doc": doc, "page": 2, "objects": [_pen("z")], "version": 0})
    assert r.status_code == 409


def test_poll_returns_changes_and_presence(people):
    s, t = people["student"], people["teacher"]
    doc = f"booklet:{_booklet(s.uid)}"
    first = s.get("/api/collab/poll", params={"doc": doc, "page": "1"}).json()
    assert first["pages"] == []
    t.get("/api/collab/poll", params={"doc": doc, "page": "3"})
    t.put("/api/collab", json={"doc": doc, "page": 0, "objects": [_pen("t1")], "version": 0})
    nxt = s.get("/api/collab/poll", params={"doc": doc, "since": first["now"], "page": "1"}).json()
    assert [p["page"] for p in nxt["pages"]] == [0]
    assert [h["name"] for h in nxt["here"]] == ["Tariq Teacher"] and nxt["here"][0]["teacher"]


def test_shared_ink_access_rules(people):
    doc = f"booklet:{_booklet(people['student'].uid)}"
    body = {"doc": doc, "page": 0, "objects": [_pen("x")], "version": 0}
    assert people["other"].put("/api/collab", json=body).status_code == 404
    assert people["stranger"].get("/api/collab", params={"doc": doc}).status_code == 404
    assert people["admin"].get("/api/collab", params={"doc": doc}).status_code == 200
    assert people["student"].get("/api/collab", params={"doc": "paper:12"}).status_code == 400
    # a booklet nobody opened up is not collaborative
    private = f"booklet:{_booklet(people['student'].uid, collab=False)}"
    assert people["teacher"].get("/api/collab", params={"doc": private}).status_code == 409


def test_student_opens_own_paper_to_teacher_and_keeps_their_ink(people):
    s, t = people["student"], people["teacher"]
    bid = _booklet(s.uid, collab=False)
    s.put("/api/annotations", json={"doc": f"booklet:{bid}", "page": 1, "strokes": [_pen("mine")]})
    assert s.get(f"/api/booklets/{bid}").json()["can_collab"] is True
    assert t.post(f"/api/booklets/{bid}/collab").status_code == 403          # only the owner
    assert s.post(f"/api/booklets/{bid}/collab").status_code == 200
    got = t.get("/api/collab", params={"doc": f"booklet:{bid}"}).json()
    assert [o["id"] for o in got["pages"]["1"]["objects"]] == ["mine"]
    assert got["pages"]["1"]["objects"][0]["by"] == s.uid


def test_student_without_teacher_cannot_open_up_a_paper(people):
    bid = _booklet(people["stranger"].uid, collab=False)
    assert people["stranger"].get(f"/api/booklets/{bid}").json()["can_collab"] is False
    assert people["stranger"].post(f"/api/booklets/{bid}/collab").status_code == 409


# ── whiteboards ──────────────────────────────────────────────────────────────

def _board(c):
    b = c.post("/api/wb/boards", json={"title": "Lesson"}).json()
    full = c.get(f"/api/wb/boards/{b['id']}").json()
    return b["id"], full["pages"][0]["id"]


def test_teacher_can_draw_once_the_student_allows_it(people):
    s, t = people["student"], people["teacher"]
    bid, pid = _board(s)
    save = {"objects": [_pen("t1")], "version": 1}
    assert t.get(f"/api/wb/boards/{bid}").status_code == 404                # not shared yet
    s.patch(f"/api/wb/boards/{bid}", json={"shared_with_teacher": True})
    assert t.get(f"/api/wb/boards/{bid}").json()["readonly"] is True
    assert t.put(f"/api/wb/boards/{bid}/pages/{pid}", json=save).status_code == 404
    s.patch(f"/api/wb/boards/{bid}", json={"teacher_edit": True})
    got = t.get(f"/api/wb/boards/{bid}").json()
    assert got["readonly"] is False and got["collab"] is True
    assert t.put(f"/api/wb/boards/{bid}/pages/{pid}", json=save).status_code == 200
    # owner-only things stay owner-only
    assert t.patch(f"/api/wb/boards/{bid}", json={"title": "Mine now"}).status_code == 404
    assert t.delete(f"/api/wb/boards/{bid}").status_code == 404
    # the student's poll sees the teacher's page + who is here
    page = s.get(f"/api/wb/boards/{bid}").json()["pages"][0]
    assert page["objects"][0]["by"] == t.uid
    # another teacher still can't see it
    assert people["other"].get(f"/api/wb/boards/{bid}").status_code == 404
    s.patch(f"/api/wb/boards/{bid}", json={"teacher_edit": False})
    assert t.put(f"/api/wb/boards/{bid}/pages/{pid}", json={"objects": [], "version": 2}).status_code == 404


def test_board_poll(people):
    s, t = people["student"], people["teacher"]
    bid, pid = _board(s)
    s.patch(f"/api/wb/boards/{bid}", json={"teacher_edit": True})
    first = s.get(f"/api/wb/boards/{bid}/poll", params={"page": "1"}).json()
    t.get(f"/api/wb/boards/{bid}/poll", params={"page": "1"})
    t.put(f"/api/wb/boards/{bid}/pages/{pid}", json={"objects": [_pen("t1")], "version": 1})
    nxt = s.get(f"/api/wb/boards/{bid}/poll", params={"since": first["now"], "page": "1"}).json()
    assert [p["id"] for p in nxt["pages"]] == [pid] and nxt["pages"][0]["version"] == 2
    assert nxt["order"] == [pid]
    assert [h["name"] for h in nxt["here"]] == ["Tariq Teacher"]


# ── messages ─────────────────────────────────────────────────────────────────

def test_messages_only_between_linked_people(people):
    s, t = people["student"], people["teacher"]
    ok = s.post("/api/messages", json={"recipient_id": t.uid, "body": "Hello sir"})
    assert ok.status_code == 200, ok.text
    assert t.post("/api/messages", json={"recipient_id": s.uid, "body": "Hi"}).status_code == 200
    assert people["stranger"].post("/api/messages", json={"recipient_id": s.uid, "body": "hey"}).status_code == 403
    assert people["other"].post("/api/messages", json={"recipient_id": s.uid, "body": "hey"}).status_code == 403
    assert s.post("/api/messages", json={"recipient_id": people["admin"].uid, "body": "help"}).status_code == 200
    assert people["admin"].post("/api/messages", json={"recipient_id": people["stranger"].uid,
                                                        "body": "welcome"}).status_code == 200
    # the stranger may reply to the admin who wrote first
    assert people["stranger"].post("/api/messages", json={"recipient_id": people["admin"].uid,
                                                           "body": "thanks"}).status_code == 200
