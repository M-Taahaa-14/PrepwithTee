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


def test_retention_keeps_an_old_paper_as_a_record_only(client, enrolled):
    import os
    import booklets as bk
    b = client.post("/api/booklets", json={**PHYS, "max_questions": 3}).json()
    assert wait_ready(client, b["id"])["status"] == "ready"
    pdf = bk.BOOKLET_DIR / f"{b['id']}.pdf"
    assert pdf.exists() and not list(bk.BOOKLET_DIR.glob(f"{b['id']}.tmp-*"))

    # opening it refreshes "last opened"
    old = pdf.stat().st_mtime - 40 * 86400
    os.utime(pdf, (old, old))
    assert client.get(f"/api/booklets/{b['id']}/pdf").status_code == 200
    assert pdf.stat().st_mtime > old + 39 * 86400

    # not opened for 40 days: swept (a fresh file is left alone)
    os.utime(pdf, (old, old))
    assert bk.sweep() >= 1 and not pdf.exists()
    assert bk.sweep() == 0

    # tutor, 2026-09-27: older than the window = a record, never rebuilt
    assert client.get(f"/api/booklets/{b['id']}/status").json()["status"] == "expired"
    assert client.get(f"/api/booklets/{b['id']}/pdf").status_code == 410
    assert not pdf.exists()
    page = client.get(f"/papers/view/{b['id']}").text
    assert "Record only" in page and "Build it again" in page and "vw-state" not in page
    listed = client.get("/api/booklets").json()["booklets"]
    assert next(x for x in listed if x["id"] == b["id"])["available"] is False
    mine = client.get("/my-papers").text
    assert "kept as a record" in mine and "pick=Motion" in mine and "pick=Pressure" in mine


def test_my_papers_lists_builds_and_annotated_download(client, enrolled):
    b = client.post("/api/booklets", json={**PHYS, "max_questions": 2}).json()
    assert wait_ready(client, b["id"])["status"] == "ready"
    html = client.get("/my-papers").text
    assert f'href="/papers/view/{b["id"]}"' in html and "With my annotations" not in html
    assert 'name="robots" content="noindex"' in html
    # no ink yet: the annotated download is just the PDF
    r = client.get(f"/api/booklets/{b['id']}/pdf?annotated=1")
    assert r.status_code == 200 and r.headers["content-disposition"].startswith("attachment")
    ink = [{"t": "pen", "c": "@red", "w": 0.004, "pts": [[0.1, 0.1, 0.5], [0.4, 0.3, 0.5]]},
           {"t": "text", "c": "#123456", "s": 0.02, "x": 0.2, "y": 0.5, "txt": "my working"},
           {"t": "arrow", "c": "@blue", "w": 0.004, "a": [0.5, 0.5], "b": [0.7, 0.6]}]
    assert client.put("/api/annotations", json={"doc": f"booklet:{b['id']}", "page": 2,
                                                 "strokes": ink}).status_code == 200
    assert "With my annotations" in client.get("/my-papers").text
    r = client.get(f"/api/booklets/{b['id']}/pdf?annotated=1")
    assert r.status_code == 200 and "annotated" in r.headers["content-disposition"]
    doc = fitz.open(stream=r.content, filetype="pdf")
    assert "my working" in doc[1].get_text()
    assert len(doc[1].get_drawings()) > len(fitz.open(
        stream=client.get(f"/api/booklets/{b['id']}/pdf").content, filetype="pdf")[1].get_drawings())


def test_mock_test_mark_scheme_annotations_are_accepted(client, enrolled):
    r = client.put("/api/annotations", json={"doc": "booklet:abcdef12:ms", "page": 1, "strokes": []})
    assert r.status_code == 200
