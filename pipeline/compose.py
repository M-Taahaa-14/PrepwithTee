"""Stage 5: compose filtered topical PDFs from the indexed crops.

    python -m pipeline.compose --syllabus 5054 --topics "Motion,Forces,Momentum" --from 2023 --to 2025
    python -m pipeline.compose --syllabus 5054 --topics Light --no-ms --out my.pdf

Builds an A4 booklet at runtime from any filter combination: topics (chapter
names from taxonomy/), year range, paper, variant. Each question is placed as
its original vector regions (never re-typeset), followed immediately by its
mark-scheme entry (tutor's requested layout, 2026-07-16; suppress with
--no-ms). Mark-scheme regions are landscape and get scaled to the portrait
content width.

A question is included if its primary topic matches a selected topic; a
question whose *secondary* topic matches is included too and marked
'also covers ...' in its header. Each question appears exactly once, under
the first selected topic it matches (primary preferred).
"""

import argparse
import json
import re
from datetime import date

import fitz

from . import config, db, heuristics, setup_logging

log = setup_logging("compose")

PAGE_W, PAGE_H = 595.28, 841.89          # A4 portrait
MARGIN_X = 24.0
TOP_Y = 40.0
BOTTOM_Y = PAGE_H - 72.0          # 62 footer band + 10px gap
CONTENT_W = PAGE_W - 2 * MARGIN_X
Q_HEADER_H = 18.0
MS_LABEL_H = 14.0
TOPIC_HEADER_H = 30.0
DIVIDER_GAP = 14.0

GREY = (0.35, 0.35, 0.35)
BLACK = (0, 0, 0)
ACCENT = config.BRAND_NAVY
GOLD = config.BRAND_GOLD
CREAM = config.BRAND_CREAM


_WM_CACHE: dict = {}
_WM_XREF: dict[int, int] = {}   # doc id → image xref (reuse avoids embedding once per page)
WM_STRENGTH = 0.12     # max ink of the owl watermark (0..1); lower = fainter
WM_TEXT_GREY = 0.92    # wordmark grey (on white, this reads ~8% ink)


def _watermark_owl():
    """Faint grayscale owl for the body-page watermark (cached).

    Black-and-white per the tutor's request (2026-07-19). The watermark is
    always the first paint on a blank white page, so instead of a real alpha
    channel (Pixmap.set_alpha premultiplies the samples and blackens the
    background - tried and reverted) the transparency is pre-blended: every
    pixel is mixed onto white at WM_STRENGTH, and near-background pixels are
    snapped to pure white so the image edge is invisible on the page.
    """
    if "owl" not in _WM_CACHE:
        clip = fitz.IRect(*config.LOGO_OWL_CLIP)
        src = fitz.Pixmap(str(config.LOGO_PATH))
        rgb = fitz.Pixmap(fitz.csRGB, clip, False)
        rgb.copy(src, clip)
        gray = fitz.Pixmap(fitz.csGRAY, rgb)
        faint = bytes(
            255 if s >= 200 else 255 - int(WM_STRENGTH * (255 - s))
            for s in gray.samples)
        _WM_CACHE["owl"] = fitz.Pixmap(fitz.csGRAY, gray.w, gray.h, faint, 0)
    return _WM_CACHE["owl"]


def page_watermark(page):
    """Faint centred PrepWithTee watermark on a body page.

    Called FIRST, before any content lands on the page: PDF paint order means
    everything drawn later (question crops, MS crops, headers) sits on top, so
    the watermark stays behind the text layer and can never cover content.
    """
    if config.LOGO_PATH.exists():
        pix = _watermark_owl()
        h = 300.0
        w = h * pix.width / pix.height
        r = fitz.Rect((PAGE_W - w) / 2, (PAGE_H - h) / 2 - 26,
                      (PAGE_W + w) / 2, (PAGE_H + h) / 2 - 26)
        doc_id = id(page.parent)
        xref = _WM_XREF.get(doc_id)
        if xref:
            page.insert_image(r, xref=xref)
        else:
            _WM_XREF[doc_id] = page.insert_image(r, pixmap=pix)
        ty = r.y1 + 40
    else:
        ty = PAGE_H / 2
    fs = 30
    tw = fitz.get_text_length(config.BRAND_NAME, fontname="hebo", fontsize=fs)
    page.insert_text(((PAGE_W - tw) / 2, ty), config.BRAND_NAME, fontsize=fs,
                     fontname="hebo",
                     color=(WM_TEXT_GREY, WM_TEXT_GREY, WM_TEXT_GREY))


