"""Yearly papers + MCQ practice pages (P1-d): SEO listings, the paper viewer's
gates and page map, and the 301s from the old tab URLs."""

import json
import os
import re
import sqlite3

import pytest

from tests.conftest import needs_index_db

pytestmark = needs_index_db


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def _paper(year=2016, syllabus="5054", paper=2, kind="qp"):
    con = sqlite3.connect(os.environ["INDEX_DB_PATH"])
    con.row_factory = sqlite3.Row
    r = con.execute("SELECT * FROM papers WHERE syllabus=? AND year=? AND paper=? AND kind=? "
                    "ORDER BY session, variant LIMIT 1", (syllabus, year, paper, kind)).fetchone()
    con.close()
    return dict(r)


def _viewer_state(html: str) -> dict:
    return json.loads(re.search(r'id="vw-state" type="application/json">(.*?)</script>',
                                html, re.S).group(1))


# ── listings ─────────────────────────────────────────────────────────────────

def test_hub_lists_boards_and_subjects(client):
    r = client.get("/yearly")
    assert r.status_code == 200
    assert 'href="/yearly/o-level/physics-5054"' in r.text
    assert 'href="/yearly/igcse/mathematics-0580"' in r.text


def test_subject_page_lists_every_sitting_as_text(client):
    r = client.get("/yearly/o-level/physics-5054")
    assert r.status_code == 200 and r.headers["cache-control"].startswith("public")
    html = r.text
    assert "<title>Physics 5054 Past Papers by Year" in html
    assert 'rel="canonical" href="https://prepwithtee.com/yearly/o-level/physics-5054"' in html
    text = _text(html)
    assert "M/J 2016" in text and "O/N 2016" in text
    p = _paper()
    assert f'href="/yearly/view/{p["id"]}"' in html
    assert f'href="/yearly/view/{p["id"]}?doc=ms"' in html
    # newest year first
    years = [int(y) for y in re.findall(r'<details class="yr-year" id="y(\d{4})"', html)]
    assert years == sorted(years, reverse=True) and 2016 in years


def test_year_grid_has_a_row_per_paper_and_a_column_per_session(client):
    html = client.get("/yearly/a-level/mathematics-9709/2024").text
    rows = re.findall(r'<div class="yr-mrow" data-comp="(\d)">', html)
    assert rows == ["1", "3", "4", "5"]
    assert "Pure Mathematics 3" in html and "yr-level-A2" in html
    assert re.findall(r'<div class="yr-mh" data-sess="(\w)">', html) == ["m", "s", "w"]
    # filter chips for every component and session
    assert 'data-comp="5" aria-pressed="false"' in html and 'data-sess="w" aria-pressed="false"' in html


