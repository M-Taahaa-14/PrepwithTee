"""Pick and order questions for a topical booklet.

The tutor's rule (2026-09-24): don't give all of topic 1, then all of topic 2 -
mix them, and make sure every picked topic is in the paper.

    select_mixed(pool, max_questions, seed)

`pool` rows are dicts with at least `id`, `bucket` (what the student picked:
a subtopic, or a whole chapter) and `year`. Pure function - no DB, no I/O -
so it is unit-tested directly (tests/unit/test_select_mixed.py).
"""

import random
from collections import defaultdict

YEAR_BASE = 2010


def _weighted_order(rows, rng):
    """Random order that favours recent years (same weighting as testgen)."""
    def key(q):
        w = 1.5 ** ((q.get("year") or YEAR_BASE) - YEAR_BASE)
        return rng.random() ** (1.0 / w)
    return sorted(rows, key=key, reverse=True)


def quotas(sizes: dict[str, int], total: int) -> dict[str, int]:
    """Split `total` across buckets proportionally to their size, but give every
    bucket at least one question (if `total` allows) and never more than it has."""
    buckets = [b for b, n in sizes.items() if n > 0]
    total = min(total, sum(sizes[b] for b in buckets))
    if not buckets or total <= 0:
        return {}
    q = {b: 0 for b in buckets}
    # Everyone gets one first (largest buckets first if total < #buckets).
    for b in sorted(buckets, key=lambda b: -sizes[b])[:total]:
        q[b] = 1
    left = total - sum(q.values())
    pool_size = sum(sizes[b] for b in buckets)
    # Proportional share of the rest, capped by availability...
    for b in buckets:
        extra = min(sizes[b] - q[b], int(left * sizes[b] / pool_size))
        q[b] += extra
    # ...then hand out any remainder one at a time to buckets with room.
    left = total - sum(q.values())
    while left > 0:
        for b in sorted(buckets, key=lambda b: (q[b] / sizes[b], -sizes[b])):
            if left and q[b] < sizes[b]:
                q[b] += 1
                left -= 1
    return q


def interleave(groups: dict[str, list]) -> list:
    """Mix buckets so no chapter comes out as a block.

    Recursive merge: interleave the smaller buckets first, then drop the
    largest bucket's questions evenly into the len(rest)+1 gaps around them.
    That reaches the best possible longest run, ceil(n / (others + 1)) - a
    greedy round-robin instead runs the small buckets dry early and leaves the
    big chapter as one long block at the end."""
    groups = {b: rows for b, rows in groups.items() if rows}
    if not groups:
        return []
    big = max(groups, key=lambda b: len(groups[b]))
    dominant = groups[big]
    rest = interleave({b: r for b, r in groups.items() if b != big})
    slots = len(rest) + 1
    counts = [0] * slots
    for j in range(len(dominant)):
        counts[j * slots // len(dominant)] += 1
    out, it = [], iter(dominant)
    for s in range(slots):
        out.extend(next(it) for _ in range(counts[s]))
        if s < len(rest):
            out.append(rest[s])
    return out


def _clashes(seq: list, i: int) -> int:
    """How many neighbours of position i are from the same bucket."""
    b = seq[i]["bucket"]
    return sum(1 for j in (i - 1, i + 1) if 0 <= j < len(seq) and seq[j]["bucket"] == b)


def longest_run(seq: list) -> int:
    best = cur = 1 if seq else 0
    for a, b in zip(seq, seq[1:]):
        cur = cur + 1 if a["bucket"] == b["bucket"] else 1
        best = max(best, cur)
    return best


def shake(seq: list, rng: random.Random, passes: int = 4) -> list:
    """Random swaps that add no same-bucket neighbour and never lengthen the
    longest same-chapter run, so the paper stays as mixed as interleave() made
    it but stops reading as a fixed A-B-C-D cycle."""
    seq = list(seq)
    n = len(seq)
    limit = longest_run(seq)
    for _ in range(passes * n):
        i, j = rng.randrange(n), rng.randrange(n)
        if i == j or seq[i]["bucket"] == seq[j]["bucket"]:
            continue
        before = _clashes(seq, i) + _clashes(seq, j)
        seq[i], seq[j] = seq[j], seq[i]
        if (_clashes(seq, i) + _clashes(seq, j) > before
                or longest_run(seq) > limit):
            seq[i], seq[j] = seq[j], seq[i]          # undo
    return seq


def select_mixed(pool: list[dict], max_questions: int, seed: int | None = None) -> list[dict]:
    """Choose up to `max_questions` from `pool`, covering every bucket, mixed."""
    rng = random.Random(seed)
    by_bucket: dict[str, list] = defaultdict(list)
    seen = set()
    for q in pool:
        if q["id"] in seen:
            continue
        seen.add(q["id"])
        by_bucket[q["bucket"]].append(q)
    q = quotas({b: len(v) for b, v in by_bucket.items()}, max_questions)
    picked = {b: _weighted_order(by_bucket[b], rng)[:n] for b, n in q.items()}
    for rows in picked.values():
        rng.shuffle(rows)
    return shake(interleave(picked), rng)
