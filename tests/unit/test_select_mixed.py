from collections import Counter

import pytest

from selection import interleave, quotas, select_mixed


def pool(bucket, n, year0=2015):
    return [{"id": f"{bucket}{i}", "bucket": bucket, "year": year0 + i % 10} for i in range(n)]


def runs(seq):
    """Length of the longest run of consecutive questions from one bucket."""
    best = cur = 1
    for a, b in zip(seq, seq[1:]):
        cur = cur + 1 if a["bucket"] == b["bucket"] else 1
        best = max(best, cur)
    return best


def test_every_bucket_is_represented_and_mixed():
    qs = pool("A", 60) + pool("B", 3) + pool("C", 12)
    out = select_mixed(qs, 15, seed=1)
    assert len(out) == 15
    assert {q["bucket"] for q in out} == {"A", "B", "C"}
    assert runs(out) <= 3            # A dominates, but never as a long block


def test_small_bucket_still_gets_a_question_when_total_is_tight():
    qs = pool("A", 100) + pool("B", 1) + pool("C", 1) + pool("D", 1)
    out = select_mixed(qs, 4, seed=2)
    assert Counter(q["bucket"] for q in out) == {"A": 1, "B": 1, "C": 1, "D": 1}


def test_never_more_than_the_pool_and_no_duplicates():
    qs = pool("A", 3) + pool("B", 2) + pool("A", 3)      # duplicate ids
    out = select_mixed(qs, 50, seed=3)
    assert len(out) == 5 == len({q["id"] for q in out})


def test_seed_is_reproducible_and_seeds_differ():
    qs = pool("A", 40) + pool("B", 40)
    a = [q["id"] for q in select_mixed(qs, 12, seed=7)]
    assert a == [q["id"] for q in select_mixed(qs, 12, seed=7)]
    assert a != [q["id"] for q in select_mixed(qs, 12, seed=8)]


def test_even_buckets_alternate():
    out = select_mixed(pool("A", 20) + pool("B", 20), 10, seed=4)
    assert runs(out) == 1


@pytest.mark.parametrize("sizes,total", [({"A": 5, "B": 5}, 4), ({"A": 1, "B": 90}, 30),
                                         ({"A": 2}, 10), ({"A": 0, "B": 3}, 2)])
def test_quotas_invariants(sizes, total):
    q = quotas(sizes, total)
    assert sum(q.values()) == min(total, sum(sizes.values()))
    assert all(q[b] <= sizes[b] for b in q)


def test_empty_pool():
    assert select_mixed([], 10) == [] and interleave({}) == []
