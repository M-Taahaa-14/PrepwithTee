"""Downloadable MCQ review PDF.

After a live MCQ session the student gets a branded A4 booklet containing, for
every question they saw:

  * the original vector question crop (never re-typeset — the same rule the
    whole pipeline lives by),
  * which option they picked, coloured green when right and red when wrong,
  * the official mark-scheme answer highlighted in green,
  * the worked explanation, so the booklet is reviewable away from the site.

Layout and branding are borrowed wholesale from `pipeline.compose` so the
review PDF, the topical booklets and the mock tests all look like one product.

The explanation HTML comes from the model as a small fixed subset of tags
(<h3> <p> <ol> <ul> <li> <strong> <code>), which `_Flow` turns into flowed
PDF text — there is no browser in the loop and no HTML engine to pull in.
"""

from __future__ import annotations

import html as _html
import re
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import fitz

from pipeline import config
from pipeline.compose import (
    BOTTOM_Y, CONTENT_W, MARGIN_X, PAGE_H, PAGE_W, TOP_Y,
    brand_backdrop, footer_band, page_watermark, _centre, _wrap,
)

ROOT = Path(__file__).resolve().parent.parent

GREY = (0.35, 0.35, 0.35)
LIGHT_GREY = (0.62, 0.62, 0.62)
BLACK = (0.08, 0.08, 0.08)
ACCENT = config.BRAND_NAVY
GOLD = config.BRAND_GOLD
CREAM = config.BRAND_CREAM

# Result palette. Deliberately the same greens and reds the live solver uses,
# but darkened for ink: #4ade80 on paper is barely visible.
GREEN_INK = (0.05, 0.44, 0.29)
GREEN_FILL = (0.82, 0.98, 0.90)
RED_INK = (0.61, 0.11, 0.11)
RED_FILL = (1.00, 0.89, 0.90)
AMBER_INK = (0.57, 0.25, 0.05)
AMBER_FILL = (1.00, 0.95, 0.78)

SESSION_LABELS = {"s": "May/June", "w": "Oct/Nov", "m": "Feb/March"}


# ── Latin-1 transliteration ────────────────────────────────────────────────
#
# PyMuPDF's base-14 fonts are Latin-1 only, and they fail SILENTLY: anything
# outside it is drawn as a middle dot. Explanations are full of exactly the
# characters that fall outside — the explainer prompt asks for √, π, Δ, ≈ and
# superscripts — so "v = √(2gh)" would print as "v = ·(2gh)", which is not
# merely ugly, it is a different equation.
#
# Embedding a Unicode TTF would mean shipping a font file and trusting it to
# exist on the server, so instead every string is rewritten into characters
# Latin-1 can actually carry, before it reaches insert_text.

_SUPERSCRIPTS = "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ"
_SUPER_PLAIN = "0123456789+-=()n"
_SUBSCRIPTS = "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎"
_SUB_PLAIN = "0123456789+-=()"

_CHAR_MAP = {
    # Maths
    "√": "sqrt", "∛": "cbrt", "∞": "infinity", "∝": " proportional to ",
    "≈": "~=", "≃": "~=", "≅": "~=", "≠": "!=", "≤": "<=", "≥": ">=",
    "→": "->", "←": "<-", "⇒": "=>", "⇌": "<=>", "⇋": "<=>", "↔": "<->",
    "∑": "sum", "∫": "integral", "∂": "d", "∆": "delta", "·": "·",
    "−": "-", "‐": "-", "‑": "-", "–": "-", "—": "-", "⁄": "/", "∙": "·",
    "≡": "=", "∓": "-/+", "⌀": "diameter",
    # Punctuation the models reach for
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "…": "...", "•": "-", "‰": "per mille", "™": "(TM)",
    " ": " ", " ": " ", " ": " ", "​": "",
}

# Greek is spelled out, which is how a student reads it aloud anyway. Handled
# apart from _CHAR_MAP so a space can be added when the letter runs straight
# into a symbol — a plain replace turns "Δp" into "deltap".
_GREEK_MAP = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "Δ": "delta",
    "ε": "epsilon", "η": "eta", "θ": "theta", "Θ": "theta", "κ": "kappa",
    "λ": "lambda", "Λ": "lambda", "ν": "nu", "ξ": "xi", "π": "pi", "Π": "pi",
    "ρ": "rho", "σ": "sigma", "Σ": "sigma", "τ": "tau", "φ": "phi",
    "Φ": "phi", "χ": "chi", "ψ": "psi", "ω": "omega", "Ω": "ohm",
}
_GREEK_RE = re.compile("([" + "".join(_GREEK_MAP) + r"])(?=[A-Za-z0-9(])")