class Booklet:
    """A4 flow layout: items are placed down a cursor with page breaks."""

    def __init__(self):
        self.doc = fitz.open()
        self.page = None
        self.y = TOP_Y
        self.body_pages = 0

    def new_page(self):
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.body_pages += 1
        page_watermark(self.page)   # first, so all content paints over it
        footer_band(self.page, right_text=f"Page {self.body_pages}")
        self.y = TOP_Y

    def ensure(self, height: float):
        if self.page is None or self.y + height > BOTTOM_Y:
            self.new_page()

    def topic_header(self, name: str):
        self.ensure(TOPIC_HEADER_H + 80)   # keep with following content
        self.page.insert_text((MARGIN_X, self.y + 16), name,
                              fontsize=15, fontname="hebo", color=ACCENT)
        self.page.draw_line(fitz.Point(MARGIN_X, self.y + 22),
                            fitz.Point(PAGE_W - MARGIN_X, self.y + 22),
                            color=ACCENT, width=1.2)
        self.y += TOPIC_HEADER_H

    def question_header(self, number: int, ref_text: str, first_rect_h: float,
                        topic: str | None = None):
        """'Q1' in the booklet's own sequence, then the Cambridge source ref.

        `topic` prints as a gold chapter tag on the right. In session order the
        section heading is a sitting ("Oct/Nov 2025"), so this is the only place
        the chapter appears — a student flicking through must still be able to
        tell what each question is testing.
        """
        max_keep = BOTTOM_Y - TOP_Y - Q_HEADER_H
        self.ensure(Q_HEADER_H + min(first_rect_h, max_keep))
        # Small navy accent bar signals the question boundary
        bar_w = 4.0
        self.page.draw_rect(
            fitz.Rect(MARGIN_X, self.y + 2, MARGIN_X + bar_w, self.y + Q_HEADER_H - 2),
            color=None, fill=ACCENT)
        label = f"Q{number}"
        lx = MARGIN_X + bar_w + 6
        self.page.insert_text((lx, self.y + 11), label,
                              fontsize=12, fontname="hebo", color=ACCENT)
        x = lx + fitz.get_text_length(label, fontname="hebo", fontsize=12)

        # Reserve the right-hand end for the chapter tag, then let the ref use
        # whatever is left — a long ref must not run underneath the tag.
        tag_w = 0.0
        if topic:
            tag_fs = 7.5
            tag_w = fitz.get_text_length(topic, fontname="hebo", fontsize=tag_fs) + 14
            tag = fitz.Rect(PAGE_W - MARGIN_X - tag_w, self.y + 1,
                            PAGE_W - MARGIN_X, self.y + 13.5)
            self.page.draw_rect(tag, color=None, fill=(0.996, 0.957, 0.878),
                                radius=0.35)
            self.page.insert_text((tag.x0 + 7, tag.y0 + 9), topic,
                                  fontsize=tag_fs, fontname="hebo",
                                  color=(0.66, 0.44, 0.06))
        ref_x = x + 8
        avail = (PAGE_W - MARGIN_X - tag_w - 8) - ref_x
        if avail > 40:
            shown = ref_text
            while (fitz.get_text_length(shown, fontname="helv", fontsize=8.5) > avail
                   and len(shown) > 8):
                shown = shown[:-2]
            self.page.insert_text((ref_x, self.y + 10), shown,
                                  fontsize=8.5, fontname="helv", color=GREY)

        # Subtle gold rule under the header
        rule_y = self.y + Q_HEADER_H - 1
        self.page.draw_line(fitz.Point(MARGIN_X, rule_y),
                            fitz.Point(PAGE_W - MARGIN_X, rule_y),
                            color=GOLD, width=0.6)
        self.y += Q_HEADER_H

    def label(self, text: str, keep_with: float):
        self.ensure(MS_LABEL_H + min(keep_with, 80))
        self.page.insert_text((MARGIN_X, self.y + 8), text,
                              fontsize=7.5, fontname="hebo", color=GREY)
        self.y += MS_LABEL_H

    def place_rects(self, src_doc, rects: list[dict], scale: float = 1.0):
        for i, r in enumerate(rects):
            w = (r["x1"] - r["x0"]) * scale
            h = (r["y1"] - r["y0"]) * scale
            # Never paginate the first rect when we are right at the top of a fresh
            # page (question header was just placed there). Without this guard, a
            # question whose first rect height > max_keep (~712 pt) triggers a new
            # page here even though question_header already started a fresh page,
            # leaving an orphan near-empty header page before every tall question.
            at_page_top = (i == 0 and self.page is not None
                           and self.y <= TOP_Y + Q_HEADER_H + 2)
            if not at_page_top:
                self.ensure(h)
            if self.page is None:
                self.new_page()
            target = fitz.Rect(MARGIN_X, self.y, MARGIN_X + w, self.y + h)
            clip = fitz.Rect(r["x0"], r["y0"], r["x1"], r["y1"])
            self.page.show_pdf_page(target, src_doc, r["page"], clip=clip)
            self.y += h + 4

    def divider(self):
        if self.page is not None and self.y + DIVIDER_GAP < BOTTOM_Y:
            mid = self.y + DIVIDER_GAP / 2
            self.page.draw_line(fitz.Point(MARGIN_X, mid),
                                fitz.Point(PAGE_W - MARGIN_X, mid),
                                color=(0.75, 0.75, 0.75), width=0.5)
            self.y += DIVIDER_GAP

    def insert_header(self, text: str):
        """Gold banner announcing a source insert."""
        self.ensure(14 + 60)
        self.page.draw_rect(fitz.Rect(MARGIN_X, self.y, PAGE_W - MARGIN_X, self.y + 14),
                            color=None, fill=GOLD)
        self.page.insert_text((MARGIN_X + 6, self.y + 10), text,
                              fontsize=7.5, fontname="hebo", color=(0.08, 0.08, 0.08))
        self.y += 18

    def place_insert(self, ins_doc: fitz.Document):
        """Embed all pages of a source insert, one full booklet page each."""
        self.place_insert_pages(ins_doc, list(range(len(ins_doc))))

    def place_insert_pages(self, ins_doc: fitz.Document, page_indices: list):
        """Embed specific pages of a source insert, one full booklet page each."""
        for pg_num in page_indices:
            self.new_page()
            ins_r = ins_doc[pg_num].rect
            scale = min(CONTENT_W / ins_r.width, (BOTTOM_Y - TOP_Y) / ins_r.height)
            w, h = ins_r.width * scale, ins_r.height * scale
            cx = MARGIN_X + (CONTENT_W - w) / 2
            target = fitz.Rect(cx, TOP_Y, cx + w, TOP_Y + h)
            self.page.show_pdf_page(target, ins_doc, pg_num)
            self.y = BOTTOM_Y  # force next content onto a new page


def _centre(page, text, y, fontsize, fontname, color):
    w = fitz.get_text_length(text, fontname=fontname, fontsize=fontsize)
    page.insert_text(((PAGE_W - w) / 2, y), text, fontsize=fontsize,
                     fontname=fontname, color=color)


def _wrap(text, fontname, fontsize, max_w):
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if fitz.get_text_length(trial, fontname=fontname, fontsize=fontsize) > max_w:
            if line:
                lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


