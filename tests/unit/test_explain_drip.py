"""pipeline.explain --drip: providers share one queue, a busy provider's question is
retried by someone, and a provider's daily limit stops only that provider."""

import argparse
import threading

from pipeline import explain

SAMPLE = {"summary": "s", "parts": [], "hints": ["1", "2", "3"], "confidence": "high"}


def _run(monkeypatch, behaviour, n=6):
    stored = []
    monkeypatch.setattr(explain.db, "connect", lambda: type("C", (), {"close": lambda s: None})())
    monkeypatch.setattr(explain, "store", lambda con, qid, *a: stored.append(qid))
    calls = {"groq": 0, "gemini": 0}

    def fake(q, provider=None):
        calls[provider] += 1
        return behaviour(provider, calls[provider], q)

    monkeypatch.setattr(explain, "generate_one", fake)
    import queue
    work = queue.Queue()
    for i in range(n):
        work.put({"id": i})
    args = argparse.Namespace(per_day=100, loop=False, gap=0, reserve=0,
                              providers=["groq", "gemini"])
    lock, stop = threading.Lock(), threading.Event()
    totals = {"stored": 0, "unusable": 0, "errors": 0}
    ts = [threading.Thread(target=explain._drip_worker, args=(p, work, args, lock, totals, stop))
          for p in args.providers]
    for t in ts:
        t.start()
    for t in ts:
        t.join(20)
    return stored, calls, totals


def test_both_providers_share_the_queue(monkeypatch):
    stored, calls, totals = _run(monkeypatch, lambda p, n, q: (SAMPLE, {}, p, {}))
    assert sorted(stored) == list(range(6)) and totals["stored"] == 6


def test_daily_limit_stops_one_provider_and_the_other_finishes(monkeypatch):
    def beh(p, n, q):
        if p == "groq":
            raise explain.RateLimited(3600, True)
        return SAMPLE, {}, p, {}
    stored, calls, totals = _run(monkeypatch, beh)
    assert sorted(stored) == list(range(6))           # nothing lost: groq's pick went back
    assert calls["groq"] == 1


def test_unusable_answer_is_counted_not_stored(monkeypatch):
    stored, _, totals = _run(monkeypatch, lambda p, n, q: (None if q["id"] == 0 else SAMPLE,
                                                             {}, p, {}), n=3)
    assert sorted(stored) == [1, 2] and totals["unusable"] == 1