# A run of superscripts becomes ^2 / ^-1 rather than being kept where Latin-1
# happens to have the glyph: mixing "m²" and "m^-1" in one line reads worse
# than making both explicit.
_SUP_RUN = re.compile(f"[{_SUPERSCRIPTS}]+")
_SUB_RUN = re.compile(f"[{_SUBSCRIPTS}]+")
_SUP_TABLE = str.maketrans(_SUPERSCRIPTS, _SUPER_PLAIN)
_SUB_TABLE = str.maketrans(_SUBSCRIPTS, _SUB_PLAIN)


def pdf_text(s) -> str:
    """Rewrite a string into something the base-14 fonts can actually draw.

    Latin-1 characters a Cambridge paper genuinely uses — ° ± × ÷ µ · ½ — are
    left alone; everything else is transliterated or dropped.
    """
    if not s:
        return ""
    t = str(s)
    t = _SUP_RUN.sub(lambda m: "^" + m.group(0).translate(_SUP_TABLE), t)
    t = _SUB_RUN.sub(lambda m: "_" + m.group(0).translate(_SUB_TABLE), t)
    # Spaced form first (Δp -> "delta p"), then the rest (Δ -> "delta").
    t = _GREEK_RE.sub(lambda m: _GREEK_MAP[m.group(1)] + " ", t)
    for k, v in _GREEK_MAP.items():
        if k in t:
            t = t.replace(k, v)
    for k, v in _CHAR_MAP.items():
        if k in t:
            t = t.replace(k, v)
    # Anything still unmappable is dropped rather than drawn as a stray dot —
    # a missing character is easier to read past than a wrong one.
    return t.encode("latin-1", "ignore").decode("latin-1")


# ── HTML → flowed PDF text ─────────────────────────────────────────────────

class _Block:
    """One renderable paragraph: a style, some text, and an optional bullet."""

    def __init__(self, style: str, text: str, bullet: str = ""):
        self.style = style          # "h3" | "p" | "li"
        self.text = text
        self.bullet = bullet


