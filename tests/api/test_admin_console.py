"""Admin console v2 API: sign-in, audit log, students table, bulk actions,
a student's activity timeline, notes, saved views and the overview."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

KEY = {"X-Admin-Key": "test-admin-key"}
PW = "Passw0rd!23"


def _udb():
    import users_db
    return users_db


def _user(role="student", name=None, **fields):
    from auth import hash_password
    u = _udb().create_user(f"c_{uuid.uuid4().hex[:10]}@test.local", name or f"Test {role}",
                           password_hash=hash_password(PW), role=role)
    if fields:
        _udb().update_profile(u["id"], fields)
    return _udb().get_user(u["id"])


def _login(client, user):
    r = client.post("/auth/login", json={"email": user["email"], "password": PW})
    assert r.status_code == 200, r.text


@pytest.fixture()
def admin_client(client):
    admin = _user("admin", "Tee Admin")
    _login(client, admin)
    client.admin = admin
    return client


def _fresh():
    import admin_students
    admin_students.invalidate()


# ── sign-in ──────────────────────────────────────────────────────────────────

def test_admin_session_is_accepted_and_checked_against_db(admin_client):
    r = admin_client.get("/api/admin/me")
    assert r.status_code == 200 and r.json()["admin"]["via"] == "session"
    # demote the account: the old session stops working at once
    _udb().update_profile(admin_client.admin["id"], {"role": "student"})
    assert admin_client.get("/api/admin/me").status_code == 401


def test_student_session_is_refused(client):
    _login(client, _user())
    assert client.get("/api/admin/students/table").status_code == 401


def test_key_only_from_header(client):
    assert client.get("/api/admin/me", headers=KEY).status_code == 200
    assert client.get("/api/admin/me", params={"key": "test-admin-key"}).status_code == 401
    client.cookies.set("admin_key", "test-admin-key")
    assert client.get("/api/admin/me").status_code == 401


def test_no_key_configured_means_no_key_login(client, monkeypatch):
    monkeypatch.delenv("ADMIN_ACCESS_KEY", raising=False)
    monkeypatch.delenv("ADMIN_KEY", raising=False)
    assert client.get("/api/admin/me", headers=KEY).status_code == 401
    assert client.get("/api/admin/me", headers={"X-Admin-Key": "prepwithtee-admin-2026"}).status_code == 401


def test_mutations_are_audited(admin_client):
    s = _user()
    r = admin_client.post(f"/api/admin/students/{s['id']}/notes", json={"body": "call parents"})
    assert r.status_code == 200
    admin_client.post(f"/api/admin/students/{uuid.uuid4()}/notes", json={"body": "x"})   # 404
    rows = admin_client.get("/api/admin/audit").json()["rows"]
    mine = [x for x in rows if x["admin_id"] == admin_client.admin["id"]]
    assert mine[0]["ok"] == 0 and mine[0]["details"]["status"] == 404
    assert mine[1]["ok"] == 1 and "notes" in mine[1]["action"] and s["id"] in mine[1]["target"]
    # reads are not audited
    assert not any(x["action"].startswith("GET") for x in rows)


# ── students table ───────────────────────────────────────────────────────────

def _seed():
    now = datetime.now(timezone.utc)
    a = _user(name="Aaa Active", phone="+92 3001234567", plan="solo",
              plan_expires_at=(now + timedelta(days=3)).isoformat(), plan_subjects_json='["5054"]')
    b = _user(name="Zzz Idle")
    udb = _udb()
    udb.enroll(a["id"], "5054")
    udb.enroll(b["id"], "0580")
    udb.set_boards(a["id"], ["o-level"], "o-level")
    udb._insert("booklets", {"id": uuid.uuid4().hex, "user_id": a["id"], "syllabus": "5054",
                             "title": "Forces", "created_at": now.isoformat()},
                ["id", "user_id", "syllabus", "title", "created_at"])
    udb._insert("mcq_sessions", {"id": uuid.uuid4().hex, "user_id": a["id"], "syllabus": "5054",
                                 "kind": "topical", "status": "submitted", "score": 30, "total": 40,
                                 "created_at": now.isoformat(), "submitted_at": now.isoformat()},
                ["id", "user_id", "syllabus", "kind", "status", "score", "total", "created_at",
                 "submitted_at"])
    udb.add_time_spent(a["id"], 600, now.strftime("%Y-%m-%d"))
    _fresh()
    return a, b


def test_table_filters_sorts_and_pages(admin_client):
    a, b = _seed()
    t = admin_client.get("/api/admin/students/table", params={"q": a["email"]}).json()
    assert t["total"] == 1
    row = t["rows"][0]
    assert row["booklets"] == 1 and row["mcq_avg"] == 75.0 and row["streak"] >= 1
    assert row["minutes_7"] == 10 and row["plan_effective"] == "solo"
    assert "password_hash" not in row

    q = {"q": "test.local", "subject": "5054"}
    ids = [r["id"] for r in admin_client.get("/api/admin/students/table", params=q).json()["rows"]]
    assert a["id"] in ids and b["id"] not in ids

    ids = [r["id"] for r in admin_client.get("/api/admin/students/table",
                                             params={"expiring": 7}).json()["rows"]]
    assert a["id"] in ids and b["id"] not in ids

    ids = [r["id"] for r in admin_client.get("/api/admin/students/table",
                                             params={"active": "never"}).json()["rows"]]
    assert b["id"] in ids and a["id"] not in ids

    asc = admin_client.get("/api/admin/students/table",
                           params={"sort": "name", "dir": "asc", "per": 500}).json()["rows"]
    names = [(r["name"] or "").lower() for r in asc]
    assert names == sorted(names)
    page2 = admin_client.get("/api/admin/students/table",
                             params={"sort": "name", "dir": "asc", "per": 1, "page": 2}).json()
    assert page2["rows"][0]["id"] == asc[1]["id"]
    assert page2["facets"]["subject"]["5054"] >= 1


def test_table_rejects_unknown_sort_and_filters(admin_client):
    for params in ({"sort": "password_hash"}, {"sort": "name; DROP TABLE profiles"},
                   {"plan": "gold"}, {"active": "yesterday"}):
        assert admin_client.get("/api/admin/students/table", params=params).status_code == 400


def test_csv_export(admin_client):
    a, _ = _seed()
    r = admin_client.get("/api/admin/students/export.csv", params={"q": a["email"]})
    assert r.status_code == 200 and "text/csv" in r.headers["content-type"]
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("name,email") and len(lines) == 2 and a["email"] in lines[1]


# ── bulk actions ─────────────────────────────────────────────────────────────

def test_bulk_plan_teacher_and_email(admin_client):
    s1, s2 = _user(), _user()
    t = _user("teacher", "Mr Bulk")
    ids = [s1["id"], s2["id"]]
    r = admin_client.post("/api/admin/students/bulk", json={
        "ids": ids, "action": "plan", "plan": "three", "subjects": ["5054", "4024", "0625"]})
    assert r.status_code == 200 and r.json()["done"] == 2
    assert _udb().get_user(s1["id"])["plan"] == "three"
    # the 3-subject rule applies to bulk changes too
    r = admin_client.post("/api/admin/students/bulk", json={
        "ids": ids, "action": "plan", "plan": "three", "subjects": ["5054"]})
    assert r.status_code == 400

    r = admin_client.post("/api/admin/students/bulk", json={
        "ids": ids, "action": "assign_teacher", "teacher_id": t["id"], "syllabus": "5054"})
    assert r.json()["done"] == 2
    rows = admin_client.get("/api/admin/students/table",
                            params={"teacher": "yes", "per": 500}).json()["rows"]
    assert {s1["id"], s2["id"]} <= {x["id"] for x in rows}
    r = admin_client.post("/api/admin/students/bulk", json={
        "ids": [s1["id"]], "action": "unassign_teacher", "teacher_id": t["id"], "syllabus": "5054"})
    assert r.json()["done"] == 1
    assert _udb().get_teacher_students(t["id"])[0]["student_id"] == s2["id"]

    # email: no provider configured in tests, so every send fails - and says so
    r = admin_client.post("/api/admin/students/bulk", json={
        "ids": ids, "action": "email", "subject": "Hi", "body": "Hello {first_name}"})
    assert r.status_code == 200 and r.json()["done"] + len(r.json()["failed"]) == 2

    assert admin_client.post("/api/admin/students/bulk", json={
        "ids": [str(uuid.uuid4())], "action": "plan", "plan": "free"}).status_code == 404
    assert admin_client.post("/api/admin/students/bulk", json={
        "ids": ids, "action": "delete_everything"}).status_code == 400


# ── one student ──────────────────────────────────────────────────────────────

def test_activity_timeline_and_notes(admin_client):
    a, _ = _seed()
    r = admin_client.post(f"/api/admin/students/{a['id']}/notes", json={"body": "Weak on graphs"})
    note_id = r.json()["note"]["id"]
    act = admin_client.get(f"/api/admin/students/{a['id']}/activity").json()
    types = {e["type"] for e in act["events"]}
    assert {"booklet", "mcq", "note", "enrol"} <= types
    assert act["summary"]["booklets"] == 1 and act["summary"]["mcq_avg"] == 75.0
    assert act["summary"]["minutes_7"] == 10
    assert act["plan"]["plan"] == "solo" and act["plan"]["plan_subjects"] == ["5054"]
    only = admin_client.get(f"/api/admin/students/{a['id']}/activity",
                            params={"type": "mcq"}).json()["events"]
    assert only and all(e["type"] == "mcq" for e in only)
    assert admin_client.get(f"/api/admin/students/{a['id']}/activity",
                            params={"type": "bogus"}).status_code == 400
    assert admin_client.delete(f"/api/admin/students/{a['id']}/notes/{note_id}").status_code == 200
    assert admin_client.delete(f"/api/admin/students/{a['id']}/notes/{note_id}").status_code == 404
    assert admin_client.get(f"/api/admin/students/{uuid.uuid4()}/activity").status_code == 404


# ── saved views, overview ────────────────────────────────────────────────────

def test_saved_views(admin_client):
    r = admin_client.post("/api/admin/views", json={
        "section": "students", "name": "Inactive O Level",
        "params": {"board": "o-level", "active": "inactive7", "evil": {"nested": 1}}})
    v = r.json()["view"]
    assert v["params"] == {"board": "o-level", "active": "inactive7"}
    views = admin_client.get("/api/admin/views", params={"section": "students"}).json()["views"]
    assert any(x["id"] == v["id"] for x in views)
    assert admin_client.delete(f"/api/admin/views/{v['id']}").status_code == 200


def test_overview_stats(admin_client):
    _seed()
    d = admin_client.get("/api/admin/overview/stats", params={"days": 7}).json()
    assert d["kpis"]["practice"]["cur"] >= 2
    assert d["attention"]["expiring_7"] >= 1
    assert any(f["type"] == "booklet" for f in d["feed"])


def test_admin_page_served(client):
    r = client.get("/admin")
    assert r.status_code == 200 and "noindex" in r.headers.get("x-robots-tag", "")


def test_bulk_writes_one_audit_row(admin_client):
    s = _user()
    admin_client.post("/api/admin/students/bulk", json={"ids": [s["id"]], "action": "plan", "plan": "free"})
    rows = [x for x in admin_client.get("/api/admin/audit").json()["rows"]
            if x["admin_id"] == admin_client.admin["id"]]
    assert [x["action"] for x in rows] == ["bulk plan"]
    assert rows[0]["details"]["ids"] == [s["id"]]
