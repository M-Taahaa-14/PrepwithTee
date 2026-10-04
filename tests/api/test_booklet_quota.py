"""Free allowance for topical papers can't be beaten by clicking Build quickly (2026-10-04).

Production: free students got a 4th booklet by asking for it while the first
three were still building - a build only counts once it succeeds, and the
check didn't see queued/building rows. Allowance (tutor): 3 booklets + 3 mock
tests a month, separately.
"""

from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import needs_index_db

PHYS = {"syllabus": "5054", "papers": [2], "year_from": 2018, "year_to": 2025,
        "picks": [{"chapter": "Motion"}, {"chapter": "Pressure"}]}


@pytest.fixture()
def held(monkeypatch):
    """Builds never start: every booklet stays 'queued', as if still building."""
    import booklets as bk
    monkeypatch.setattr(bk._EXEC, "submit", lambda *a, **k: None)
    return bk


@pytest.fixture()
def free_student(client, new_student):
    user = new_student()
    client.post("/api/enrollments", json={"syllabus": "5054"})
    return user


def test_free_allowance_numbers():
    import access
    assert access.MONTHLY_QUOTAS["topical_paper"]["free"] == 3
    assert access.MONTHLY_QUOTAS["topic_test"]["free"] == 3


@needs_index_db
def test_builds_in_progress_count_against_the_limit(client, free_student, held):
    ids = [client.post("/api/booklets", json=PHYS).json()["id"] for _ in range(3)]
    r = client.post("/api/booklets", json=PHYS)
    assert r.status_code == 429, r.text
    assert r.json()["detail"]["used"] == 3

    # mock tests are a separate allowance
    for _ in range(3):
        assert client.post("/api/booklets", json={**PHYS, "kind": "test"}).status_code == 200
    assert client.post("/api/booklets", json={**PHYS, "kind": "test"}).status_code == 429

    # a failed build never counts - and retrying it is a new build, so it needs room
    import users_db as udb
    udb.update_booklet(ids[0], {"status": "failed", "error": '{"code": "busy"}'})
    assert client.post(f"/api/booklets/{ids[0]}/retry").status_code == 200
    udb.update_booklet(ids[0], {"status": "failed", "error": '{"code": "busy"}'})
    assert client.post("/api/booklets", json=PHYS).status_code == 200      # took the free slot
    assert client.post(f"/api/booklets/{ids[0]}/retry").status_code == 429


@needs_index_db
def test_dead_builds_dont_lock_a_student_out(client, free_student, held):
    import users_db as udb
    ids = [client.post("/api/booklets", json=PHYS).json()["id"] for _ in range(3)]
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    with udb._local() as c:                                    # worker died long ago
        c.execute("UPDATE booklets SET created_at=?, updated_at=? WHERE id=?", (old, old, ids[0]))
        c.commit()
    assert client.post("/api/booklets", json=PHYS).status_code == 200


@needs_index_db
def test_recorded_and_building_are_not_double_counted(client, free_student, held):
    """A finished build is recorded BEFORE its row says ready, and only queued /
    building rows are added on top - so a finished paper counts exactly once."""
    import access
    import users_db as udb
    bid = client.post("/api/booklets", json=PHYS).json()["id"]
    user_id = udb.get_booklet(bid)["user_id"]
    access.record_quota({"id": user_id}, "topical_paper", "5054")
    udb.update_booklet(bid, {"status": "ready"})
    client.post("/api/booklets", json=PHYS)
    assert client.post("/api/booklets", json=PHYS).status_code == 200      # 1 + 2 = 3
    assert client.post("/api/booklets", json=PHYS).status_code == 429
