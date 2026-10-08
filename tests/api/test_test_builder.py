"""Test builder v2: draft / alternatives / build-by-ids / ratings / sharing."""

import pytest

from tests.conftest import ROOT, needs_index_db

pytestmark = [needs_index_db, pytest.mark.skipif(
    not (ROOT / "data" / "raw").exists(), reason="raw PDFs not present")]

# 0625 has MCQ (P2) and theory (P4) for the same chapters.
MIXED = {"syllabus": "0625", "papers": [2, 4], "year_from": 2021, "year_to": 2025,
         "picks": [{"chapter": "Motion"}, {"chapter": "Momentum"}]}
PHYS = {"syllabus": "5054", "papers": [2], "year_from": 2018, "year_to": 2025,
        "picks": [{"chapter": "Motion"}, {"chapter": "Pressure"}]}


@pytest.fixture()
def student(client, new_student):
    u = new_student()
    for s in ("0625", "5054"):
        client.post("/api/enrollments", json={"syllabus": s})
    return u


def make_teacher(client, user):
    import users_db
    users_db.update_profile(user["id"], {"role": "teacher"})
    client.post("/auth/login", json={"email": user["email"], "password": user["password"]})


# ── draft ────────────────────────────────────────────────────────────────────

def test_draft_proposes_cards_with_mcq_first(client, student):
    r = client.post("/api/booklets/draft", json={**MIXED, "max_questions": 10, "seed": 3})
    assert r.status_code == 200, r.text
    d = r.json()
    qs = d["questions"]
    assert len(qs) == 10 and d["has_mcq"]
    kinds = [q["mcq"] for q in qs]
    assert kinds == sorted(kinds, reverse=True)            # MCQ section, then theory
    assert any(kinds) and not all(kinds)
    q = qs[0]
    assert {"id", "ref", "chapter", "marks", "thumb", "difficulty", "snippet"} <= set(q)
    assert q["ref"].startswith("0625/")
    keys = [b["key"] for b in d["buckets"]]
    assert keys == ["Motion", "Momentum"]
    assert all(b["mcq"] + b["theory"] > 0 for b in d["buckets"])
    assert set(d["plan"]) == {"Motion", "Momentum"}


def test_draft_honours_a_per_chapter_mcq_theory_plan(client, student):
    plan = {"Motion": {"mcq": 3, "theory": 1}, "Momentum": {"mcq": 0, "theory": 2}}
    qs = client.post("/api/booklets/draft", json={**MIXED, "plan": plan, "seed": 1}).json()["questions"]
    got = {}
    for q in qs:
        k = (q["bucket"], "mcq" if q["mcq"] else "theory")
        got[k] = got.get(k, 0) + 1
    assert got == {("Motion", "mcq"): 3, ("Motion", "theory"): 1, ("Momentum", "theory"): 2}


def test_draft_keeps_locked_questions(client, student):
    first = client.post("/api/booklets/draft", json={**MIXED, "max_questions": 6, "seed": 1}).json()
    keep = [first["questions"][0]["id"], first["questions"][-1]["id"]]
    again = client.post("/api/booklets/draft",
                        json={**MIXED, "max_questions": 6, "seed": 99, "locked": keep}).json()
    assert set(keep) <= {q["id"] for q in again["questions"]}


def test_draft_mark_target(client, student):
    qs = client.post("/api/booklets/draft",
                     json={**PHYS, "marks_target": 40, "seed": 2}).json()["questions"]
    total = sum(q["marks"] or 0 for q in qs)
    assert 30 <= total <= 40


def test_draft_needs_login(client):
    assert client.post("/api/booklets/draft", json=MIXED).status_code == 401


# ── alternatives ─────────────────────────────────────────────────────────────