def brand_backdrop(doc):
    """New cover page painted with the PrepWithTee logo, owl watermark and
    gold rule. Shared by compose and testgen so the branding stays identical.

    The logo PNG's own background is BRAND_CREAM, so painting the whole page
    cream lets the artwork sit on it seamlessly - no cropping or alpha channel
    needed. The watermark is that same art veiled by a high-opacity cream
    rectangle. Cover only: body pages stay clean behind the question crops.
    """
    page = doc.new_page(pno=0, width=PAGE_W, height=PAGE_H)
    page.draw_rect(fitz.Rect(0, 0, PAGE_W, PAGE_H), color=None, fill=CREAM)

    logo = config.LOGO_PATH
    if logo.exists():
        # Watermark: the owl only (LOGO_OWL_CLIP excludes the wordmark, which
        # would otherwise duplicate the crisp logo above it). Crop the pixmap
        # directly - going via convert_to_pdf/show_pdf_page rescales the clip
        # by the PNG's DPI metadata and lifts the wrong region.
        clip = fitz.IRect(*config.LOGO_OWL_CLIP)
        src = fitz.Pixmap(str(logo))
        owl = fitz.Pixmap(fitz.csRGB, clip, False)
        owl.copy(src, clip)
        h = 520.0
        w = h * (clip.width / clip.height)
        wm = fitz.Rect(PAGE_W / 2 - w / 2, 252, PAGE_W / 2 + w / 2, 252 + h)
        page.insert_image(wm, pixmap=owl)
        # 0.955: the owl's silhouette has long straight sides, which read as
        # hard rectangle edges if the veil is any lighter than this.
        page.draw_rect(wm, color=None, fill=CREAM, fill_opacity=0.955)
        page.insert_image(fitz.Rect(PAGE_W / 2 - 88, 44, PAGE_W / 2 + 88, 220),
                          filename=str(logo))
    else:
        log.warning("logo not found at %s - cover falls back to text", logo)
        _centre(page, config.BRAND_NAME, 150, 30, "hebo", ACCENT)

    page.draw_line(fitz.Point(PAGE_W / 2 - 130, 232),
                   fitz.Point(PAGE_W / 2 + 130, 232), color=GOLD, width=2)
    return page


def footer_band(page, right_text=None):
    """Navy footer band — three rows: brand+tagline, website+email, phone."""
    BAND_H = 62
    page.draw_rect(fitz.Rect(0, PAGE_H - BAND_H, PAGE_W, PAGE_H), color=None,
                   fill=ACCENT)
    LX = MARGIN_X + 14
    # ── Row 1: brand name (left) | tagline (centre-ish) | generated date (right)
    page.insert_text((LX, PAGE_H - BAND_H + 17), config.BRAND_NAME,
                     fontsize=11, fontname="hebo", color=CREAM)
    tag = config.BRAND_TAGLINE
    tw = fitz.get_text_length(tag, fontname="helv", fontsize=7.5)
    page.insert_text(((PAGE_W - tw) / 2, PAGE_H - BAND_H + 17), tag,
                     fontsize=7.5, fontname="helv", color=(0.85, 0.83, 0.75))
    stamp = right_text or f"Generated {date.today().isoformat()}"
    sw = fitz.get_text_length(stamp, fontname="helv", fontsize=7.5)
    page.insert_text((PAGE_W - MARGIN_X - 14 - sw, PAGE_H - BAND_H + 17), stamp,
                     fontsize=7.5, fontname="helv", color=(0.65, 0.68, 0.76))
    # ── Row 2: website (left, clickable) | email (centre)
    DIM = (0.55, 0.62, 0.80)
    GOLD = (0.957, 0.651, 0.196)
    site_label = config.BRAND_WEBSITE
    page.insert_text((LX, PAGE_H - BAND_H + 34), site_label,
                     fontsize=8.5, fontname="helv", color=GOLD)
    site_w = fitz.get_text_length(site_label, fontname="helv", fontsize=8.5)
    page.insert_link({"kind": fitz.LINK_URI, "uri": config.BRAND_WEBSITE_URL,
                      "from": fitz.Rect(LX - 1, PAGE_H - BAND_H + 24,
                                        LX + site_w + 2, PAGE_H - BAND_H + 38)})
    wa = "WhatsApp: " + config.BRAND_WHATSAPP
    ww = fitz.get_text_length(wa, fontname="helv", fontsize=8)
    page.insert_text(((PAGE_W - ww) / 2, PAGE_H - BAND_H + 34), wa,
                     fontsize=8, fontname="helv", color=DIM)
    page.insert_link({"kind": fitz.LINK_URI,
                      "uri": config.BRAND_WHATSAPP_URL,
                      "from": fitz.Rect((PAGE_W - ww) / 2 - 1, PAGE_H - BAND_H + 24,
                                        (PAGE_W - ww) / 2 + ww + 2, PAGE_H - BAND_H + 38)})
    # ── phone (right)
    ph = config.BRAND_PHONE
    phw = fitz.get_text_length(ph, fontname="helv", fontsize=8)
    page.insert_text((PAGE_W - MARGIN_X - 14 - phw, PAGE_H - BAND_H + 34),
                     ph, fontsize=8, fontname="helv", color=DIM)
    # ── Separator gold rule above band
    page.draw_line((0, PAGE_H - BAND_H), (PAGE_W, PAGE_H - BAND_H),
                   color=(0.957, 0.651, 0.196), width=1.5)


# Syllabuses where the question paper has lined answer pages that should be
# stripped from the topical output (students write in a separate booklet).
_ESSAY_SYLLABUSES = {"2058"}

# Syllabuses whose question papers append a [Total: N marks] footer after the
# last sub-part of each question.  The footer belongs to the parent question
# and must be trimmed from sub-part crops so it doesn't appear in the booklet.
_TOTAL_MARKER_SYLLABUSES = {"2059"}


def _trim_total_marker_rects(src_doc: fitz.Document,
                              rects: list[dict]) -> list[dict]:
    """Clip a [Total: N marks] line from the tail of the last rect."""
    if not rects:
        return rects
    last = dict(rects[-1])
    page = src_doc[last["page"]]
    clip = fitz.Rect(last["x0"], last["y0"], last["x1"], last["y1"])
    for blk in page.get_text("blocks", clip=clip):
        by0, text = blk[1], blk[4]
        if re.search(r"\[\s*Total\s*:", text) and by0 > last["y0"] + 8:
            last["y1"] = round(by0 - 2, 2)
            return (rects[:-1] + [last]) if last["y1"] - last["y0"] > 8 else rects[:-1]
    return rects


