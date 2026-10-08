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


# Within a year, the later sitting first: Oct/Nov, then May/June, then Feb/March.
_SESSION_RANK = {"w": 0, "s": 1, "m": 2}


def order_recent_first(rows: list[dict]) -> list[dict]:
    """The booklet's reading order: newest paper first (2025, 2024, ...), and
    within one sitting the questions in paper order (tutor, 2026-09-27 -
    replaces the shuffled order). Rows without paper details keep their place
    after the dated ones."""
    def key(q):
        return (-(q.get("year") or 0), _SESSION_RANK.get(q.get("session") or "", 9),
                q.get("paper") or 0, str(q.get("variant") or ""), q.get("number") or 0,
                str(q.get("sub_part") or ""))
    return sorted(rows, key=key)



# ── Targeted drafts (the "Review & customise" step) ──────────────────────────

def kind_of(q: dict) -> str:
    return "mcq" if q.get("mcq") else "theory"


def availability(pool: list[dict]) -> dict[str, dict]:
    """{bucket: {"mcq": n, "theory": n, "mcq_marks": m, "theory_marks": m}}."""
    out: dict[str, dict] = {}
    for q in pool:
        a = out.setdefault(q["bucket"], {"mcq": 0, "theory": 0, "mcq_marks": 0, "theory_marks": 0})
        k = kind_of(q)
        a[k] += 1
        a[f"{k}_marks"] += q.get("marks") or 0
    return out


def default_plan(pool: list[dict], total: int) -> dict[str, dict]:
    """Split `total` the way select_mixed would (every bucket gets one), then
    each bucket's share between MCQ and theory in proportion to what it has."""
    avail = availability(pool)
    per = quotas({b: a["mcq"] + a["theory"] for b, a in avail.items()}, total)
    plan = {}
    for b, n in per.items():
        a = avail[b]
        mcq = round(n * a["mcq"] / max(1, a["mcq"] + a["theory"]))
        mcq = min(mcq, a["mcq"])
        theory = min(n - mcq, a["theory"])
        mcq = min(a["mcq"], n - theory)
        plan[b] = {"mcq": mcq, "theory": theory}
    return plan


def select_targeted(pool: list[dict], plan: dict[str, dict] | None = None,
                    marks_target: int | None = None, total: int = 20,
                    seed: int | None = None, locked: list | tuple = ()) -> list[dict]:
    """Pick questions to a per-bucket MCQ / theory plan.

    `locked` ids are always kept and count towards their own bucket's share.
    With `marks_target` the plan is only a cap per bucket/kind: questions are
    added round-robin across buckets until the marks are reached (never going
    over when a smaller question still fits). Without a plan the split is
    default_plan(pool, total). Returns rows in no particular order - the caller
    orders them (sectioned + order_recent_first)."""
    rng = random.Random(seed)
    seen, rows = set(), []
    for q in pool:
        if q["id"] not in seen:
            seen.add(q["id"])
            rows.append(q)
    by_id = {q["id"]: q for q in rows}
    keep = [by_id[i] for i in dict.fromkeys(locked) if i in by_id]
    if plan is None:
        plan = default_plan(rows, total if marks_target is None else len(rows))
    groups: dict[tuple, list] = defaultdict(list)
    kept_ids = {q["id"] for q in keep}
    for q in rows:
        if q["id"] not in kept_ids:
            groups[(q["bucket"], kind_of(q))].append(q)
    for k in groups:
        groups[k] = _weighted_order(groups[k], rng)
    used = defaultdict(int)
    for q in keep:
        used[(q["bucket"], kind_of(q))] += 1

    def cap(key):
        return max(0, int((plan.get(key[0]) or {}).get(key[1]) or 0))

    chosen = list(keep)
    if marks_target is None:
        for key, cands in groups.items():
            chosen.extend(cands[:max(0, cap(key) - used[key])])
        return chosen

    marks = sum(q.get("marks") or 0 for q in chosen)
    keys = [k for k in groups if cap(k) > used[k]]
    rng.shuffle(keys)
    while marks < marks_target and keys:
        nxt = []
        for key in keys:
            if marks >= marks_target:
                break
            cands, room = groups[key], marks_target - marks
            fit = next((i for i, q in enumerate(cands) if (q.get("marks") or 0) <= room), None)
            if fit is None:
                continue
            q = cands.pop(fit)
            chosen.append(q)
            marks += q.get("marks") or 0
            used[key] += 1
            if cands and used[key] < cap(key):
                nxt.append(key)
        keys = nxt
    return chosen


def sectioned(rows: list[dict]) -> list[dict]:
    """Section A (multiple choice) before Section B (structured); each section
    keeps the order it was given."""
    return [q for q in rows if q.get("mcq")] + [q for q in rows if not q.get("mcq")]
