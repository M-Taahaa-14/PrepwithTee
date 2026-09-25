"""The web topical builder: validation, access, mixing, the build job and the PDF."""

import time

import fitz
import pytest

from tests.conftest import ROOT, needs_index_db

pytestmark = [needs_index_db, pytest.mark.skipif(
    not (ROOT / "data" / "raw").exists(), reason="raw PDFs not present")]

PHYS = {"syllabus": "5054", "papers": [2], "year_from": 2018, "year_to": 2025,
        "picks": [{"chapter": "Motion"}, {"chapter": "Pressure"}]}


@pytest.fixture()
def enrolled(client, new_student):
    user = new_student()
    client.post("/api/enrollments", json={"syllabus": "5054"})
    return user


def wait_ready(client, bid, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = client.get(f"/api/booklets/{bid}/status").json()
        if st["status"] in ("ready", "failed"):
            return st
        time.sleep(0.5)
    raise AssertionError("booklet never finished")


def test_tree_has_chapters_and_limits(client):
    t = client.get("/api/topical/5054/tree").json()
    assert t["max_chapters"] == 4
    motion = next(c for c in t["chapters"] if c["name"] == "Motion")
    assert motion["count"] > 0 and motion["subtopics"]


def test_needs_login(client):
    assert client.post("/api/booklets", json={**PHYS, "max_questions": 3}).status_code == 401


def test_not_enrolled_is_403_with_a_way_forward(client, new_student):
    new_student()
    r = client.post("/api/booklets", json={**PHYS, "max_questions": 3})
    assert r.status_code == 403
    d = r.json()["detail"]
    assert d["code"] == "not_enrolled" and d["url"] == "/papers/o-level/physics-5054"


def test_more_than_four_chapters_rejected(client, enrolled):
    picks = [{"chapter": c} for c in ("Motion", "Pressure", "Density", "Momentum", "Forces")]
    r = client.post("/api/booklets", json={**PHYS, "picks": picks, "max_questions": 5})
    assert r.status_code == 422


def test_unknown_chapter_or_subtopic_rejected(client, enrolled):
    r = client.post("/api/booklets/count", json={**PHYS, "picks": [{"chapter": "Nope"}]})
    assert r.status_code == 422
    r = client.post("/api/booklets/count",
                    json={**PHYS, "picks": [{"chapter": "Motion", "subtopics": ["Nope"]}]})
    assert r.status_code == 422


def test_count_respects_subtopics(client, enrolled):
    whole = client.post("/api/booklets/count", json=PHYS).json()
    tree = client.get("/api/topical/5054/tree").json()
    sub = next(c for c in tree["chapters"] if c["name"] == "Motion")["subtopics"][0]["name"]
    narrow = client.post("/api/booklets/count", json={
        **PHYS, "picks": [{"chapter": "Motion", "subtopics": [sub]}]}).json()
    assert 0 < narrow["pool"] < whole["pool"]
    assert list(narrow["per_bucket"]) == [f"Motion › {sub}"]


def test_build_mixes_chapters_and_serves_the_pdf(client, enrolled):
    r = client.post("/api/booklets", json={**PHYS, "max_questions": 6, "seed": 11})
    assert r.status_code == 200, r.text
    bid = r.json()["id"]
    assert r.json()["url"] == f"/papers/view/{bid}"
    st = wait_ready(client, bid)
    assert st["status"] == "ready" and st["progress"] == 100

    meta = client.get(f"/api/booklets/{bid}").json()
    qs = meta["page_map_json"]["questions"]
    assert len(qs) == 6
    assert {q["topic"] for q in qs} == {"Motion", "Pressure"}        # both chapters present
    assert any(a["topic"] != b["topic"] for a, b in zip(qs, qs[1:]))  # and mixed

    pdf = client.get(f"/api/booklets/{bid}/pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert pdf.headers["content-disposition"].startswith("inline")
    doc = fitz.open(stream=pdf.content, filetype="pdf")
    assert doc.page_count >= 3 and doc.get_toc()[0][1] == "Contents"

    dl = client.get(f"/api/booklets/{bid}/pdf", params={"download": 1})
    assert dl.headers["content-disposition"].startswith("attachment")

    mine = client.get("/api/booklets").json()["booklets"]
    assert mine[0]["id"] == bid and mine[0]["questions"] == 6


def test_other_students_cannot_see_a_booklet(client, enrolled, new_student):
    bid = client.post("/api/booklets", json={**PHYS, "max_questions": 2}).json()["id"]
    wait_ready(client, bid)
    client.post("/auth/logout")
    new_student()
    assert client.get(f"/api/booklets/{bid}").status_code == 404
    assert client.get(f"/api/booklets/{bid}/pdf").status_code == 404
    assert client.get(f"/papers/view/{bid}").status_code == 404


def test_viewer_page_requires_login_and_is_noindex(client, enrolled):
    bid = client.post("/api/booklets", json={**PHYS, "max_questions": 2}).json()["id"]
    html = client.get(f"/papers/view/{bid}").text
    assert '<meta name="robots" content="noindex">' in html and bid in html
    client.post("/auth/logout")
    r = client.get(f"/papers/view/{bid}", follow_redirects=False)
    assert r.status_code == 302 and "login.html" in r.headers["location"]


def test_mock_test_builds_paper_and_separate_mark_scheme(client, enrolled):
    r = client.post("/api/booklets", json={**PHYS, "max_questions": 3, "kind": "test"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["title"].startswith("Mock test: ")
    st = wait_ready(client, b["id"])
    assert st["status"] == "ready", st
    meta = client.get(f"/api/booklets/{b['id']}").json()
    assert meta["kind"] == "test"
    paper = client.get(f"/api/booklets/{b['id']}/pdf")
    ms = client.get(f"/api/booklets/{b['id']}/pdf?part=ms")
    assert paper.status_code == 200 and ms.status_code == 200
    assert paper.content != ms.content
    assert "mark-scheme" in client.get(f"/api/booklets/{b['id']}/pdf?part=ms&download=1").headers[
        "content-disposition"]
    listed = next(x for x in client.get("/api/booklets").json()["booklets"] if x["id"] == b["id"])
    assert listed["kind"] == "test"
    page = client.get(f"/papers/view/{b['id']}").text
    assert '"kind": "test"' in page


def test_practice_booklet_has_no_separate_mark_scheme(client, enrolled):
    b = client.post("/api/booklets", json={**PHYS, "max_questions": 2}).json()
    assert wait_ready(client, b["id"])["status"] == "ready"
    assert client.get(f"/api/booklets/{b['id']}/pdf?part=ms").status_code == 404
    assert client.get(f"/api/booklets/{b['id']}").json()["kind"] == "booklet"
