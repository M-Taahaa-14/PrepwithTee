"""The '3 Subjects' plan covers exactly the subjects the student paid for (tutor, 2026-10-01).

Inside those subjects it is unlimited; every other subject behaves like the
free plan, and that free allowance counts only usage in the other subjects.
"""

import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

ADMIN = {"X-Admin-Key": "test-admin-key"}
PLAN_SUBS = ["5054", "4024", "0625"]


def _mods():
    import access
    import users_db
    return access, users_db


def _student(plan="three", subjects=PLAN_SUBS, enrol=()):
    access, udb = _mods()
    u = udb.create_user(f"p_{uuid.uuid4().hex[:10]}@test.local", "Plan Student")
    for code in enrol:
        udb.enroll(u["id"], code)
        time.sleep(0.01)                     # enrolled_at order is what the backfill uses
    if plan != "free":
        exp = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        udb.update_user_plan(u["id"], plan, exp, subjects=subjects)
    return udb.get_user(u["id"])


# ── validation ───────────────────────────────────────────────────────────────

def test_clean_plan_subjects():
    access, _ = _mods()
    assert access.clean_plan_subjects("all", None) is None
    assert access.clean_plan_subjects("three", ["5054", "4024", "5054", "0625"]) == PLAN_SUBS
    for bad in (None, [], ["5054", "4024"], ["5054", "4024", "0625", "9702"], ["5054", "4024", "xxxx"]):
        with pytest.raises(HTTPException) as e:
            access.clean_plan_subjects("three", bad)
        assert e.value.status_code == 400


# ── access decisions ─────────────────────────────────────────────────────────

def test_three_plan_is_paid_only_inside_its_subjects():
    access, _ = _mods()
    u = _student()
    assert access._plan_active(u) == "three"
    assert access._plan_active(u, "5054") == "three"
    assert access._plan_active(u, "9702") == "free"
    info = access.plan_info(u)
    assert info["subject_limit"] == 3 and info["plan_subjects"] == PLAN_SUBS


def test_other_plans_unaffected():
    access, _ = _mods()
    u = _student(plan="all", subjects=None)
    assert access._plan_active(u, "9702") == "all"


def test_free_allowance_outside_plan_counts_only_outside_usage():
    access, udb = _mods()
    u = _student()
    for _ in range(6):                       # plenty inside the plan: unlimited
        access.check_quota(u, "topical_paper", "5054")
    free_limit = access.MONTHLY_QUOTAS["topical_paper"]["free"]
    for _ in range(free_limit):              # in-plan usage didn't eat the free allowance
        access.check_quota(u, "topical_paper", "9702")
    with pytest.raises(HTTPException) as e:
        access.check_quota_gate(u, "topical_paper", "9702")
    assert e.value.status_code == 429
    d = e.value.detail
    assert d["outside_plan_subjects"] is True and "9702" in d["message"]
    access.check_quota_gate(u, "topical_paper", "4024")     # still unlimited inside


def test_legacy_three_plan_uses_first_three_enrolments():
    access, udb = _mods()
    u = _student(subjects=[], enrol=["0580", "5054", "9709", "0625"])
    assert access.plan_subjects(u) == ["0580", "5054", "9709"]
    fresh = udb.get_user(u["id"])
    assert "0580" in fresh["plan_subjects_json"]      # saved, so it can't drift
    assert access._plan_active(fresh, "0625") == "free"


# ── payment proof -> approval ────────────────────────────────────────────────

def test_proof_needs_three_subjects_and_approval_applies_them(client, new_student):
    new_student()
    base = {"plan": "three", "amount_pkr": 2000, "method": "jazzcash",
            "transaction_id": "T-3", "screenshot_url": "/uploads/payments/x.png"}
    assert client.post("/api/payment-proof", json=base).status_code == 400
    assert client.post("/api/payment-proof",
                       json={**base, "subjects": ["5054", "4024"]}).status_code == 400
    r = client.post("/api/payment-proof", json={**base, "subjects": PLAN_SUBS})
    assert r.status_code == 200, r.text
    pid = r.json()["proof_id"]
    # plans without a subject limit ignore subjects
    assert client.post("/api/payment-proof", json={**base, "plan": "all"}).status_code == 200

    r = client.post(f"/api/admin/payment-proofs/{pid}/review", headers=ADMIN,
                    json={"status": "approved"})
    assert r.status_code == 200, r.text
    access, udb = _mods()
    user = udb.get_user(r.json()["proof"]["user_id"])
    assert user["plan"] == "three"
    assert access.plan_subjects(user) == PLAN_SUBS


