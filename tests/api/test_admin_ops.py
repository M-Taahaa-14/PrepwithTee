"""Admin console phase 3: billing rules, payment review, private screenshots,
the Inbox, newsletter subscribe/broadcast jobs, renewal reminders."""

import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

KEY = {"X-Admin-Key": "test-admin-key"}
ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)


def _mods():
    import billing
    import users_db
    return billing, users_db


def _user(**fields):
    _, udb = _mods()
    u = udb.create_user(f"o_{uuid.uuid4().hex[:10]}@test.local", "Ops Student")
    if fields:
        udb.update_profile(u["id"], fields)
    return udb.get_user(u["id"])


@pytest.fixture()
def shot():
    """A real screenshot file under data/uploads/payments, removed afterwards."""
    d = ROOT / "data" / "uploads" / "payments"
    d.mkdir(parents=True, exist_ok=True)
    made = []

    def make(content: bytes = None):
        name = f"test-{uuid.uuid4().hex}.png"
        (d / name).write_bytes(content or uuid.uuid4().bytes)
        made.append(d / name)
        return f"/uploads/payments/{name}"
    yield make
    for f in made:
        f.unlink(missing_ok=True)


# ── billing rules ────────────────────────────────────────────────────────────

def test_new_expiry_rules():
    billing, _ = _mods()
    # fresh monthly: 30 days from now
    assert billing.new_expiry("monthly", None, "free", NOW) == NOW + timedelta(days=30)
    # renewing early adds to the current expiry - no paid days lost
    cur = (NOW + timedelta(days=10)).isoformat()
    assert billing.new_expiry("monthly", cur, "solo", NOW) == NOW + timedelta(days=40)
    # an already-expired plan starts from now
    old = (NOW - timedelta(days=5)).isoformat()
    assert billing.new_expiry("monthly", old, "solo", NOW) == NOW + timedelta(days=30)
    assert billing.new_expiry("yearly", None, "free", NOW) == NOW + timedelta(days=365)
    # session package runs to its fixed date...
    assert billing.new_expiry("octnov", None, "free", NOW).date().isoformat() == "2026-11-30"
    # ...unless the student already has paid time beyond it
    far = (NOW + timedelta(days=90)).isoformat()
    assert billing.new_expiry("octnov", far, "all", NOW) == NOW + timedelta(days=90)


def test_reminder_steps_and_dedupe():
    billing, _ = _mods()
    def u(days):
        return {"plan": "solo", "plan_expires_at": (NOW + timedelta(days=days)).isoformat()}
    assert billing.reminder_due(u(10), NOW, set()) is None
    tid, left = billing.reminder_due(u(6.5), NOW, set())
    assert tid.startswith("EXP7:") and left == 7
    assert billing.reminder_due(u(2.5), NOW, set())[0].startswith("EXP3:")
    assert billing.reminder_due(u(0.5), NOW, set())[0].startswith("EXP1:")
    assert billing.reminder_due(u(-1), NOW, set())[0].startswith("EXPIRED:")
    assert billing.reminder_due(u(-5), NOW, set()) is None          # too late to say "ended"
    sent = {billing.reminder_due(u(2.5), NOW, set())[0]}
    assert billing.reminder_due(u(2.5), NOW, sent) is None          # once per step
    assert billing.reminder_due({"plan": "free"}, NOW, set()) is None


def test_pricing_page_matches_server_prices():
    billing, _ = _mods()
    html = (ROOT / "website" / "static" / "pricing.html").read_text(encoding="utf-8")
    block = html[html.index("var PERIODS = {"):html.index("window.PWT_PERIODS")]
    for period, conf in billing.PERIODS.items():
        seg = block[block.index(f"{period}:"):]
        for plan, amount in conf["amount"].items():
            line = re.search(rf"{plan}:\s*\{{([^}}]*)\}}", seg).group(1)
            field = "total" if period == "yearly" else "num"
            shown = int(re.search(rf"{field}:'([\d,]+)'", line).group(1).replace(",", ""))
            assert shown == amount, (period, plan, shown, amount)


# ── payment proofs ───────────────────────────────────────────────────────────

def _submit(client, new_student, shot_url, **body):
    new_student()
    base = {"plan": "all", "amount_pkr": 3000, "method": "jazzcash", "transaction_id": "TID-1",
            "screenshot_url": shot_url, "period": "monthly"}
    r = client.post("/api/payment-proof", json={**base, **body})
    return r


