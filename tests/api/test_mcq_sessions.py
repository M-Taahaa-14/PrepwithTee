"""MCQ practice sessions (P1-e): start, answer, live check, submit + scoring,
paper progress, and the annotation store."""

import os
import sqlite3

import pytest

from tests.conftest import needs_index_db

pytestmark = needs_index_db


def _db():
    con = sqlite3.connect(os.environ["INDEX_DB_PATH"])
    con.row_factory = sqlite3.Row
    return con


def _mcq_paper(year=2016, syllabus="5054"):
    """A 5054 P1 question paper whose mark scheme has answer letters."""
    con = _db()
    r = con.execute(
        """SELECT p.* FROM papers p WHERE p.syllabus=? AND p.year=? AND p.paper=1 AND p.kind='qp'
             AND EXISTS (SELECT 1 FROM papers pm JOIN ms_entries m ON m.paper_id=pm.id
                         WHERE pm.syllabus=p.syllabus AND pm.year=p.year AND pm.session=p.session
                           AND pm.paper=p.paper AND pm.variant=p.variant AND pm.kind='ms'
                           AND m.answer IS NOT NULL)
           ORDER BY p.session, p.variant LIMIT 1""", (syllabus, year)).fetchone()
    con.close()
    return dict(r)


def _keys(paper_id):
    con = _db()
    rows = con.execute(
        """SELECT q.id, m.answer FROM questions q JOIN papers p ON p.id=q.paper_id
           JOIN papers pm ON pm.syllabus=p.syllabus AND pm.year=p.year AND pm.session=p.session
                         AND pm.paper=p.paper AND pm.variant=p.variant AND pm.kind='ms'
           JOIN ms_entries m ON m.paper_id=pm.id AND m.question_number=q.number AND m.sub_part=q.sub_part
           WHERE q.paper_id=?""", (paper_id,)).fetchall()
    con.close()
    return {r["id"]: r["answer"] for r in rows if r["answer"]}


def _enrolled(client, new_student, syllabus="5054"):
    new_student()
    client.post("/api/enrollments", json={"syllabus": syllabus})


