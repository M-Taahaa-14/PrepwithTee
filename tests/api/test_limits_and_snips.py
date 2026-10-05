"""Free-plan limit card data (/api/me/offer), the once-per-account self-serve
trial (/api/me/trial), and screenshots ("snips") attached to feedback."""

import base64
import json
import os

KEY = {"X-Admin-Key": "test-admin-key"}

# 1x1 PNG / tiny JPEG headers are enough: the server checks the magic number.
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def _data(raw: bytes, kind: str = "png") -> str:
    return f"data:image/{kind};base64," + base64.b64encode(raw).decode()


def _me(client):
    return client.get("/auth/me").json()


# ── Offer + trial ────────────────────────────────────────────────────────────

def test_offer_for_a_free_student(client, new_student):
    new_student()
    d = client.get("/api/me/offer", params={"event": "topical_paper"}).json()
    assert d["plan"] == "free" and d["trial_eligible"] is True and d["trial"] is False
    assert d["feature"]["name"] == "topical papers" and d["limit"] == 3 and d["used"] == 0
    assert [p["id"] for p in d["plans"]] == ["solo", "three", "all"]
    assert all(p["price"] > 0 and p["perks"] for p in d["plans"])
    assert d["trial_days"] == 7 and any(x["event"] == "topical_paper" for x in d["trial_includes"])
    assert d["resets_on"]


def test_trial_is_once_per_account(client, new_student):
    new_student()
    r = client.post("/api/me/trial")
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["plan"] == "all" and t["trial"] is True and t["days"] == 7
    d = client.get("/api/me/offer", params={"event": "topical_paper"}).json()
    assert d["trial"] is True and d["trial_eligible"] is False and d["limit"] == 8   # trial caps
    again = client.post("/api/me/trial")
    assert again.status_code == 409 and again.json()["detail"]["code"] == "trial_used"


def test_trial_needs_login(client):
    assert client.post("/api/me/trial").status_code == 401
    assert client.get("/api/me/offer").status_code == 401


def test_ai_upgrade_errors_say_what_ran_out():
    from website import ai_help
    e = ai_help._upgrade("x", "ai_hint")
    assert e.detail["event_type"] == "ai_hint" and e.detail["code"] == "upgrade_required"


# ── Feedback snips ───────────────────────────────────────────────────────────

def _send(client, **extra):
    me = _me(client)
    return client.post("/api/feedback", json={
        "message": "The crop on Q3 is cut off", "name": "Test Student",
        "email": me["email"], "page": "/papers/view/1", "type": "issue", **extra})


def test_feedback_with_snips_is_stored_privately(client, new_student):
    new_student()
    r = _send(client, snips=[_data(PNG), _data(JPG, "jpeg")])
    assert r.status_code == 200, r.text
    inbox = client.get("/api/admin/inbox", headers=KEY).json()
    items = inbox.get("items", inbox) if isinstance(inbox, dict) else inbox
    mine = [i for i in items if i["source"] == "feedback" and i["body"] == "The crop on Q3 is cut off"]
    assert mine, "feedback reached the inbox"
    snips = mine[0]["meta"]["snips"]
    assert len(snips) == 2 and snips[0].startswith("/api/admin/feedback/snips/")
    assert snips[0].endswith(".png") and snips[1].endswith(".jpg")
    got = client.get(snips[0], headers=KEY)
    assert got.status_code == 200 and got.content == PNG
    # never public: a student (or anyone without the admin role) can't read it
    assert client.get(snips[0]).status_code == 401
    assert client.get(f"/uploads/../data/feedback-snips/{os.path.basename(snips[0])}").status_code == 404


def test_feedback_snips_are_checked(client, new_student):
    new_student()
    assert _send(client, snips=[_data(b"GIF89a" + b"\x00" * 20, "png")]).status_code == 400   # not png/jpeg bytes
    assert _send(client, snips=["data:text/html;base64,PGI+"]).status_code == 400
    assert _send(client, snips=[_data(PNG)] * 4).status_code == 400                         # max 3
    assert _send(client, snips=[]).status_code == 200                                      # optional


def test_snip_route_rejects_odd_names(client):
    assert client.get("/api/admin/feedback/snips/..%2F..%2Fusers.db", headers=KEY).status_code == 404
    assert client.get("/api/admin/feedback/snips/nothere.png", headers=KEY).status_code == 404
