"""Booklet builds must never fail silently (tutor, 2026-10-01).

Production: 134 of 252 builds in a week died with Supabase's EMAXCONNSESSION
("max clients reached in session mode") because the web workers' connection
pool held more seats than the pooler has. The student only ever saw "We
couldn't build this paper", and a build whose worker died spun forever.
"""

import json
import subprocess
import threading
import time

import pytest

from tests.conftest import ROOT, needs_index_db

needs_raw = pytest.mark.skipif(not (ROOT / "data" / "raw").exists(), reason="raw PDFs not present")

PHYS = {"syllabus": "5054", "papers": [2], "year_from": 2018, "year_to": 2025,
        "picks": [{"chapter": "Motion"}, {"chapter": "Pressure"}]}
EMAX = ('psycopg2.OperationalError: connection to server at "aws-1-ap-northeast-2.pooler.'
        'supabase.com", port 5432 failed: FATAL:  (EMAXCONNSESSION) max clients reached in '
        'session mode - max clients are limited to pool_size: 15')


@pytest.fixture()
def enrolled(client, new_student):
    user = new_student()
    client.post("/api/enrollments", json={"syllabus": "5054"})
    return user


def wait_done(client, bid, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = client.get(f"/api/booklets/{bid}/status").json()
        if st["status"] in ("ready", "failed"):
            return st
        time.sleep(0.3)
    raise AssertionError("booklet never finished")


# ── Pure: classification + messages ───────────────────────────────────────────

def test_failures_are_classified():
    import booklets as bk
    assert bk.classify_failure(1, ["Traceback", EMAX], False) == "busy"
    assert bk.classify_failure(-9, ["..."], True) == "timeout"
    assert bk.classify_failure(-9, ["..."], False) == "too_big"
    assert bk.classify_failure(1, ["SystemExit: --ids: none of the given questions could be "
                                   "loaded (not in the database, or their original papers "
                                   "are missing)"], False) == "missing_source"
    assert bk.classify_failure(1, ["KeyError: 'x'"], False) == "internal"


def test_every_failure_tells_the_student_what_to_do():
    import booklets as bk
    for code, f in bk.FAILURES.items():
        assert f["title"] and len(f["message"]) > 40, code
        assert "couldn't build this paper" not in f["message"].lower()
    # pre-2026-10-01 rows hold a bare sentence, not JSON
    old = bk.failure({"error": "We couldn't build this paper. Please try again."})
    assert old["code"] == "internal" and old["retryable"] and old["attention"]
    new = bk.failure({"error": json.dumps({"code": "busy", "detail": EMAX})})
    assert new["code"] == "busy" and new["retryable"] and not new["attention"]


# ── Pool: never more connections than seats ──────────────────────────────────

class _FakeConn:
    def __init__(self):
        self.closed = 0

    def rollback(self):
        pass

    def close(self):
        self.closed = 1


def test_pool_caps_open_connections_and_returns_idle_seats(monkeypatch):
    import db
    opened = []
    monkeypatch.setattr(db, "_new_conn", lambda: opened.append(_FakeConn()) or opened[-1])
    monkeypatch.setattr(db, "_SEATS", threading.BoundedSemaphore(2))
    monkeypatch.setattr(db, "_idle", [])
    monkeypatch.setattr(db, "_POOL_WAIT_S", 0.2)

    a, pa = db._pg_acquire()
    b, pb = db._pg_acquire()
    assert pa and pb
    # Both seats taken: the third waits, then gets an UNPOOLED connection
    c, pc = db._pg_acquire()
    assert pc is False
    db._pg_release(c, pc)
    assert c.closed

    # A released connection is reused, not reopened
    db._pg_release(a, pa)
    again, _ = db._pg_acquire()
    assert again is a and len(opened) == 3

    # Idle too long: closed, and its seat is free again
    db._pg_release(again, True)
    monkeypatch.setattr(db, "_IDLE_CLOSE_S", -1)
    db._reap_idle()
    assert a.closed and db._idle == []
    d, pd = db._pg_acquire()
    assert pd is True and d is not a


def test_pool_default_fits_the_supabase_session_pooler():
    import db
    # 2 gunicorn workers x PG_POOL_MAX + 4 build subprocesses must stay under 15
    assert 2 * db._POOL_MAX + 4 <= 15


# ── API: real builds with an injected failure ────────────────────────────────

class _FailingProc:
    """Stands in for the compose subprocess: prints a traceback, exits 1."""
    def __init__(self, lines, rc=1):
        self.stdout = iter(line + "\n" for line in lines)
        self._rc = rc

    def wait(self):
        return self._rc

    def kill(self):
        pass


@needs_index_db
@needs_raw
def test_busy_pooler_is_retried_then_builds(client, enrolled, monkeypatch):
    import booklets as bk
    real = subprocess.Popen
    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        return _FailingProc(["Traceback (most recent call last):", EMAX]) if calls["n"] == 1 \
            else real(*a, **kw)
    monkeypatch.setattr(bk.subprocess, "Popen", flaky)
    monkeypatch.setattr(bk, "BUSY_RETRIES", (0, 0))
    b = client.post("/api/booklets", json={**PHYS, "max_questions": 3}).json()
    st = wait_done(client, b["id"])
    assert st["status"] == "ready" and calls["n"] == 2


@needs_index_db
@needs_raw
def test_failure_reaches_the_student_and_try_again_works(client, enrolled, monkeypatch):
    import booklets as bk
    real = subprocess.Popen
    broken = {"on": True}
    monkeypatch.setattr(bk.subprocess, "Popen", lambda *a, **kw: (
        _FailingProc(["Traceback (most recent call last):", EMAX]) if broken["on"]
        else real(*a, **kw)))
    monkeypatch.setattr(bk, "BUSY_RETRIES", (0, 0))
    b = client.post("/api/booklets", json={**PHYS, "max_questions": 3}).json()
    st = wait_done(client, b["id"])
    assert st["status"] == "failed" and st["error_code"] == "busy"
    assert st["retryable"] is True and "Try again" in st["error"] and st["error_title"]
    assert "EMAXCONN" not in st["error"]                       # no internals to students
    # the tutor gets the real cause
    import users_db
    assert "EMAXCONN" in json.loads(users_db.get_booklet(b["id"])["error"])["detail"]
    # My papers offers a way back in
    assert "See why · try again" in client.get("/my-papers").text

    broken["on"] = False
    assert client.post(f"/api/booklets/{b['id']}/retry").json() == {"ok": True}
    assert wait_done(client, b["id"])["status"] == "ready"
    # only failed papers can be retried
    assert client.post(f"/api/booklets/{b['id']}/retry").status_code == 409


@needs_index_db
@needs_raw
def test_a_build_whose_worker_died_stops_spinning(client, enrolled, monkeypatch):
    import booklets as bk
    import users_db
    monkeypatch.setattr(bk, "_EXEC", type("NoRun", (), {"submit": lambda *a, **k: None})())
    b = client.post("/api/booklets", json={**PHYS, "max_questions": 3}).json()
    assert client.get(f"/api/booklets/{b['id']}/status").json()["status"] == "queued"
    users_db.update_booklet(b["id"], {"status": "building", "progress": 30})
    monkeypatch.setattr(bk, "STUCK_BUILDING_S", -1)
    st = client.get(f"/api/booklets/{b['id']}/status").json()
    assert st["status"] == "failed" and st["error_code"] == "interrupted" and st["retryable"]


@needs_index_db
@needs_raw
def test_questions_with_missing_source_papers_are_never_offered(client, enrolled, monkeypatch):
    import booklets as bk
    full = client.post("/api/booklets/count", json=PHYS).json()["pool"]
    gone = {"5054"}
    monkeypatch.setattr(bk, "_source_exists", lambda rel: not any(
        ("_s23_" in str(rel)) and g in str(rel) for g in gone))
    fewer = client.post("/api/booklets/count", json=PHYS).json()["pool"]
    assert 0 < fewer < full


def test_source_exists_helper():
    from pipeline import config
    assert config.source_exists(None) is False
    assert config.source_exists("data/raw/does/not/exist.pdf") is False