def _start(client, **kw):
    r = client.post("/api/mcq/sessions", json={"syllabus": "5054", **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_topics_lists_chapters_with_mcq_counts(client):
    d = client.get("/api/mcq/topics", params={"syllabus": "5054"}).json()
    assert d["papers"] == [1] and d["topics"] and all(t["count"] > 0 for t in d["topics"])
    assert client.get("/api/mcq/topics", params={"syllabus": "4024"}).status_code == 404


def test_needs_login_and_enrolment(client, new_student):
    assert client.post("/api/mcq/sessions", json={"syllabus": "5054", "paper_id": 1}).status_code == 401
    new_student()
    p = _mcq_paper()
    r = client.post("/api/mcq/sessions", json={"syllabus": "5054", "paper_id": p["id"]})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "not_enrolled"


def test_full_paper_session_hides_keys_then_marks_on_submit(client, new_student):
    _enrolled(client, new_student)
    p = _mcq_paper()
    s = _start(client, paper_id=p["id"], mode="single")
    assert s["url"] == f"/mcq/session/{s['id']}" and s["title"].endswith(" 2016")
    d = client.get(f"/api/mcq/sessions/{s['id']}").json()
    assert d["kind"] == "paper" and d["time_limit_s"] == 60 * 60 and d["settings"]["mode"] == "single"
    assert d["pdf_url"] == f"/api/library/pdf/{p['id']}"
    qs = d["questions"]
    assert len(qs) >= 30 and all("key" not in q for q in qs)           # no key before submit
    assert qs[0]["page"] >= 2 and qs[0]["label"] == "Q1"

    keys = _keys(p["id"])
    right = [q for q in qs if q["qid"] in keys][:3]
    wrong = [q for q in qs if q["qid"] in keys][3]
    for q in right:
        assert client.put(f"/api/mcq/sessions/{s['id']}/answer",
                          json={"qid": q["qid"], "answer": keys[q["qid"]], "time_s": 40}).json()["ok"]
    bad = next(x for x in "ABCD" if x != keys[wrong["qid"]])
    client.put(f"/api/mcq/sessions/{s['id']}/answer", json={"qid": wrong["qid"], "answer": bad})
    client.put(f"/api/mcq/sessions/{s['id']}/answer",
               json={"qid": wrong["qid"], "flagged": True, "only_flag": True})
    # no live check: nothing revealed on answer
    mid = client.get(f"/api/mcq/sessions/{s['id']}").json()["questions"]
    assert all("key" not in q for q in mid)
    assert next(q for q in mid if q["qid"] == wrong["qid"])["flagged"] is True
    assert next(q for q in mid if q["qid"] == wrong["qid"])["answer"] == bad   # flag kept the answer

    done = client.post(f"/api/mcq/sessions/{s['id']}/submit").json()
    assert done["status"] == "submitted" and done["score"] == 3
    assert done["total"] == len(keys)
    assert done["review"]["right"] == 3 and done["review"]["wrong"] == 1
    assert all(q.get("key") for q in done["questions"] if q["has_key"])
    # answering after submit is refused; submitting twice is harmless
    assert client.put(f"/api/mcq/sessions/{s['id']}/answer",
                      json={"qid": right[0]["qid"], "answer": "A"}).status_code == 409
    assert client.post(f"/api/mcq/sessions/{s['id']}/submit").json()["score"] == 3
    # the paper is recorded as done, with the score
    prog = client.get("/api/papers-progress", params={"syllabus": "5054"}).json()["papers"]
    row = next(r for r in prog if r["year"] == p["year"] and r["session"] == p["session"]
               and int(r["paper"]) == 1 and str(r["variant"]) == str(p["variant"]))
    assert row["status"] == "confident" and row["score"] == 3 and row["max_score"] == len(keys)


def test_live_check_reveals_one_key_and_locks_it(client, new_student):
    _enrolled(client, new_student)
    p = _mcq_paper()
    s = _start(client, paper_id=p["id"], live_check=True, timer="none")
    d = client.get(f"/api/mcq/sessions/{s['id']}").json()
    assert d["time_limit_s"] is None
    keys = _keys(p["id"])
    q = next(q for q in d["questions"] if q["qid"] in keys)
    bad = next(x for x in "ABCD" if x != keys[q["qid"]])
    r = client.put(f"/api/mcq/sessions/{s['id']}/answer", json={"qid": q["qid"], "answer": bad}).json()
    assert r["correct"] is False and r["key"] == keys[q["qid"]]
    again = client.put(f"/api/mcq/sessions/{s['id']}/answer",
                       json={"qid": q["qid"], "answer": keys[q["qid"]]})
    assert again.status_code == 409                                   # no second guess
    after = client.get(f"/api/mcq/sessions/{s['id']}").json()["questions"]
    shown = [x for x in after if "key" in x]
    assert [x["qid"] for x in shown] == [q["qid"]]                    # only that one revealed


def test_topical_session_mixes_chapters_and_uses_exam_pace(client, new_student):
    _enrolled(client, new_student)
    topics = [t["name"] for t in client.get("/api/mcq/topics", params={"syllabus": "5054"}).json()["topics"][:2]]
    s = _start(client, topics=topics, count=12, seed=3)
    d = client.get(f"/api/mcq/sessions/{s['id']}").json()
    assert d["kind"] == "topical" and len(d["questions"]) == 12
    assert {q["topic"] for q in d["questions"]} == set(topics)
    assert all(q["has_key"] for q in d["questions"])                  # only markable ones
    assert d["time_limit_s"] == 12 * 90                               # 60 min / 40 questions
    assert "pdf_url" not in d


@pytest.mark.parametrize("body,code", [
    ({"topics": []}, 422), ({"topics": ["Not a chapter"]}, 422),
    ({"mode": "scroll", "topics": ["x"]}, 422), ({"paper_id": 99999999}, 404)])
def test_bad_starts(client, new_student, body, code):
    _enrolled(client, new_student)
    assert client.post("/api/mcq/sessions", json={"syllabus": "5054", **body}).status_code == code


def test_sessions_are_private_and_listed(client, new_student):
    _enrolled(client, new_student)
    s = _start(client, paper_id=_mcq_paper()["id"])
    assert client.put(f"/api/mcq/sessions/{s['id']}/clock", json={"elapsed_s": 75, "mode": "single"}).json()["ok"]
    listed = client.get("/api/mcq/sessions", params={"syllabus": "5054"}).json()["sessions"]
    assert listed[0]["id"] == s["id"] and listed[0]["mode"] == "single"
    assert client.get(f"/api/mcq/sessions/{s['id']}").json()["elapsed_s"] == 75
    page = client.get(f"/mcq/session/{s['id']}")
    assert page.status_code == 200 and 'content="noindex"' in page.text
    new_student()                                                     # someone else
    assert client.get(f"/api/mcq/sessions/{s['id']}").status_code == 404
    assert client.get(f"/mcq/session/{s['id']}").status_code == 404


def test_old_solver_url_redirects(client):
    r = client.get("/mcq-solver.html?syllabus=0625", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "/mcq/igcse/physics-0625"


def test_crop_pdf_served(client):
    p = _mcq_paper()
    qid = next(iter(_keys(p["id"])))
    r = client.get(f"/api/question/{qid}/crop.pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"


def test_annotations_round_trip(client, new_student):
    new_student()
    doc = "paper:123"
    stroke = {"tool": "pen", "c": "#1d4ed8", "w": 0.004, "pts": [[0.1, 0.2], [0.3, 0.4]]}
    assert client.put("/api/annotations", json={"doc": doc, "page": 2, "strokes": [stroke]}).json()["ok"]
    got = client.get("/api/annotations", params={"doc": doc}).json()
    assert got["pages"] == {"2": [stroke]}
    client.put("/api/annotations", json={"doc": doc, "page": 2, "strokes": []})      # cleared
    assert client.get("/api/annotations", params={"doc": doc}).json()["pages"] == {}
    assert client.get("/api/annotations", params={"doc": "../etc"}).status_code == 400
    new_student()
    assert client.get("/api/annotations", params={"doc": doc}).json()["pages"] == {}  # private
