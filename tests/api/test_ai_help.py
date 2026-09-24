"""Explain / Guide me / follow-ups: the plan rules, and the follow-up stream.
No real model calls - the free-provider calls are replaced with fakes."""

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import users_db
from tests.conftest import needs_index_db

pytestmark = needs_index_db

SAMPLE = {"summary": "Tests pressure = force / area.",
          "parts": [{"label": "(a)", "steps": [{"title": "Use p = F/A",
                                                "body": "$p = \\frac{F}{A}$"}],
                     "answer": "2000 Pa", "marking": "C1 formula, A1 answer"}],
          "hints": ["What quantity links force and area?", "Write p = F/A.",
                    "Check your area is in m²."],
          "mcq_options": [], "common_mistakes": ["Area in cm²"], "confidence": "high"}


def _qids(n=3):
    con = sqlite3.connect(os.environ["INDEX_DB_PATH"])
    ids = [r[0] for r in con.execute(
        "SELECT q.id FROM questions q JOIN papers p ON p.id=q.paper_id "
        "WHERE p.syllabus='5054' AND p.paper=2 AND p.kind='qp' LIMIT ?", (n,))]
    con.execute("""CREATE TABLE IF NOT EXISTS question_explanations (
        question_id INTEGER PRIMARY KEY, content_json TEXT NOT NULL, model TEXT,
        prompt_version INTEGER NOT NULL DEFAULT 1, input_tokens INTEGER, output_tokens INTEGER,
        flagged INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT (datetime('now')))""")
    for qid in ids[:-1]:                      # the last one stays "not ready"
        con.execute("INSERT OR REPLACE INTO question_explanations (question_id, content_json) "
                    "VALUES (?, ?)", (qid, json.dumps(SAMPLE)))
    con.commit()
    con.close()
    return ids


@pytest.fixture()
def qids():
    return _qids()


def make_paid(user, plan="solo"):
    users_db.update_profile(user["id"], {
        "plan": plan, "plan_trial": 0,
        "plan_started_at": datetime.now(timezone.utc).isoformat(),
        "plan_expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()})


def test_free_student_gets_one_explanation_and_can_reopen_it(client, new_student, qids):
    new_student()
    a, b, _ = qids
    r = client.get(f"/api/questions/{a}/explain")
    assert r.status_code == 200 and r.json()["parts"][0]["answer"] == "2000 Pa"
    assert "hints" not in r.json()                      # hints are a separate, gated call
    assert client.get(f"/api/questions/{a}/explain").status_code == 200   # reopen: free
    r = client.get(f"/api/questions/{b}/explain")
    assert r.status_code == 403
    d = r.json()["detail"]
    assert d["code"] == "upgrade_required" and d["url"] == "/pricing.html"


def test_not_ready_does_not_use_up_the_free_one(client, new_student, qids):
    new_student()                      # no provider key in tests -> cannot generate
    a, _, missing = qids
    r = client.get(f"/api/questions/{missing}/explain")
    assert r.status_code == 404 and "being prepared" in r.json()["detail"]
    assert client.get(f"/api/questions/{a}/explain").status_code == 200


def test_missing_explanation_is_generated_once_and_stored(client, new_student, qids, monkeypatch):
    from pipeline import explain as ex
    calls = []
    monkeypatch.setattr(ex, "available_providers", lambda: ["groq"])
    monkeypatch.setattr(ex, "generate_one",
                        lambda q, provider=None: calls.append(q["id"]) or
                        (SAMPLE, {"prompt_tokens": 10, "completion_tokens": 20}, "groq:test", {}))
    new_student()
    missing = qids[-1]
    assert client.get(f"/api/questions/{missing}/explain").status_code == 200
    assert client.get(f"/api/questions/{missing}/explain").status_code == 200   # now stored
    assert calls == [missing]
    con = sqlite3.connect(os.environ["INDEX_DB_PATH"])
    assert con.execute("SELECT model FROM question_explanations WHERE question_id=?",
                       (missing,)).fetchone()[0] == "groq:test"
    con.execute("DELETE FROM question_explanations WHERE question_id=?", (missing,))
    con.commit()
    con.close()


def test_busy_provider_does_not_spend_the_free_one(client, new_student, qids, monkeypatch):
    from pipeline import explain as ex
    monkeypatch.setattr(ex, "available_providers", lambda: ["groq"])

    def busy(q, provider=None):
        raise ex.RateLimited(30, False)

    monkeypatch.setattr(ex, "generate_one", busy)
    new_student()
    r = client.get(f"/api/questions/{qids[-1]}/explain")
    assert r.status_code == 503 and "busy" in r.json()["detail"]
    assert client.get(f"/api/questions/{qids[0]}/explain").status_code == 200   # still free


def test_hints_and_followups_need_a_plan(client, new_student, qids):
    new_student()
    a = qids[0]
    assert client.get(f"/api/questions/{a}/hints", params={"level": 1}).status_code == 403
    assert client.post(f"/api/questions/{a}/ask", json={"message": "why?"}).status_code == 403


def test_paid_student_explains_everything_and_gets_hints_one_at_a_time(client, new_student, qids):
    make_paid(new_student())
    a, b, _ = qids
    assert client.get(f"/api/questions/{a}/explain").status_code == 200
    assert client.get(f"/api/questions/{b}/explain").status_code == 200
    h1 = client.get(f"/api/questions/{a}/hints", params={"level": 1}).json()["hints"]
    h3 = client.get(f"/api/questions/{a}/hints", params={"level": 3}).json()["hints"]
    assert len(h1) == 1 and len(h3) == 3


def test_followup_streams_is_saved_and_quotes_the_selection(client, new_student, qids, monkeypatch):
    import ai_help
    make_paid(new_student())
    sent = []
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(ai_help, "_stream_chat",
                        lambda msgs, key: sent.append(msgs) or
                        iter(["Because ", "area must be ", "in $\\mathrm{m^2}$."]))
    a = qids[0]
    r = client.post(f"/api/questions/{a}/ask",
                    json={"message": "Why convert?", "quoted_text": "Check your area is in m²."})
    assert r.status_code == 200 and r.text == "Because area must be in $\\mathrm{m^2}$."
    msgs = sent[0]
    assert msgs[0]["role"] == "system" and "Worked solution the student read" in msgs[0]["content"]
    assert msgs[-1]["content"].startswith('About this part: "Check your area is in m²."')
    thread = client.get(f"/api/questions/{a}/thread").json()["messages"]
    assert [m["role"] for m in thread] == ["user", "assistant"]
    assert thread[0]["quoted_text"] == "Check your area is in m²."


def test_followup_without_a_key_says_so(client, new_student, qids):
    make_paid(new_student())
    r = client.post(f"/api/questions/{qids[0]}/ask", json={"message": "hi"})
    assert r.status_code == 503


def test_report_flags_the_explanation(client, new_student, qids):
    new_student()
    a = qids[0]
    assert client.post(f"/api/questions/{a}/report", json={"reason": "wrong unit"}).json()["ok"]
    con = sqlite3.connect(os.environ["INDEX_DB_PATH"])
    assert con.execute("SELECT flagged FROM question_explanations WHERE question_id=?",
                       (a,)).fetchone()[0] >= 1
    con.close()