def test_proof_records_period_and_checks(client, new_student, shot):
    url = shot(b"same-bytes")
    r = _submit(client, new_student, url, period="yearly", amount_pkr=2400, transaction_id="TX 777")
    assert r.status_code == 200, r.text
    assert _submit(client, new_student, url, period="weekly").status_code == 400
    r2 = _submit(client, new_student, shot(b"same-bytes"), transaction_id="tx777")
    assert r2.status_code == 200
    proofs = {p["id"]: p for p in client.get("/api/admin/payments", headers=KEY).json()["proofs"]}
    p1, p2 = proofs[r.json()["proof_id"]], proofs[r2.json()["proof_id"]]
    assert p1["expected_pkr"] == 28800 and p1["period"] == "yearly"
    by = {c["code"]: c for c in p1["checks"]}
    assert not by["amount"]["ok"]                                   # paid the per-month figure
    assert not by["tid"]["ok"] and not by["shot"]["ok"]             # same TID + screenshot as p2
    assert "screenshot_url" not in p1 and p1["has_screenshot"]


def test_approve_and_reject(client, new_student, shot):
    _, udb = _mods()
    r = _submit(client, new_student, shot())
    pid = r.json()["proof_id"]
    assert client.post(f"/api/admin/payments/{pid}/approve", headers=KEY, json={}).status_code == 400
    r = client.post(f"/api/admin/payments/{pid}/approve", headers=KEY,
                    json={"received": True, "note": "Thanks!"})
    assert r.status_code == 200, r.text
    proof = r.json()["proof"]
    assert proof["status"] == "approved" and proof["reviewer_note"] == "Thanks!"
    assert proof["reviewed_by"]
    user = udb.get_user(proof["user_id"])
    assert user["plan"] == "all"
    exp = datetime.fromisoformat(user["plan_expires_at"])
    assert 29 <= (exp - datetime.now(timezone.utc)).days <= 30
    assert client.post(f"/api/admin/payments/{pid}/approve", headers=KEY,
                       json={"received": True}).status_code == 409

    r = _submit(client, new_student, shot(), transaction_id="TID-2")
    pid = r.json()["proof_id"]
    assert client.post(f"/api/admin/payments/{pid}/reject", headers=KEY, json={"reason": " "}).status_code == 400
    r = client.post(f"/api/admin/payments/{pid}/reject", headers=KEY,
                    json={"reason": "No money arrived"})
    assert r.status_code == 200 and r.json()["proof"]["status"] == "rejected"


def test_renewal_extends_from_current_expiry(client, new_student, shot):
    _, udb = _mods()
    pid = _submit(client, new_student, shot()).json()["proof_id"]
    client.post(f"/api/admin/payments/{pid}/approve", headers=KEY, json={"received": True})
    uid = udb.get_payment_proof(pid)["user_id"]
    first = datetime.fromisoformat(udb.get_user(uid)["plan_expires_at"])
    r = client.post("/api/payment-proof", json={"plan": "all", "amount_pkr": 3000, "method": "bank",
                                                "transaction_id": "TID-R", "screenshot_url": shot(),
                                                "period": "monthly"})
    pid2 = r.json()["proof_id"]
    client.post(f"/api/admin/payments/{pid2}/approve", headers=KEY, json={"received": True})
    second = datetime.fromisoformat(udb.get_user(uid)["plan_expires_at"])
    assert abs((second - first).total_seconds() - 30 * 86400) < 120


def test_three_plan_approval_needs_subjects(client, new_student, shot):
    r = _submit(client, new_student, shot(), plan="three", amount_pkr=2000,
                subjects=["5054", "4024", "0625"])
    pid = r.json()["proof_id"]
    r = client.post(f"/api/admin/payments/{pid}/approve", headers=KEY, json={"received": True})
    assert r.status_code == 200
    import access
    _, udb = _mods()
    assert access.plan_subjects(udb.get_user(r.json()["proof"]["user_id"])) == ["5054", "4024", "0625"]


def test_classic_review_route_uses_new_rules(client, new_student, shot):
    pid = _submit(client, new_student, shot()).json()["proof_id"]
    r = client.post(f"/api/admin/payment-proofs/{pid}/review", headers=KEY, json={"status": "rejected"})
    assert r.status_code == 200 and r.json()["proof"]["reviewer_note"]


def test_screenshots_are_private(client, new_student, shot, app):
    from fastapi.testclient import TestClient
    url = shot()
    pid = _submit(client, new_student, url).json()["proof_id"]
    assert client.get(url).status_code == 200                       # the student who sent it
    with TestClient(app) as anon:
        assert anon.get(url).status_code == 404                     # nobody else
        assert anon.get(f"/api/admin/payments/{pid}/screenshot", headers=KEY).status_code == 200
    with TestClient(app) as other:
        other.post("/auth/register", json={"email": f"x_{uuid.uuid4().hex[:8]}@test.local",
                                           "password": "Passw0rd!23", "name": "Other"})
        assert other.get(url).status_code == 404


# ── inbox ────────────────────────────────────────────────────────────────────

