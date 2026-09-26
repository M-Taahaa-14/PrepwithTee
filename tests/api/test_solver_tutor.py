"""P2-e: the Solver's two modes + follow-up, and the Tutor's truncate endpoint
(regenerate / edit-and-resend). AI calls are stubbed - no network in tests."""

import base64
import sys
import uuid

import pytest

PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 64).decode()


@pytest.fixture()
def appmod(client):
    return sys.modules["website.app"]


@pytest.fixture()
def vision(appmod, monkeypatch):
    calls = []

    def fake(system, prompt, media_type, b64, extra=None):
        calls.append({"system": system, "prompt": prompt, "images": 1 + len(extra or [])})
        return "<h3>Working</h3><p>F = ma</p>", "fake"
    monkeypatch.setattr(appmod, "_solve_vision_complete", fake)
    appmod._solve_hits.clear()                     # the per-IP hourly limit is shared by tests
    return calls


def test_solve_mode(client, vision):
    r = client.post("/api/solve", json={"image": PNG, "note": "part (b)", "syllabus": "0625"})
    assert r.status_code == 200 and r.json()["mode"] == "solve" and "F = ma" in r.json()["html"]
    assert vision[-1]["images"] == 1 and "0625" in vision[-1]["prompt"] and "part (b)" in vision[-1]["prompt"]
    assert "Where marks get lost" in vision[-1]["system"]


def test_check_mode_with_a_photo_of_the_working(client, vision):
    r = client.post("/api/solve", json={"image": PNG, "mode": "check", "working": PNG})
    assert r.status_code == 200 and r.json()["mode"] == "check"
    assert vision[-1]["images"] == 2 and "Estimated mark" in vision[-1]["system"]


def test_check_mode_with_typed_working(client, vision):
    r = client.post("/api/solve", json={"image": PNG, "mode": "check", "working_text": "v = 20/4 = 5 m/s"})
    assert r.status_code == 200
    assert vision[-1]["images"] == 1 and "v = 20/4 = 5 m/s" in vision[-1]["prompt"]


def test_check_mode_needs_working_and_rejects_junk(client, vision):
    assert client.post("/api/solve", json={"image": PNG, "mode": "check"}).status_code == 400
    assert client.post("/api/solve", json={"image": PNG, "mode": "nope"}).status_code == 400
    assert client.post("/api/solve", json={"image": "not an image"}).status_code == 400
    r = client.post("/api/solve", json={"image": PNG, "mode": "check", "working": "junk"})
    assert r.status_code == 400 and "working" in r.json()["detail"]


def test_followup_uses_the_solution_as_context(client, appmod, monkeypatch):
    seen = {}

    def fake_chat(messages, max_tokens=1500):
        seen["messages"] = messages
        return "<p>Because the forces are balanced.</p>", "fake"
    monkeypatch.setattr(appmod, "_chat_complete", fake_chat)
    r = client.post("/api/solve/followup", json={"solution": "<h3>Working</h3><p>F = ma = 12 N</p>",
                                                  "message": "why is it 12?"})
    assert r.status_code == 200 and "balanced" in r.json()["html"]
    assert "F = ma = 12 N" in seen["messages"][0]["content"] and seen["messages"][1]["content"] == "why is it 12?"
    assert client.post("/api/solve/followup", json={"solution": "x", "message": " "}).status_code == 400


def test_truncate_drops_a_message_and_everything_after(client, new_student):
    import users_db as udb
    user = new_student()
    sid = str(uuid.uuid4())
    uid = client.get("/auth/me").json()["id"]
    udb.create_tutor_session(uid, sid, "0625", None)
    ids = [str(uuid.uuid4()) for _ in range(4)]
    for i, (mid, role) in enumerate(zip(ids, ["user", "assistant", "user", "assistant"])):
        udb.save_tutor_message(mid, sid, role, f"m{i}")
    r = client.delete(f"/api/tutor/sessions/{sid}/messages/{ids[2]}")
    assert r.status_code == 200 and r.json()["deleted"] == 2
    msgs = client.get(f"/api/tutor/sessions/{sid}").json()["session"]["messages"]
    assert [m["content"] for m in msgs] == ["m0", "m1"]
    assert client.delete(f"/api/tutor/sessions/{sid}/messages/{ids[3]}").status_code == 404   # gone
    # someone else's session: not found
    new_student()
    assert client.delete(f"/api/tutor/sessions/{sid}/messages/{ids[0]}").status_code == 404
    assert user
