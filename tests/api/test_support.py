"""Help centre API (website/support.py): live facts, account-aware answers with
one-tap fixes, handoff to Tee's Inbox and back, votes, report, status banner."""

import uuid

import pytest

KEY = {"X-Admin-Key": "test-admin-key"}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    import support          # the app imports it top-level (website/ on sys.path)
    monkeypatch.setattr(support, "STATUS_FILE", tmp_path / "status.json")
    monkeypatch.setattr(support, "AI_CALL", None)
    support._hits.clear()
    yield


def _me(client):
    return client.get("/auth/me").json()


def ask(client, text, page="/papers/topical"):
    r = client.post("/api/support/chat", json={"message": text, "page": page})
    assert r.status_code == 200, r.text
    return r.json()


# ── Facts come from the live tables ─────────────────────────────────────────

def test_facts_match_billing_and_catalog():
    import billing
    import catalog
    import support
    txt = support.facts_text()
    for p in billing.PERIODS.values():
        for v in p["amount"].values():
            assert f"PKR {v:,}" in txt
    for code in catalog.SUBJECTS:
        assert code in txt


def test_pricing_answer_uses_live_prices(client):
    import billing
    d = ask(client, "how much are the plans")
    assert d["intent"] == "pricing"
    assert f"PKR {billing.PERIODS['monthly']['amount']['solo']:,}" in d["reply"]
    assert any(a["kind"] == "link" and a["url"].startswith("/pricing.html") for a in d["actions"])


def test_guest_context_has_no_account(client):
    d = client.get("/api/support/context").json()
    assert d["signed_in"] is False and "hours" in d and d["whatsapp_url"].startswith("https://wa.me/")


# ── Account-aware answers ───────────────────────────────────────────────────

def test_free_student_allowance_and_trial(client, new_student):
    new_student()
    ctx = client.get("/api/support/context").json()
    assert ctx["signed_in"] and ctx["plan"] == "free" and ctx["trial_eligible"] is True
    ev = {a["event"]: a for a in ctx["allowance"]}
    assert ev["topical_paper"]["limit"] == 3 and ev["topical_paper"]["used"] == 0
    d = ask(client, "how many booklets do I have left")
    assert d["intent"] == "quota" and "3 of 3 left" in d["reply"]
    assert any(a["kind"] == "trial" for a in d["actions"])


def test_payment_status_reads_their_proof(client, new_student):
    import users_db
    new_student()
    me = _me(client)
    d = ask(client, "I paid but my plan is still free")
    assert d["intent"] == "payment_status" and "can't see a payment proof" in d["reply"]
    users_db.create_payment_proof({"user_id": me["id"], "plan": "three", "amount_pkr": 2000,
                                   "method": "jazzcash", "period": "monthly"})
    d = ask(client, "I paid but my plan is still free")
    assert "waiting to be checked" in d["reply"] and "3 Subjects" in d["reply"]


def test_failed_booklet_gets_retry_button(client, new_student):
    import users_db
    new_student()
    me = _me(client)
    bid = uuid.uuid4().hex[:12]
    users_db.create_booklet({"id": bid, "user_id": me["id"], "syllabus": "5054", "title": "Physics 5054 · Motion",
                             "params_json": {"syllabus": "5054", "picks": [{"chapter": "Motion"}]},
                             "question_ids": [1, 2], "status": "failed",
                             "error": '{"code": "busy", "detail": "EMAXCONNSESSION"}'})
    d = ask(client, "my booklet failed to build")
    assert d["intent"] == "booklet_problem"
    assert "Our server was too busy" in d["reply"] and "EMAXCONN" not in d["reply"]
    assert {"kind": "retry", "label": "Try again", "booklet_id": bid} in d["actions"]
    ctx = client.get("/api/support/context").json()
    assert ctx["booklets"][0]["id"] == bid and ctx["booklets"][0]["retryable"] is True


# ── AI path ─────────────────────────────────────────────────────────────────

def test_ai_answer_has_made_up_links_removed(client, monkeypatch):
    import support          # the app imports it top-level (website/ on sys.path)
    seen = {}

    def fake(messages):
        seen["system"] = messages[0]["content"]
        return "Try the [notes](/notes) or the [secret page](/nope-not-real.html)."
    monkeypatch.setattr(support, "AI_CALL", fake)
    d = ask(client, "what does the dark paper toggle do")
    assert d["source"] == "ai"
    assert "[notes](/notes)" in d["reply"] and "/nope-not-real" not in d["reply"]
    assert "PKR" in seen["system"] and "Current page: /papers/topical" in seen["system"]


def test_no_ai_falls_back_to_handoff(client):
    d = ask(client, "what does the dark paper toggle do")
    assert d["source"] == "fallback" and d["suggest_handoff"] is True
    assert d["actions"][0]["kind"] == "handoff"


def test_old_chatbot_endpoint_still_answers(client):
    r = client.post("/api/chatbot", json={"message": "how much are the plans"})
    assert r.status_code == 200 and "PKR" in r.json()["reply"]