class _ExplanationParser(HTMLParser):
    """Flatten the explainer's HTML subset into a list of _Block.

    Inline <strong>/<code>/<em> are folded into the text rather than tracked as
    runs: the worked solutions are short and this keeps the renderer to one
    font per block, which is what makes the wrapping trivially correct.
    <code> is marked with thin brackets so an equation still reads as a unit.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[_Block] = []
        self._buf: list[str] = []
        self._style = "p"
        self._bullet = ""
        self._list_stack: list[list] = []   # each entry: ["ol", counter] | ["ul"]

    # -- helpers --
    def _flush(self):
        text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        self._buf = []
        if text:
            self.blocks.append(_Block(self._style, text, self._bullet))
        self._bullet = ""

    # -- parser hooks --
    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2", "h3", "h4", "p"):
            self._flush()
            self._style = "h3" if tag.startswith("h") else "p"
        elif tag in ("ol", "ul"):
            self._flush()
            self._list_stack.append([tag, 0])
        elif tag == "li":
            self._flush()
            self._style = "li"
            if self._list_stack:
                top = self._list_stack[-1]
                if top[0] == "ol":
                    top[1] += 1
                    self._bullet = f"{top[1]}."
                else:
                    # U+00B7, not U+2022: the base-14 fonts have the former.
                    self._bullet = "·"
            else:
                self._bullet = "•"
        elif tag == "br":
            self._buf.append(" ")

    def handle_endtag(self, tag):
        if tag in ("h1", "h2", "h3", "h4", "p", "li"):
            self._flush()
            self._style = "p"
        elif tag in ("ol", "ul"):
            self._flush()
            if self._list_stack:
                self._list_stack.pop()
            self._style = "p"

    def handle_data(self, data):
        self._buf.append(data)

    def close(self):
        super().close()
        self._flush()


def parse_explanation(html: str) -> list[_Block]:
    """Explanation HTML → blocks. Bad markup degrades to one plain paragraph."""
    if not html:
        return []
    try:
        p = _ExplanationParser()
        p.feed(html)
        p.close()
        if p.blocks:
            for b in p.blocks:
                b.text = pdf_text(b.text)
            return p.blocks
    except Exception:
        pass
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", _html.unescape(text)).strip()
    return [_Block("p", pdf_text(text))] if text else []


# ── Booklet ────────────────────────────────────────────────────────────────

class _Flow:
    """A4 flow layout: content is placed down a cursor and pages break for it.

    A trimmed-down sibling of `compose.Booklet` — the review PDF needs coloured
    callouts and wrapped prose, which the booklet class has no notion of, but
    the page furniture (watermark first, brand footer, page number) is kept
    byte-identical so the two outputs stack on a desk without looking related
    by accident.
    """

    def __init__(self):
        self.doc = fitz.open()
        self.page = None
        self.y = TOP_Y
        self.body_pages = 0

    # -- page management --
    def new_page(self):
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.body_pages += 1
        page_watermark(self.page)     # first, so all content paints over it
        self.page.insert_text((MARGIN_X, PAGE_H - 22), config.BRAND_NAME,
                              fontsize=7.5, fontname="hebo", color=ACCENT)
        num = f"Page {self.body_pages}"
        w = fitz.get_text_length(num, fontname="helv", fontsize=7)
        self.page.insert_text(((PAGE_W - w) / 2, PAGE_H - 22), num,
                              fontsize=7, fontname="helv", color=GREY)
        self.y = TOP_Y

    def ensure(self, height: float):
        if self.page is None or self.y + height > BOTTOM_Y:
            self.new_page()

    def space(self, h: float):
        self.y += h

    # -- text --
    def text_block(self, blocks: list[_Block], x0: float = None,
                   width: float = None):
        """Flow parsed explanation blocks, breaking pages between lines."""
        x0 = MARGIN_X + 10 if x0 is None else x0
        width = (CONTENT_W - 20) if width is None else width
        for b in blocks:
            if b.style == "h3":
                font, size, colour, lead = "hebo", 9.5, ACCENT, 13.0
                self.space(4)
            elif b.style == "li":
                font, size, colour, lead = "helv", 9.0, BLACK, 12.0
            else:
                font, size, colour, lead = "helv", 9.0, BLACK, 12.0

            indent = 16.0 if b.style == "li" else 0.0
            lines = _wrap(b.text, font, size, width - indent)
            for i, line in enumerate(lines):
                self.ensure(lead)
                if i == 0 and b.bullet:
                    self.page.insert_text((x0, self.y + size), b.bullet,
                                          fontsize=size, fontname="hebo",
                                          color=GREY)
                self.page.insert_text((x0 + indent, self.y + size), line,
                                      fontsize=size, fontname=font, color=colour)
                self.y += lead
            self.space(2)

    # -- question furniture --
    def question_header(self, n: int, ref: str, result: str, keep: float = 90):
        """'Q7' plus the Cambridge source ref and a coloured result chip."""
        ref = pdf_text(ref)
        self.ensure(24 + min(keep, BOTTOM_Y - TOP_Y - 24))
        bar_w = 4.0
        self.page.draw_rect(
            fitz.Rect(MARGIN_X, self.y + 2, MARGIN_X + bar_w, self.y + 20),
            color=None, fill=ACCENT)
        label = f"Q{n}"
        lx = MARGIN_X + bar_w + 6
        self.page.insert_text((lx, self.y + 13), label, fontsize=12,
                              fontname="hebo", color=ACCENT)
        x = lx + fitz.get_text_length(label, fontname="hebo", fontsize=12)
        self.page.insert_text((x + 8, self.y + 12), ref, fontsize=8.5,
                              fontname="helv", color=GREY)
        self._chip_right(result, self.y + 2)
        rule_y = self.y + 21
        self.page.draw_line(fitz.Point(MARGIN_X, rule_y),
                            fitz.Point(PAGE_W - MARGIN_X, rule_y),
                            color=GOLD, width=0.6)
        self.y += 26

    def _chip_right(self, result: str, y: float):
        text, ink, fill = _result_chip(result)
        w = fitz.get_text_length(text, fontname="hebo", fontsize=7.5) + 16
        r = fitz.Rect(PAGE_W - MARGIN_X - w, y, PAGE_W - MARGIN_X, y + 15)
        self.page.draw_rect(r, color=None, fill=fill, radius=0.35)
        self.page.insert_text((r.x0 + 8, r.y0 + 10.5), text, fontsize=7.5,
                              fontname="hebo", color=ink)

    def image(self, png: bytes, max_h: float = 430.0):
        """Place the question crop, scaled to the text column."""
        try:
            pix = fitz.Pixmap(png)
        except Exception:
            return
        w = CONTENT_W
        h = w * pix.height / pix.width
        if h > max_h:
            h = max_h
            w = h * pix.width / pix.height
        # A crop taller than a whole page is placed on its own page and scaled
        # to fit rather than being clipped in half by the flow.
        self.ensure(h)
        r = fitz.Rect(MARGIN_X, self.y, MARGIN_X + w, self.y + h)
        self.page.insert_image(r, pixmap=pix)
        self.y += h + 6

    def answer_row(self, your: str | None, correct: str | None, result: str,
                   time_secs: int | None):
        """The A/B/C/D strip: the student's pick and the mark-scheme answer."""
        self.ensure(34)
        y0 = self.y
        box = fitz.Rect(MARGIN_X, y0, PAGE_W - MARGIN_X, y0 + 28)
        self.page.draw_rect(box, color=(0.88, 0.88, 0.88), fill=(0.98, 0.98, 0.98),
                            width=0.6, radius=0.25)
        x = MARGIN_X + 10
        for letter in ("A", "B", "C", "D"):
            is_correct = correct is not None and letter == correct
            is_yours = your is not None and letter == your
            if is_correct:
                ink, fill = GREEN_INK, GREEN_FILL
            elif is_yours:
                ink, fill = RED_INK, RED_FILL
            else:
                ink, fill = LIGHT_GREY, (1, 1, 1)
            cell = fitz.Rect(x, y0 + 5, x + 22, y0 + 23)
            self.page.draw_rect(cell, color=ink, fill=fill, width=0.9, radius=0.3)
            lw = fitz.get_text_length(letter, fontname="hebo", fontsize=10)
            self.page.insert_text((cell.x0 + (22 - lw) / 2, cell.y0 + 13), letter,
                                  fontsize=10, fontname="hebo", color=ink)
            # Marker under the letter the student actually chose, so the row is
            # still readable when their pick WAS the correct one. Drawn, not
            # typed: the base-14 fonts have no triangle glyph.
            if is_yours:
                _up_triangle(self.page, cell.x0 + 11, cell.y1 + 2.5, 4.0,
                             GREEN_INK if is_correct else RED_INK)
            x += 30

        parts = []
        parts.append(f"Your answer: {your}" if your else "Not answered")
        if correct:
            parts.append(f"Mark scheme: {correct}")
        if time_secs is not None:
            parts.append(f"{time_secs} s")
        note = "     ".join(parts)
        nw = fitz.get_text_length(note, fontname="helv", fontsize=8.5)
        ink = (GREEN_INK if result == "correct"
               else RED_INK if result == "wrong" else GREY)
        self.page.insert_text((box.x1 - 10 - nw, y0 + 18), note, fontsize=8.5,
                              fontname="helv", color=ink)
        self.y += 34

    def note(self, text: str, ink=GREY):
        self.ensure(14)
        self.page.insert_text((MARGIN_X + 10, self.y + 9), pdf_text(text),
                              fontsize=8.5, fontname="helv", color=ink)
        self.y += 14

    def divider(self):
        if self.page is not None and self.y + 14 < BOTTOM_Y:
            self.page.draw_line(fitz.Point(MARGIN_X, self.y + 7),
                                fitz.Point(PAGE_W - MARGIN_X, self.y + 7),
                                color=(0.82, 0.82, 0.82), width=0.5)
            self.y += 16


