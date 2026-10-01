"""Search boxes (feedback 2026-09-30).

- Typing into the topical builder's search is not scrambled: the box used to be
  rebuilt on every keystroke with the caret at the start ("c" + "ircles" came
  out "irclesc").
- A search on a Resources / Notes page covers every folder and file BELOW the
  page you are on - and nothing outside it.
"""

import re
import sys
from pathlib import Path

from playwright.sync_api import expect

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "website")]
import resources  # noqa: E402


def _deep_file(code="0580"):
    """(top folder slug, second-level folder, a file inside it) for a subject."""
    tree = resources.index()["subjects"][code]
    for top in tree["dirs"]:
        for sub in top["dirs"]:
            if sub["files"]:
                return top, sub, sub["files"][0]
    raise AssertionError("no nested resource files to test with")


def test_builder_search_keeps_the_caret(student):
    student.request.post("/api/enrollments", data={"syllabus": "0625"})
    page = student.new_page()
    page.goto("/papers/igcse/physics-0625")
    box = page.locator("#bld-filter")
    expect(box).to_be_visible()
    box.click()
    page.keyboard.type("circles", delay=180)          # slower than the 120 ms re-render
    expect(page.locator("#bld-filter")).to_have_value("circles")
    page.keyboard.press("Home")
    page.keyboard.type("x")
    expect(page.locator("#bld-filter")).to_have_value("xcircles")


def test_resources_search_covers_subfolders_only(student, shots):
    top, sub, f = _deep_file()
    page = student.new_page()
    page.goto(resources.subject_url("0580"))
    q = page.locator("[data-ps-q]")
    q.fill(f["title"])
    results = page.locator(".ps-results")
    expect(results).to_be_visible()
    hit = results.locator("li:not([hidden])", has_text=f["title"]).first
    expect(hit).to_be_visible()
    expect(hit.locator("small")).to_contain_text(sub["title"])      # where it lives
    expect(page.locator("[data-ps-browse]")).to_be_hidden()
    expect(page).to_have_url(re.compile(r"[?&]q="))                  # Back returns to the results
    page.screenshot(path=str(shots / "resources-search.png"))

    # inside a sibling folder, that file is out of scope
    other = next(d for d in resources.index()["subjects"]["0580"]["dirs"] if d["slug"] != top["slug"]
                 and all(x["title"] != f["title"] for x in resources._all_files(d)))
    page.goto(f'{resources.subject_url("0580")}/{other["slug"]}')
    page.locator("[data-ps-q]").fill(f["title"])
    expect(page.locator(".ps-results")).to_be_visible()
    expect(page.locator(".ps-results li:not([hidden])", has_text=f["title"])).to_have_count(0)
    expect(page.locator(".ps-empty")).to_be_visible()

    # clearing the box brings the folder view back
    page.locator("[data-ps-q]").fill("")
    expect(page.locator("[data-ps-browse]")).to_be_visible()
    expect(page.locator(".ps-results")).to_be_hidden()


def test_notes_search_finds_notes_inside_chapters(student):
    import notes
    code = next(c for c, chs in notes.index().items() if any(chs.values()))
    ch, lst = next((k, v) for k, v in notes.index()[code].items() if v)
    page = student.new_page()
    page.goto(notes.notes_url(code))
    page.locator("[data-ps-q]").fill(lst[0]["title"])
    hit = page.locator(".ps-results li:not([hidden])", has_text=lst[0]["title"]).first
    expect(hit).to_be_visible()
    expect(hit.locator(".ps-kind")).to_have_text("Note")
