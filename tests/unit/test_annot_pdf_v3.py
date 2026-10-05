"""annot_pdf draws every annotate.js object type (ink rail v3) and whole whiteboards."""
import fitz
import pytest

import annot_pdf as A

OBJS = [
    {"t": "pen", "k": "fountain", "c": "@blue", "w": .004, "pts": [[.1, .1, .5], [.2, .15, .5], [.3, .1, .5]]},
    {"t": "pen", "k": "dash", "c": "#16a34aaa", "w": .004, "pts": [[.1, .2, .5], [.3, .2, .5]]},
    {"t": "arrow", "two": 1, "c": "@red", "w": .003, "a": [.1, .3], "b": [.4, .3]},
    {"t": "rect", "rr": 1, "fl": "@purple", "c": "@purple", "w": .003, "a": [.5, .05], "b": [.8, .15]},
    {"t": "ellipse", "d": 1, "c": "@teal", "w": .003, "a": [.5, .2], "b": [.7, .3]},
    {"t": "poly", "k": "star", "fl": "@yellow", "c": "@orange", "w": .003, "a": [.1, .35], "b": [.3, .5]},
    {"t": "poly", "pts": [[.55, .35, .5], [.75, .4, .5], [.6, .5, .5], [.55, .35, .5]], "c": "@pink", "w": .003},
    {"t": "arc", "o": [.3, .7], "r": .12, "a0": -2.5, "sw": 2.2, "c": "@blue", "w": .003},
    {"t": "stk", "k": "good_work", "a": [.55, .7], "b": [.9, .79]},
    {"t": "note", "bg": "@pink", "txt": "Angles in a triangle add to 180", "a": [.05, .82], "b": [.3, .97]},
    {"t": "text", "x": .4, "y": .85, "s": .03, "c": "@ink", "txt": "Hello board", "f": "serif", "b": 1},
]


def _ink(pdf: bytes, page=0) -> int:
    pix = fitz.open("pdf", pdf)[page].get_pixmap(dpi=30)
    s = pix.samples
    return sum(1 for i in range(0, len(s), pix.n) if s[i] < 235 or s[i + 1] < 235 or s[i + 2] < 235)


@pytest.mark.parametrize("obj", OBJS, ids=[o["t"] + o.get("k", "") for o in OBJS])
def test_every_object_draws(obj):
    pdf = A.render_board({"kind": "pages", "settings": {}}, [{"objects": [obj]}])
    assert _ink(pdf) > 3, obj


def test_board_pages_patterns_and_sizes():
    pdf = A.render_board({"kind": "pages", "settings": {"pattern": "squared", "size": "a4l"}},
                         [{"objects": OBJS}, {"settings": {"pattern": "cornell", "size": "a4"}, "objects": []}])
    doc = fitz.open("pdf", pdf)
    assert doc.page_count == 2
    assert doc[0].rect.width > doc[0].rect.height and doc[1].rect.width < doc[1].rect.height
    assert _ink(pdf, 1) > 20                                    # the Cornell lines


def test_infinite_board_fits_its_content():
    pdf = A.render_board({"kind": "infinite", "settings": {"paper": "night"}},
                         [{"objects": [{"t": "pen", "c": "@sky", "w": .003, "pts": [[0, 0, .5], [3, 1, .5]]}]}])
    r = fitz.open("pdf", pdf)[0].rect
    assert r.width / r.height > 2                               # wide content -> wide page


def test_old_ink_still_burns_on_rotated_pages():
    doc = fitz.open()
    pg = doc.new_page(width=595, height=842)
    pg.set_rotation(90)
    out = A.burn(_tmp(doc), {1: [
        {"t": "pen", "c": "#1d4ed8", "w": .004, "pts": [[.1, .1, .5], [.5, .5, .5]]},
        {"t": "stk", "k": "tick", "a": [.6, .6], "b": [.7, .7]}]})
    assert _ink(out) > 5


def _tmp(doc):
    import tempfile
    f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    f.write(doc.tobytes())
    f.close()
    return f.name


def test_alpha_and_tokens():
    assert A._alpha("#ff000080") == pytest.approx(128 / 255)
    assert A._alpha("@blue") == 1.0
    assert A._rgb("#f00") == (1.0, 0.0, 0.0)