def _up_triangle(page, cx: float, top_y: float, size: float, colour):
    """Small solid ▲ pointing at the cell above it."""
    pts = [fitz.Point(cx - size / 2, top_y + size * 0.85),
           fitz.Point(cx + size / 2, top_y + size * 0.85),
           fitz.Point(cx, top_y)]
    page.draw_polyline(pts, color=None, fill=colour, closePath=True)


def _result_chip(result: str):
    return {
        "correct": ("CORRECT", GREEN_INK, GREEN_FILL),
        "wrong":   ("WRONG", RED_INK, RED_FILL),
        "skipped": ("SKIPPED", AMBER_INK, AMBER_FILL),
        "no-key":  ("SELF-CHECK", ACCENT, (0.90, 0.92, 0.98)),
    }.get(result, ("NOT ANSWERED", GREY, (0.94, 0.94, 0.94)))


# ── Cover ──────────────────────────────────────────────────────────────────

def _cover(doc, summary: dict):
    """Cream branded cover carrying the score, exactly like the topical cover
    but with the session result where the topic title normally sits."""
    page = brand_backdrop(doc)

    title = pdf_text(summary.get("title") or "MCQ Session Review")
    _centre(page, "MCQ SESSION REVIEW", 262, 9, "hebo", GOLD)
    for i, line in enumerate(_wrap(title, "hebo", 21, CONTENT_W - 60)[:2]):
        _centre(page, line, 292 + i * 26, 21, "hebo", ACCENT)

    # Score card
    card = fitz.Rect(MARGIN_X + 40, 348, PAGE_W - MARGIN_X - 40, 470)
    page.draw_rect(card, color=ACCENT, fill=(1, 1, 1), width=1.1, radius=0.2)

    score = f"{summary.get('correct', 0)} / {summary.get('attempted', 0)}"
    _centre(page, score, 396, 30, "hebo", ACCENT)
    _centre(page, f"{summary.get('pct', 0)}% correct", 416, 11, "helv", GREY)

    stats = [
        ("Correct", str(summary.get("correct", 0))),
        ("Wrong", str(summary.get("wrong", 0))),
        ("Skipped", str(summary.get("skipped", 0))),
        ("Time", summary.get("time_label", "—")),
    ]
    cw = (card.width - 24) / len(stats)
    for i, (lbl, val) in enumerate(stats):
        cx = card.x0 + 12 + cw * i + cw / 2
        vw = fitz.get_text_length(val, fontname="hebo", fontsize=13)
        page.insert_text((cx - vw / 2, 445), val, fontsize=13,
                         fontname="hebo", color=ACCENT)
        lw = fitz.get_text_length(lbl, fontname="helv", fontsize=8)
        page.insert_text((cx - lw / 2, 458), lbl, fontsize=8,
                         fontname="helv", color=GREY)

    sub = summary.get("subtitle")
    if sub:
        _centre(page, pdf_text(sub), 492, 9.5, "helv", GREY)

    # Legend. The triangle is drawn rather than typed, so the line is built in
    # two pieces around it instead of centred as one string.
    legend_a = "Green = the mark-scheme answer."
    legend_b = "= the option you chose"
    aw = fitz.get_text_length(legend_a, fontname="helv", fontsize=8.5)
    bw = fitz.get_text_length(legend_b, fontname="helv", fontsize=8.5)
    total = aw + 8 + 7 + 4 + bw
    lx = (PAGE_W - total) / 2
    page.insert_text((lx, 514), legend_a, fontsize=8.5, fontname="helv", color=GREY)
    _up_triangle(page, lx + aw + 8 + 3.5, 508, 6.0, GREY)
    page.insert_text((lx + aw + 8 + 7 + 4, 514), legend_b, fontsize=8.5,
                     fontname="helv", color=GREY)

    footer_band(page, f"Generated {date.today().isoformat()}")
    return page


