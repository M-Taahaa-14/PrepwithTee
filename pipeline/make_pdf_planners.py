#!/usr/bin/env python3
"""
make_pdf_planners.py — Generate Cambridge study planner PDFs with fillable checkboxes.

Each PDF loads inline in the site's PDF viewer, has AcroForm checkboxes that
work in Acrobat/Preview when downloaded, and prints beautifully for manual ticking.

Usage:
  python -m pipeline.make_pdf_planners
  python -m pipeline.make_pdf_planners --syllabuses 5054 4024
"""

import argparse
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

ROOT = Path(__file__).parent.parent
OUT_ROOT = ROOT / "data" / "resources" / "Study Planners"

W, H = A4           # 595.27 × 841.89 pt
LM = 18 * mm        # left margin
RM = W - 18 * mm    # right margin
TM = H - 18 * mm    # top margin (y starts at bottom in reportlab)
BM = 18 * mm        # bottom margin
CW = RM - LM        # usable width  ≈ 159 mm

# ── column widths (pts) ────────────────────────────────────────────────────
CB_W = 14           # checkbox column
DAY_W = 32          # day label
SUB_W = 255         # sub-topic text
PAP_W = 72          # paper pills
NOT_W = CW - CB_W - DAY_W - SUB_W - PAP_W   # notes remainder

ROW_H = 17          # body row height
HDR_H = 24          # topic-group header height
DAY_HDR_H = 30      # day-banner height

# ── palette ────────────────────────────────────────────────────────────────
def _c(h): return colors.HexColor(h)

TITLE_BG   = _c("#1B2631")
SUBHD_BG   = _c("#2E4057")
COL_HDR_BG = _c("#1A5276")
WHITE      = colors.white
LIGHT_GREY = _c("#F2F2F0")
INK        = _c("#1C2B3A")
INK2       = _c("#4A5568")
INK3       = _c("#8896AA")
GREEN      = _c("#2A9D6E")
LINE       = _c("#D8D4CC")

PALETTE = [
    (_c("#D6EAF8"), _c("#AED6F1"), _c("#2980B9")),
    (_c("#D5F5E3"), _c("#A9DFBF"), _c("#27AE60")),
    (_c("#FEF9E7"), _c("#FAD7A0"), _c("#F39C12")),
    (_c("#F4ECF7"), _c("#D7BDE2"), _c("#8E44AD")),
    (_c("#FDEDEC"), _c("#F5B7B1"), _c("#C0392B")),
    (_c("#FEF5E7"), _c("#F8C471"), _c("#E67E22")),
    (_c("#E8F8F5"), _c("#A2D9CE"), _c("#1ABC9C")),
    (_c("#FDF2F8"), _c("#D98EAE"), _c("#A93266")),
    (_c("#EAF2FF"), _c("#BDD7EE"), _c("#2471A3")),
    (_c("#E8F6F3"), _c("#A3E4D7"), _c("#17A589")),
    (_c("#F9EBEA"), _c("#F1948A"), _c("#CB4335")),
    (_c("#F0F3FF"), _c("#BFC9E8"), _c("#5B82C4")),
]


# ── helpers ────────────────────────────────────────────────────────────────

def _wrap_text(text: str, max_chars: int) -> list[str]:
    """Very simple word-wrap."""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 <= max_chars:
            cur = (cur + " " + w).strip()
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