def test_alternatives_filter_by_bucket_kind_and_exclude(client, student):
    d = client.post("/api/booklets/draft", json={**MIXED, "max_questions": 4, "seed": 1}).json()
    used = [q["id"] for q in d["questions"]]
    r = client.post("/api/booklets/alternatives", json={
        **MIXED, "bucket": "Motion", "kind": "theory", "exclude": used}).json()
    assert r["total"] > 0 and len(r["questions"]) <= r["per_page"]
    assert all(q["bucket"] == "Motion" and not q["mcq"] and q["id"] not in used
               for q in r["questions"])


def test_alternatives_text_search(client, student):
    r = client.post("/api/booklets/alternatives", json={**PHYS, "q": "speed"}).json()
    assert r["total"] > 0
    none = client.post("/api/booklets/alternatives", json={**PHYS, "q": "zzzqqqxx"}).json()
    assert none["total"] == 0


# ── build by ids ─────────────────────────────────────────────────────────────

def test_build_by_ids_keeps_order_mcq_first(client, student):
    d = client.post("/api/booklets/draft", json={**MIXED, "max_questions": 6, "seed": 5}).json()
    mcq = [q["id"] for q in d["questions"] if q["mcq"]]
    theory = [q["id"] for q in d["questions"] if not q["mcq"]]
    sent = list(reversed(theory)) + list(reversed(mcq))     # theory first, on purpose
    r = client.post("/api/booklets", json={**MIXED, "ids": sent, "kind": "test"})
    assert r.status_code == 200, r.text
    b = client.get(f"/api/booklets/{r.json()['id']}").json()
    import users_db
    row = users_db.get_booklet(r.json()["id"])
    assert row["question_ids"] == list(reversed(mcq)) + list(reversed(theory))
    assert row["params_json"]["reviewed"] is True and "ids" not in row["params_json"]
    assert b["kind"] == "test"


def test_build_rejects_ids_outside_the_selection(client, student):
    other = client.post("/api/booklets/draft", json={**PHYS, "max_questions": 2}).json()
    foreign = [q["id"] for q in other["questions"]]            # 5054 ids, 0625 selection
    r = client.post("/api/booklets", json={**MIXED, "ids": foreign})
    assert r.status_code == 422
    r = client.post("/api/booklets", json={**MIXED, "ids": [999999999]})
    assert r.status_code == 422


# ── thumbnails ───────────────────────────────────────────────────────────────

def test_thumbnail_is_a_png_and_cached(client, student):
    q = client.post("/api/booklets/draft", json={**PHYS, "max_questions": 1}).json()["questions"][0]
    r = client.get(q["thumb"])
    assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert "immutable" in r.headers["cache-control"]
    assert client.get("/api/question/999999999/thumb.png").status_code == 404


# ── ratings ──────────────────────────────────────────────────────────────────

def test_only_teachers_rate_and_students_see_the_median(client, new_student):
    s = new_student()
    client.post("/api/enrollments", json={"syllabus": "5054"})
    qid = client.post("/api/booklets/draft", json={**PHYS, "max_questions": 1}).json()["questions"][0]["id"]
    assert client.put(f"/api/questions/{qid}/rating", json={"difficulty": 3}).status_code == 403

    for diff in (3, 3, 1):
        t = new_student()
        make_teacher(client, t)
        r = client.put(f"/api/questions/{qid}/rating", json={"difficulty": diff})
        assert r.status_code == 200, r.text
        assert r.json()["difficulty"]["mine"] == diff
    # the last teacher (rated 1) sees their own rating first
    one = {**PHYS, "max_questions": 1, "locked": [qid], "plan": {}}
    mine = client.post("/api/booklets/draft", json=one).json()["questions"]
    assert [q["id"] for q in mine] == [qid]
    assert mine[0]["difficulty"] == {"value": 1, "mine": 1, "n": 3}
    assert client.put(f"/api/questions/{qid}/rating", json={"difficulty": 5}).status_code == 422
    assert client.put("/api/questions/999999999/rating", json={"difficulty": 2}).status_code == 404

    client.post("/auth/login", json={"email": s["email"], "password": s["password"]})
    d = client.post("/api/booklets/alternatives",
                    json={**PHYS, "difficulty": ["3"]}).json()
    hit = next(q for q in d["questions"] if q["id"] == qid)       # median of 3,3,1 = hard
    assert hit["difficulty"] == {"value": 3, "mine": None, "n": 3}