# Column origins for the "At a glance" table, measured from the left margin.
_C_REF = 34.0
_C_TOPIC = 176.0
_C_YOURS = 396.0
_C_ANSWER = 434.0
_C_RESULT = 472.0


def _contents_head(flow: _Flow, continued: bool = False):
    flow.new_page()
    title = "At a glance (continued)" if continued else "At a glance"
    flow.page.insert_text((MARGIN_X, flow.y + 14), title, fontsize=15,
                          fontname="hebo", color=ACCENT)
    flow.page.draw_line(fitz.Point(MARGIN_X, flow.y + 20),
                        fitz.Point(PAGE_W - MARGIN_X, flow.y + 20),
                        color=ACCENT, width=1.2)
    flow.y += 30
    for label, dx in (("Question", _C_REF), ("Topic", _C_TOPIC),
                      ("Yours", _C_YOURS), ("Answer", _C_ANSWER),
                      ("Result", _C_RESULT)):
        flow.page.insert_text((MARGIN_X + dx, flow.y + 8), label.upper(),
                              fontsize=6.5, fontname="hebo", color=GREY)
    flow.y += 13


def _contents(flow: _Flow, items: list[dict]):
    """One-line-per-question index, so a wrong answer can be found at a glance.

    "Yours" and "Answer" are separate labelled columns rather than one
    "B -> C" cell: with no arrow glyph in the base-14 fonts, a joined cell
    would have to spell the arrow out, and two columns read better anyway.
    """
    _contents_head(flow)
    for it in items:
        if flow.y + 15 > BOTTOM_Y:
            _contents_head(flow, continued=True)
        text, ink, fill = _result_chip(it["result"])
        row_y = flow.y
        dot = fitz.Rect(MARGIN_X, row_y + 1, MARGIN_X + 26, row_y + 13)
        flow.page.draw_rect(dot, color=None, fill=fill, radius=0.3)
        nl = f"Q{it['n']}"
        nw = fitz.get_text_length(nl, fontname="hebo", fontsize=7.5)
        flow.page.insert_text((dot.x0 + (26 - nw) / 2, row_y + 10), nl,
                              fontsize=7.5, fontname="hebo", color=ink)
        flow.page.insert_text((MARGIN_X + _C_REF, row_y + 10),
                              pdf_text(it.get("ref") or ""),
                              fontsize=8, fontname="helv", color=GREY)
        topic = pdf_text(it.get("topic") or "")
        topic = (_wrap(topic, "helv", 8, _C_YOURS - _C_TOPIC - 8) or [""])[0]
        flow.page.insert_text((MARGIN_X + _C_TOPIC, row_y + 10), topic,
                              fontsize=8, fontname="helv", color=BLACK)
        flow.page.insert_text((MARGIN_X + _C_YOURS, row_y + 10),
                              it.get("your") or "-",
                              fontsize=8, fontname="hebo", color=ink)
        flow.page.insert_text((MARGIN_X + _C_ANSWER, row_y + 10),
                              it.get("correct") or "?",
                              fontsize=8, fontname="hebo", color=GREEN_INK)
        flow.page.insert_text((MARGIN_X + _C_RESULT, row_y + 10), text,
                              fontsize=7, fontname="helv", color=ink)
        flow.y += 15


