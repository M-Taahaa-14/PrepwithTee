"""Regression tests for the admin audit of 2026-10-01 (admin console v2, phase 1).

Each test names the audit item it pins. Admin routes are called with the test
admin key (conftest sets ADMIN_ACCESS_KEY); fixtures are made straight in the
users DB so a test only exercises the route it is about.
"""

import re
import uuid
from pathlib import Path

import pytest

ADMIN = {"X-Admin-Key": "test-admin-key"}
STATIC = Path(__file__).resolve().parents[2] / "website" / "static"


def _udb():
    import users_db
    return users_db


def _person(role="student", email=None, password=None):
    from auth import hash_password
    email = email or f"t_{uuid.uuid4().hex[:10]}@test.local"
    return _udb().create_user(email, f"Test {role}",
                              password_hash=hash_password(password) if password else None,
                              role=role)


def _teacher_row(email, profile_id=None):
    row = {"name": "Mr Test", "role": "Teacher", "email": email}
    if profile_id:
        row["profile_id"] = profile_id
    return _udb().create_teacher(row)


# ── 1. Inline onclick handlers in a module script ────────────────────────────

def test_admin_js_has_no_inline_handlers_calling_module_functions():
    """admin.js is loaded as type=module, so onclick="fn()" can never find fn."""
    src = (STATIC / "admin.js").read_text(encoding="utf-8")
    calls = [m for m in re.findall(r'onclick="([A-Za-z_]\w*)\(', src)]
    assert calls == [], f"inline handlers calling module functions: {calls}"


# ── 2 + 3. Teacher-student links: one soft-removal style everywhere ──────────

def test_teacher_can_drop_own_student(client):
    pw = "Passw0rd!23"
    t = _person("teacher", password=pw)
    s = _person()
    _udb().assign_teacher_student(t["id"], s["id"], "5054")
    _udb().assign_teacher_student(t["id"], s["id"], "4024")
    assert client.post("/auth/login", json={"email": t["email"], "password": pw}).status_code == 200

    r = client.delete(f"/api/teacher/student/{s['id']}/allocation")
    assert r.status_code == 200, r.text
    assert _udb().get_teacher_students(t["id"]) == []


def test_allocation_remove_then_reassign(client):
    t, s = _person("teacher"), _person()
    r = client.post("/api/admin/allocations", headers=ADMIN,
                    json={"teacher_id": t["id"], "student_id": s["id"], "syllabus": "5054"})
    assert r.status_code == 200, r.text
    alloc_id = r.json()["allocation"]["id"]

    listed = client.get("/api/admin/allocations", headers=ADMIN).json()["allocations"]
    assert any(a["id"] == alloc_id for a in listed)

    assert client.delete(f"/api/admin/allocations/{alloc_id}", headers=ADMIN).status_code == 200
    listed = client.get("/api/admin/allocations", headers=ADMIN).json()["allocations"]
    assert all(a["id"] != alloc_id for a in listed), "removed link still listed"
    # removing twice is a 404, not a silent success
    assert client.delete(f"/api/admin/allocations/{alloc_id}", headers=ADMIN).status_code == 404

    # re-assigning the same pair used to hit the unique key and 500
    r = client.post("/api/admin/allocations", headers=ADMIN,
                    json={"teacher_id": t["id"], "student_id": s["id"], "syllabus": "5054"})
    assert r.status_code == 200, r.text
    assert r.json()["allocation"]["id"] == alloc_id
    assert r.json()["allocation"]["status"] == "active"


def test_teachers_drawer_and_allocations_tab_agree(client):
    email = f"Mixed.Case_{uuid.uuid4().hex[:6]}@Test.local"
    tp = _person("teacher", email=email.lower())
    trow = _teacher_row(email)                        # raw case, no profile_id (item 4)
    s = _person()

    r = client.post(f"/api/admin/teachers/{trow['id']}/students", headers=ADMIN,
                    json={"student_id": s["id"], "syllabus": "0625"})
    assert r.status_code == 200, r.text
    assert _udb().get_teacher(trow["id"])["profile_id"] == tp["id"]   # backfilled

    listed = client.get("/api/admin/allocations", headers=ADMIN).json()["allocations"]
    assert any(a["student_id"] == s["id"] and a["teacher_id"] == tp["id"] for a in listed)

    r = client.delete(f"/api/admin/teachers/{trow['id']}/students/{s['id']}",
                      headers=ADMIN, params={"syllabus": "0625"})
    assert r.status_code == 200, r.text
    listed = client.get("/api/admin/allocations", headers=ADMIN).json()["allocations"]
    assert not any(a["student_id"] == s["id"] and a["teacher_id"] == tp["id"] for a in listed)
    # nothing left to remove -> 404
    r = client.delete(f"/api/admin/teachers/{trow['id']}/students/{s['id']}",
                      headers=ADMIN, params={"syllabus": "0625"})
    assert r.status_code == 404


