"""Boards, the subject catalogue, and the server-rendered /papers pages."""

import re

import pytest

from tests.conftest import needs_index_db

pytestmark = needs_index_db


def test_boards_api_lists_every_board_and_subject(client):
    boards = client.get("/api/boards").json()["boards"]
    assert [b["slug"] for b in boards] == ["o-level", "igcse", "a-level"]
    o = next(b for b in boards if b["slug"] == "o-level")
    phys = next(s for s in o["subjects"] if s["code"] == "5054")
    assert phys["url"] == "/papers/o-level/physics-5054"


def test_my_boards_round_trip(client, new_student):
    new_student()
    assert client.get("/api/me/boards").json()["boards"] == []
    r = client.put("/api/me/boards", json={"boards": ["igcse", "o-level", "bogus"], "primary": "igcse"})
    assert r.status_code == 200
    assert r.json() == {"boards": ["igcse", "o-level"], "primary": "igcse"}
    got = client.get("/api/me/boards").json()
    assert got["boards"] == ["o-level", "igcse"] and got["primary"] == "igcse" and got["saved"]


def test_boards_must_not_be_empty(client, new_student):
    new_student()
    assert client.put("/api/me/boards", json={"boards": []}).status_code == 422


def test_boards_inferred_from_enrolments_until_saved(client, new_student):
    new_student()
    client.post("/api/enrollments", json={"syllabus": "9702"})
    got = client.get("/api/me/boards").json()
    assert got["boards"] == ["a-level"] and got["saved"] is False


def test_catalogue_puts_enrolled_first_and_locks_the_rest(client, new_student):
    new_student()
    client.post("/api/enrollments", json={"syllabus": "5070"})
    subs = client.get("/api/catalogue", params={"board": "o-level"}).json()["subjects"]
    assert subs[0]["code"] == "5070" and subs[0]["enrolled"] and not subs[0]["locked"]
    assert all(s["locked"] for s in subs[1:])
    assert subs[0]["questions"] > 0 and subs[0]["chapters"] > 0


def test_catalogue_anonymous_is_all_locked(client):
    subs = client.get("/api/catalogue", params={"board": "igcse"}).json()["subjects"]
    assert subs and all(s["locked"] for s in subs)


# ── HTML pages ────────────────────────────────────────────────────────────────

def _text(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def test_subject_page_is_readable_without_js(client):
    r = client.get("/papers/o-level/physics-5054")
    assert r.status_code == 200
    html = r.text
    assert "<title>Physics 5054 Topical Past Papers" in html
    assert 'rel="canonical" href="https://prepwithtee.com/papers/o-level/physics-5054"' in html
    assert '"@type": "BreadcrumbList"' in html
    # chapter names are in the HTML itself (the SEO value), no question images
    assert "Motion" in _text(html)
    assert "/api/question/" not in html and ".png" not in html.replace("logo.png", "").replace("favicon-32.png", "").replace("apple-touch-icon.png", "")
    assert r.headers["cache-control"].startswith("public")


def test_chapter_page(client):
    r = client.get("/papers/o-level/physics-5054/motion")
    assert r.status_code == 200 and "<h1>Motion</h1>" in r.text


@pytest.mark.parametrize("url", ["/papers/o-level/physics-9999", "/papers/gcse",
                                 "/papers/o-level/physics-5054/not-a-chapter"])
def test_unknown_pages_404(client, url):
    assert client.get(url).status_code == 404


def test_hub_redirects_a_student_with_saved_boards(client, new_student):
    new_student()
    client.put("/api/me/boards", json={"boards": ["a-level"]})
    r = client.get("/papers", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/papers/a-level"


def test_board_page_personalised_and_not_cached(client, new_student):
    new_student()
    client.post("/api/enrollments", json={"syllabus": "0625"})
    r = client.get("/papers/igcse")
    assert r.headers["cache-control"] == "private, no-store"
    html = r.text
    assert html.index("Your subjects") < html.index("All IGCSE subjects")
    assert 'data-enrol="0580"' in html and 'data-enrol="0625"' not in html


def test_board_prompt_flag_for_student_without_boards(client, new_student):
    new_student()
    state = re.search(r'id="cat-state" type="application/json">(.*?)</script>',
                      client.get("/papers/igcse").text).group(1)
    assert '"needsBoards": true' in state


def test_sitemap_lists_catalogue_pages(client):
    xml = client.get("/sitemap.xml").text
    assert "/papers/o-level/physics-5054</loc>" in xml
    assert "/papers/igcse/mathematics-0580/" in xml


@pytest.mark.parametrize("url,where", [
    ("/papers.html", "/papers"),
    ("/papers.html?syllabus=0625&topics=Motion,Forces", "/papers/igcse/physics-0625?pick=Motion#builder"),
    ("/papers.html?syllabus=0625&topic=Motion", "/papers/igcse/physics-0625?pick=Motion#builder"),
    ("/papers.html?s=9618", "/papers/a-level/computer-science-9618#builder"),
    ("/papers.html?syllabus=nope", "/papers"),
    # the old Test Builder now lives in the same builder, as "Mock test"
    ("/papers.html?mode=test", "/papers?mode=test"),
    ("/papers.html?mode=test&syllabus=0625", "/papers/igcse/physics-0625?mode=test#builder"),
    ("/papers.html?key=5054_s23_22&q=3", "/yearly/open?key=5054_s23_22"),
])
def test_legacy_builder_redirects(client, url, where):
    r = client.get(url, follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == where


def test_retired_pages_are_gone(client):
    for page in ("/app.js", "/library.js", "/mcq-solver.js", "/papers-ui.css"):
        assert client.get(page).status_code == 404, page
    for api in ("/api/mcq/questions", "/api/mcq/preview-pdf", "/api/mcq/explain"):
        assert client.post(api, json={}).status_code in (404, 405), api
    assert client.get("/api/library/search?q=x").status_code == 404


def test_mock_test_mode_carries_through_board_pages(client, new_student):
    new_student()
    client.post("/api/enrollments", json={"syllabus": "5054"})
    html = client.get("/papers/o-level?mode=test").text
    assert "mock tests" in html.lower()
    assert 'href="/papers/o-level/physics-5054?mode=test#builder"' in html
    assert 'href="/papers/igcse?mode=test"' in html


def test_builder_tree_groups_chapters_by_paper(client):
    t = client.get("/api/topical/9709/tree").json()
    assert [(g["papers"], g["level"]) for g in t["groups"]] == [([1], "AS"), ([3], "A2"), ([4], "AS"), ([5], "AS")]
    assert t["groups"][0]["title"] == "Pure Mathematics 1"
    as_ = client.get("/api/topical/9702/tree").json()["groups"][0]
    assert as_["papers"] == [1, 2] and as_["title"] == "AS Level content"
    assert client.get("/api/topical/0625/tree").json()["groups"] == []     # one shared syllabus
    assert {c["level"] for c in t["components"]} == {"AS", "A2"}


def test_public_subject_page_lists_chapters_per_paper(client):
    html = client.get("/papers/a-level/mathematics-9709").text
    assert "Paper 3 · Pure Mathematics 3" in html and "cat-level-A2" in html


def test_subject_cards_link_to_the_new_yearly_and_mcq_pages(client, new_student):
    new_student()
    client.post("/api/enrollments", json={"syllabus": "5054"})
    html = client.get("/papers/o-level").text
    assert 'href="/yearly/o-level/physics-5054"' in html
    assert 'href="/mcq/o-level/physics-5054"' in html
    assert "tab=yearly" not in html and "mcq-solver.html" not in html