# ── Entry point ────────────────────────────────────────────────────────────

def build_report(summary: dict, items: list[dict], out_path: Path,
                 progress=None) -> Path:
    """Write the review PDF.

    `items` is one dict per question, in booklet order:
        n, ref, topic, your, correct, result, time_secs,
        png (bytes | None), explanation (html str | None)

    `progress` is an optional callable(done, total) so a caller running this in
    a worker thread can report how far it has got.
    """
    flow = _Flow()
    _cover(flow.doc, summary)
    if items:
        _contents(flow, items)

    total = len(items)
    for i, it in enumerate(items):
        # Start each question on a fresh page. Question crops are tall and a
        # split one is exactly the thing that makes a review sheet unusable.
        flow.new_page()
        flow.question_header(it["n"], it.get("ref") or "", it.get("result") or "")
        topic = it.get("topic")
        if topic:
            flow.note(topic, LIGHT_GREY)

        if it.get("png"):
            flow.image(it["png"])
        else:
            flow.note("[question image unavailable — see the original paper]",
                      LIGHT_GREY)

        flow.answer_row(it.get("your"), it.get("correct"),
                        it.get("result") or "", it.get("time_secs"))

        expl = it.get("explanation")
        if expl:
            flow.space(4)
            flow.ensure(30)
            flow.page.insert_text((MARGIN_X, flow.y + 9), "HOW TO DO IT",
                                  fontsize=8, fontname="hebo", color=GOLD)
            flow.y += 14
            flow.text_block(parse_explanation(expl))
        else:
            flow.note("Worked explanation not available for this question.",
                      LIGHT_GREY)

        if progress:
            progress(i + 1, total)

    if flow.page is None:
        flow.new_page()
        flow.note("This session had no questions to review.")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    flow.doc.save(str(out_path), deflate=True, garbage=3)
    flow.doc.close()
    return out_path