# ── 5. Approving an applicant who already has an account ─────────────────────

def test_approve_application_for_existing_account(client):
    existing = _person()
    app_row = _udb()._insert("teacher_applications", {
        "name": "Existing Person", "email": existing["email"].upper(),
        "subject_codes": "5054", "status": "pending", "created_at": _udb()._now()},
        ["name", "email", "subject_codes", "status", "created_at"])
    r = client.post(f"/api/admin/teacher-applications/{app_row['id']}/approve",
                    headers=ADMIN, json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["profile_id"] == existing["id"]
    assert body["email_error"] == ""
    assert body["teacher"]["profile_id"] == existing["id"]
    assert _udb().get_user(existing["id"])["role"] == "teacher"


# ── 6. Payment proof review keeps the student's note ─────────────────────────

def test_proof_review_keeps_student_note(client):
    s = _person()
    proof = _udb().create_payment_proof({"user_id": s["id"], "plan": "solo",
                                         "amount_pkr": 1000, "method": "jazzcash",
                                         "transaction_id": "TID1", "note": "paid from dad's phone",
                                         "subjects_json": '["5054"]'})   # Solo covers 1 subject
    listed = client.get("/api/admin/payment-proofs", headers=ADMIN).json()["proofs"]
    row = next(p for p in listed if p["id"] == proof["id"])
    assert row["name"] and row["email"] == s["email"]

    r = client.post(f"/api/admin/payment-proofs/{proof['id']}/review", headers=ADMIN,
                    json={"status": "approved", "reviewer_note": "seen in JazzCash"})
    assert r.status_code == 200, r.text
    p = r.json()["proof"]
    assert p["note"] == "paid from dad's phone"
    assert p["reviewer_note"] == "seen in JazzCash"
    assert _udb().get_user(s["id"])["plan"] == "solo"


# ── 7. Admin marks drawer: grade and note land in the right columns ──────────

def test_admin_paper_write_keeps_grade_and_note(client):
    s = _person()
    r = client.post(f"/api/admin/students/{s['id']}/papers", headers=ADMIN, json={
        "syllabus": "5054", "year": 2023, "session": "s", "paper": 22, "variant": "",
        "status": "confident", "score": 61, "max_score": 80, "grade": "A",
        "note": "strong on circuits"})
    assert r.status_code == 200, r.text
    row = next(p for p in _udb().get_paper_progress(s["id"]) if p["paper"] == 22)
    assert row["grade"] == "A"
    assert row["note"] == "strong on circuits"


# ── 8. Unknown ids are 404, not 500 ──────────────────────────────────────────

def test_unknown_student_is_404(client):
    missing = str(uuid.uuid4())
    assert _udb().get_user(missing) is None
    r = client.get(f"/api/admin/students/{missing}", headers=ADMIN)
    assert r.status_code == 404
    r = client.post("/api/admin/allocations", headers=ADMIN,
                    json={"teacher_id": missing, "student_id": missing, "syllabus": "5054"})
    assert r.status_code == 404


def test_email_lookup_is_case_insensitive():
    p = _person(email=f"lower_{uuid.uuid4().hex[:6]}@test.local")
    assert _udb().get_user_by_email(p["email"].upper())["id"] == p["id"]
    assert _udb().get_user_by_email("") is None


# ── 9. Newsletter CSV export ─────────────────────────────────────────────────

def test_newsletter_export_csv(client):
    client.post("/api/newsletter", json={"email": f"n_{uuid.uuid4().hex[:6]}@test.local"})
    r = client.get("/api/admin/newsletter/export", headers=ADMIN)
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers["content-type"]


# ── 10. Email activity works on the local SQLite schema ──────────────────────

def test_email_activity_local(client):
    _person()
    r = client.get("/api/admin/email-activity", headers=ADMIN)
    assert r.status_code == 200, r.text


# ── 12. Page titles for every sidebar tab ────────────────────────────────────

def test_every_nav_tab_has_a_page_title():
    html = (STATIC / "admin.html").read_text(encoding="utf-8")
    js = (STATIC / "admin.js").read_text(encoding="utf-8")
    tabs = set(re.findall(r'data-tab="(\w+)"', html))
    pages = set(re.findall(r"^\s{2}(\w+):\s+\[", js.split("const PAGES", 1)[1].split("};", 1)[0],
                           re.M))
    assert tabs <= pages, f"tabs without a title: {sorted(tabs - pages)}"


def test_admin_routes_need_credentials(client):
    assert client.get("/api/admin/students").status_code == 401
    assert client.get("/api/admin/students", headers={"X-Admin-Key": "nope"}).status_code == 401