def test_difficulty_filter_in_draft(client, new_student):
    t = new_student()
    make_teacher(client, t)
    qs = client.post("/api/booklets/draft", json={**PHYS, "max_questions": 3}).json()["questions"]
    for q in qs:
        client.put(f"/api/questions/{q['id']}/rating", json={"difficulty": 1})
    d = client.post("/api/booklets/draft",
                    json={**PHYS, "max_questions": 10, "difficulty": ["1"]}).json()
    assert {q["id"] for q in d["questions"]} == {q["id"] for q in qs}
    assert d["can_rate"] is True
    for q in qs:                                                      # clear again
        client.put(f"/api/questions/{q['id']}/rating", json={"difficulty": None})


# ── sharing ──────────────────────────────────────────────────────────────────

def login(client, u):
    client.post("/auth/login", json={"email": u["email"], "password": u["password"]})


def wait_ready(client, bid, timeout=180):
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = client.get(f"/api/booklets/{bid}/status").json()
        if st["status"] in ("ready", "failed"):
            return st
        time.sleep(0.5)
    raise AssertionError("booklet never finished")


@pytest.fixture()
def classroom(client, new_student):
    """A teacher with one rostered student (and a group with them), one stranger,
    and a 2-question mock test the teacher built."""
    import users_db
    s1, s2 = new_student(), new_student()
    t = new_student()
    make_teacher(client, t)
    users_db.create_allocation(t["id"], s1["id"], "5054")
    g = users_db.create_group({"name": "Thursday", "teacher_id": t["id"], "syllabus": "5054",
                               "status": "active"})
    users_db.join_group(g["id"], s1["id"])
    qs = client.post("/api/booklets/draft", json={**PHYS, "max_questions": 2, "seed": 4}).json()["questions"]
    r = client.post("/api/booklets", json={**PHYS, "kind": "test", "ids": [q["id"] for q in qs]})
    assert r.status_code == 200, r.text
    bid = r.json()["id"]
    assert wait_ready(client, bid)["status"] == "ready"
    return {"teacher": t, "s1": s1, "s2": s2, "group": g, "bid": bid}


def test_student_cannot_open_a_paper_not_shared_with_them(client, classroom):
    login(client, classroom["s1"])
    assert client.get(f"/api/booklets/{classroom['bid']}").status_code == 404
    assert client.get(f"/api/booklets/{classroom['bid']}/pdf").status_code == 404


def test_assign_to_roster_and_group_only(client, classroom):
    c = classroom
    r = client.post(f"/api/booklets/{c['bid']}/assign", json={"student_ids": [c["s2"]["id"]]})
    assert r.status_code == 403                          # not on this teacher's roster
    r = client.post(f"/api/booklets/{c['bid']}/assign",
                    json={"group_ids": [c["group"]["id"]], "student_ids": [c["s1"]["id"]],
                          "due_date": "2026-11-01"})
    assert r.status_code == 200 and r.json()["assigned"] == 1      # deduped
    sh = client.get(f"/api/booklets/{c['bid']}/shares").json()
    assert [s["student_id"] for s in sh["shares"]] == [c["s1"]["id"]]
    assert {s["id"] for s in sh["students"]} == {c["s1"]["id"]}

    login(client, c["s1"])
    d = client.get(f"/api/booklets/{c['bid']}").json()
    assert d["role"] == "shared" and d["ms_open"] is False and d["can_share"] is False
    assert client.get(f"/api/booklets/{c['bid']}/pdf").status_code == 200
    mine = client.get("/api/booklets").json()
    assert [b["id"] for b in mine["shared"]] == [c["bid"]]
    page = client.get("/my-papers").text
    assert "Shared with me" in page and f"/papers/view/{c['bid']}" in page
    # students can't share or retry someone else's paper
    assert client.post(f"/api/booklets/{c['bid']}/link").status_code == 403
    assert client.post(f"/api/booklets/{c['bid']}/retry").status_code == 404