def test_inbox(client):
    _, udb = _mods()
    udb.create_contact("Sana", "sana@test.local", "Group timings?", "When are the classes?")
    items = client.get("/api/admin/inbox", headers=KEY).json()["items"]
    item = next(i for i in items if i["source"] == "contact" and i["email"] == "sana@test.local")
    assert item["status"] == "new"
    path = f"/api/admin/inbox/contact/{item['id']}"
    assert client.patch(path, headers=KEY, json={"status": "bogus"}).status_code == 400
    r = client.patch(path, headers=KEY, json={"status": "handled", "note": "Called her"})
    assert r.status_code == 200
    items = client.get("/api/admin/inbox", headers=KEY).json()["items"]
    item = next(i for i in items if i["key"] == item["key"])
    assert item["status"] == "handled" and item["note"] == "Called her"
    r = client.post("/api/admin/inbox/bulk", headers=KEY, json={"keys": [item["key"]], "status": "archived"})
    assert r.json()["done"] == 1
    # no mail provider in tests: the reply fails loudly instead of pretending
    r = client.post(f"{path}/reply", headers=KEY, json={"subject": "Re", "body": "Hi"})
    assert r.status_code == 502
    assert client.patch("/api/admin/inbox/martians/1", headers=KEY, json={"status": "new"}).status_code == 404


def test_reply_needs_an_address(client):
    _, udb = _mods()
    udb._insert("subject_requests", {"subject": "Biology", "board": "IGCSE", "message": "please"},
                ["subject", "board", "message"])
    items = client.get("/api/admin/inbox", headers=KEY).json()["items"]
    req = next(i for i in items if i["source"] == "request" and "Biology" in i["title"])
    r = client.post(f"/api/admin/inbox/request/{req['id']}/reply", headers=KEY,
                    json={"subject": "x", "body": "y"})
    assert r.status_code == 400


# ── newsletter ───────────────────────────────────────────────────────────────

def test_resubscribe_and_legacy_rows(client):
    _, udb = _mods()
    email = f"n_{uuid.uuid4().hex[:6]}@test.local"
    assert client.post("/api/newsletter", json={"email": email}).status_code == 200
    row = udb.get_newsletter_subscriber(email)
    udb.unsubscribe_newsletter(row["unsubscribe_token"])
    assert udb.get_newsletter_subscriber(email)["status"] == "unsubscribed"
    is_new, _ = udb.create_newsletter_subscriber(email.upper())
    assert is_new and udb.get_newsletter_subscriber(email)["status"] == "subscribed"
    # a legacy row with no status and no token still gets newsletters, with a real link
    legacy = f"l_{uuid.uuid4().hex[:6]}@test.local"
    udb._insert("newsletter_subscribers", {"email": legacy, "subscribed_at": "2025-01-01"},
                ["email", "subscribed_at"])
    active = {s["email"]: s for s in udb.get_newsletter_subscribers(limit=100000, active_only=True)}
    assert legacy in active and active[legacy]["unsubscribe_token"]


def test_broadcast_job(client):
    import admin_ops
    _, udb = _mods()
    emails = [f"b_{uuid.uuid4().hex[:6]}@test.local" for _ in range(3)]
    for e in emails:
        udb.create_newsletter_subscriber(e)
    r = client.post("/api/admin/newsletter/broadcasts", headers=KEY, json={
        "subject": "Exam tips", "body_markdown": "## Hello\n\nRead **this**.",
        "cta_label": "Open", "cta_url": "https://prepwithtee.com/"})
    assert r.status_code == 200, r.text
    b = r.json()["broadcast"]
    assert b["status"] == "queued" and b["total"] >= 3
    sent_to = []

    def fake(subject, text, to=None, html_override=None, **kw):
        assert "unsubscribe?token=" in html_override and "<h2" in html_override
        sent_to.append(to)
        return not to.startswith(emails[0][:4]) or to != emails[0]
    out = admin_ops.run_broadcast(b["id"], notify=fake, pause=0)
    assert out["status"] == "sent"
    assert set(emails) <= set(sent_to)
    assert out["failed"] >= 1 and out["sent"] + out["failed"] == len(sent_to)
    # resumable: a second run sends nobody twice
    sent_to.clear()
    admin_ops.run_broadcast(b["id"], notify=fake, pause=0)
    assert sent_to == []
    listed = client.get("/api/admin/newsletter/broadcasts", headers=KEY).json()["broadcasts"]
    assert any(x["id"] == b["id"] and x["status"] == "sent" for x in listed)


def test_broadcast_claim_and_cancel(client):
    import admin_ops
    _, udb = _mods()
    b = udb.create_broadcast({"subject": "s", "body_markdown": "b", "total": 0})
    stale = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    assert udb.claim_broadcast(b["id"], "w1", stale)
    assert not udb.claim_broadcast(b["id"], "w2", stale)            # fresh heartbeat: taken
    assert client.post(f"/api/admin/newsletter/broadcasts/{b['id']}/cancel", headers=KEY).status_code == 200
    assert client.post(f"/api/admin/newsletter/broadcasts/{b['id']}/cancel", headers=KEY).status_code == 409
    assert admin_ops.run_broadcast(b["id"], notify=lambda *a, **k: True)["status"] == "cancelled"