class PDFPlanner:
    def __init__(self, path: Path, syl: dict):
        self.path = path
        self.syl = syl
        self.c = canvas.Canvas(str(path), pagesize=A4)
        self.c.setTitle(syl["name"])
        self.c.setAuthor("PrepWithTee")
        self.c.setSubject(f"Cambridge {syl['level']} {syl['subject']} Study Planner")
        self.y = TM
        self.page_n = 1
        self.cb_idx = 0  # unique checkbox counter
        self._new_page_needed = False

    # ── canvas shortcuts ────────────────────────────────────────────────────

    def rect(self, x, y, w, h, fill=None, stroke=None, line_w=0.4):
        self.c.setLineWidth(line_w)
        if fill:
            self.c.setFillColor(fill)
        if stroke:
            self.c.setStrokeColor(stroke)
        self.c.rect(x, y, w, h,
                    fill=1 if fill else 0,
                    stroke=1 if stroke else 0)

    def text(self, x, y, s, size=8, color=None, bold=False):
        if color:
            self.c.setFillColor(color)
        fname = "Helvetica-Bold" if bold else "Helvetica"
        self.c.setFont(fname, size)
        self.c.drawString(x, y, str(s))

    def text_right(self, x, y, s, size=8, color=None):
        if color:
            self.c.setFillColor(color)
        self.c.setFont("Helvetica", size)
        self.c.drawRightString(x, y, str(s))

    def line(self, x1, y1, x2, y2, color=None, lw=0.3):
        self.c.setLineWidth(lw)
        if color:
            self.c.setStrokeColor(color)
        self.c.line(x1, y1, x2, y2)

    def checkbox(self, x, y, name: str):
        """Draw a visual checkbox square + AcroForm widget."""
        sz = 9
        # Visual outline
        self.rect(x, y, sz, sz, fill=WHITE, stroke=LINE, line_w=0.8)
        # AcroForm widget (fillable in Acrobat / Preview)
        form = self.c.acroForm
        form.checkbox(
            name=name,
            tooltip="Mark as done",
            x=x, y=y, size=sz,
            buttonStyle="check",
            borderColor=LINE,
            fillColor=WHITE,
            textColor=GREEN,
            borderWidth=0.8,
            checked=False,
        )

    # ── pagination ──────────────────────────────────────────────────────────

    def _footer(self):
        self.c.setFillColor(INK3)
        self.c.setFont("Helvetica", 6.5)
        self.c.drawString(LM, BM - 8, f"© PrepWithTee · {self.syl['name']} · prepwithtee.com")
        self.c.drawRightString(RM, BM - 8, f"Page {self.page_n}")
        self.line(LM, BM - 2, RM, BM - 2, color=LINE, lw=0.4)

    def new_page(self):
        self._footer()
        self.c.showPage()
        self.page_n += 1
        self.y = TM
        self._new_page_needed = False

    def check_space(self, needed):
        if self.y - needed < BM + 12:
            self.new_page()

    # ── title page ──────────────────────────────────────────────────────────

    def draw_title(self):
        # Big title block
        block_h = 52
        self.rect(0, H - block_h, W, block_h, fill=TITLE_BG)
        self.c.setFillColor(WHITE)
        self.c.setFont("Helvetica-Bold", 18)
        self.c.drawString(LM, H - 34, self.syl["name"])

        # Papers subtitle
        sub_h = 26
        self.rect(0, H - block_h - sub_h, W, sub_h, fill=SUBHD_BG)
        papers_txt = "   ·   ".join(
            f"{k}: {v}" for k, v in self.syl["papers"].items()
        )
        self.c.setFillColor(_c("#C8D6E5"))
        self.c.setFont("Helvetica", 7.5)
        self.c.drawString(LM, H - block_h - 16, papers_txt)

        # How to use strip
        tip_h = 18
        tip_y = H - block_h - sub_h - tip_h
        self.rect(0, tip_y, W, tip_h, fill=_c("#F7F5F1"))
        self.c.setFillColor(INK2)
        self.c.setFont("Helvetica", 6.5)
        self.c.drawString(
            LM, tip_y + 6,
            "How to use:  Tick each checkbox as you study the sub-topic.  "
            "Check off in Acrobat / Preview, or print and tick by hand.  "
            "Aim for 100% before your exam."
        )
        self.y = tip_y - 4

        # Column headers
        col_h = 18
        self.rect(LM, self.y - col_h, CW, col_h, fill=COL_HDR_BG)
        hx = LM
        for label, w in [("✓", CB_W), ("Day", DAY_W), ("Sub-Topic / Learning Objective", SUB_W),
                          ("Paper(s)", PAP_W), ("Notes", NOT_W)]:
            self.c.setFillColor(WHITE)
            self.c.setFont("Helvetica-Bold", 7.5)
            self.c.drawString(hx + 3, self.y - col_h + 6, label)
            hx += w
        self.y -= col_h + 2

    # ── day-plan header banner ───────────────────────────────────────────────

    def draw_day_banner(self, day_label: str, note: str, pal_idx: int):
        self.check_space(DAY_HDR_H + ROW_H)
        _, dark, accent = PALETTE[pal_idx % len(PALETTE)]

        self.rect(LM, self.y - DAY_HDR_H, CW, DAY_HDR_H, fill=dark)
        # Day label
        self.c.setFillColor(accent)
        self.c.setFont("Helvetica-Bold", 9.5)
        self.c.drawString(LM + 4, self.y - DAY_HDR_H + 16, day_label)
        # Note (wrapped)
        if note:
            lines = _wrap_text(note, 105)
            ny = self.y - DAY_HDR_H + (DAY_HDR_H - 8) - 4
            for ln in lines[:2]:
                self.c.setFillColor(INK)
                self.c.setFont("Helvetica", 6.5)
                self.c.drawString(LM + 4, ny, ln)
                ny -= 8
        self.y -= DAY_HDR_H

    # ── topic-group header ───────────────────────────────────────────────────

    def draw_topic_header(self, name: str, papers: str, pal_idx: int):
        self.check_space(HDR_H + ROW_H)
        _, dark, accent = PALETTE[pal_idx % len(PALETTE)]
        self.rect(LM, self.y - HDR_H, CW, HDR_H, fill=dark)
        self.c.setFillColor(INK)
        self.c.setFont("Helvetica-Bold", 8.5)
        self.c.drawString(LM + CB_W + DAY_W + 4, self.y - HDR_H + 8, name.upper())
        self.c.setFillColor(accent)
        self.c.setFont("Helvetica", 7)
        self.c.drawRightString(RM - 4, self.y - HDR_H + 8, papers)
        self.y -= HDR_H

    # ── subtopic row ─────────────────────────────────────────────────────────

    def draw_subtopic_row(self, sub_name: str, papers: str, day_label: str,
                          pal_idx: int, notes: str = ""):
        lines = _wrap_text(sub_name, 52)
        extra_lines = max(0, len(lines) - 1)
        row_h = ROW_H + extra_lines * 9

        self.check_space(row_h + 2)
        light, _, accent = PALETTE[pal_idx % len(PALETTE)]

        # background
        self.rect(LM, self.y - row_h, CW, row_h, fill=light, stroke=LINE, line_w=0.25)

        # checkbox
        self.cb_idx += 1
        self.checkbox(LM + 2, self.y - row_h + (row_h - 9) / 2,
                      f"cb_{self.cb_idx:04d}")

        # day label (small)
        if day_label:
            self.c.setFillColor(INK3)
            self.c.setFont("Helvetica", 6)
            self.c.drawString(LM + CB_W + 2, self.y - row_h // 2 - 3, day_label)

        # sub-topic text (multi-line)
        tx = LM + CB_W + DAY_W + 3
        ty = self.y - 5 - (row_h - ROW_H) // 2
        for i, ln in enumerate(lines):
            self.c.setFillColor(INK)
            self.c.setFont("Helvetica", 7.5)
            self.c.drawString(tx, ty - i * 9, ln)

        # papers
        px = LM + CB_W + DAY_W + SUB_W + 3
        self.c.setFillColor(accent)
        self.c.setFont("Helvetica-Bold", 6.5)
        self.c.drawString(px, self.y - row_h // 2 - 3, papers)

        self.y -= row_h

    # ── build ────────────────────────────────────────────────────────────────

    def build(self):
        self.draw_title()

        for group in self.syl.get("groups", []):
            gtype = group.get("type", "topic")

            if gtype == "day":
                self.draw_day_banner(
                    group["day_label"], group.get("note", ""),
                    group["pal_idx"]
                )
                for entry in group["entries"]:
                    self.draw_subtopic_row(
                        entry[0], entry[1], entry[2],
                        group["pal_idx"]
                    )
            else:
                self.draw_topic_header(
                    group["name"], group.get("papers", ""),
                    group["pal_idx"]
                )
                for entry in group["entries"]:
                    self.draw_subtopic_row(
                        entry[0], entry[1], "", group["pal_idx"]
                    )

        self._footer()
        self.c.save()


# ─── SYLLABUS DATA ────────────────────────────────────────────────────────────

def _topic(name, papers, pal_idx, subs):
    return {"type": "topic", "name": name, "papers": papers,
            "pal_idx": pal_idx, "entries": subs}

def _day(label, note, pal_idx, entries):
    return {"type": "day", "day_label": label, "note": note,
            "pal_idx": pal_idx, "entries": entries}

# entry = (sub_topic_name, papers_str, day_label)
def _e(name, papers, day=""):
    return (name, papers, day)


def syl_4024() -> dict:
    """4024 O Level Maths — follows the actual 60-day plan structure."""
    return {
        "code": "4024",
        "subject": "Mathematics",
        "level": "O Level",
        "name": "4024 O Level Mathematics — 60-Day Study Plan",
        "papers": {
            "P1": "Short questions, no calculator (80 marks, 2 h)",
            "P2": "Long questions, calculator allowed (100 marks, 2 h 30 min)",
        },
        "subfolder": "O Level",
        "groups": [
            _day("DAY 1", "Basics that underpin everything — 4 topics (~10 marks). Read notes & practise plenty of questions before moving on.", 0, [
                _e("BODMAS — order of operations", "P1, P2", "Day 1"),
                _e("Number families — integers, rationals, irrationals, primes", "P1, P2", "Day 1"),
                _e("Decimals — converting, comparing, recurring decimal notation", "P1, P2", "Day 1"),
                _e("Fractions — adding, subtracting, multiplying, dividing", "P1, P2", "Day 1"),
                _e("Midway and difference between two values", "P1, P2", "Day 1"),
                _e("Recurring to decimal conversion", "P1", "Day 1"),
                _e("Indices — properties (aᵐ·aⁿ = aᵐ⁺ⁿ etc.) and equation solving", "P1, P2", "Day 1"),
                _e("Standard form — converting and DMAS in standard form", "P1, P2", "Day 1"),
                _e("Significant figures — rules and estimation", "P1, P2", "Day 1"),
            ]),
            _day("DAY 2", "4 topics (~12 marks). Essential algebra skills. Practise lots of questions — you cannot get a good grade without practice.", 1, [
                _e("Factorisation — two terms (common factor, difference of squares)", "P1, P2", "Day 2"),
                _e("Factorisation — three terms (trinomials)", "P1, P2", "Day 2"),
                _e("Factorisation — four terms (grouping)", "P1, P2", "Day 2"),
                _e("Factorisation — solving equations by factorising", "P1, P2", "Day 2"),
                _e("Time — adding and subtracting hours/minutes", "P1, P2", "Day 2"),
                _e("Time — inter-city travel problems", "P1, P2", "Day 2"),
                _e("Simultaneous equations — elimination method", "P1, P2", "Day 2"),
                _e("Simultaneous equations — substitution method", "P1, P2", "Day 2"),
                _e("Proportionality — simple (direct and inverse)", "P2", "Day 2"),
                _e("Proportionality — advanced (combined variation)", "P2", "Day 2"),
            ]),
            _day("DAY 3", "4 topics (~8 marks). Easy marks in the first loop of the non-calculator paper.", 2, [
                _e("Limits of accuracy — upper/lower bounds (direct question)", "P1", "Day 3"),
                _e("Limits of accuracy — indirect (errors in calculations)", "P1", "Day 3"),
                _e("HCF and LCM — simple (prime factorisation method)", "P1", "Day 3"),
                _e("HCF and LCM — smallest integer n problems", "P1", "Day 3"),
                _e("HCF and LCM — advanced applications", "P1", "Day 3"),
                _e("Similarity — properties and ratio of areas/volumes", "P1, P2", "Day 3"),
                _e("Similarity — same-height problems", "P2", "Day 3"),
                _e("Congruency — rules (SSS, SAS, AAS, RHS)", "P1", "Day 3"),
            ]),
            _day("DAYS 4–6", "Statistics — 1 section, 4 chapters (~25–30 marks). This section alone can raise your grade by two letters. Spend 3+ hours per day and complete both worksheets for each paper.", 3, [
                _e("Mean, median, mode — raw data", "P1, P2", "Day 4"),
                _e("Mean, median, mode — single-value frequency table", "P1, P2", "Day 4"),
                _e("Mean, median, mode — grouped frequency table (estimate)", "P2", "Day 4"),
                _e("Histogram — single-value table", "P2", "Day 5"),
                _e("Histogram — range table with same class widths", "P2", "Day 5"),
                _e("Histogram — range table with different class widths (freq. density)", "P2", "Day 5"),
                _e("Cumulative frequency — constructing table and curve", "P2", "Day 5"),
                _e("Cumulative frequency — reading quartiles (median, Q1, Q3, IQR)", "P2", "Day 6"),
                _e("Cumulative frequency — box-and-whisker plots", "P2", "Day 6"),
                _e("Scatter plots — correlation, line of best fit, interpolation", "P1, P2", "Day 6"),
            ]),
            _day("DAYS 7–10", "Trigonometry — one huge section (~20 marks). Watch YouTube videos first, write notes, then practise. This section will challenge you but will also unlock Mensuration.", 4, [
                _e("Types of triangles — angle sum, properties (isoceles, equilateral)", "P1", "Day 7"),
                _e("Right-angled triangles — SOHCAHTOA", "P1, P2", "Day 7"),
                _e("Non-right triangles — Sine Rule (a/sin A = b/sin B)", "P2", "Day 8"),
                _e("Non-right triangles — Cosine Rule (a² = b²+c²−2bc cos A)", "P2", "Day 8"),
                _e("Area of triangle — Area = ½ab sin C", "P2", "Day 8"),
                _e("Angle of elevation and depression", "P1, P2", "Day 9"),
                _e("Triangles with obtuse angles — ambiguous case", "P2", "Day 9"),
                _e("P1 special case — exact values (30°, 45°, 60°)", "P1", "Day 9"),
                _e("P1 square roots — rationalising, surd trigonometry", "P1", "Day 9"),
                _e("P1 table / angle-reading problems", "P1", "Day 10"),
                _e("Bearings — 3-digit notation, N/E/S/W problems", "P1, P2", "Day 10"),
            ]),
            _day("DAYS 11–15", "Mensuration — scary but manageable after Trig. Make flashcards for all formulas.", 5, [
                _e("2D basic shapes — area and perimeter (rectangle, triangle, parallelogram, trapezium)", "P1, P2", "Day 11"),
                _e("2D circle sector and arc length", "P1, P2", "Day 11"),
                _e("2D major segment area", "P2", "Day 12"),
                _e("2D minor segment area", "P2", "Day 12"),
                _e("3D basic shapes — surface area and volume (cuboid, prism)", "P1, P2", "Day 13"),
                _e("3D cylinder — curved surface area, volume", "P1, P2", "Day 13"),
                _e("3D cone — slant height, curved SA, volume", "P2", "Day 14"),
                _e("3D sphere and hemisphere — SA = 4πr², V = 4/3πr³", "P2", "Day 14"),
                _e("3D combined/upright conical shapes", "P2", "Day 14"),
                _e("Frustums — truncated cone remaining after removing small cone", "P2", "Day 15"),
                _e("Nets of 3D shapes — drawing and calculating from nets", "P1, P2", "Day 15"),
            ]),
            _day("DAYS 16–17", "Daily Maths — 7 small chapters (~20 marks). A pleasant breeze after recent hard sections. Push for as many calculator questions as possible.", 6, [
                _e("Unit conversion — length, mass, volume, speed", "P1, P2", "Day 16"),
                _e("Ratios — sharing in a given ratio, combining ratios", "P1, P2", "Day 16"),
                _e("Currency rates — converting between currencies", "P2", "Day 16"),
                _e("Maps and scales — RF and calculating actual distances", "P1, P2", "Day 16"),
                _e("Percentages — formula method (x% of y)", "P1, P2", "Day 16"),
                _e("Percentages — percentage increase/decrease boxes method", "P1, P2", "Day 16"),
                _e("Simple interest — types 1, 2, 3", "P2", "Day 17"),
                _e("Compound interest — C = P(1+r/100)ⁿ", "P2", "Day 17"),
                _e("Pie charts — drawing and reading", "P1, P2", "Day 17"),
            ]),
            _day("DAY 18", "Graphical Solutions — 1 chapter (~10 marks). The easiest 10 marks Cambridge will let you take. Learn the notes and watch examples.", 7, [
                _e("Table, graph and tangent — plotting the curve, drawing tangent", "P2", "Day 18"),
                _e("Graphical solutions — Case 1: reading x where f(x) = k", "P2", "Day 18"),
                _e("Graphical solutions — Case 2: drawing line to solve rearranged equation", "P2", "Day 18"),
            ]),
            _day("DAY 19", "Co-ordinate Geometry — 1 chapter (~5 marks).", 8, [
                _e("Formulas — gradient, midpoint, distance between two points", "P1, P2", "Day 19"),
                _e("Equation of a line — y = mx + c form", "P1, P2", "Day 19"),
                _e("Gradient relationships — parallel and perpendicular lines", "P1, P2", "Day 19"),
                _e("Notes — finding equation given gradient and a point", "P1, P2", "Day 19"),
            ]),
            _day("DAYS 20–21", "Number Sequences — 1 chapter (~5–8 marks). Deliberately left late because it requires a strong algebra base.", 9, [
                _e("Arithmetic patterns — nth term of a linear sequence", "P1, P2", "Day 20"),
                _e("Square, cube, triangular numbers and shifts", "P1", "Day 20"),
                _e("Patterns with table — extending a pattern using a two-variable table", "P2", "Day 21"),
                _e("Patterns with equations — forming and solving an equation for the nth term", "P2", "Day 21"),
                _e("Patterns-only problems — no formula, just reasoning", "P1", "Day 21"),
            ]),
            _day("DAYS 22–23", "Circles — 1 chapter (~5 marks). The only good way to learn this is to memorise all the theorems using examples.", 10, [
                _e("Circle properties — chord, diameter, tangent, arc, sector", "P1", "Day 22"),
                _e("Circle theorems — angle in semicircle = 90°", "P1", "Day 22"),
                _e("Circle theorems — angles in same segment are equal", "P1", "Day 22"),
                _e("Circle theorems — angle at centre = 2 × angle at circumference", "P1", "Day 22"),
                _e("Circle theorems — cyclic quadrilateral (opposite angles sum to 180°)", "P1", "Day 22"),
                _e("Circle theorems — tangent-radius at 90°; tangents from external point equal", "P1", "Day 23"),
                _e("Question rules — identifying which theorem to apply", "P1", "Day 23"),
            ]),
            _day("DAYS 24–25", "Linear Inequalities, Symmetry and Polygons — 3 chapters (~8 marks).", 11, [
                _e("Linear inequalities — solving and writing solution sets", "P1", "Day 24"),
                _e("Shading regions — identifying correct region from inequalities", "P2", "Day 24"),
                _e("Line symmetry — number of lines in shapes", "P1", "Day 25"),
                _e("Rotational symmetry — order of rotational symmetry", "P1", "Day 25"),
                _e("Polygons — interior angle = (n−2)×180/n; exterior angle = 360/n", "P1", "Day 25"),
            ]),
            _day("DAY 26", "Kinematics — 1 chapter (~5 marks). Straightforward once you know the rules.", 0, [
                _e("Unit conversion — km/h to m/s and vice versa", "P1, P2", "Day 26"),
                _e("Graphs rules — what gradient and area represent", "P1, P2", "Day 26"),
                _e("Distance-time graphs — reading speed, rest, direction", "P1, P2", "Day 26"),
                _e("Speed-time graphs — calculating acceleration, distance, average speed", "P1, P2", "Day 26"),
                _e("Graph conversion — converting between d-t and v-t forms", "P2", "Day 26"),
            ]),
            _day("DAYS 27–30", "Algebra — complete section (~20 marks). The most important section in the syllabus. Master each sub-topic before moving on.", 1, [
                _e("Expanding brackets — single, double, binomial", "P1, P2", "Day 27"),
                _e("Quadratic equations — solving by factorising", "P1, P2", "Day 27"),
                _e("Completing the square — writing in (x+a)²+b form", "P2", "Day 28"),
                _e("Quadratic formula — x = (−b ± √(b²−4ac)) / 2a", "P1, P2", "Day 28"),
                _e("Scenario-based quadratic questions — forming the equation", "P2", "Day 29"),
                _e("Algebraic fractions — simplifying, adding, subtracting", "P1, P2", "Day 29"),
                _e("Rearranging formulae — making a letter the subject", "P1, P2", "Day 30"),
                _e("Surds — simplifying √x; rationalising the denominator", "P1", "Day 31"),
            ]),
            _day("DAYS 32–33", "Sets — 1 chapter (~3–6 marks). Set notation is fairly straightforward with proper practice.", 2, [
                _e("Listing — finding elements of sets using conditions", "P1", "Day 32"),
                _e("Venn diagram shading — identifying correct region", "P1", "Day 32"),
                _e("Venn diagram scenario-based — completing with given information", "P1, P2", "Day 33"),
                _e("Set notation — ∪, ∩, A', ξ, n(A); reading notation", "P1", "Day 33"),
            ]),
            _day("DAYS 34–35", "Probability — 1 chapter (~5 marks). Learn the concepts and use tree diagrams.", 3, [
                _e("Concept and formula — P(event) = favourable/total", "P1, P2", "Day 34"),
                _e("Sample spaces — listing all outcomes in a table/grid", "P1", "Day 34"),
                _e("Tree diagrams and rules — AND (×), OR (+)", "P1, P2", "Day 35"),
                _e("With replacement — probabilities constant each draw", "P1, P2", "Day 35"),
                _e("Without replacement — probabilities change each draw", "P1, P2", "Day 35"),
            ]),
            _day("DAYS 36–38", "Vectors — 1 chapter (~5–8 marks). Easy to pick up — understand column vectors before moving to diagrams.", 4, [
                _e("Column vectors — notation, addition and subtraction", "P1, P2", "Day 36"),
                _e("Magnitude of a vector — |v| = √(x²+y²)", "P1", "Day 36"),
                _e("Position vectors — OA, OB and their relationship", "P2", "Day 37"),
                _e("Simple vector diagrams — expressing paths in terms of a and b", "P2", "Day 37"),
                _e("Advanced vector diagrams — ratio method (dividing lines)", "P2", "Day 38"),
            ]),
            _day("DAY 39", "Transformations — 1 chapter (~5 marks). Cambridge has changed this topic — study both old and new-style questions.", 5, [
                _e("Introduction — types of transformations overview", "P1, P2", "Day 39"),
                _e("Reflection — on grid and constructing using perpendicular bisector", "P1, P2", "Day 39"),
                _e("Rotation — on grid and finding centre/angle of rotation", "P1, P2", "Day 39"),
                _e("Translation — by column vector", "P1, P2", "Day 39"),
                _e("Enlargement — scale factor, centre of enlargement (positive & negative)", "P1, P2", "Day 39"),
            ]),
            _day("DAY 40", "Graphs of Functions and Functions — 2 chapters (~10 marks).", 6, [
                _e("Shapes of graphs — y = ax^n; recognise linear, quadratic, cubic, reciprocal, exponential", "P1, P2", "Day 40"),
                _e("Exam techniques — which function matches which graph", "P2", "Day 40"),
                _e("Functions — f(x) notation; evaluating f(a)", "P1, P2", "Day 40"),
                _e("Inverse function — finding f⁻¹(x)", "P1, P2", "Day 40"),
                _e("Composite functions — fg(x) = f(g(x))", "P2", "Day 40"),
                _e("Domain and range — identifying valid inputs and outputs", "P2", "Day 40"),
                _e("Asymptotes — identifying lines the curve approaches", "P2", "Day 40"),
            ]),
            _day("DAYS 41–45", "3D Trigonometry and Exponential Growth/Decay — completing the final topics.", 7, [
                _e("3D trig — cuboid and cube space diagonal length", "P2", "Day 41"),
                _e("3D trig — angle in a pyramid (vertex to base diagonal)", "P2", "Day 42"),
                _e("3D trig — prism diagonal problems", "P2", "Day 43"),
                _e("Exponential growth — y = ab^x; rate questions", "P2", "Day 44"),
                _e("Exponential decay — half-life type problems", "P2", "Day 44"),
                _e("Finding number of years — using trial/logs approach", "P2", "Day 45"),
            ]),
            _day("DAYS 46–50", "Constructions, Scale Drawings and final review of Algebra.", 8, [
                _e("Constructing triangles — using ruler and compasses", "P1", "Day 46"),
                _e("Perpendicular and angle bisectors", "P1", "Day 46"),
                _e("Scale drawings — reading and completing (bearing, north line)", "P1, P2", "Day 47"),
                _e("Loci — set of points satisfying given conditions", "P1, P2", "Day 47"),
                _e("Review: Hard algebra — rearranging with squares and roots", "P1, P2", "Day 48"),
                _e("Review: Matrices — only if on your specific syllabus variation", "P2", "Day 49"),
                _e("Mixed practice — attempt full P1 under timed conditions", "P1", "Day 50"),
            ]),
        ],
    }


def syl_5054() -> dict:
    return {
        "code": "5054",
        "subject": "Physics",
        "level": "O Level",
        "name": "5054 O Level Physics — Study Planner",
        "papers": {
            "P1": "Multiple Choice (40 marks, 45 min)",
            "P2": "Theory (80 marks, 1 h 45 min)",
            "P3": "Practical (40 marks, 1 h 15 min)",
        },
        "subfolder": "O Level",
        "groups": [
            _topic("1. Physical Quantities & Measurement", "P1 · P2 · P3", 0, [
                _e("SI units — base units (m, kg, s, A, K) and prefixes (kilo, milli, micro, nano)", "P1, P2"),
                _e("Scalars vs vectors — examples; adding vectors", "P1, P2"),
                _e("Measuring length — ruler, Vernier caliper, micrometer screw gauge", "P1, P2, P3"),
                _e("Measuring volume — measuring cylinder, eureka can (displacement)", "P1, P2, P3"),
                _e("Measuring mass — beam balance and electronic balance", "P1, P2, P3"),
                _e("Measuring time — stopwatch, ticker tape, pendulum period", "P1, P2, P3"),
                _e("Precision, accuracy and parallax error — how to avoid", "P1, P2, P3"),
            ]),
            _topic("2. Motion", "P1 · P2", 1, [
                _e("Speed, velocity and acceleration — definitions and units", "P1, P2"),
                _e("Distance–time graphs — gradient = speed; horizontal = at rest", "P1, P2"),
                _e("Velocity–time graphs — gradient = acceleration; area = distance", "P1, P2"),
                _e("Equations of uniform motion — v=u+at; s=ut+½at²; v²=u²+2as", "P2"),
                _e("Free fall — g = 10 m/s²; acceleration due to gravity", "P1, P2"),
                _e("Terminal velocity — forces balanced, no further acceleration", "P1, P2"),
            ]),
            _topic("3. Forces (Newton's Laws, Moments, Pressure)", "P1 · P2", 2, [
                _e("Newton's First Law — inertia; object stays at rest/constant velocity", "P1, P2"),
                _e("Newton's Second Law — F = ma (net/resultant force)", "P1, P2"),
                _e("Newton's Third Law — equal and opposite forces on different objects", "P1, P2"),
                _e("Mass vs weight — W = mg; gravitational field strength g = 10 N/kg", "P1, P2"),
                _e("Friction and air resistance — causes, direction, reducing methods", "P1, P2"),
                _e("Hooke's Law — F = ke; limit of proportionality; spring constant", "P1, P2"),
                _e("Moments — moment = F × perpendicular distance; principle of moments", "P1, P2"),
                _e("Centre of gravity — finding by experiment; stability conditions", "P1, P2"),
                _e("Circular motion — centripetal force directed inward", "P1, P2"),
                _e("Pressure in solids — P = F/A; unit pascal (Pa)", "P1, P2"),
                _e("Pressure in liquids — P = hρg; increases with depth", "P1, P2"),
                _e("Atmospheric pressure and manometer", "P1, P2"),
            ]),
            _topic("4. Momentum", "P1 · P2", 3, [
                _e("Momentum — p = mv; units kg m/s", "P1, P2"),
                _e("Impulse — F × t = change in momentum", "P1, P2"),
                _e("Conservation of momentum — isolated system; collisions + explosions", "P1, P2"),
            ]),
            _topic("5. Energy, Work & Power", "P1 · P2", 4, [
                _e("Work done — W = Fd cos θ (force must be parallel to displacement)", "P1, P2"),
                _e("Kinetic energy — KE = ½mv²", "P1, P2"),
                _e("Gravitational PE — GPE = mgh", "P1, P2"),
                _e("Conservation of mechanical energy — KE ↔ GPE conversions", "P1, P2"),
                _e("Power — P = W/t = Fv; unit watt (W)", "P1, P2"),
                _e("Efficiency — useful output energy / total input energy × 100%", "P1, P2"),
                _e("Energy resources — renewable vs non-renewable; advantages/disadvantages", "P1, P2"),
                _e("Sankey diagrams — representing energy transfers visually", "P1, P2"),
            ]),
            _topic("6. Kinetic Particle Model & Thermal Physics", "P1 · P2 · P3", 5, [
                _e("States of matter — properties of solid, liquid, gas explained by particles", "P1, P2"),
                _e("Changes of state — melting, boiling, condensing, freezing, sublimation", "P1, P2"),
                _e("Brownian motion — evidence for random particle movement", "P1, P2"),
                _e("Diffusion — spreading from high to low concentration; rate factors", "P1, P2"),
                _e("Gas pressure — due to particle collisions with container walls", "P1, P2"),
                _e("Thermal expansion — solids, liquids, gases; applications and problems", "P1, P2"),
                _e("Specific heat capacity — Q = mcΔT; measuring c by experiment", "P1, P2, P3"),
                _e("Specific latent heat — Q = mL; plateau on heating/cooling curve", "P1, P2"),
                _e("Evaporation — factors (temp, surface area, wind, humidity); cooling effect", "P1, P2"),
            ]),
            _topic("7. Thermal Energy Transfer", "P1 · P2", 6, [
                _e("Conduction — particle vibration; free electrons in metals; good vs poor conductors", "P1, P2"),
                _e("Convection — fluid movement due to density differences; applications", "P1, P2"),
                _e("Radiation — infrared; black/dull surfaces emit/absorb more than shiny/white", "P1, P2"),
                _e("Vacuum flask — how it reduces all three types of heat transfer", "P1, P2"),
            ]),
            _topic("8. General Wave Properties", "P1 · P2", 7, [
                _e("Wave terms — wavelength (λ), frequency (f), amplitude, period (T = 1/f)", "P1, P2"),
                _e("Wave equation — v = fλ; calculations", "P1, P2"),
                _e("Transverse waves — oscillation perpendicular to travel direction", "P1, P2"),
                _e("Longitudinal waves — compressions and rarefactions; sound is longitudinal", "P1, P2"),
                _e("Diffraction — waves spread through a gap; most when λ ≈ gap width", "P1, P2"),
            ]),
            _topic("9. Light", "P1 · P2 · P3", 8, [
                _e("Laws of reflection — angle of incidence = angle of reflection", "P1, P2, P3"),
                _e("Refraction — Snell's law; n₁ sin θ₁ = n₂ sin θ₂; n = sin i / sin r", "P1, P2"),
                _e("Total internal reflection — critical angle; sin C = 1/n", "P1, P2"),
                _e("Optical fibres — TIR application in communications and medicine", "P1, P2"),
                _e("Converging lens — focal point, focal length, ray diagrams (3 types of image)", "P1, P2"),
                _e("Diverging lens — ray diagrams; always virtual, upright, diminished", "P1, P2"),
                _e("Magnifying glass — object inside focal length; virtual, upright, magnified", "P1, P2"),
            ]),
            _topic("10. Electromagnetic Spectrum & Sound", "P1 · P2", 9, [
                _e("EM spectrum — order: radio → micro → IR → visible → UV → X-ray → gamma", "P1, P2"),
                _e("All EM waves — transverse; travel at c = 3×10⁸ m/s in vacuum", "P1, P2"),
                _e("Radio, microwave, infrared — uses and dangers", "P1, P2"),
                _e("UV, X-rays, gamma — uses and dangers (sterilisation, imaging, cancer treatment)", "P1, P2"),
                _e("Sound — longitudinal; needs medium; cannot travel through vacuum", "P1, P2"),
                _e("Speed of sound (~340 m/s in air) — much slower than light", "P1, P2"),
                _e("Pitch (frequency) and loudness (amplitude)", "P1, P2"),
                _e("Echo — reflected sound; calculating distance = (v × t) / 2", "P1, P2"),
                _e("Ultrasound — > 20 000 Hz; medical scanning, sonar, cleaning", "P1, P2"),
                _e("Oscilloscope — reading peak voltage, frequency, period from a trace", "P1, P2"),
            ]),
            _topic("11. Magnetism & Electrostatics", "P1 · P2", 10, [
                _e("Magnetic materials — iron, nickel, cobalt, steel", "P1, P2"),
                _e("Magnetic field lines — direction (N to S outside), properties", "P1, P2"),
                _e("Induced magnetism — temporary in soft iron; permanent in steel", "P1, P2"),
                _e("Electrostatics — charging by friction; attraction and repulsion", "P1, P2"),
                _e("Electric field lines — direction and shape for various charge configurations", "P1, P2"),
            ]),
            _topic("12. Electrical Quantities & Circuits", "P1 · P2 · P3", 11, [
                _e("Charge — Q (coulombs); current I = Q/t (amperes)", "P1, P2"),
                _e("PD (voltage) — energy per unit charge; unit volt; V = W/Q", "P1, P2"),
                _e("Resistance — Ohm's law V = IR; non-ohmic conductors", "P1, P2"),
                _e("I–V characteristics — Ohmic resistor, filament lamp, diode", "P1, P2, P3"),
                _e("Thermistor (NTC) — R decreases as temperature increases", "P1, P2"),
                _e("LDR — R decreases as light intensity increases", "P1, P2"),
                _e("Series circuits — same current, voltages add, R_total = R1 + R2", "P1, P2"),
                _e("Parallel circuits — same voltage, currents add, 1/R = 1/R1 + 1/R2", "P1, P2"),
                _e("Potential divider — voltage split proportional to resistance", "P1, P2"),
                _e("EMF and internal resistance — terminal PD = E − Ir", "P1, P2"),
                _e("Power in circuits — P = IV = I²R = V²/R", "P1, P2"),
                _e("Energy and cost — E = Pt; kilowatt-hour (kWh); electricity bills", "P1, P2"),
                _e("Mains safety — live/neutral/earth; fuse; circuit breaker; double insulation", "P1, P2"),
            ]),
            _topic("13. Electromagnetic Effects", "P1 · P2", 0, [
                _e("Magnetic field around a current-carrying wire and solenoid", "P1, P2"),
                _e("Force on current in field — F = BIL; left-hand (Fleming's) rule", "P1, P2"),
                _e("DC motor — coil in field; split-ring commutator; applications", "P1, P2"),
                _e("Relay — electromagnet switching a high-current circuit", "P1, P2"),
                _e("Electromagnetic induction — changing flux induces EMF (Faraday's law)", "P1, P2"),
                _e("Factors affecting induced EMF — speed, turns, field strength", "P1, P2"),
                _e("AC generator — slip rings; sinusoidal output", "P1, P2"),
                _e("Transformer — turns ratio Vs/Vp = Ns/Np; step-up vs step-down", "P1, P2"),
                _e("National grid — high voltage / low current reduces power loss", "P1, P2"),
            ]),
            _topic("14. Atomic & Nuclear Physics", "P1 · P2", 1, [
                _e("Atomic structure — protons, neutrons, electrons; nucleus size vs atom", "P1, P2"),
                _e("Nuclide notation — mass number A, atomic number Z, neutron number N", "P1, P2"),
                _e("Isotopes — same Z, different A; same chemical properties", "P1, P2"),
                _e("Alpha particles — helium nucleus ⁴He; range ~5 cm air; blocked by paper", "P1, P2"),
                _e("Beta particles — fast electron; range ~1 m air; blocked by few mm aluminium", "P1, P2"),
                _e("Gamma rays — EM radiation; no mass/charge; reduced by thick lead", "P1, P2"),
                _e("Background radiation — radon, cosmic rays, medical, food; correction", "P1, P2"),
                _e("Half-life — time for activity to halve; calculations from data and graphs", "P1, P2"),
                _e("Radioactive decay equations — balancing A and Z on both sides", "P1, P2"),
                _e("Uses of radioactivity — medical tracers, cancer treatment, carbon-14 dating", "P1, P2"),
                _e("Safety precautions — distance, shielding, tongs, storage, monitoring", "P1, P2"),
                _e("Nuclear fission — splitting a heavy nucleus; chain reaction; nuclear power", "P1, P2"),
                _e("Nuclear fusion — joining light nuclei; energy source of stars", "P1, P2"),
            ]),
            _topic("15. Earth, Solar System & Universe", "P1 · P2", 2, [
                _e("Solar system — planets, moons, comets, asteroids; order from Sun", "P1, P2"),
                _e("Gravitational orbits — satellites; orbital period and radius relationship", "P1, P2"),
                _e("Stars — lifecycle: nebula → main sequence → red giant → white dwarf / neutron star / BH", "P1, P2"),
                _e("The Universe — galaxies; Milky Way; light-years", "P1, P2"),
                _e("Big Bang — redshift as evidence; universe is expanding; CMBR", "P1, P2"),
            ]),
        ],
    }


def syl_5070() -> dict:
    return {
        "code": "5070",
        "subject": "Chemistry",
        "level": "O Level",
        "name": "5070 O Level Chemistry — Study Planner",
        "papers": {
            "P1": "Multiple Choice (40 marks, 45 min)",
            "P2": "Theory (80 marks, 1 h 45 min)",
            "P3": "Practical (40 marks, 1 h 15 min)",
        },
        "subfolder": "O Level",
        "groups": [
            _topic("1. Particulate Nature of Matter", "P1 · P2 · P3", 0, [
                _e("States of matter — properties; particle arrangement diagrams", "P1, P2"),
                _e("Changes of state — melting, boiling, condensing, freezing, sublimation", "P1, P2"),
                _e("Kinetic particle theory — Brownian motion; diffusion and rate factors", "P1, P2"),
                _e("Filtration — separating insoluble solid from liquid", "P1, P2, P3"),
                _e("Crystallisation — obtaining pure solid from solution", "P1, P2, P3"),
                _e("Simple distillation — separating liquid from dissolved solid", "P1, P2, P3"),
                _e("Fractional distillation — separating liquids with different boiling points", "P1, P2"),
                _e("Paper chromatography — Rf value; identifying pure substances", "P1, P2, P3"),
                _e("Pure substance tests — sharp melting/boiling point as purity indicator", "P1, P2, P3"),
            ]),
            _topic("2. Atomic Structure & Periodic Table", "P1 · P2", 1, [
                _e("Sub-atomic particles — proton (+1, ~1u), neutron (0, ~1u), electron (−1, ~0)", "P1, P2"),
                _e("Atomic number (Z) and mass number (A); neutron number N = A − Z", "P1, P2"),
                _e("Isotopes — same Z, different A; identical chemical properties", "P1, P2"),
                _e("Electron configuration — shells 2, 8, 8…; drawing dot diagrams", "P1, P2"),
                _e("Periodic Table position — period = shells; group = outer electrons", "P1, P2"),
                _e("Group I alkali metals — increasing reactivity; reactions with water", "P1, P2"),
                _e("Group VII halogens — decreasing reactivity; displacement reactions", "P1, P2"),
                _e("Group 0 noble gases — inert; full outer shell; uses", "P1, P2"),
                _e("Transition metals — variable oxidation state; coloured compounds; catalysts", "P1, P2"),
                _e("Trends across a period — metallic → non-metallic character", "P1, P2"),
            ]),
            _topic("3. Chemical Bonding", "P1 · P2", 2, [
                _e("Ionic bonding — electron transfer; forming ions; giant ionic lattice", "P1, P2"),
                _e("Properties of ionic compounds — high mp/bp; conducts when molten/dissolved", "P1, P2"),
                _e("Covalent bonding — electron sharing; dot-and-cross diagrams", "P1, P2"),
                _e("Simple molecular structures — low mp/bp; non-conductors (e.g. H₂O, CO₂)", "P1, P2"),
                _e("Giant covalent structures — very high mp/bp; diamond, graphite, SiO₂", "P1, P2"),
                _e("Metallic bonding — positive ions in sea of delocalised electrons", "P1, P2"),
                _e("Properties of metals — malleable, ductile, conduct heat/electricity", "P1, P2"),
            ]),
            _topic("4. Stoichiometry — Chemical Calculations", "P1 · P2", 3, [
                _e("Relative atomic mass (Ar) and relative molecular mass (Mr)", "P1, P2"),
                _e("Mole concept — n = mass / Mr; Avogadro's constant 6.02×10²³", "P1, P2"),
                _e("Empirical formula — from percentage composition by mass", "P1, P2"),
                _e("Molecular formula — from empirical formula and Mr", "P1, P2"),
                _e("Molar gas volume — 24 dm³/mol at r.t.p.", "P1, P2"),
                _e("Concentration — c = n/V in mol/dm³", "P1, P2"),
                _e("Reacting masses — using mole ratios from balanced equations", "P1, P2"),
                _e("Percentage yield and limiting reagent", "P1, P2"),
            ]),
            _topic("5. Electrolysis", "P1 · P2 · P3", 4, [
                _e("Electrolytes — ionic compounds conduct when molten or in solution", "P1, P2"),
                _e("Electrolysis setup — electrolyte, anode (+), cathode (−), cell", "P1, P2"),
                _e("Products at electrodes — cations to cathode; anions to anode", "P1, P2"),
                _e("Electrolysis of dilute H₂SO₄ — H₂ at cathode, O₂ at anode", "P1, P2"),
                _e("Electrolysis of CuSO₄ — Cu at cathode, O₂ at anode; copper electrode", "P1, P2, P3"),
                _e("Electrolysis of concentrated brine — H₂, Cl₂, NaOH products", "P1, P2"),
                _e("Electroplating — object as cathode; plating metal as anode", "P1, P2"),
                _e("Industrial electrolysis — aluminium extraction; chlor-alkali industry", "P1, P2"),
            ]),
            _topic("6. Chemical Energetics", "P1 · P2", 5, [
                _e("Exothermic reactions — ΔH negative; heat released; examples", "P1, P2"),
                _e("Endothermic reactions — ΔH positive; heat absorbed; examples", "P1, P2"),
                _e("Bond breaking (endothermic) and bond making (exothermic)", "P1, P2"),
                _e("Energy level diagrams — reactants, products, Ea, ΔH", "P1, P2"),
                _e("Calculating ΔH from bond energies", "P1, P2"),
                _e("Measuring enthalpy change — combustion of fuels by experiment", "P1, P2, P3"),
            ]),
            _topic("7. Rates of Reaction", "P1 · P2 · P3", 6, [
                _e("Rate of reaction — definition; measuring by loss of mass or gas volume", "P1, P2, P3"),
                _e("Effect of temperature — higher T → more frequent high-energy collisions", "P1, P2"),
                _e("Effect of concentration — more particles → more frequent collisions", "P1, P2"),
                _e("Effect of surface area — powder vs lumps; more particles exposed", "P1, P2"),
                _e("Catalysts — lowers activation energy; not used up; industrial examples", "P1, P2"),
                _e("Collision theory — minimum energy (activation energy) required", "P1, P2"),
                _e("Interpreting rate graphs — comparing gradients and end-points", "P1, P2, P3"),
            ]),
            _topic("8. Acids, Bases and Salts", "P1 · P2 · P3", 7, [
                _e("Acids — H⁺ ions; pH < 7; common acids (HCl, H₂SO₄, HNO₃, CH₃COOH)", "P1, P2"),
                _e("Alkalis — OH⁻ ions; pH > 7; examples (NaOH, Ca(OH)₂, NH₃)", "P1, P2"),
                _e("pH scale and indicators — litmus, universal indicator, phenolphthalein", "P1, P2, P3"),
                _e("Acid + metal → salt + hydrogen (conditions and equations)", "P1, P2"),
                _e("Acid + base/alkali → salt + water (neutralisation; ionic equation)", "P1, P2"),
                _e("Acid + carbonate → salt + water + CO₂", "P1, P2"),
                _e("Preparing soluble salts — choosing appropriate reaction type", "P1, P2, P3"),
                _e("Preparing insoluble salts — precipitation method", "P1, P2, P3"),
                _e("Titration — procedure, concordant results, calculations", "P1, P2, P3"),
                _e("Ammonium salts — acid + ammonia; fertiliser applications", "P1, P2"),
            ]),
            _topic("9. Metals and Reactivity", "P1 · P2", 8, [
                _e("Reactivity series — K, Na, Ca, Mg, Al, (C), Zn, Fe, (H), Cu, Ag, Au, Pt", "P1, P2"),
                _e("Metal reactions — with cold water, steam, dilute acids; writing equations", "P1, P2"),
                _e("Displacement reactions — more reactive metal displaces less reactive", "P1, P2"),
                _e("Extraction of metals — carbon reduction (Fe, Zn) vs electrolysis (Al)", "P1, P2"),
                _e("Blast furnace — iron production; roles of limestone, coke, iron ore, air", "P1, P2"),
                _e("Rusting — conditions (water + oxygen); prevention (painting, galvanising, sacrificial)", "P1, P2"),
                _e("Aluminium — extraction by electrolysis of bauxite; Hall–Héroult process", "P1, P2"),
            ]),
            _topic("10. Air, Water and the Environment", "P1 · P2 · P3", 9, [
                _e("Composition of air — 78% N₂, 21% O₂, ~1% Ar, 0.04% CO₂", "P1, P2"),
                _e("Tests for gases — O₂, H₂, CO₂, NH₃, Cl₂; reagents and results", "P1, P2, P3"),
                _e("Tests for water — anhydrous CuSO₄ turns blue; cobalt chloride turns pink", "P1, P2, P3"),
                _e("Complete vs incomplete combustion — products and conditions", "P1, P2"),
                _e("Air pollution — CO, SO₂, NOₓ; acid rain; global warming; ozone depletion", "P1, P2"),
                _e("Water treatment — filtration, sedimentation, chlorination, pH adjustment", "P1, P2"),
                _e("Haber process — N₂ + 3H₂ ⇌ 2NH₃; 450°C, 200 atm, Fe catalyst", "P1, P2"),
                _e("Contact process — manufacture of H₂SO₄ via SO₂ → SO₃ → H₂SO₄", "P1, P2"),
            ]),
            _topic("11. Organic Chemistry", "P1 · P2", 10, [
                _e("Homologous series — same general formula; gradual change in properties", "P1, P2"),
                _e("Alkanes — CₙH₂ₙ₊₂; methane to butane; combustion reactions", "P1, P2"),
                _e("Crude oil and fractional distillation — fractions and their uses", "P1, P2"),
                _e("Cracking — breaking large hydrocarbons into smaller ones + alkenes", "P1, P2"),
                _e("Alkenes — CₙH₂ₙ; double bond; addition reactions (H₂, Br₂, H₂O)", "P1, P2"),
                _e("Test for alkenes — bromine water is decolourised", "P1, P2"),
                _e("Addition polymerisation — monomer → polymer; poly(ethene), PVC, PTFE", "P1, P2"),
                _e("Ethanol — fermentation (yeast + glucose, 37°C); industrial synthesis", "P1, P2"),
                _e("Carboxylic acids — ethanoic acid; reactions with metals, carbonates, alcohols", "P1, P2"),
                _e("Esters — esterification (acid + alcohol, acid catalyst); fragrances", "P1, P2"),
                _e("Condensation polymerisation — nylon; peptide bonds in proteins", "P1, P2"),
            ]),
        ],
    }


def syl_9618() -> dict:
    return {
        "code": "9618",
        "subject": "Computer Science",
        "level": "A Level",
        "name": "9618 A Level Computer Science — Study Planner",
        "papers": {
            "P1": "Theory AS (75 marks, 1 h 30 min)",
            "P2": "Written Algorithms AS (75 marks, 2 h)",
            "P3": "Advanced Theory A2 (75 marks, 1 h 30 min)",
            "P4": "Practical Programming A2 (75 marks, 2 h 30 min)",
        },
        "subfolder": "A Level",
        "groups": [
            _topic("1. Information Representation", "P1", 0, [
                _e("Binary, hexadecimal, denary conversions (including fractions)", "P1"),
                _e("Two's complement — representing negative integers; overflow", "P1"),
                _e("ASCII and Unicode — character encoding; UTF-8, UTF-16, UTF-32", "P1"),
                _e("Floating point — mantissa, exponent, bias; normalisation", "P1"),
                _e("Images — bitmap; pixels; bit depth; colour depth; resolution; file size", "P1"),
                _e("Sound — sampling; sample rate; bit depth; file size calculation", "P1"),
                _e("Compression — lossy vs lossless; run-length encoding; Huffman", "P1"),
            ]),
            _topic("2. Communication (AS)", "P1", 1, [
                _e("Network types — LAN, WAN, PAN; star, bus, ring topologies", "P1"),
                _e("Transmission media — copper, fibre optic, wireless; bandwidth, attenuation", "P1"),
                _e("Protocols — TCP/IP; layered model; encapsulation; socket", "P1"),
                _e("Error detection — parity bit, checksum, CRC", "P1"),
                _e("Serial and parallel transmission — comparison; bit rate vs baud rate", "P1"),
                _e("Wireless — Wi-Fi standards; Bluetooth; security risks", "P1"),
            ]),
            _topic("3. Hardware (P1)", "P1", 2, [
                _e("Logic gates — AND, OR, NOT, NAND, NOR, XOR; truth tables", "P1"),
                _e("Boolean algebra — simplification; De Morgan's laws", "P1"),
                _e("Half adder and full adder — logic circuits", "P1"),
                _e("Input/output devices — types and applications", "P1"),
                _e("Storage — primary (RAM/ROM), secondary (HDD, SSD, optical)", "P1"),
                _e("Embedded systems — microcontroller; real-time control; feedback loops", "P1"),
                _e("Cloud computing — SaaS, PaaS, IaaS; advantages and disadvantages", "P1"),
            ]),
            _topic("4. Processor Fundamentals (P1 & P3)", "P1 · P3", 3, [
                _e("Von Neumann architecture — ALU, CU, MAR, MDR, PC, ACC, IX", "P1, P3"),
                _e("Fetch–execute cycle — each stage in detail", "P1, P3"),
                _e("Addressing modes — immediate, direct, indirect, indexed", "P1, P3"),
                _e("Assembly language — mnemonics; writing and tracing programs", "P1, P3"),
                _e("Interrupts — types; interrupt service routine; saving registers", "P1, P3"),
                _e("Clock speed, cores and pipelining — effect on performance", "P1, P3"),
            ]),
            _topic("5. Algorithm Design & Problem Solving (P2 & P3)", "P2 · P3", 4, [
                _e("Pseudocode conventions — Cambridge pseudocode standards", "P2"),
                _e("Flowcharts — symbols and drawing algorithms", "P2"),
                _e("Linear search — algorithm; O(n) complexity", "P2, P3"),
                _e("Binary search — algorithm; requires sorted list; O(log n)", "P2, P3"),
                _e("Bubble sort — algorithm; O(n²) worst case; passes", "P2, P3"),
                _e("Insertion sort — algorithm; O(n²); efficient for nearly-sorted", "P2, P3"),
                _e("Merge sort — divide and conquer; O(n log n); stable", "P2, P3"),
                _e("Quicksort — pivot; O(n log n) average; in-place", "P2, P3"),
                _e("Recursion — base case; recursive case; call stack; stack frame", "P2, P3"),
                _e("Big-O notation — O(1), O(n), O(n²), O(log n), O(n log n)", "P2, P3"),
                _e("State transition diagrams — states, transitions, inputs, outputs", "P2, P3"),
            ]),
            _topic("6. Data Types and Structures (P2 & P3)", "P2 · P3", 5, [
                _e("Primitive types — integer, real, boolean, char, string; enumerated types", "P2, P3"),
                _e("Arrays — 1D and 2D; declaring, accessing, traversing in pseudocode", "P2, P3"),
                _e("Records — composite type; fields of different types", "P2, P3"),
                _e("Stack — LIFO; push, pop, peek; using array or linked list", "P2, P3"),
                _e("Queue — FIFO; enqueue, dequeue; linear and circular queue", "P2, P3"),
                _e("Linked list — node + pointer; insertion, deletion, traversal", "P2, P3"),
                _e("Binary tree — node, left/right child; in-order, pre-order, post-order traversal", "P2, P3"),
                _e("Hash table — hash function; collision handling; chaining; open addressing", "P2, P3"),
                _e("RPN / Postfix — converting infix to postfix; evaluating using stack", "P2, P3"),
            ]),
            _topic("7. Databases (P1 & P3)", "P1 · P3", 6, [
                _e("Database concepts — entity, attribute, primary key, foreign key", "P1, P3"),
                _e("Relational database — tables, relationships, referential integrity", "P1, P3"),
                _e("SQL — SELECT FROM WHERE, ORDER BY, GROUP BY, JOIN", "P1, P3"),
                _e("Normalisation — 1NF, 2NF, 3NF; removing redundancy", "P3"),
                _e("File types — serial, sequential, indexed sequential, random access", "P3"),
                _e("Record locking and deadlock — concurrency in multi-user databases", "P3"),
                _e("Transactions — ACID properties; commit and rollback", "P3"),
            ]),
            _topic("8. System Software A2 (P3)", "P3", 7, [
                _e("BNF / Backus–Naur Form — describing syntax; production rules", "P3"),
                _e("Syntax diagrams — railroad diagrams; reading and drawing", "P3"),
                _e("Compiler stages — lexical analysis (tokenising), syntax analysis, semantic analysis", "P3"),
                _e("Code generation and optimisation — intermediate and object code", "P3"),
                _e("FSM — finite state machine; state transition diagrams and tables", "P3"),
                _e("Scheduling — round-robin, SJF, priority; preemptive vs non-preemptive", "P3"),
                _e("Virtual memory — paging; page table; page fault; thrashing", "P3"),
                _e("Multitasking, threads and concurrent processes", "P3"),
                _e("Exception handling — types of error; runtime exceptions", "P3"),
            ]),
            _topic("9. Further Programming (P3 & P4)", "P3 · P4", 8, [
                _e("OOP — class, object, instantiation, encapsulation", "P3, P4"),
                _e("Inheritance — subclass, superclass, overriding methods", "P3, P4"),
                _e("Polymorphism — overloading and overriding", "P3, P4"),
                _e("Abstract classes and interfaces", "P3, P4"),
                _e("Exception handling — try, catch, finally, throw", "P3, P4"),
                _e("Declarative programming — Prolog; facts, rules, queries, backtracking", "P3"),
                _e("Functional programming — lambda, HOF, map/filter/reduce, immutability", "P3"),
                _e("Practical programming (P4) — implement all above in chosen language", "P4"),
            ]),
        ],
    }


def syl_9702() -> dict:
    return {
        "code": "9702",
        "subject": "Physics",
        "level": "A Level",
        "name": "9702 A Level Physics — Study Planner",
        "papers": {
            "P1": "MCQ AS (30 marks, 1 h)",
            "P2": "AS Structured (60 marks, 1 h 15 min)",
            "P3": "AS Practical (40 marks, 2 h)",
            "P4": "A2 Structured (100 marks, 2 h)",
            "P5": "A2 Planning & Analysis (30 marks, 1 h 15 min)",
        },
        "subfolder": "A Level",
        "groups": [
            _topic("1. Physical Quantities, Units & Measurement", "P1 · P2 · P3 · P5", 0, [
                _e("SI base units — kg, m, s, A, K, mol; derived units; homogeneity", "P1, P2"),
                _e("Scalars and vectors — resolving components; vector addition", "P1, P2"),
                _e("Absolute, fractional and percentage uncertainty", "P2, P3, P5"),
                _e("Systematic vs random errors; reducing uncertainty in experiments", "P2, P3, P5"),
                _e("Combining uncertainties — add absolute for ±; add % for × and ÷", "P2, P3, P5"),
                _e("Straight-line graphs — gradient, y-intercept; y = mx + c", "P2, P3, P5"),
                _e("Logarithmic graphs — ln y vs x; log y vs log x; extracting constants", "P2, P3, P5"),
            ]),
            _topic("2. Kinematics & Dynamics (AS)", "P1 · P2", 1, [
                _e("SUVAT equations — uniform acceleration; choosing the right equation", "P1, P2"),
                _e("Velocity-time graphs — area = displacement; gradient = acceleration", "P1, P2"),
                _e("Free fall — g = 9.81 m/s²; measuring g by free-fall experiment", "P1, P2, P3"),
                _e("Projectile motion — horizontal component constant; vertical free-fall", "P1, P2"),
                _e("Newton's Laws — First, Second (F = ma resultant), Third", "P1, P2"),
                _e("Linear momentum — p = mv; conservation in closed system", "P1, P2"),
                _e("Impulse — Ft = Δp; area under F–t graph", "P1, P2"),
                _e("Elastic vs inelastic collisions — KE conserved only in elastic", "P1, P2"),
            ]),
            _topic("3. Forces, Density and Pressure (AS)", "P1 · P2", 2, [
                _e("Types of forces — weight, normal, tension, friction, upthrust, drag", "P1, P2"),
                _e("Turning effect — moment = Fd; principle of moments; couple = Fd", "P1, P2"),
                _e("Centre of gravity — equilibrium conditions; three types of equilibrium", "P1, P2"),
                _e("Density — ρ = m/V; measuring density of solids and liquids", "P1, P2, P3"),
                _e("Pressure in fluids — P = hρg; Archimedes' principle and upthrust", "P1, P2"),
            ]),
            _topic("4. Work, Energy, Power (AS)", "P1 · P2", 3, [
                _e("Work — W = Fd cos θ; unit joule", "P1, P2"),
                _e("Gravitational PE (ΔEp = mgh) and KE (Ek = ½mv²)", "P1, P2"),
                _e("Conservation of energy and energy conversions", "P1, P2"),
                _e("Power — P = W/t = Fv; efficiency = useful output / total input", "P1, P2"),
            ]),
            _topic("5. Deformation of Solids (AS)", "P1 · P2", 4, [
                _e("Hooke's law — F = ke; spring constant k; limit of proportionality", "P1, P2"),
                _e("Elastic and plastic deformation; elastic limit", "P1, P2"),
                _e("Stress (σ = F/A) and strain (ε = ΔL/L); Young modulus E = σ/ε", "P1, P2"),
                _e("Stress–strain graph — proportional, elastic, plastic, necking, breaking", "P1, P2"),
                _e("Energy stored in a spring — E = ½Fe = ½ke² = area under F-e graph", "P1, P2"),
            ]),
            _topic("6. Waves and Superposition (AS)", "P1 · P2 · P3", 5, [
                _e("Progressive waves — λ, f, T, phase difference; v = fλ", "P1, P2"),
                _e("Intensity — I = P/A; I ∝ A²; I ∝ 1/r²", "P1, P2"),
                _e("Transverse and longitudinal waves; polarisation of transverse waves", "P1, P2"),
                _e("EM waves — all travel at c = 3×10⁸ m/s in vacuum", "P1, P2"),
                _e("Reflection, refraction and total internal reflection", "P1, P2"),
                _e("Diffraction — condition λ ≈ gap; Huygens' principle", "P1, P2"),
                _e("Young's double slit — λ = ax/D; fringe pattern", "P1, P2, P3"),
                _e("Diffraction grating — d sin θ = nλ; maxima pattern", "P1, P2"),
                _e("Stationary waves — nodes, antinodes; λ = 2L/n; measuring speed of sound", "P1, P2, P3"),
            ]),
            _topic("7. Electricity and D.C. Circuits (AS)", "P1 · P2 · P3", 6, [
                _e("Charge — Q = It; electron charge e = 1.6×10⁻¹⁹ C", "P1, P2"),
                _e("Current — I = ΔQ/Δt; conventional vs electron flow", "P1, P2"),
                _e("Resistance — Ohm's law; I–V characteristics (ohmic and non-ohmic)", "P1, P2, P3"),
                _e("Resistivity — ρ = RA/L; measuring by experiment", "P1, P2, P3"),
                _e("Power — P = IV = I²R = V²/R", "P1, P2"),
                _e("Kirchhoff's First Law — ΣI = 0 at a junction", "P1, P2"),
                _e("Kirchhoff's Second Law — ΣE = ΣIR around any loop", "P1, P2"),
                _e("Series and parallel resistors — total R and V/I relationships", "P1, P2"),
                _e("EMF and internal resistance — terminal PD = E − Ir", "P1, P2"),
                _e("Potential divider — voltage split; potentiometer; sensor circuits", "P1, P2"),
            ]),
            _topic("8. Particle Physics (AS)", "P1 · P2", 7, [
                _e("Atomic structure — nucleus, protons, neutrons; nuclide notation", "P1, P2"),
                _e("Isotopes — same Z, different A; radioactive isotopes", "P1, P2"),
                _e("Nuclear emissions — α, β⁻, β⁺, γ; properties and decay equations", "P1, P2"),
                _e("Photoelectric effect — hf = Φ + Ek(max); threshold frequency", "P1, P2"),
                _e("Electron energy levels — emission/absorption spectra; line spectra", "P1, P2"),
                _e("Wave-particle duality — de Broglie λ = h/mv; electron diffraction", "P1, P2"),
            ]),
            _topic("9. Circular Motion & Gravitational Fields (A2)", "P1 · P4", 8, [
                _e("Angular velocity — ω = v/r = 2πf; period T = 2π/ω", "P1, P4"),
                _e("Centripetal acceleration — a = v²/r = ω²r; centripetal force F = mv²/r", "P1, P4"),
                _e("Applications — banked tracks, conical pendulum, vertical circles", "P4"),
                _e("Newton's law of gravitation — F = Gm₁m₂/r²", "P1, P4"),
                _e("Gravitational field strength — g = F/m = GM/r²", "P1, P4"),
                _e("Gravitational potential — φ = −GM/r; work done = mΔφ", "P1, P4"),
                _e("Satellite orbits — geostationary; orbital speed and period", "P1, P4"),
            ]),
            _topic("10. Oscillations / SHM (A2)", "P1 · P4", 9, [
                _e("SHM definition — a = −ω²x; restoring force proportional to displacement", "P1, P4"),
                _e("Equations — x = x₀ sin ωt; v = ω√(x₀² − x²); amax = ω²x₀", "P1, P4"),
                _e("Energy in SHM — total E constant; KE max at equilibrium; PE max at extremes", "P1, P4"),
                _e("Damping — light, heavy, critical; overdamped; Q factor", "P1, P4"),
                _e("Resonance — driving frequency = natural frequency; forced oscillations", "P4"),
                _e("Simple pendulum — T = 2π√(L/g); experiment to measure g", "P1, P4, P3"),
            ]),
            _topic("11. Temperature and Ideal Gases (A2)", "P1 · P4", 10, [
                _e("Thermal equilibrium; absolute zero (0 K = −273.15 °C)", "P1, P4"),
                _e("Ideal gas laws — Boyle's, Charles', pressure-temperature law", "P1, P4"),
                _e("Ideal gas equation — pV = nRT = NkT", "P1, P4"),
                _e("Assumptions of an ideal gas — kinetic theory model", "P1, P4"),
                _e("Mean kinetic energy — ½m⟨c²⟩ = 3/2 kT", "P1, P4"),
                _e("First Law of Thermodynamics — ΔU = q + w", "P1, P4"),
            ]),
            _topic("12. Electric and Magnetic Fields (A2)", "P1 · P4", 11, [
                _e("Coulomb's law — F = kQ₁Q₂/r²; electric field strength E = F/Q", "P1, P4"),
                _e("Uniform electric field — E = V/d; motion of charges between plates", "P1, P4"),
                _e("Electric potential — V = kQ/r; work done W = QΔV", "P1, P4"),
                _e("Capacitance — C = Q/V; parallel plate C = ε₀εᵣA/d", "P1, P4"),
                _e("Series and parallel capacitors; energy stored W = ½CV²", "P1, P4"),
                _e("Capacitor charge/discharge — Q = Q₀e^(−t/RC); time constant τ = RC", "P1, P4"),
                _e("Magnetic flux density B; force F = BIL sin θ; left-hand rule", "P1, P4"),
                _e("Force on moving charge — F = BQv; circular motion in magnetic field", "P1, P4"),
                _e("Faraday's law — EMF = −d(NΦ)/dt; Lenz's law", "P1, P4"),
                _e("AC — rms values Vrms = V₀/√2; transformer turns ratio; power transmission", "P1, P4"),
            ]),
            _topic("13. Quantum and Nuclear Physics (A2)", "P1 · P4", 0, [
                _e("Photoelectric effect — stopping potential; work function Φ; hf = Φ + Ek", "P1, P4"),
                _e("Energy levels — photon emission E = hf; absorption spectra", "P1, P4"),
                _e("de Broglie wavelength λ = h/p; wave-particle duality", "P1, P4"),
                _e("Mass defect and binding energy — E = mc²; binding energy per nucleon", "P1, P4"),
                _e("Nuclear fission — chain reaction; critical mass; energy released", "P1, P4"),
                _e("Nuclear fusion — conditions; energy per nucleon; stars", "P1, P4"),
                _e("Radioactive decay — A, β⁻, β⁺, EC, γ; decay equations", "P1, P4"),
                _e("Decay law — A = λN; N = N₀e^(−λt); half-life T½ = ln2/λ", "P1, P4"),
            ]),
        ],
    }


ALL = {
    "4024": syl_4024,
    "5054": syl_5054,
    "5070": syl_5070,
    "9618": syl_9618,
    "9702": syl_9702,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--syllabuses", nargs="*", default=list(ALL.keys()))
    args = parser.parse_args()

    for code in args.syllabuses:
        if code not in ALL:
            print(f"  [skip] Unknown: {code}", file=sys.stderr)
            continue
        syl = ALL[code]()
        subfolder = OUT_ROOT / syl["subfolder"]
        subfolder.mkdir(parents=True, exist_ok=True)
        out = subfolder / f"{code} {syl['subject']} Study Plan.pdf"
        p = PDFPlanner(out, syl)
        p.build()
        pages = p.page_n
        print(f"  [ok] {out.relative_to(ROOT)}  ({pages} pages, {p.cb_idx} checkboxes)")

    print(f"\nDone. PDFs in: {OUT_ROOT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