def test_admin_plan_change_requires_subjects(client):
    _, udb = _mods()
    u = udb.create_user(f"a_{uuid.uuid4().hex[:8]}@test.local", "Admin Target")
    url = f"/api/admin/students/{u['id']}/plan"
    assert client.patch(url, headers=ADMIN, json={"plan": "three"}).status_code == 400
    assert client.patch(url, headers=ADMIN,
                        json={"plan": "three", "subjects": ["5054"]}).status_code == 400
    r = client.patch(url, headers=ADMIN, json={"plan": "three", "subjects": PLAN_SUBS})
    assert r.status_code == 200, r.text
    assert r.json()["plan_subjects"] == PLAN_SUBS
    # renewing later keeps the saved subjects without re-sending them
    assert client.patch(url, headers=ADMIN, json={"plan": "three"}).status_code == 200


def test_ai_help_outside_plan_explains_why():
    import ai_help
    u = _student()
    with pytest.raises(HTTPException) as e:
        ai_help.gate_usage(u, "ai_hint", "9702")
    assert e.value.status_code == 403 and "9702" in e.value.detail["message"]
    ai_help.gate_usage(u, "ai_hint", "5054")          # inside the plan: allowed


# ── Solo = exactly 1 subject ─────────────────────────────────────────────────

def test_solo_covers_exactly_one_subject(client):
    access, udb = _mods()
    for bad in (None, [], ["5054", "4024"]):
        with pytest.raises(HTTPException):
            access.clean_plan_subjects("solo", bad)
    u = _student(plan="solo", subjects=["0580"])
    assert access._plan_active(u, "0580") == "solo"
    assert access._plan_active(u, "0625") == "free"
    assert access.plan_info(u)["subject_limit"] == 1

    url = f"/api/admin/students/{u['id']}/plan"
    assert client.patch(url, headers=ADMIN,
                        json={"plan": "solo", "subjects": PLAN_SUBS}).status_code == 400
    assert client.patch(url, headers=ADMIN,
                        json={"plan": "solo", "subjects": ["9702"]}).status_code == 200
    assert access.plan_subjects(udb.get_user(u["id"])) == ["9702"]


def test_legacy_solo_uses_first_enrolment():
    access, _ = _mods()
    u = _student(plan="solo", subjects=[], enrol=["9709", "5054"])
    assert access.plan_subjects(u) == ["9709"]


# ── pricing page offers every subject the site has ───────────────────────────

def test_pricing_picker_lists_every_site_subject():
    import re
    from pathlib import Path
    import catalog
    html = (Path(__file__).resolve().parents[2] / "website" / "static" / "pricing.html"
            ).read_text(encoding="utf-8")
    offered = set(re.findall(r'class="pr-subj-option" data-val="[^"]*\((\w+)\)"', html))
    site = {code for _, subs in catalog.BOARDS for code, _ in subs}
    assert offered == site
    access, _ = _mods()
    assert access.clean_plan_subjects("three", ["2058", "2059", "9618"]) == ["2058", "2059", "9618"]


# ── progress tracking is free for every subject ──────────────────────────────

def test_free_student_tracks_progress_in_any_subject(client, new_student):
    new_student()
    for code in ("5054", "0580"):
        assert client.post("/api/enrollments", json={"syllabus": code}).status_code == 200
    for code in ("5054", "0580"):
        r = client.post("/api/progress", json={"syllabus": code, "topic": "Some chapter",
                                               "status": "learning"})
        assert r.status_code == 200, r.text
