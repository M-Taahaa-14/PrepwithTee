"""Pre-2017 mark schemes (no Question/Answer/Marks table): question starts come
from the numbers in the left margin. Uses the real archive PDFs, one per layout
family; skipped where data/raw is not present."""

from pathlib import Path

import fitz
import pytest

from pipeline.link_ms import legacy_boundaries, legacy_regions

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"


def _open(rel):
    f = RAW / rel
    if not f.exists():
        pytest.skip(f"{rel} not in data/raw")
    doc = fitz.open(f)
    for page in doc:
        if page.rotation:
            page.remove_rotation()
    return doc


@pytest.mark.parametrize("rel, qp_max, count", [
    ("9709/2012/9709_w12_ms_11.pdf", 11, 11),     # ruled table, maths
    ("9702/2014/9702_s14_ms_21.pdf", None, None),  # unruled, (a)/(i) indented
    ("5054/2013/5054_s13_ms_21.pdf", None, None),
    ("5070/2012/5070_s12_ms_21.pdf", None, None),  # Section A/B: 'A1', 'B7'
    ("0620/2016/0620_w16_ms_31.pdf", None, None),  # rotated, plain-number Mark column
])
def test_margin_numbers_run_from_one(rel, qp_max, count):
    doc = _open(rel)
    b, pages = legacy_boundaries(doc, qp_max)
    ns = [x["n"] for x in b]
    assert ns[0] == 1 and ns == sorted(ns) and len(ns) >= 4
    if count:
        assert ns == list(range(1, count + 1))
    # every question gets a non-empty crop that stays inside the page
    for rects in legacy_regions(doc, b, pages):
        assert rects
        for r in rects:
            page = doc[r["page"]]
            assert 0 <= r["x0"] < r["x1"] <= page.rect.width
            assert 60 < r["y0"] < r["y1"] <= page.rect.height


def test_physics_p5_numbered_points_are_not_questions():
    # Q1's marking points are numbered 1..7 in the margin; the two real
    # questions are the '(15 marks)' headers
    doc = _open("9702/2012/9702_s12_ms_51.pdf")
    b, _ = legacy_boundaries(doc, qp_max=2)
    assert [x["n"] for x in b] == [1, 2]
    assert b[1]["page"] == 2 and b[1]["y"] < 90
