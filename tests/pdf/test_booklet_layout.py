"""Layout invariants for generated topical booklets (pipeline.compose).

These build real PDFs from the local archive (data/index.db + data/raw), so
they are marked slow and skip when the archive is absent.

    pytest tests/pdf -q
"""

import json
import re
from collections import defaultdict

import fitz
import pytest

from tests.conftest import ROOT, needs_index_db

pytestmark = [pytest.mark.slow, needs_index_db,
              pytest.mark.skipif(not (ROOT / "data" / "raw").exists(),
                                 reason="raw PDFs not present")]

# (syllabus, topics, from, to, papers) - maths (fractions/powers), physics
# theory, CS theory, and an MCQ-only booklet (bubble sheet + answer grid).
CASES = [
    ("4024", "Algebra", 2019, 2025, None),
    ("9709", "Integration (P3)", 2016, 2025, "3"),
    ("5054", "Forces", 2014, 2025, "2"),
    ("0625", "Motion", 2021, 2025, "2"),
]


@pytest.fixture(scope="module")
def placements():
    """Record every crop placement (page, target rect) made by compose."""
    from pipeline import compose
    seen = defaultdict(list)
    orig = fitz.Page.show_pdf_page

    def spy(self, rect, *a, **k):
        seen[(id(self.parent), self.number)].append(fitz.Rect(rect))
        return orig(self, rect, *a, **k)

    fitz.Page.show_pdf_page = spy
    yield seen
    fitz.Page.show_pdf_page = orig


def build(tmp_path, case, *extra):
    from pipeline import compose
    syl, topics, y0, y1, papers = case
    out = tmp_path / f"{syl}.pdf"
    pmap = tmp_path / f"{syl}.json"
    argv = ["--syllabus", syl, "--topics", topics, "--from", str(y0), "--to", str(y1),
            "--out", str(out), "--page-map", str(pmap), *extra]
    if papers:
        argv += ["--papers", papers]
    compose.main(argv)
    return out, json.loads(pmap.read_text("utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_nothing_runs_into_the_footer(tmp_path, placements, case):
    from pipeline.compose import BOTTOM_Y
    placements.clear()
    build(tmp_path, case)
    over = [(pg, round(r.y1, 1)) for (_d, pg), rects in placements.items()
            for r in rects if r.y1 > BOTTOM_Y + 0.5]
    assert not over, f"crops below the footer line: {over[:5]}"


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_no_empty_or_orphan_pages(tmp_path, case):
    from pipeline.compose import BOTTOM_Y
    out, pmap = build(tmp_path, case)
    doc = fitz.open(out)
    heading = re.compile(r"^(May/June|Oct/Nov|Feb/March) \d{4}$")
    for i in range(pmap["body_offset"], len(doc)):
        page = doc[i]
        words = [w for w in page.get_text("words")
                 if w[3] < BOTTOM_Y and "PrepWithTee" not in w[4]]
        assert len(words) >= 4, f"page {i + 1} is (nearly) empty: {[w[4] for w in words]}"
        # A sitting heading ("May/June 2024") must have its first question
        # under it on the same page, never be stranded at the foot.
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                text = "".join(s["text"] for s in line["spans"]).strip()
                if heading.match(text):
                    below = [w for w in words if re.fullmatch(r"Q\d+", w[4])
                             and w[1] > line["bbox"][1]]
                    assert below, f"heading {text!r} stranded on page {i + 1}"
    doc.close()


@pytest.mark.parametrize("case", CASES[:2], ids=[c[0] for c in CASES[:2]])
def test_contents_links_land_on_their_question(tmp_path, case):
    out, pmap = build(tmp_path, case)
    doc = fitz.open(out)
    by_seq = {q["seq"]: q for q in pmap["questions"]}
    links = [l for p in doc[:pmap["body_offset"]] for l in p.get_links()
             if l["kind"] == fitz.LINK_GOTO]
    assert len(links) == len(by_seq)
    for seq, link in zip(sorted(by_seq), links):
        target = doc[link["page"]]
        assert f"Q{seq}" in target.get_text().split(), \
            f"contents row Q{seq} jumps to page {link['page'] + 1} which lacks Q{seq}"
    toc = doc.get_toc()
    assert toc[0][1] == "Contents"
    doc.close()


def test_ids_keep_the_given_order_and_page_map_matches(tmp_path):
    import sqlite3
    con = sqlite3.connect(ROOT / "data" / "index.db")
    ids = [r[0] for r in con.execute(
        """SELECT q.id FROM questions q JOIN classifications c ON c.question_id=q.id
           JOIN papers p ON p.id=q.paper_id
           WHERE p.syllabus='5054' AND p.paper=2 AND p.year>=2020
             AND c.topic IN ('Forces','Pressure','Motion') LIMIT 9""")]
    con.close()
    ids = ids[::-1]                                     # deliberately not DB order
    out, pmap = build(tmp_path, ("5054", "Forces|Pressure|Motion", 2010, 2026, None),
                      "--ids", ",".join(map(str, ids)))
    assert [q["qid"] for q in pmap["questions"]] == ids
    doc = fitz.open(out)
    for q in pmap["questions"]:
        assert f"Q{q['seq']}" in doc[q["page"] - 1].get_text().split()
        assert q["page"] <= q["page_end"] <= len(doc)
    doc.close()


def test_mcq_answer_sheet_is_fillable(tmp_path):
    """Each question on the answer sheet is ONE radio group with options A-D
    (not four linked boxes), and the cover has fillable Name/Class/Date."""
    out, pmap = build(tmp_path, ("0625", "Motion", 2024, 2025, "2"))
    doc = fitz.open(out)
    cover_page, sheet_page = doc[0], doc[1]      # widgets die with their page handle
    cover = {w.field_name for w in cover_page.widgets()}
    assert {"cover_name", "cover_class", "cover_date"} <= cover
    sheet = list(sheet_page.widgets())
    radios = [w for w in sheet if w.field_type == fitz.PDF_WIDGET_TYPE_RADIOBUTTON]
    groups = defaultdict(list)
    for w in radios:
        groups[w.field_name].append(w.on_state())
    assert groups and all(sorted(v) == ["A", "B", "C", "D"] for v in groups.values())
    # AcroForm lists parents (one per question), never the individual kids
    fields = doc.xref_get_key(doc.pdf_catalog(), "AcroForm/Fields")[1]
    assert len(re.findall(r"\d+ 0 R", fields)) == len(groups) + 3 + 2   # + cover + name/date
    doc.close()


def test_cover_and_watermark_link_to_the_website(tmp_path):
    out, pmap = build(tmp_path, CASES[0])
    doc = fitz.open(out)
    site = "https://prepwithtee.com"
    assert sum(l.get("uri") == site for l in doc[0].get_links()) >= 2   # wordmark + medallion
    body = doc[pmap["body_offset"]]
    assert any(l.get("uri") == site for l in body.get_links())
    doc.close()