def _trim_essay_rects(src_doc: fitz.Document, rects: list[dict]) -> list[dict]:
    """Remove or clip rects whose content is entirely answer lines (dot rows).

    For 2058 the QP has pages of Quran passages followed by blank lined pages
    for essay answers.  The lined pages are all-dot blocks and should be
    excluded from the topical worksheet.  A rect that mixes real content and
    dots is clipped just above the first dot row.
    """
    trimmed = []
    for rect in rects:
        page = src_doc[rect["page"]]
        clip = fitz.Rect(rect["x0"], rect["y0"], rect["x1"], rect["y1"])
        blocks = page.get_text("blocks", clip=clip)
        first_dot_y: float | None = None
        has_content = False
        for block in blocks:
            x0, y0, x1, y1, text = block[:5]
            stripped = text.strip().replace("\n", "").replace(" ", "")
            if not stripped:
                continue
            dot_frac = sum(1 for c in stripped if c in ".…_") / len(stripped)
            if dot_frac > 0.70:
                if first_dot_y is None:
                    first_dot_y = y0
            else:
                has_content = True
                first_dot_y = None  # content after dots resets the cut point
        if not has_content:
            continue  # entire rect is answer lines — skip it
        if first_dot_y is not None and first_dot_y > rect["y0"] + 20:
            trimmed.append({**rect, "y1": first_dot_y})
        else:
            trimmed.append(rect)
    return trimmed


_P1_INSERT_MARKERS = ("Source A", "Source B", "Source C", "Insert")
_P2_INSERT_MARKERS = ("(Insert)",)


def _needs_insert(text: str, paper: int) -> bool:
    """True only when this sub-part's text explicitly references the insert."""
    if not text:
        return False
    markers = _P1_INSERT_MARKERS if paper == 1 else _P2_INSERT_MARKERS
    return any(m in text for m in markers)


def _p2_insert_question_pages(ins_doc: fitz.Document) -> dict:
    """Parse a 2059 P2 insert to map question numbers → page indices.

    Insert pages carry labels like "Fig. 3.1 for Question 3" in their text
    layer.  Returns {q_num: [page_index, ...]} for all detected mappings.
    """
    q_pages: dict[int, list[int]] = {}
    for pg_i in range(len(ins_doc)):
        text = ins_doc[pg_i].get_text()
        matches = re.findall(r"for\s+Question\s+(\d+)", text, re.I)
        if matches:
            q_num = int(matches[0])
            q_pages.setdefault(q_num, []).append(pg_i)
    return q_pages


OPTIONS = ("A", "B", "C", "D")
BUBBLE_R = 6.5
BUBBLE_GAP = 22.0
ROW_H = 24.0
SHEET_TOP = 150.0                 # y of the first row on a printable page
SHEET_BOTTOM = PAGE_H - 70.0      # last row must clear the footer band (BAND_H=62 + 8px margin)
BUBBLE_COLS = 3                   # question columns per bubble-sheet page
KEY_COLS = 3                      # answer-grid table blocks per page


def _sheet_header(doc, title, subtitle):
    """Plain white page with a gold rule - the printable pages (bubble sheet,
    answer key) deliberately skip the owl watermark so a filled-in sheet stays
    legible and cheap to photocopy."""
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    page.insert_text((MARGIN_X, 56), title, fontsize=20, fontname="hebo",
                     color=ACCENT)
    page.draw_line(fitz.Point(MARGIN_X, 66), fitz.Point(PAGE_W - MARGIN_X, 66),
                   color=GOLD, width=2)
    page.insert_text((MARGIN_X, 84), subtitle, fontsize=9, fontname="helv",
                     color=GREY)
    return page