def test_open_resolves_a_sitting_to_its_viewer(client):
    p = _paper()
    q = (f"syllabus=5054&year=2016&session={p['session']}&paper=2&variant={p['variant'] or ''}")
    r = client.get(f"/yearly/open?{q}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == f"/yearly/view/{p['id']}"
    key = f"5054_{p['session']}16_2{p['variant'] or ''}"
    r = client.get(f"/yearly/open?key={key}", follow_redirects=False)
    assert r.headers["location"] == f"/yearly/view/{p['id']}"
    r = client.get("/yearly/open?syllabus=5054&year=2016", follow_redirects=False)
    assert r.headers["location"] == "/yearly/o-level/physics-5054/2016"
    assert client.get("/yearly/open?key=junk", follow_redirects=False).headers["location"] == "/yearly"


def test_year_page_only_that_year(client):
    html = client.get("/yearly/o-level/physics-5054/2016").text
    assert set(re.findall(r'id="y(\d{4})"', html)) == {"2016"}
    assert 'href="/yearly/o-level/physics-5054/2015"' in html     # older neighbour


@pytest.mark.parametrize("url", ["/yearly/gcse", "/yearly/o-level/physics-9999",
                                 "/yearly/o-level/physics-5054/1999", "/yearly/view/99999999",
                                 "/mcq/o-level/mathematics-4024"])
def test_unknown_pages_404(client, url):
    assert client.get(url).status_code == 404


def test_mcq_pages(client):
    hub = client.get("/mcq").text
    assert 'href="/mcq/o-level/physics-5054"' in hub
    assert "/mcq/o-level/mathematics-4024" not in hub            # no MCQ papers
    r = client.get("/mcq/o-level/physics-5054")
    assert r.status_code == 200 and "Physics 5054 MCQ practice" in r.text
    assert "Create a free account to practise" in r.text          # signed out


def test_mcq_page_start_button_for_enrolled_student(client, new_student):
    new_student()
    client.post("/api/enrollments", json={"syllabus": "5054"})
    html = client.get("/mcq/o-level/physics-5054").text
    assert 'id="mq-setup" data-syllabus="5054"' in html and "/mcq-setup.js?v=" in html
    assert "mcq-solver.html" not in html


# ── viewer ───────────────────────────────────────────────────────────────────

def test_viewer_opens_for_guests(client):
    """Tutor, 2026-09-27: yearly papers need no account and no enrolment."""
    p = _paper()
    r = client.get(f"/yearly/view/{p['id']}?doc=ms", follow_redirects=False)
    assert r.status_code == 200 and "vw-state" in r.text
    assert 'name="robots" content="noindex"' in r.text
    s = _viewer_state(r.text)
    assert s["signedIn"] is False and s["doc"] == "ms" and s["loginUrl"].startswith("/login.html")
    assert client.get(s["files"]["qp"]["url"]).status_code == 200      # the PDF itself is public


def test_viewer_opens_without_enrolling(client, new_student):
    new_student()
    r = client.get(f"/yearly/view/{_paper()['id']}")
    assert r.status_code == 200 and 'data-enrol="5054"' not in r.text and "vw-state" in r.text
    assert _viewer_state(r.text)["signedIn"] is True


def test_viewer_pairs_the_sitting_and_maps_questions(client, new_student):
    new_student()
    client.post("/api/enrollments", json={"syllabus": "5054"})
    p = _paper()
    r = client.get(f"/yearly/view/{p['id']}")
    assert r.status_code == 200 and r.headers["cache-control"] == "private, no-store"
    s = _viewer_state(r.text)
    assert s["files"]["qp"]["id"] == p["id"] and "ms" in s["files"]
    assert s["files"]["ms"]["url"].startswith("/api/library/pdf/")
    qs = s["questions"]
    assert qs and qs[0]["label"] == "Q1" and qs[0]["page"] >= 2      # page 1 is the cover
    assert [q["seq"] for q in qs] == list(range(1, len(qs) + 1))
    assert qs[0]["ref"].startswith(f"5054/{p['paper']}{p['variant']}/")
    assert s["totalMarks"] > 0


def test_viewer_knows_where_mark_scheme_answers_start(client, new_student):
    new_student()
    client.post("/api/enrollments", json={"syllabus": "5054"})
    s = _viewer_state(client.get(f"/yearly/view/{_paper(year=2019)['id']}").text)
    assert s["msAt"] and all(v["page"] >= 1 for v in s["msAt"].values())


def test_opening_the_mark_scheme_link_opens_the_same_sitting(client, new_student):
    new_student()
    client.post("/api/enrollments", json={"syllabus": "5054"})
    ms = _paper(kind="ms")
    s = _viewer_state(client.get(f"/yearly/view/{ms['id']}?doc=ms").text)
    assert s["doc"] == "ms" and s["files"]["ms"]["id"] == ms["id"] and "qp" in s["files"]


def test_approved_teachers_do_not_need_to_enrol(client, new_student):
    import users_db
    u = new_student()
    users_db.update_profile(u["id"], {"role": "teacher"})
    client.post("/auth/login", json={"email": u["email"], "password": u["password"]})
    r = client.get(f"/yearly/view/{_paper()['id']}")
    assert 'data-enrol="5054"' not in r.text and "vw-state" in r.text


# ── old URLs + sitemap ───────────────────────────────────────────────────────

@pytest.mark.parametrize("url,where", [
    ("/papers.html?tab=yearly", "/yearly"),
    ("/papers.html?tab=yearly&syllabus=0625", "/yearly/igcse/physics-0625"),
    ("/papers.html?tab=mcq", "/mcq"),
    ("/papers.html?tab=mcq&syllabus=9702", "/mcq/a-level/physics-9702"),
    ("/papers.html?tab=mcq&syllabus=4024", "/mcq"),
    ("/library.html", "/yearly"),
    ("/library.html?syllabus=5070", "/yearly/o-level/chemistry-5070"),
    ("/papers.html?tab=yearly&syllabus=0625&year=2023&session=s&paper=4&variant=2",
     "/yearly/open?syllabus=0625&year=2023&session=s&paper=4&variant=2"),
])
def test_old_urls_301(client, url, where):
    r = client.get(url, follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == where


def test_sitemap_has_yearly_and_mcq_pages(client):
    xml = client.get("/sitemap.xml").text
    assert "/yearly/o-level/physics-5054</loc>" in xml
    assert "/yearly/o-level/physics-5054/2016</loc>" in xml
    assert "/mcq/igcse/chemistry-0620</loc>" in xml
    assert "/yearly/view/" not in xml
