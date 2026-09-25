"""Yearly papers: listing -> viewer, QP <-> MS switch, side by side with the
mark scheme following the question, marks + thresholds, done tick on the list."""

import re
import sqlite3

from playwright.sync_api import expect

from tests.conftest import INDEX_DB


def _paper_id(year):
    con = sqlite3.connect(INDEX_DB)
    pid = con.execute("SELECT id FROM papers WHERE syllabus='5054' AND year=? AND session='s' "
                      "AND paper=2 AND variant='1' AND kind='qp'", (year,)).fetchone()[0]
    con.close()
    return pid


def test_open_2016_paper_and_switch_to_mark_scheme(student, shots):
    student.request.post("/api/enrollments", data={"syllabus": "5054"})
    page = student.new_page()
    page.goto("/yearly/o-level/physics-5054")
    expect(page.locator("h1")).to_have_text("Physics 5054 past papers")
    page.locator(".yr-jump").get_by_role("link", name="2016").click()     # opens the year
    page.locator("#y2016 .yr-main", has_text="Paper 21").first.click()
    expect(page).to_have_url(re.compile(r"/yearly/view/\d+$"))

    # 1280 wide: opens side by side; single view for the toggle test
    split = page.get_by_role("button", name=re.compile("Side by side"))
    expect(split).to_have_attribute("aria-pressed", "true")
    split.click()
    expect(page.locator("#pv-qp .vw-pg canvas").first).to_be_visible(timeout=30_000)
    expect(page.locator("#pv-qp .vw-chips").first).to_be_visible()
    page.get_by_role("tab", name=re.compile("Mark scheme")).click()
    expect(page).to_have_url(re.compile(r"\?doc=ms$"))
    expect(page.locator("#pv-ms .vw-pg canvas").first).to_be_visible(timeout=30_000)
    expect(page.locator("#pv-qp")).to_be_hidden()
    page.screenshot(path=str(shots / "yearly_ms_2016.png"))
    page.get_by_role("tab", name=re.compile("Question paper")).click()
    expect(page.locator("#pv-qp")).to_be_visible()


def test_side_by_side_follows_and_marks_save(student, shots):
    student.request.post("/api/enrollments", data={"syllabus": "5054"})
    pid = _paper_id(2019)
    page = student.new_page()
    page.goto(f"/yearly/view/{pid}")
    expect(page.locator("#pv-qp .vw-pg canvas").first).to_be_visible(timeout=30_000)
    expect(page.locator("#pv-ms .vw-pg canvas").first).to_be_visible(timeout=30_000)
    # scroll the question paper to Q5: the mark scheme jumps to Q5's answers
    page.evaluate("""() => {
        const S = JSON.parse(document.getElementById('vw-state').textContent);
        const q = S.questions.find(q => q.number === 5);
        const st = document.getElementById('pv-qp');
        st.scrollTop = st.querySelectorAll('.vw-pg')[q.page - 1].offsetTop;
    }""")
    page.wait_for_function("document.getElementById('pv-ms').scrollTop > 500", timeout=10_000)
    page.screenshot(path=str(shots / "yearly_split_follow.png"))

    page.get_by_role("button", name=re.compile("Marks & grades")).click()
    panel = page.locator(".vw-panel")
    expect(panel.locator("#pv-th")).to_contain_text("out of 75")
    expect(panel.get_by_label("Out of")).to_have_value("75")      # official maximum, not the sum
    panel.get_by_label("Your mark").fill("52")
    panel.get_by_role("button", name="Save").click()
    expect(panel.locator("#pv-grade")).to_contain_text("52/75 = grade A")
    expect(page.get_by_role("button", name=re.compile("Done"))).to_have_attribute("aria-pressed", "true")
    page.screenshot(path=str(shots / "yearly_marks.png"))

    # the listing shows it done, with the score
    page.goto("/yearly/o-level/physics-5054/2019")
    expect(page.locator(".yr-row.is-done .yr-done")).to_have_attribute("data-score", "52/75")