def test_rate_limit_for_guests(client, monkeypatch):
    import support          # the app imports it top-level (website/ on sys.path)
    monkeypatch.setattr(support, "LIMIT_GUEST", 2)
    ask(client, "pricing")
    ask(client, "pricing")
    r = client.post("/api/support/chat", json={"message": "pricing"})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "support_rate"


# ── Votes + report ──────────────────────────────────────────────────────────

def test_vote_and_report(client):
    d = ask(client, "how much are the plans")
    assert client.post("/api/support/vote", json={"event_id": d["event_id"], "vote": -1}).status_code == 200
    assert client.post("/api/support/vote", json={"event_id": d["event_id"], "vote": 5}).status_code == 400
    rep = client.get("/api/admin/support/report?days=7", headers=KEY).json()
    assert rep["asked"] >= 1 and rep["down"] >= 1
    assert any(e["id"] == d["event_id"] for e in rep["downvoted"])
    assert client.get("/api/admin/support/report").status_code in (401, 403)


def test_cannot_vote_on_someone_elses_answer(client, new_student):
    new_student()
    d = ask(client, "how much are the plans")
    client.post("/auth/logout")
    new_student()
    assert client.post("/api/support/vote", json={"event_id": d["event_id"], "vote": 1}).status_code == 403


# ── Handoff -> Inbox -> reply back to the student ───────────────────────────

def test_handoff_reaches_inbox_and_reply_comes_back(client, new_student, monkeypatch):
    new_student()
    me = _me(client)
    ask(client, "my booklet failed to build")
    r = client.post("/api/support/handoff", json={
        "name": "Test Student", "email": me["email"], "message": "Paper keeps failing",
        "transcript": [{"role": "user", "content": "my booklet failed"}, {"role": "assistant", "content": "Try again"}],
        "page": "/papers/topical", "diag": {"ua": "Firefox", "errors": ["TypeError: x"], "evil": "dropped"}})
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    assert tid

    inbox = client.get("/api/admin/inbox", headers=KEY).json()["items"]
    item = next(i for i in inbox if i["key"] == f"support:{tid}")
    assert item["status"] == "new" and item["email"] == me["email"]
    assert item["meta"]["transcript"][0] == {"role": "student", "text": "my booklet failed"}
    assert item["meta"]["diag"]["errors"] == ["TypeError: x"] and "evil" not in item["meta"]["diag"]
    acct = client.get(f"/api/admin/support/{tid}/account", headers=KEY).json()["account"]
    assert acct["id"] == me["id"] and acct["plan"] == "Free"

    import app as app_mod          # admin_ops does `from app import _notify`
    monkeypatch.setattr(app_mod, "_notify", lambda *a, **k: True)
    rr = client.post(f"/api/admin/inbox/support/{tid}/reply", headers=KEY,
                     json={"subject": "Re: your paper", "body": "Fixed - press Try again."})
    assert rr.status_code == 200, rr.text

    th = client.get("/api/support/threads").json()["threads"]
    assert th[0]["id"] == tid and th[0]["status"] == "replied"
    assert th[0]["replies"][0]["body"] == "Fixed - press Try again."


def test_handoff_validation(client):
    assert client.post("/api/support/handoff", json={"name": "A", "email": "x@y.com", "message": "hi"}).status_code == 400
    assert client.post("/api/support/handoff", json={"name": "Ali", "email": "nope", "message": "hi"}).status_code == 400
    assert client.post("/api/support/handoff", json={"name": "Ali", "email": "ali@gmail.com"}).status_code == 400


def test_threads_need_login(client):
    assert client.get("/api/support/threads").status_code == 401


# ── Status banner + office hours ────────────────────────────────────────────

def test_status_banner_and_hours(client):
    r = client.put("/api/admin/support/status", headers=KEY,
                   json={"banner_text": "Builds are slow tonight", "banner_tone": "warn",
                         "hours_start": 9, "hours_end": 21, "hours_days": [0, 1, 2, 3, 4]})
    assert r.status_code == 200, r.text
    ctx = client.get("/api/support/context").json()
    assert ctx["banner"] == {"text": "Builds are slow tonight", "tone": "warn"}
    assert ctx["hours"]["start"] == 9 and ctx["hours"]["end"] == 21
    bad = client.put("/api/admin/support/status", headers=KEY, json={"hours_start": 20, "hours_end": 8})
    assert bad.status_code == 400
    client.put("/api/admin/support/status", headers=KEY, json={"banner_text": ""})
    assert client.get("/api/support/context").json()["banner"] is None


def test_hours_text():
    from datetime import datetime, timezone
    import support          # the app imports it top-level (website/ on sys.path)
    st = {"hours": {"start": 10, "end": 22, "days": [0, 1, 2, 3, 4, 5, 6]}}
    noon_pkt = datetime(2026, 10, 9, 7, 0, tzinfo=timezone.utc)      # 12:00 PKT
    night_pkt = datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc)    # 01:00 PKT
    assert support.hours(noon_pkt, st)["open"] is True
    late = support.hours(night_pkt, st)
    assert late["open"] is False and "10am today" in late["text"]
