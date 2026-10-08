from collections import Counter

from selection import availability, default_plan, sectioned, select_targeted


def pool(bucket, n, mcq=False, marks=None, year0=2015):
    return [{"id": f"{bucket}{'m' if mcq else 't'}{i}", "bucket": bucket, "mcq": mcq,
             "marks": marks if marks is not None else (1 if mcq else 4),
             "year": year0 + i % 10} for i in range(n)]


QS = pool("A", 30, mcq=True) + pool("A", 10) + pool("B", 5, mcq=True) + pool("B", 8)


def kinds(rows):
    return Counter((q["bucket"], "mcq" if q["mcq"] else "theory") for q in rows)


def test_plan_counts_are_hit_exactly():
    plan = {"A": {"mcq": 6, "theory": 2}, "B": {"mcq": 3, "theory": 4}}
    out = select_targeted(QS, plan, seed=1)
    assert kinds(out) == {("A", "mcq"): 6, ("A", "theory"): 2, ("B", "mcq"): 3, ("B", "theory"): 4}
    assert len({q["id"] for q in out}) == len(out)


def test_plan_never_exceeds_what_is_available():
    out = select_targeted(QS, {"B": {"mcq": 50, "theory": 50}}, seed=2)
    assert kinds(out) == {("B", "mcq"): 5, ("B", "theory"): 8}


def test_locked_questions_are_kept_and_count_towards_their_share():
    locked = ["Am3", "At7"]
    out = select_targeted(QS, {"A": {"mcq": 2, "theory": 1}}, seed=3, locked=locked)
    ids = [q["id"] for q in out]
    assert set(locked) <= set(ids)
    assert kinds(out) == {("A", "mcq"): 2, ("A", "theory"): 1}


def test_locked_ids_not_in_pool_are_ignored():
    out = select_targeted(QS, {"A": {"mcq": 1, "theory": 0}}, seed=3, locked=["nope"])
    assert len(out) == 1


def test_marks_target_is_reached_without_overshooting():
    out = select_targeted(QS, None, marks_target=30, seed=4)
    assert sum(q["marks"] for q in out) == 30
    assert {q["bucket"] for q in out} == {"A", "B"}


def test_marks_target_respects_plan_caps():
    out = select_targeted(QS, {"A": {"mcq": 0, "theory": 3}}, marks_target=40, seed=5)
    assert kinds(out) == {("A", "theory"): 3}


def test_default_plan_covers_every_bucket_and_splits_by_kind():
    plan = default_plan(QS, 20)
    assert sum(v["mcq"] + v["theory"] for v in plan.values()) == 20
    assert all(v["mcq"] and v["theory"] for v in plan.values())
    a = availability(QS)
    assert a["A"] == {"mcq": 30, "theory": 10, "mcq_marks": 30, "theory_marks": 40}


def test_no_plan_means_total_questions():
    assert len(select_targeted(QS, None, total=12, seed=6)) == 12


def test_sectioned_puts_mcq_first_and_keeps_order():
    rows = [{"id": 1, "mcq": False}, {"id": 2, "mcq": True}, {"id": 3, "mcq": False},
            {"id": 4, "mcq": True}]
    assert [q["id"] for q in sectioned(rows)] == [2, 4, 1, 3]
