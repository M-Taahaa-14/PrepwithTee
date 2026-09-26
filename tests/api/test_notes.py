"""Revision notes pages (P2-d): every note file is a page, chapters come from the
syllabus taxonomy, empty chapters are 'coming soon' + noindex, old URLs 301,
the sitemap lists only real notes, and a dropped-in file shows up by itself."""


import re

import pytest

import notes as nt
from tests.conftest import needs_index_db

pytestmark = needs_index_db


def _all_notes():
    return [(code, ch, n) for code, chs in nt.index().items() for ch, ns in chs.items() for n in ns]


def test_every_note_file_is_under_a_real_taxonomy_chapter(client):
    import catalog
    client.get("/notes")                                  # loads the chapter data
    notes = _all_notes()
    assert len(notes) >= 36
    for code, ch, n in notes:
        assert code in catalog.SUBJECTS, code
        assert ch in {c["slug"] for c in catalog.chapters(code)}, f"{code}/{ch} is not a syllabus chapter"


@pytest.mark.parametrize("i", range(0, 36, 6))
def test_note_pages_render_full_text(client, i):
    code, ch, n = _all_notes()[i]
    r = client.get(nt.notes_url(code, ch, n["slug"]))
    assert r.status_code == 200
    html = r.text
    assert f"<h1>{n['title']}</h1>".replace("'", "&#x27;") in html
    body = n["path"].read_text(encoding="utf-8")
    first_h2 = re.search(r"<h2[^>]*>(.*?)</h2>", body)
    if first_h2:
        assert first_h2.group(1) in html                     # the note text is in the page
    assert '"@type": "Article"' in html and "Practise this chapter" in html


def test_subject_page_lists_chapters_and_notes(client):
    html = client.get("/notes/igcse/physics-0625").text
    assert "Physics 0625 revision notes" in html
    assert 'href="/notes/igcse/physics-0625/forces/hookes-law"' in html
    assert "Coming soon" in html                              # chapters without notes yet
    assert 'href="/papers/igcse/physics-0625?pick=Forces#builder"' in html


def test_a_level_subject_groups_chapters_by_paper(client):
    html = client.get("/notes/a-level/mathematics-9709").text
    assert "Paper 3 · Pure Mathematics 3" in html
    assert 'name="robots" content="noindex"' in html          # no notes yet


def test_empty_chapter_is_coming_soon_and_noindex(client):
    r = client.get("/notes/igcse/physics-0625/light")
    assert r.status_code == 200
    assert "being written" in r.text and 'content="noindex"' in r.text


def test_unknown_pages_404(client):
    assert client.get("/notes/igcse/physics-0625/forces/nope").status_code == 404
    assert client.get("/notes/igcse/physics-0625/not-a-chapter").status_code == 404
    assert client.get("/notes/gcse").status_code == 404


@pytest.mark.parametrize("url,where", [
    ("/note.html?code=0625&ch=forces&st=hookes-law", "/notes/igcse/physics-0625/forces/hookes-law"),
    ("/note.html?code=2058&ch=battles-of-islam&st=battle-of-badr",
     "/notes/o-level/islamiyat-2058/the-life-of-the-prophet-muhammad-pbuh/battle-of-badr"),
    ("/chapter.html?code=0625&ch=physical-quantities", "/notes/igcse/physics-0625/physical-quantities-measurement"),
    ("/subject.html?code=4024", "/notes/o-level/mathematics-4024"),
    ("/note.html?code=nope", "/notes"),
])
def test_old_urls_301(client, url, where):
    r = client.get(url, follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == where


def test_sitemap_lists_only_real_notes(client):
    xml = client.get("/sitemap.xml").text
    assert "/notes/igcse/physics-0625/forces/hookes-law</loc>" in xml
    assert "/notes/igcse/physics-0625/light</loc>" not in xml


def test_a_dropped_in_note_appears_by_itself(client):
    d = nt.NOTES_DIR / "0625" / "sound"
    f = d / "zz-test-echoes.html"
    d.mkdir(exist_ok=True)
    try:
        f.write_text('<!--note {"title": "Echoes and the speed of sound", "order": 1, '
                     '"subtopic": "Echoes"} -->\n<h2 id="echo">Echoes</h2><p>An echo is a reflected sound.</p>',
                     encoding="utf-8")
        assert "Echoes and the speed of sound" in client.get("/notes/igcse/physics-0625/sound").text
        r = client.get("/notes/igcse/physics-0625/sound/zz-test-echoes")
        assert r.status_code == 200 and "An echo is a reflected sound." in r.text
    finally:
        f.unlink(missing_ok=True)
    assert client.get("/notes/igcse/physics-0625/sound/zz-test-echoes").status_code == 404


def test_metadata_is_optional():
    d = nt.NOTES_DIR / "0625" / "sound"
    f = d / "zz-plain.html"
    try:
        f.write_text("<h2 id='a'>A</h2>", encoding="utf-8")
        n = next(x for x in nt.index()["0625"]["sound"] if x["slug"] == "zz-plain")
        assert n["title"] == "Zz plain" and n["subtopic"] is None
    finally:
        f.unlink(missing_ok=True)