def test_mark_scheme_opens_after_finish(client, classroom):
    c = classroom
    client.post(f"/api/booklets/{c['bid']}/assign", json={"student_ids": [c["s1"]["id"]]})
    login(client, c["s1"])
    r = client.get(f"/api/booklets/{c['bid']}/pdf?part=ms")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "ms_locked"
    assert client.post(f"/api/booklets/{c['bid']}/finish").json()["ms_open"] is True
    assert client.get(f"/api/booklets/{c['bid']}/pdf?part=ms").status_code == 200


def test_teacher_only_mark_scheme_stays_shut(client, classroom):
    c = classroom
    client.post(f"/api/booklets/{c['bid']}/assign",
                json={"student_ids": [c["s1"]["id"]], "ms_policy": "teacher_only"})
    login(client, c["s1"])
    assert client.post(f"/api/booklets/{c['bid']}/finish").json()["ms_open"] is False
    assert client.get(f"/api/booklets/{c['bid']}/pdf?part=ms").status_code == 403


def test_share_link_join_and_revoke(client, classroom):
    c = classroom
    link = client.post(f"/api/booklets/{c['bid']}/link", json={"ms_policy": "now"}).json()["link"]
    assert client.post(f"/api/booklets/{c['bid']}/link").json()["link"] == link    # stable

    login(client, c["s2"])                                   # not on the roster - links are open
    r = client.get(link, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == f"/papers/view/{c['bid']}"
    assert client.get(f"/api/booklets/{c['bid']}/pdf?part=ms").status_code == 200

    login(client, c["teacher"])
    sh = client.get(f"/api/booklets/{c['bid']}/shares").json()
    assert any(s["student_id"] == c["s2"]["id"] and s["via"] == "link" for s in sh["shares"])
    assert client.delete(f"/api/booklets/{c['bid']}/link").status_code == 200
    login(client, c["s1"])
    assert client.get(link, follow_redirects=False).status_code == 404
    # who already joined keeps it
    login(client, c["s2"])
    assert client.get(f"/api/booklets/{c['bid']}").status_code == 200


def test_link_needs_sign_in(client, classroom):
    link = client.post(f"/api/booklets/{classroom['bid']}/link").json()["link"]
    client.post("/auth/logout")
    client.cookies.clear()
    r = client.get(link, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("/login.html?next=/papers/s/")


def test_opening_a_shared_paper_uses_no_quota_and_is_recorded(client, classroom):
    c = classroom
    client.post(f"/api/booklets/{c['bid']}/assign", json={"student_ids": [c["s1"]["id"]]})
    login(client, c["s1"])
    assert client.get(f"/papers/view/{c['bid']}").status_code == 200
    import users_db
    assert users_db.get_booklet_share(c["bid"], c["s1"]["id"])["opened_at"]
    assert users_db.count_usage_this_month(c["s1"]["id"], "topic_test", None) == 0


def test_preview_and_review(client, student):
    qs = client.post("/api/booklets/draft", json={**MIXED, "max_questions": 6, "seed": 2}).json()["questions"]
    m = next(q for q in qs if q["mcq"])
    t = next(q for q in qs if not q["mcq"])
    rm = client.get(f"/api/question/{m['id']}/review").json()
    assert rm["mcq"] and rm["answer"] in "ABCD" and rm["ms_image"] is None
    rt = client.get(f"/api/question/{t['id']}/review").json()
    assert not rt["mcq"] and rt["ms_image"] and rt["answer"] is None and rt["can_rate"] is False
    img = client.get(rt["image"])
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"
