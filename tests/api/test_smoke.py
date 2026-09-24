"""Smoke tests: the app boots in test mode and the core auth flow works."""

from tests.conftest import needs_index_db


def test_runs_on_sqlite_not_production():
    import db, users_db
    assert db.USE_PG is False
    assert users_db._USE_SUPABASE is False


@needs_index_db
def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_register_then_me(client, new_student):
    user = new_student()
    r = client.get("/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == user["email"]


def test_login_wrong_password_is_401(client, new_student):
    user = new_student()
    client.post("/auth/logout")
    r = client.post("/auth/login", json={"email": user["email"], "password": "nope"})
    assert r.status_code == 401


def test_protected_endpoint_needs_login(client):
    assert client.get("/api/enrollments").status_code == 401


def test_enrol_and_list(client, new_student):
    new_student()
    r = client.post("/api/enrollments", json={"syllabus": "5054"})
    assert r.status_code in (200, 201), r.text
    codes = [e["syllabus"] for e in client.get("/api/enrollments").json().get("enrollments", [])]
    assert "5054" in codes