def test_broadcast_validation_and_test_send(client):
    for body in ({"subject": "", "body_markdown": "x"},
                 {"subject": "x", "body_markdown": "x", "cta_url": "javascript:alert(1)"}):
        assert client.post("/api/admin/newsletter/broadcasts", headers=KEY, json=body).status_code == 400
    r = client.post("/api/admin/newsletter/broadcasts", headers=KEY,
                    json={"subject": "x", "body_markdown": "y", "test_email": "me@test.local"})
    assert r.status_code == 502                                      # no mail provider in tests


def test_renewal_reminder_requires_paid_plan(client):
    u = _user()
    assert client.post(f"/api/admin/students/{u['id']}/renewal-reminder", headers=KEY).status_code == 400
    paid = _user(plan="solo", plan_expires_at=(datetime.now(timezone.utc) + timedelta(days=3)).isoformat())
    assert client.post(f"/api/admin/students/{paid['id']}/renewal-reminder", headers=KEY).status_code == 502
    r = client.get("/api/admin/payments/expiring", headers=KEY, params={"days": 7})
    assert any(x["id"] == paid["id"] for x in r.json()["rows"])


# ── homework: real file types, topical paper built for a student ─────────────

def test_upload_content_must_match_extension():
    import admin
    assert admin.content_matches(".pdf", b"%PDF-1.4 ...")
    assert not admin.content_matches(".pdf", b"MZ\x90\x00 not a pdf")
    assert admin.content_matches(".png", b"\x89PNG\r\n\x1a\n....")
    assert admin.content_matches(".webp", b"RIFF\x00\x00\x00\x00WEBPVP8 ")
    assert not admin.content_matches(".webp", b"RIFF\x00\x00\x00\x00AVI LIST")
    assert admin.content_matches(".docx", b"PK\x03\x04....")
    assert admin.content_matches(".txt", "Hello, maths".encode())
    assert not admin.content_matches(".txt", b"\x00\x01\x02binary")
    assert not admin.content_matches(".exe", b"MZ")


def test_upload_route_refuses_renamed_files(client):
    u = _user()
    r = client.post(f"/api/admin/students/{u['id']}/assignments?notify=false", headers=KEY,
                    json={"title": "Worksheet"})
    aid = r.json()["assignment"]["id"]
    ok = client.post(f"/api/admin/assignments/{aid}/files", headers=KEY,
                     files={"file": ("w.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")})
    assert ok.status_code == 200, ok.text
    bad = client.post(f"/api/admin/assignments/{aid}/files", headers=KEY,
                      files={"file": ("w.pdf", b"MZ\x90 this is an exe", "application/pdf")})
    assert bad.status_code == 400 and "isn't really" in bad.json()["detail"]
    import admin
    for att in ok.json()["assignment"]["attachments"]:
        (admin.UPLOADS_DIR / att["rel"]).unlink(missing_ok=True)


@pytest.mark.skipif(not (ROOT / "data" / "index.db").exists(), reason="needs the question archive")
def test_topical_paper_for_student_and_attachment(client):
    import catalog
    _, udb = _mods()
    u = _user()
    ch = next(c for c in catalog.chapters("5054") if c.get("count"))
    r = client.post(f"/api/admin/students/{u['id']}/booklets", headers=KEY, json={
        "syllabus": "5054", "picks": [{"chapter": ch["name"]}], "max_questions": 5,
        "year_from": 2015, "year_to": 2025})
    assert r.status_code == 200, r.text
    bid = r.json()["id"]
    b = udb.get_booklet(bid)
    assert b["user_id"] == u["id"] and len(b["question_ids"]) <= 5
    assert udb.count_usage_this_month(u["id"], "topical_paper") == 0      # no quota used
    r = client.post(f"/api/admin/students/{u['id']}/assignments?notify=false", headers=KEY, json={
        "title": "Paper homework", "attachments": [{"type": "paper", "booklet_id": bid}]})
    att = r.json()["assignment"]["attachments"][0]
    assert att["type"] == "paper" and att["booklet_id"] == bid and ch["display"] in att["name"]
    bad = client.post(f"/api/admin/students/{u['id']}/assignments?notify=false", headers=KEY, json={
        "title": "x", "attachments": [{"type": "paper", "booklet_id": "nope123"}]})
    assert bad.status_code == 400
    assert client.post(f"/api/admin/students/{u['id']}/booklets", headers=KEY,
                       json={"syllabus": "5054", "picks": [{"chapter": "Not a chapter"}]}).status_code == 422