def _rows_per_col():
    """How many rows of height ROW_H fit between the header and the footer."""
    return max(1, int((SHEET_BOTTOM - SHEET_TOP) // ROW_H))


def _paginate(n, cols):
    """Split n items across printable pages.

    Each page holds up to `cols` columns of `_rows_per_col()` rows. Items fill
    a column top-to-bottom before the next column starts (read down, then
    right). The final page balances its columns so it never leaves, say, one
    lonely item in a third column. Returns a list of pages; each page is a list
    of (item_index, col, row, cols_on_this_page).
    """
    rows = _rows_per_col()
    per_page = cols * rows
    pages = []
    for start in range(0, n, per_page):
        take = min(per_page, n - start)
        pcols = min(cols, -(-take // rows))       # drop empty trailing columns
        prows = -(-take // pcols)                 # balance the last page
        pages.append([(start + i, i // prows, i % prows, pcols)
                      for i in range(take)])
    return pages


def _name_date(page, y=118.0):
    """Name/Date write-in lines used at the top of the first bubble sheet."""
    for label, x in (("Name", MARGIN_X), ("Date", PAGE_W / 2 + 40)):
        page.insert_text((x, y), f"{label}:", fontsize=9.5, fontname="hebo",
                         color=(0.2, 0.2, 0.2))
        x0 = x + fitz.get_text_length(f"{label}:", fontname="hebo",
                                      fontsize=9.5) + 6
        page.draw_line(fitz.Point(x0, y + 2),
                       fitz.Point(x + (PAGE_W / 2 - MARGIN_X - 60), y + 2),
                       color=(0.7, 0.7, 0.7), width=0.7)


def bubble_sheet(doc, numbers, meta):
    """Fill-in answer sheet: one row per question, a circle per option.

    `numbers` are the booklet's own question numbers, not 1..N - a mixed
    booklet ("All papers") interleaves multiple-choice and structured
    questions, and the sheet has to skip the structured ones rather than
    renumber, or the rows stop lining up with the questions.

    Paginates across as many sheets as the question count needs (a 40-question
    paper is one sheet; a big topical set spills onto a second) so the rows
    never crowd or overrun the page. Returns the list of pages created; the
    caller moves them to sit directly after the cover.
    """
    layout = _paginate(len(numbers), BUBBLE_COLS)
    made = []
    for pi, placements in enumerate(layout):
        sub = f"{meta}  ·  shade one circle per question"
        if len(layout) > 1:
            sub += f"   (sheet {pi + 1} of {len(layout)})"
        page = _sheet_header(doc, "Answer Sheet", sub)
        if pi == 0:
            _name_date(page)
        for idx, c, r, pcols in placements:
            col_w = (PAGE_W - 2 * MARGIN_X) / pcols
            x = MARGIN_X + c * col_w
            y = SHEET_TOP + r * ROW_H
            num = str(numbers[idx])
            nw = fitz.get_text_length(num, fontname="hebo", fontsize=9)
            page.insert_text((x + 22 - nw, y + 3), num, fontsize=9,
                             fontname="hebo", color=(0.2, 0.2, 0.2))
            for k, opt in enumerate(OPTIONS):
                cx = x + 38 + k * BUBBLE_GAP
                page.draw_circle(fitz.Point(cx, y), BUBBLE_R,
                                 color=(0.45, 0.45, 0.45), width=0.8)
                ow = fitz.get_text_length(opt, fontname="helv", fontsize=5.5)
                page.insert_text((cx - ow / 2, y + 2), opt, fontsize=5.5,
                                 fontname="helv", color=(0.6, 0.6, 0.6))
        footer_band(page, "Shade the circle completely")
        made.append(page)
    return made


def _key_block(page, x0, w, rows, entries):
    """One ruled table block (Q · Ans · Source) filling a single column."""
    qx, ax, sx = x0 + 4, x0 + 34, x0 + 66
    hy = SHEET_TOP - 16
    for lbl, lx in (("Q", qx), ("Ans", ax), ("Source", sx)):
        page.insert_text((lx, hy), lbl, fontsize=7.5, fontname="hebo", color=GOLD)
    page.draw_line(fitz.Point(x0, hy + 5), fitz.Point(x0 + w, hy + 5),
                   color=GOLD, width=1)
    for r, idx in rows:
        seq, answer, ref = entries[idx]
        y = SHEET_TOP + r * ROW_H
        if r % 2 == 1:
            page.draw_rect(fitz.Rect(x0, y - 12, x0 + w, y + 6),
                           color=None, fill=(0.965, 0.965, 0.965))
        page.insert_text((qx, y), str(seq), fontsize=9, fontname="hebo",
                         color=(0.2, 0.2, 0.2))
        page.insert_text((ax, y), answer or "-", fontsize=11, fontname="hebo",
                         color=ACCENT)
        page.insert_text((sx, y), ref, fontsize=6.5, fontname="helv", color=GREY)
        page.draw_line(fitz.Point(x0, y + 6), fitz.Point(x0 + w, y + 6),
                       color=(0.9, 0.9, 0.9), width=0.4)


def answer_key(doc, entries):
    """Answer grid at the back, laid out as ruled tables.

    `entries` is [(seq, answer, ref)]; the source ref is printed so a student
    can trace any answer back to its original Cambridge paper. Rendered as
    boxed Q/Ans/Source table blocks (the tutor asked for a grid, 2026-07-23),
    paginated so a long booklet's answers never overlap. Returns the pages.
    """
    layout = _paginate(len(entries), KEY_COLS)
    made = []
    for pi, placements in enumerate(layout):
        sub = (f"{len(entries)} multiple-choice questions  ·  booklet "
               "numbering, with the original paper reference")
        if len(layout) > 1:
            sub += f"   (page {pi + 1} of {len(layout)})"
        page = _sheet_header(doc, "Answers", sub)
        blocks: dict = {}
        for idx, c, r, pcols in placements:
            blocks.setdefault((c, pcols), []).append((r, idx))
        for (c, pcols), rows in blocks.items():
            col_w = (PAGE_W - 2 * MARGIN_X) / pcols
            _key_block(page, MARGIN_X + c * col_w, col_w - 14, rows, entries)
        footer_band(page)
        made.append(page)
    return made


def build_cover(doc, args, subject, sections, contents=None):
    """Branded PrepWithTee cover: logo, faint owl watermark, contents card.

    The title always names the TOPICS — that is what the booklet is — while
    `contents` is however the pages are actually grouped, so a session-ordered
    booklet lists its sittings without the cover claiming to be about them.
    """
    page = brand_backdrop(doc)
    y = 270
    title = " · ".join(name for name, _ in sections)
    subtopics_active = getattr(args, "subtopics", None)
    if subtopics_active:
        title += "  —  " + ", ".join(subtopics_active)
    size = 25 if len(title) < 34 else (19 if len(title) < 62 else 15)
    for line in _wrap(title, "hebo", size, CONTENT_W - 60)[:3]:
        _centre(page, line, y, size, "hebo", ACCENT)
        y += size + 6

    y += 12
    codes = ", ".join(getattr(args, "syllabuses", None) or [args.syllabus])
    _centre(page, f"{subject}  ·  {codes}", y, 13, "helv", (0.2, 0.2, 0.2))
    y += 20

    total_q = sum(len(qs) for _, qs in sections)
    total_m = sum(q["marks"] or 0 for _, qs in sections for q in qs)
    meta = [f"Years {args.year_from}-{args.year_to}"]
    papers_active = getattr(args, "papers_list", None) or (
        [args.paper] if getattr(args, "paper", None) else [])
    if papers_active:
        meta.append("Paper " + "+".join(str(p) for p in sorted(papers_active)))
    if args.variant:
        meta.append(f"Variant {args.variant}")
    meta += [f"{total_q} questions", f"{total_m} marks"]
    _centre(page, "   ·   ".join(meta), y, 9.5, "helv", GREY)
    y += 36

    # Contents card: white on cream so it reads as a panel. A long booklet can
    # run to many sittings, so the list is capped and the remainder summarised
    # rather than overflowing off the bottom of the cover.
    listing = contents if contents is not None else [
        (name, [(name, q) for q in qs]) for name, qs in sections]
    MAX_ROWS = 12
    shown = listing[:MAX_ROWS]
    hidden = listing[MAX_ROWS:]
    rows_h = (len(shown) + (1 if hidden else 0)) * 17

    panel = fitz.Rect(MARGIN_X + 46, y, PAGE_W - MARGIN_X - 46,
                      y + 42 + rows_h + 14)
    page.draw_rect(panel, color=None, fill=(1, 1, 1))
    page.draw_line(fitz.Point(panel.x0, panel.y0), fitz.Point(panel.x0, panel.y1),
                   color=GOLD, width=2.5)

    ty = y + 24
    page.insert_text((panel.x0 + 18, ty), "CONTENTS", fontsize=8.5,
                     fontname="hebo", color=GOLD)
    ty += 20
    for name, questions in shown:
        marks = sum(q["marks"] or 0 for _t, q in questions)
        page.insert_text((panel.x0 + 18, ty), name, fontsize=10,
                         fontname="hebo", color=ACCENT)
        tail = f"{len(questions)} questions · {marks} marks"
        tw = fitz.get_text_length(tail, fontname="helv", fontsize=9)
        page.insert_text((panel.x1 - 18 - tw, ty), tail, fontsize=9,
                         fontname="helv", color=GREY)
        ty += 17
    if hidden:
        more = sum(len(qs) for _n, qs in hidden)
        page.insert_text((panel.x0 + 18, ty),
                         f"+ {len(hidden)} more · {more} questions", fontsize=9,
                         fontname="helv", color=GREY)
        ty += 17

    if not args.no_ms:
        _centre(page, "Mark scheme follows each question", panel.y1 + 26,
                9, "helv", GREY)

    footer_band(page)


def fetch_sections(con, args, topics: list[str]):
    """[(topic, [question rows])], each question exactly once."""
    syllabuses = getattr(args, "syllabuses", None) or [args.syllabus]
    marks = ",".join("?" for _ in syllabuses)

    # Multi-value session and variant filters (comma-separated on CLI; list from API)
    sessions = getattr(args, "sessions", None) or (
        [args.session] if getattr(args, "session", None) and args.session != "all" else None)
    variants = getattr(args, "variants", None) or (
        [str(args.variant)] if getattr(args, "variant", None) else None)
    # clean up: remove "all" sentinels
    if sessions:
        sessions = [s for s in sessions if s and s != "all"]
    if variants:
        variants = [v for v in variants if v and v != "all"]

    session_clause = ""
    session_params: list = []
    if sessions:
        ph = ",".join("?" for _ in sessions)
        session_clause = f" AND p.session IN ({ph})"
        session_params = sessions

    variant_clause = ""
    variant_params: list = []
    if variants:
        ph = ",".join("?" for _ in variants)
        variant_clause = f" AND p.variant IN ({ph})"
        variant_params = variants

    # Build multi-paper filter from --papers list or legacy --paper single value
    papers_list: list[int] = list(getattr(args, "papers_list", None) or [])
    if not papers_list and getattr(args, "paper", None):
        papers_list = [args.paper]
    paper_clause = ""
    paper_params: list = []
    if papers_list:
        ph = ",".join("?" for _ in papers_list)
        paper_clause = f" AND p.paper IN ({ph})"
        paper_params = papers_list

    rows = con.execute(
        f"""
        SELECT q.id, q.number, q.sub_part, q.marks, q.rects_json, q.text, c.topic,
               c.secondary_topic, c.subtopic, p.syllabus, p.rel_path, p.filename,
               p.year, p.session, p.paper, p.variant
        FROM questions q
        JOIN classifications c ON c.question_id = q.id
        JOIN papers p ON p.id = q.paper_id
        WHERE p.syllabus IN ({marks}) AND p.kind = 'qp'
          AND p.year BETWEEN ? AND ?
          AND q.status IS NOT 'excluded'
        """ + paper_clause + session_clause + variant_clause
        + " ORDER BY p.year DESC, p.session, p.variant, q.number",
        [*syllabuses, args.year_from, args.year_to]
        + paper_params + session_params + variant_params).fetchall()

    # --contains narrows to questions whose text matches a regex. Topics are
    # the wrong granularity for something like a frustum, which is a handful of
    # questions scattered across Mensuration and 3D Trigonometry.
    if getattr(args, "contains", None):
        try:
            pattern = re.compile(args.contains, re.I)
        except re.error as exc:
            log.error("--contains: invalid regex %r: %s", args.contains, exc)
            raise SystemExit(1)
        rows = [r for r in rows if pattern.search(r["text"] or "")]

    # --subtopics narrows within the selected topics (fine-grained filter)
    subtopic_filter: set[str] = set(getattr(args, "subtopics", None) or [])

    sections = {t: [] for t in topics}
    seen = set()
    for r in rows:
        if r["id"] in seen:
            continue
        home = next((t for t in topics if r["topic"] == t), None) \
            or next((t for t in topics if r["secondary_topic"] == t), None)
        if home:
            if subtopic_filter and r["subtopic"] not in subtopic_filter:
                continue
            # `home` is which of the SELECTED topics this question was filed
            # under. Session ordering regroups the rows and would otherwise
            # lose it, so carry it on the row itself.
            sections[home].append((home, r))
            seen.add(r["id"])
    return [(t, [r for _h, r in qs]) for t, qs in sections.items() if qs]


# Sessions run Feb/March, then May/June, then Oct/Nov. Sorting the codes would
# give m,s,w by luck; the real order is written down.
_SESSION_SEQ = {"m": 0, "s": 1, "w": 2}

# Section headings say the sitting in full. "F/M 2025" is the Cambridge source
# ref shorthand — right on a question line, too terse for a heading a student
# navigates by.
_SESSION_FULL = {"s": "May/June", "w": "Oct/Nov", "m": "Feb/March"}


def render_groups(sections, order_mode: str):
    """Sections -> [(heading, [(topic, row), ...])] in the requested order.

    One uniform shape for both modes so the render loop never has to ask which
    one it is looking at; the topic travels with every row either way, which is
    what lets the question header print the chapter.
    """
    if order_mode != "session":
        return [(t, [(t, r) for r in rows]) for t, rows in sections]

    # Session order: the tutor's booklets are worked through the way papers are
    # sat, not the way a syllabus is indexed — one sitting at a time, and inside
    # it every selected topic in turn. Grouping by topic instead put six years
    # between two questions a student would answer in the same half hour.
    order = {t: i for i, (t, _) in enumerate(sections)}
    buckets: dict[tuple, list] = {}
    for topic, rows in sections:
        for r in rows:
            buckets.setdefault((r["year"], r["session"]), []).append((topic, r))

    out = []
    # Newest sitting first, and newest WITHIN a year too — Oct/Nov before
    # May/June before Feb/March — so the booklet opens on the most recent paper.
    for year, session in sorted(
            buckets, key=lambda k: (-k[0], -_SESSION_SEQ.get(k[1], 9))):
        rows = buckets[(year, session)]
        # Inside a sitting: selected-topic order, then paper, variant, number —
        # so one chapter's questions from P1 and P2 still sit together.
        rows.sort(key=lambda tr: (order.get(tr[0], 99), tr[1]["paper"],
                                  str(tr[1]["variant"]), tr[1]["number"]))
        out.append((f"{_SESSION_FULL.get(session, session)} {year}", rows))
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--syllabus", required=True,
                   help="syllabus code, or several comma-separated "
                        "(e.g. 4024,0580) to build one cross-board worksheet")
    p.add_argument("--topics", required=True,
                   help="comma-separated chapter names from taxonomy/")
    p.add_argument("--from", dest="year_from", type=int, default=config.YEAR_MIN)
    p.add_argument("--to", dest="year_to", type=int, default=config.YEAR_MAX)
    p.add_argument("--paper", type=int, help="single paper component (legacy; prefer --papers)")
    p.add_argument("--papers", help="comma-separated paper numbers, e.g. 1,2")
    p.add_argument("--variant", type=int)
    p.add_argument("--session")
    p.add_argument("--sessions", help="comma-separated session codes, e.g. s,w")
    p.add_argument("--variants", help="comma-separated variant numbers, e.g. 1,2")
    p.add_argument("--subtopics", help="comma-separated subtopic names to include")
    p.add_argument("--contains", metavar="REGEX",
                   help="keep only questions whose text matches this regex — "
                        "for sub-topics too small to be a chapter of their own, "
                        r'e.g. --contains "frustum|cone .{0,40}removed"')
    p.add_argument("--order", choices=("session", "topic"), default="session",
                   help="session: newest sitting first, topics grouped inside "
                        "each (default). topic: all of one chapter, then the next.")
    p.add_argument("--no-ms", action="store_true", help="omit mark schemes")
    p.add_argument("--out", help="output path (default: data/output/...)")
    args = p.parse_args()

    args.syllabuses = [s.strip() for s in args.syllabus.split(",") if s.strip()]
    if args.sessions:
        args.sessions = [s.strip() for s in args.sessions.split(",") if s.strip()]
    if args.variants:
        args.variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    if args.subtopics:
        args.subtopics = [s.strip() for s in args.subtopics.split(",") if s.strip()]
    # Normalise multi-paper: --papers wins over --paper
    if args.papers:
        args.papers_list = [int(x.strip()) for x in args.papers.split(",") if x.strip()]
    elif args.paper:
        args.papers_list = [args.paper]
    else:
        args.papers_list = []
    unknown = [s for s in args.syllabuses if s not in config.SUBJECT_FOLDERS]
    if unknown:
        raise SystemExit(f"unknown syllabus {unknown}; "
                         f"known: {sorted(config.SUBJECT_FOLDERS)}")

    # A topic only has to exist in one of the chosen syllabuses — 4024 and 0580
    # both have "Mensuration" but only 0580 has "3D Trigonometry".
    valid, known = {}, []
    for syl in args.syllabuses:
        for t in heuristics.load_taxonomy(syl)["topics"]:
            valid.setdefault(t["name"].lower(), t["name"])
            known.append(f"{syl}: {t['name']}")
    topics = []
    for raw in args.topics.split("|"):
        name = valid.get(raw.strip().lower())
        if name is None:
            raise SystemExit(
                f"unknown topic {raw.strip()!r}; valid topics:\n  "
                + "\n  ".join(known))
        topics.append(name)

    con = db.connect()
    sections = fetch_sections(con, args, topics)
    if not sections:
        raise SystemExit("no classified questions match these filters")

    booklet = Booklet()
    src_cache: dict[str, fitz.Document] = {}

    def src(rel_path):
        if rel_path not in src_cache:
            d = fitz.open(config.ROOT / str(rel_path).replace("\\", "/"))
            for pg in d:
                if pg.rotation:
                    pg.remove_rotation()
            src_cache[rel_path] = d
        return src_cache[rel_path]

    n_ms_missing = 0
    mcq_answers = []   # [(seq, letter, source ref)] for the answer grid
    seq = 0   # the booklet's own Q1, Q2, Q3... across all sections
    shown_inserts: set = set()   # (syllabus, year, session, paper) already embedded
    # Cache: (syl, year, session, paper) → (ins_doc | None, p2_page_map | None)
    ins_cache: dict = {}

    def _get_insert(syl, year, session, paper):
        key = (syl, year, session, paper)
        if key not in ins_cache:
            row = con.execute(
                "SELECT rel_path FROM papers "
                "WHERE syllabus=? AND year=? AND session=? AND paper=? AND kind='in' "
                "LIMIT 1", (syl, year, session, paper)).fetchone()
            if row:
                idoc = src(row["rel_path"])
                p2map = _p2_insert_question_pages(idoc) if (syl == "2059" and paper == 2) else None
                ins_cache[key] = (idoc, p2map)
            else:
                ins_cache[key] = None
        return ins_cache[key]

    groups = render_groups(sections, getattr(args, "order", "session"))
    for heading, questions in groups:
        booklet.topic_header(heading)
        for topic, q in questions:
            syl = q["syllabus"]
            year, session, paper = q["year"], q["session"], q["paper"]
            sd = config.session_display(session)
            ins_ref = f"{syl}/{paper:02d}/{sd}/{year % 100:02d}"
            ins_result = _get_insert(syl, year, session, paper)

            if ins_result and syl == "2059":
                ins_doc, p2map = ins_result
                q_text = q["text"] or ""
                if paper == 1 and q["number"] == 1 and _needs_insert(q_text, 1):
                    # P1: insert only for sub-parts that reference a Source
                    ins_key = (syl, year, session, paper)
                    if ins_key not in shown_inserts:
                        shown_inserts.add(ins_key)
                        source_pages = list(range(1, len(ins_doc)))
                        if source_pages:
                            booklet.insert_header(f"Sources (Insert)  —  {ins_ref}")
                            booklet.place_insert_pages(ins_doc, source_pages)
                elif paper == 2 and p2map and _needs_insert(q_text, 2):
                    # P2: insert only for sub-parts that reference "Fig."
                    ins_key = (syl, year, session, paper, q["number"])
                    q_pages = p2map.get(q["number"], [])
                    if q_pages and ins_key not in shown_inserts:
                        shown_inserts.add(ins_key)
                        booklet.insert_header(
                            f"Insert figures for Q{q['number']}  —  {ins_ref}")
                        booklet.place_insert_pages(ins_doc, q_pages)
            elif ins_result:
                # Other syllabuses: show insert once per paper (original behaviour)
                ins_key = (syl, year, session, paper)
                if ins_key not in shown_inserts:
                    shown_inserts.add(ins_key)
                    ins_doc, _ = ins_result
                    booklet.insert_header(f"Source Insert  —  {ins_ref}")
                    booklet.place_insert(ins_doc)

            seq += 1
            rects = json.loads(q["rects_json"])
            if syl in _ESSAY_SYLLABUSES:
                rects = _trim_essay_rects(src(q["rel_path"]), rects)
            if syl in _TOTAL_MARKER_SYLLABUSES and q["sub_part"]:
                rects = _trim_total_marker_rects(src(q["rel_path"]), rects)
            code = f"{q['paper']}{q['variant']}"
            syl = q["syllabus"]
            ref = config.source_ref(syl, code, q["session"],
                                    q["year"], q["number"], q["sub_part"] or "")
            plain_ref = ref
            if q["marks"]:
                ref += f"   [{q['marks']} marks]"
            if q["topic"] != topic:
                ref += f"   (also covers {q['topic']})"
            first_h = (rects[0]["y1"] - rects[0]["y0"]) if rects else 40.0
            # In session order the section heading is a sitting, so the chapter
            # has to ride on the question itself or it is nowhere on the page.
            booklet.question_header(seq, ref, first_h, topic=topic)
            if rects:
                booklet.place_rects(src(q["rel_path"]), rects)

            # Multiple choice: the answer is a single letter, so it goes in the
            # grid at the back rather than under the question where it would
            # spoil the attempt.
            if config.is_mcq(syl, q["paper"]):
                row = con.execute(
                    """SELECT m.answer FROM ms_entries m
                       JOIN papers mp ON mp.id = m.paper_id
                       WHERE mp.kind = 'ms' AND mp.syllabus = ? AND mp.year = ?
                         AND mp.session = ? AND mp.paper = ? AND mp.variant = ?
                         AND m.question_number = ?""",
                    (syl, q["year"], q["session"], q["paper"],
                     q["variant"], q["number"])).fetchone()
                answer = row["answer"] if row else None
                if answer is None:
                    n_ms_missing += 1
                mcq_answers.append((seq, answer, plain_ref))
                booklet.divider()
                continue

            if not args.no_ms:
                ms = con.execute(
                    """
                    SELECT m.rects_json, mp.rel_path FROM ms_entries m
                    JOIN papers mp ON mp.id = m.paper_id
                    WHERE mp.kind = 'ms' AND mp.syllabus = ? AND mp.year = ?
                      AND mp.session = ? AND mp.paper = ? AND mp.variant = ?
                      AND m.question_number = ? AND m.sub_part = ?
                    """, (syl, q["year"], q["session"], q["paper"],
                          q["variant"], q["number"],
                          q["sub_part"] or "")).fetchone()
                if ms is None:
                    n_ms_missing += 1
                    booklet.label(f"Mark scheme for {ref}: not available",
                                  keep_with=0)
                else:
                    ms_rects = json.loads(ms["rects_json"])
                    if ms_rects:
                        scale = min(1.0, CONTENT_W / max(
                            r["x1"] - r["x0"] for r in ms_rects))
                        booklet.label(f"Mark scheme  -  {ref}",
                                      keep_with=(ms_rects[0]["y1"]
                                                 - ms_rects[0]["y0"]) * scale)
                        booklet.place_rects(src(ms["rel_path"]), ms_rects, scale)
            booklet.divider()

    subject = (heuristics.load_taxonomy(args.syllabuses[0])
               .get("subject", args.syllabuses[0])
               if len(args.syllabuses) == 1 else "Mathematics")
    codes = ", ".join(args.syllabuses)
    if mcq_answers and not args.no_ms:
        answer_key(booklet.doc, mcq_answers)
    build_cover(booklet.doc, args, subject, sections, contents=groups)
    if mcq_answers:
        # Built last but moved to sit straight after the cover, so the sheet(s)
        # can be detached and used while working.
        base = booklet.doc.page_count          # sheets are appended here...
        sheets = bubble_sheet(booklet.doc, [s for s, _, _ in mcq_answers],
                              f"{subject} {codes}  ·  multiple choice")
        for i in range(len(sheets)):           # ...then moved to follow the cover
            booklet.doc.move_page(base + i, 1 + i)

    slug = re.sub(r"[^a-z0-9]+", "-", ",".join(topics).lower()).strip("-")
    if getattr(args, "subtopics", None):
        sub_slug = re.sub(r"[^a-z0-9]+", "-", ",".join(args.subtopics).lower()).strip("-")
        slug = slug + "_" + sub_slug
    out = config.ROOT / (args.out or
                         f"data/output/{'-'.join(args.syllabuses)}_{slug}_"
                         f"{args.year_from}-{args.year_to}.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)
    booklet.doc.save(out, deflate=True, garbage=3)
    n_q = sum(len(qs) for _, qs in sections)
    log.info("wrote %s: %d questions in %d sections, %d pages%s",
             out, n_q, len(sections), booklet.doc.page_count,
             f", {n_ms_missing} mark schemes missing" if n_ms_missing else "")
    for d in src_cache.values():
        d.close()
    booklet.doc.close()
    con.close()


if __name__ == "__main__":
    main()
