"""Graph-with-axes whiteboard paper: the settings rules and the PDF drawing.

static/board/paper.js (checkAxes / axesLayout) mirrors these rules."""
import fitz

import website.annot_pdf as A


def test_clean_axes_accepts_and_tidies():
    v = A.clean_axes({"x0": "-10", "x1": 10, "y0": 0, "y1": 2.5, "dx": "2", "dy": 0.5, "sub": "4", "eq": False})
    assert v == {"x0": -10, "x1": 10, "y0": 0, "y1": 2.5, "dx": 2, "dy": 0.5, "sub": 4, "eq": False, "lab": True}


def test_clean_axes_rejects_bad_ranges():
    assert A.clean_axes({"x0": 5, "x1": 5}) is None                  # empty x range
    assert A.clean_axes({"y0": 3, "y1": -3}) is None                 # backwards
    assert A.clean_axes({"dx": 0}) is None
    assert A.clean_axes({"x0": 0, "x1": 1000, "dx": 1}) is None      # 1000 big squares
    assert A.clean_axes({"x0": "abc"}) is None
    assert A.clean_axes("nope") is None
    assert A.clean_axes({"x0": 0, "x1": 0.5, "dx": 1}) is None       # less than one square


def test_unknown_sub_falls_back():
    assert A.clean_axes({"sub": 7})["sub"] == 5


def test_layout_equal_scale_is_square_and_centred():
    W, H, mm = 595, 842, A.MM
    L = A.axes_layout(W, H, mm, A.AXES_DEFAULT)
    assert L["nx"] == L["ny"] == 10
    assert abs(L["cw"] - L["ch"]) < 1e-9
    assert abs((L["left"] + L["right"]) / 2 - W / 2) < 1e-6
    assert abs((L["top"] + L["bottom"]) / 2 - H / 2) < 1e-6


def test_layout_free_scale_fills_both_ways():
    L = A.axes_layout(595, 842, A.MM, {**A.AXES_DEFAULT, "x0": 0, "x1": 360, "dx": 30, "y0": -2, "y1": 2, "dy": 0.5, "eq": False})
    assert (L["nx"], L["ny"]) == (12, 8)
    assert L["cw"] != L["ch"]


def test_fmt_num():
    assert [A.fmt_num(x) for x in (0.1 + 0.2, -0.0, 2.0, 1e-9, -1.5)] == ["0.3", "0", "2", "0", "-1.5"]


def test_pdf_page_has_axis_numbers():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    A._pattern(page, {"pattern": "axes", "ax": {**A.AXES_DEFAULT, "x0": 0, "x1": 360, "dx": 30, "y0": -2, "y1": 2, "dy": 0.5, "eq": False}})
    words = {w[4] for w in page.get_text("words")}
    assert {"x", "y", "0", "90", "180", "360", "-2", "1.5"} <= words
    assert len(page.get_drawings()) > 0


def test_axes_on_infinite_board_falls_back_to_graph():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    A._pattern(page, {"pattern": "axes", "ax": A.AXES_DEFAULT}, infinite=True)
    assert page.get_text("words") == []                             # plain graph grid, no numbers
