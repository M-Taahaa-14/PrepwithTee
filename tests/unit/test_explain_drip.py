"""pipeline.explain: provider fallback, the official-answer gate, the drip queues.
No network: pipeline.ai_providers.call is replaced with fakes."""

import argparse
import json
import queue
import threading

import pytest

from pipeline import ai_providers as ap
from pipeline import explain
from pipeline import explain_check as ck


def _q(mcq=True, qid=1, key="B", syl="5054"):
    return {"id": qid, "syllabus": syl, "paper": 1 if mcq else 2, "variant": "1", "session": "s",
            "year": 2020, "number": 3, "sub_part": "", "marks": 1, "topic": "Motion", "subtopic": None,
            "crop_path": None, "ms_crop": None if mcq else "ms.pdf", "mcq_answer": key if mcq else None}


def _mcq_json(correct="B"):
    return json.dumps({"summary": "s", "parts": [{"label": "", "steps": [{"title": "t", "body": "b"}],
                                                   "answer": correct, "marking": "m"}],
                       "hints": ["1", "2", "3"], "confidence": "high",
                       "mcq_options": [{"letter": L, "correct": L == correct, "why": "w"} for L in "ABCD"]})


@pytest.fixture()
def env(monkeypatch):
    for k in ("MISTRAL_API_KEY", "NVIDIA_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setenv(k, "k")
    for k in ("GROQ_API_KEY", "OPENROUTER_API_KEY", "CLOUDFLARE_API_TOKEN", "OLLAMA_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(ck, "question_text", lambda q: "3 A ball ...\nA 1\nB 2\nC 3\nD 4")
    monkeypatch.setattr(ck, "ms_text", lambda q: "3(a) 0.56 kg m/s B1")
    monkeypatch.setattr(explain, "_image_parts", lambda p: [])
    calls = []

    def fake(name, messages, max_tokens=None, temperature=0.2):
        calls.append(name)
        return FAKE[name](messages), {"prompt_tokens": 10}, f"{name}:m", {}
    FAKE = {}
    monkeypatch.setattr(ap, "call", fake)
    return FAKE, calls


def test_wrong_letter_is_rejected_and_the_next_provider_used(env):
    fake, calls = env
    fake["mistral"] = lambda m: _mcq_json("C")          # disagrees with the key B
    fake["nvidia"] = lambda m: _mcq_json("B")
    data, _u, model, _h = explain.generate_one(_q(), route="text")
    assert model == "nvidia:m" and data["check"]["key"] == "matches the official key"
    assert calls == ["mistral", "nvidia"]


def test_nothing_stored_when_no_provider_agrees(env):
    fake, _ = env
    fake["mistral"] = fake["nvidia"] = fake["gemini"] = lambda m: _mcq_json("A")
    data, *_ = explain.generate_one(_q(), route="text")
    assert data is None


def test_text_model_can_hand_over_to_vision(env):
    fake, calls = env
    fake["mistral"] = lambda m: ('{"needs_diagram": true}' if isinstance(m[1]["content"], str)
                                 else _mcq_json("B"))
    data, _u, model, _h = explain.generate_one(_q(), route="text")
    assert data["check"]["route"] == "vision"


def test_structured_needs_the_verifier_to_agree(env):
    fake, calls = env
    good = {"summary": "s", "parts": [{"label": "(a)", "steps": [{"title": "t", "body": "p = 0.56"}],
                                       "answer": "0.56 kg m/s", "marking": "B1"}],
            "hints": ["1", "2", "3"], "confidence": "high"}
    verdicts = iter(['{"agrees": false, "problem": "wrong unit"}', '{"agrees": true, "problem": ""}'])
    fake["mistral"] = lambda m: (next(verdicts) if "check worked solutions" in m[0]["content"]
                                 else json.dumps(good))
    fake["nvidia"] = fake["mistral"]
    data, _u, model, _h = explain.generate_one(_q(mcq=False), route="text")
    assert data is not None and data["check"]["verdict"] == "agrees with the mark scheme"


def test_rate_limited_everywhere_raises(env):
    fake, _ = env

    def limited(m):
        raise ap.RateLimited(30, False)
    fake["mistral"] = fake["nvidia"] = fake["gemini"] = limited
    with pytest.raises(ap.RateLimited):
        explain.generate_one(_q(), route="text")


# ── the official-answer check (no models) ─────────────────────────────────────

def test_check_mcq():
    q = _q()
    assert ck.check(json.loads(_mcq_json("B")), q)[0]
    ok, why = ck.check(json.loads(_mcq_json("D")), q)
    assert not ok and "key is B" in why


def test_check_structured_numbers_ranges_and_partial_credit():
    q = _q(mcq=False)
    ms = "3(a) 0.60 × 560 × 25 C1\n8.4 × 10^3 J A1\n(b) –2.8 to –2.6 B1\nM1 for 1234 seen"
    good = {"parts": [{"answer": "8.4 \\times 10^{3} J", "steps": [{"body": "0.60 × 560 × 25"}]},
                      {"answer": "x = -2.7"}], "confidence": "high"}
    assert ck.check(good, q, ms)[0]                   # 1234 is partial-credit working, not required
    bad = {"parts": [{"answer": "9.1 × 10^3 J"}, {"answer": "x = -3"}], "confidence": "high"}
    assert not ck.check(bad, q, ms)[0]
    low = {**good, "confidence": "low"}
    assert not ck.check(low, q, ms)[0]


def test_maths_numbers_go_to_the_image_verifier():
    ok, why = ck.check({"parts": [{"answer": "x = 7"}], "confidence": "high"}, _q(mcq=False, syl="4024"), "19 –4")
    assert ok and "model verification" in why


def test_verdict_parsing():
    assert ck.parse_verdict('{"agrees": true, "problem": ""}') == (True, "")
    assert ck.parse_verdict('```json\n{"agrees": false, "problem": "unit"}\n```') == (False, "unit")
    assert ck.parse_verdict("no idea") is None


# ── the drip ─────────────────────────────────────────────────────────────────

def test_drip_workers_route_and_store(env, monkeypatch):
    fake, calls = env
    fake["mistral"] = fake["nvidia"] = fake["gemini"] = lambda m: _mcq_json("B")
    stored = []
    monkeypatch.setattr(explain.db, "connect", lambda: type("C", (), {"close": lambda s: None})())
    monkeypatch.setattr(explain, "store", lambda con, qid, *a: stored.append(qid))
    monkeypatch.setattr(explain, "route_of", lambda q: "vision" if q["id"] % 2 else "text")
    monkeypatch.setattr(ap, "registry", lambda: {
        "mistral": {"vision": True, "text": True, "min_gap": 0},
        "nvidia": {"vision": False, "text": True, "min_gap": 0}})
    queues = {"new": queue.Queue(), "text": queue.Queue(), "vision": queue.Queue()}
    for i in range(1, 9):
        queues["new"].put(_q(qid=i))
    args = argparse.Namespace(per_day=100, loop=False, providers=["mistral", "nvidia"])
    lock, stop = threading.Lock(), threading.Event()
    totals = {"stored": 0, "rejected": 0}
    ts = [threading.Thread(target=explain._drip_worker,
                           args=(n, queues, explain.Pacer(n, 100), args, lock, totals, stop, {}))
          for n in args.providers]
    for t in ts:
        t.start()
    for t in ts:
        t.join(30)
    assert sorted(stored) == list(range(1, 9))
    assert totals["vision"] == 4 and totals["text"] == 4


def test_reset_header_parsing():
    assert ap.seconds("2m59.5s") == pytest.approx(179.5)
