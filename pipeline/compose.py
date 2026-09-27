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
import os
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
_WM_XREF: dict[int, tuple] = {}  # id(doc) -> (doc, image xref); reuse avoids embedding once per page
WM_STRENGTH = 0.12     # max ink of the owl watermark (0..1); lower = fainter
WM_TEXT_GREY = 0.92    # wordmark grey (on white, this reads ~8% ink)


def save_small(doc: fitz.Document, path) -> None:
    """Save a generated PDF, merging duplicate objects (the same source paper's
    fonts are pulled in by every crop taken from it). Lossless.

    NOT subset_fonts(): MuPDF's subsetter drops the space glyph from some
    Cambridge fonts ("downward pointing arrow" came out "downwardpointingarrow")
    - crops must reproduce the original exactly (checked 2026-09-27)."""
    doc.save(path, garbage=4, deflate=True, deflate_fonts=True, deflate_images=True)


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
        # Keyed by id() but the document itself is kept alongside: once a doc
        # is freed Python may hand its id to a new one, and reusing the stale
        # xref there fails with "is no image".
        doc = page.parent
        cached = _WM_XREF.get(id(doc))
        if cached and cached[0] is doc:
            page.insert_image(r, xref=cached[1])
        else:
            _WM_XREF[id(doc)] = (doc, page.insert_image(r, pixmap=pix))
        ty = r.y1 + 40
    else:
        ty = PAGE_H / 2
    fs = 30
    tw = fitz.get_text_length(config.BRAND_NAME, fontname="hebo", fontsize=fs)
    page.insert_text(((PAGE_W - tw) / 2, ty), config.BRAND_NAME, fontsize=fs,
                     fontname="hebo",
                     color=(WM_TEXT_GREY, WM_TEXT_GREY, WM_TEXT_GREY))
    # The wordmark (not the whole owl) links to the site: a link over the owl
    # would hijack every click/selection in the middle of a question.
    page.insert_link({"kind": fitz.LINK_URI, "uri": config.BRAND_WEBSITE_URL,
                      "from": fitz.Rect((PAGE_W - tw) / 2 - 4, ty - fs * 0.8,
                                        (PAGE_W + tw) / 2 + 4, ty + fs * 0.25)})


class Booklet:
    """A4 flow layout: items are placed down a cursor with page breaks."""

    def __init__(self):
        self.doc = fitz.open()
        self.page = None
        self.y = TOP_Y
        self.body_pages = 0
        # True once a crop has landed on the current page. Headers alone do
        # not count: a page holding only headers is never abandoned for a new
        # one (that is what stranded "May/June 2024" alone at a page foot) -
        # the content that follows is scaled to fit instead.
        self.page_has_content = False
        # Where each section/question starts, for the contents page, the PDF
        # outline and the web viewer: dicts with kind, label, page (0-based
        # index among body pages, before cover/contents are inserted), y.
        self.anchors: list[dict] = []

    def new_page(self):
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.body_pages += 1
        page_watermark(self.page)   # first, so all content paints over it
        footer_band(self.page, right_text=f"Page {self.body_pages}")
        self.y = TOP_Y
        self.page_has_content = False

    def ensure(self, height: float):
        if self.page is None:
            self.new_page()
        elif self.y + height > BOTTOM_Y and self.page_has_content:
            self.new_page()

    def topic_header(self, name: str, keep_with: float = 80.0):
        """Section heading, kept on the same page as `keep_with` points of
        whatever follows (normally the first question's header + first crop)."""
        self.ensure(TOPIC_HEADER_H + min(keep_with, BOTTOM_Y - TOP_Y - TOPIC_HEADER_H))
        self.anchors.append({"kind": "section", "label": name,
                             "page": self.page.number, "y": self.y})
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
        self.anchors.append({"kind": "question", "label": f"Q{number}",
                             "seq": number, "page": self.page.number, "y": self.y})
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
        for r in rects:
            w = (r["x1"] - r["x0"]) * scale
            h = (r["y1"] - r["y0"]) * scale
            if self.page is None:
                self.new_page()
            if self.y + h > BOTTOM_Y and self.page_has_content:
                self.new_page()
            # Still too tall for what this page offers (a near-full-page crop
            # under a question or section header): scale it down to fit. Placing
            # it at full size ran the bottom lines - often the powers and the
            # final [marks] - under the navy footer band.
            room = BOTTOM_Y - self.y
            if h > room:
                f = room / h
                w, h = w * f, room
            target = fitz.Rect(MARGIN_X, self.y, MARGIN_X + w, self.y + h)
            clip = fitz.Rect(r["x0"], r["y0"], r["x1"], r["y1"])
            self.page.show_pdf_page(target, src_doc, r["page"], clip=clip)
            self.page_has_content = True
            self.y += h + 4

    def divider(self):
        if self.page is not None and self.y + DIVIDER_GAP < BOTTOM_Y:
            mid = self.y + DIVIDER_GAP / 2
            self.page.draw_line(fitz.Point(MARGIN_X, mid),
                                fitz.Point(PAGE_W - MARGIN_X, mid),
                                color=(0.75, 0.75, 0.75), width=0.5)
            self.y += DIVIDER_GAP

    def insert_header(self, text: str):
        """Gold banner announcing a source insert. Inserts are full pages, so
        the banner always opens a fresh page and the insert follows under it."""
        if self.page is None or self.page_has_content:
            self.new_page()
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
            # The banner from insert_header() may sit alone on the current page;
            # the first insert page goes under it rather than leaving it stranded.
            if self.page is None or self.page_has_content:
                self.new_page()
            top = self.y
            ins_r = ins_doc[pg_num].rect
            scale = min(CONTENT_W / ins_r.width, (BOTTOM_Y - top) / ins_r.height)
            w, h = ins_r.width * scale, ins_r.height * scale
            cx = MARGIN_X + (CONTENT_W - w) / 2
            target = fitz.Rect(cx, top, cx + w, top + h)
            self.page.show_pdf_page(target, ins_doc, pg_num)
            self.page_has_content = True
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


_FURNITURE_RE = re.compile(
    r"^(©\s*UCLES.*|\[?\s*Turn over\s*\]?|\d{1,2}|BLANK PAGE|PMT|"
    r"DO NOT WRITE IN THIS MARGIN|\*\s*\d{6,}\s*\*)$", re.I)


def _is_answer_space(src_doc: fitz.Document, rect: dict) -> bool:
    """True if a rect holds nothing a student reads: only dotted answer rows,
    ruled lines and page furniture. Diagrams, grids and any real text say no."""
    page = src_doc[rect["page"]]
    clip = fitz.Rect(rect["x0"], rect["y0"], rect["x1"], rect["y1"])
    for block in page.get_text("blocks", clip=clip):
        for line in block[4].splitlines():
            s = line.strip()
            if not s or _FURNITURE_RE.match(s):
                continue
            compact = s.replace(" ", "")
            if sum(c in ".…_" for c in compact) / len(compact) <= 0.7:
                return False
    def overlaps(b):
        return b.x1 > clip.x0 and b.x0 < clip.x1 and b.y1 > clip.y0 and b.y0 < clip.y1

    if any(overlaps(fitz.Rect(i["bbox"])) for i in page.get_image_info()):
        return False
    for d in page.get_drawings():
        b = d["rect"]
        # Flat horizontal rules are answer lines; anything with height (a box,
        # grid, graph axis, figure) is content. Zero-height rects never
        # "overlap", so they fall through here as intended.
        if b.height > 1.5 and overlaps(b):
            return False
    return True


_EDGE_GROW_MAX = 14.0   # never grow a crop edge by more than this (pt)


def _fit_rect_to_text(src_doc: fitz.Document, rect: dict) -> dict:
    """Grow a crop's top/bottom edge to take in any text line it slices through.

    Segmentation sometimes ends a rect on the baseline of the last line (an
    answer line such as 'x = ....... or x = ....... [3]' at the foot of a
    page), so the bottoms of the glyphs - and superscripts/fractions at the top
    - were shaved off in the booklet. Only lines that genuinely straddle the
    edge count, page furniture is ignored, and growth is capped so a crop never
    swallows its neighbour."""
    page = src_doc[rect["page"]]
    y0, y1 = rect["y0"], rect["y1"]
    new_y0, new_y1 = y0, y1
    for block in page.get_text("dict", clip=fitz.Rect(
            rect["x0"], y0 - _EDGE_GROW_MAX, rect["x1"], y1 + _EDGE_GROW_MAX))["blocks"]:
        for line in block.get("lines", []):
            text = "".join(s["text"] for s in line["spans"]).strip()
            if not text or _FURNITURE_RE.match(text):
                continue
            lx0, ly0, lx1, ly1 = line["bbox"]
            if lx1 < rect["x0"] or lx0 > rect["x1"]:
                continue
            if ly0 < y1 - 1 < ly1 and ly1 - y1 <= _EDGE_GROW_MAX:
                new_y1 = max(new_y1, ly1 + 1)
            if ly0 < y0 + 1 < ly1 and y0 - ly0 <= _EDGE_GROW_MAX:
                new_y0 = min(new_y0, ly0 - 1)
    if (new_y0, new_y1) == (y0, y1):
        return rect
    return {**rect, "y0": round(max(new_y0, 0), 2),
            "y1": round(min(new_y1, page.rect.height), 2)}


def _drop_answer_only_rects(src_doc: fitz.Document, rects: list[dict]) -> list[dict]:
    """Drop continuation rects that are pure answer space.

    A long structured question often runs onto a following page that is nothing
    but dotted lines; in a topical booklet that prints as a blank page. The
    first rect is always kept (it carries the question number)."""
    if len(rects) < 2:
        return rects
    return rects[:1] + [r for r in rects[1:] if not _is_answer_space(src_doc, r)]


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
    """Name/Date write-in lines at the top of the first bubble sheet. Each line
    is also a fillable text field, so the sheet can be completed on screen."""
    for label, x in (("Name", MARGIN_X), ("Date", PAGE_W / 2 + 40)):
        page.insert_text((x, y), f"{label}:", fontsize=9.5, fontname="hebo",
                         color=(0.2, 0.2, 0.2))
        x0 = x + fitz.get_text_length(f"{label}:", fontname="hebo",
                                      fontsize=9.5) + 6
        x1 = x + (PAGE_W / 2 - MARGIN_X - 60)
        page.draw_line(fitz.Point(x0, y + 2), fitz.Point(x1, y + 2),
                       color=(0.7, 0.7, 0.7), width=0.7)
        w = fitz.Widget()
        w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w.field_name = f"student_{label.lower()}"
        w.rect = fitz.Rect(x0, y - 11, x1, y + 1.5)
        w.text_font, w.text_fontsize, w.text_color = "Helv", 10, (0.16, 0.21, 0.33)
        w.border_width, w.fill_color = 0, None
        page.add_widget(w)


# Filled-bubble appearance: a navy disc filling the whole circle, like a
# shaded OMR sheet (PyMuPDF's default "on" look is a small black dot).
def _disc_stream(r: float, rgb) -> bytes:
    k = 0.5523 * r
    c = r
    path = (f"{c} {2*r} m {c+k} {2*r} {2*r} {c+k} {2*r} {c} c "
            f"{2*r} {c-k} {c+k} 0 {c} 0 c {c-k} 0 0 {c-k} 0 {c} c "
            f"0 {c+k} {c-k} {2*r} {c} {2*r} c f")
    return f"q {rgb[0]:.3f} {rgb[1]:.3f} {rgb[2]:.3f} rg {path} Q".encode()


def _radio_bubble(page, name: str, option: str, centre, r: float) -> int:
    """One clickable option circle; returns its widget xref for grouping."""
    w = fitz.Widget()
    w.field_type = fitz.PDF_WIDGET_TYPE_RADIOBUTTON
    w.field_name = name
    w.rect = fitz.Rect(centre.x - r, centre.y - r, centre.x + r, centre.y + r)
    w.border_width, w.fill_color = 0, None
    w.field_value = False
    return page.add_widget(w).xref


def _group_radio_fields(doc, groups: dict[str, list[tuple[int, str]]]):
    """Turn same-named radio widgets into real radio groups.

    PyMuPDF writes every widget as its own field with the on-state "Yes", so a
    viewer treats the four options of a question as one linked box and ticks
    them all. A proper radio group is one parent field (/Ff radio +
    NoToggleToOff) whose kids each carry their own on-state (/A../D). Keys are
    removed by rewriting the object: PyMuPDF's "null" leaves a literal null
    that pdf.js rejects."""
    cat = doc.pdf_catalog()
    kind, val = doc.xref_get_key(cat, "AcroForm")
    af, pre = ((int(val.split()[0]), "") if kind == "xref" else (cat, "AcroForm/"))
    kid_xrefs = set()
    parents = []
    for name, kids in groups.items():
        px = doc.get_new_xref()
        doc.update_object(px, "<</FT/Btn/Ff 49152/T(%s)/V/Off/Kids[%s]>>" % (
            name, " ".join(f"{k} 0 R" for k, _ in kids)))
        parents.append(px)
        for k, opt in kids:
            kid_xrefs.add(k)
            obj = doc.xref_object(k, compressed=True)
            obj = re.sub(r"/(T|FT|Ff|V)(\s*\([^)]*\)|\s*/\w+|\s+\d+)", "", obj)
            doc.update_object(k, obj.rstrip()[:-2] + f"/Parent {px} 0 R>>")
            for ap in ("AP/N", "AP/D"):
                t, v = doc.xref_get_key(k, ap)
                if t != "dict":
                    continue
                doc.xref_set_key(k, ap, re.sub(r"/Yes\b", f"/{opt}", v))
                if ap == "AP/N":
                    on = re.search(rf"/{opt} (\d+) 0 R", doc.xref_get_key(k, ap)[1])
                    if on:
                        r = doc.xref_get_key(int(on.group(1)), "BBox")[1]
                        size = float(r.strip("[]").split()[2])
                        doc.update_stream(int(on.group(1)), _disc_stream(size / 2, ACCENT))
            doc.xref_set_key(k, "AS", "/Off")
    t, v = doc.xref_get_key(af, pre + "Fields")
    refs = [int(x) for x in re.findall(r"(\d+) 0 R", v)]
    keep = [x for x in refs if x not in kid_xrefs] + parents
    doc.xref_set_key(af, pre + "Fields", "[" + " ".join(f"{x} 0 R" for x in keep) + "]")


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
        groups: dict[str, list] = {}
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
                # Clickable too: on screen a tap shades the bubble; printed,
                # the drawn circle underneath is still there to fill by hand.
                groups.setdefault(f"Q{num}", []).append(
                    (_radio_bubble(page, f"Q{num}", opt, fitz.Point(cx, y), BUBBLE_R), opt))
        _group_radio_fields(doc, groups)
        footer_band(page, "Click or shade one circle per question")
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


DIFFICULTY_COLOURS = {1: (0.18, 0.62, 0.38), 2: (0.89, 0.69, 0.11),
                      3: (0.82, 0.26, 0.23)}
DIFFICULTY_NAMES = {1: "easy", 2: "medium", 3: "hard"}
TOC_TOP = 104.0
TOC_ROW_H = 16.5


def _toc_rows(qmeta):
    """Contents rows: a heading row whenever the section changes, then one row
    per question. Sections are sittings or chapters; a shuffled booklet has none."""
    rows, last = [], object()
    for m in qmeta:
        if m.get("section") and m["section"] != last:
            rows.append(("section", m["section"], None))
        last = m.get("section")
        rows.append(("question", None, m))
    return rows


def contents_pages(doc, qmeta, anchors, insert_at: int, subject: str) -> int:
    """Clickable contents: Q number, difficulty dot, source ref, chapter, page.

    Every row links to the page where that question's header sits, and the
    page number printed is the one in that page's footer. Returns how many
    pages were inserted (at `insert_at`, pushing the body back)."""
    if not qmeta:
        return 0
    q_anchor = {a["seq"]: a for a in anchors if a["kind"] == "question"}
    rows = _toc_rows(qmeta)
    per_page = int((BOTTOM_Y - 16 - TOC_TOP) // TOC_ROW_H)
    chunks = [rows[i:i + per_page] for i in range(0, len(rows), per_page)]
    n = len(chunks)
    # Create them all first: inserting a page invalidates Page handles taken
    # before it, so each page is fetched fresh by index when drawn on.
    for i in range(n):
        doc.new_page(pno=insert_at + i, width=PAGE_W, height=PAGE_H)
    body_offset = insert_at + n
    has_difficulty = any(m.get("difficulty") in DIFFICULTY_COLOURS for m in qmeta)

    x_q, x_dot, x_ref, x_ch, x_pg = MARGIN_X + 4, MARGIN_X + 44, MARGIN_X + 58, 330.0, PAGE_W - MARGIN_X - 4
    for i, chunk in enumerate(chunks):
        page = doc[insert_at + i]
        page.insert_text((MARGIN_X, 58), "Contents", fontsize=22, fontname="hebo",
                         color=ACCENT)
        sub = f"{subject}  ·  {len(qmeta)} questions  ·  click a row to jump to it"
        if n > 1:
            sub += f"   (page {i + 1} of {n})"
        page.insert_text((MARGIN_X, 76), sub, fontsize=8.5, fontname="helv", color=GREY)
        page.draw_line(fitz.Point(MARGIN_X, 84), fitz.Point(PAGE_W - MARGIN_X, 84),
                       color=GOLD, width=1.5)
        for label, x in (("Q", x_q), ("Source", x_ref), ("Chapter", x_ch)):
            page.insert_text((x, 98), label.upper(), fontsize=6.5, fontname="hebo", color=GREY)
        pw = fitz.get_text_length("PAGE", fontname="hebo", fontsize=6.5)
        page.insert_text((x_pg - pw, 98), "PAGE", fontsize=6.5, fontname="hebo", color=GREY)

        y = TOC_TOP
        for kind, heading, m in chunk:
            if kind == "section":
                page.insert_text((x_q, y + 12), heading, fontsize=9.5, fontname="hebo",
                                 color=ACCENT)
                y += TOC_ROW_H
                continue
            a = q_anchor.get(m["seq"])
            body_idx = a["page"] if a else 0
            base = y + 11.5
            page.insert_text((x_q, base), f"Q{m['seq']}", fontsize=9.5, fontname="hebo",
                             color=ACCENT)
            d = m.get("difficulty")
            if d in DIFFICULTY_COLOURS:
                page.draw_circle(fitz.Point(x_dot + 3, base - 3.2), 3.2, color=None,
                                 fill=DIFFICULTY_COLOURS[d])
            page.insert_text((x_ref, base), m["ref"], fontsize=8.5, fontname="helv",
                             color=(0.15, 0.15, 0.15))
            chapter = m.get("topic") or ""
            while (fitz.get_text_length(chapter, fontname="helv", fontsize=8) > x_pg - 40 - x_ch
                   and len(chapter) > 4):
                chapter = chapter[:-2].rstrip() + "…"
            page.insert_text((x_ch, base), chapter, fontsize=8, fontname="helv",
                             color=(0.56, 0.30, 0.05))
            num = str(body_idx + 1)
            nw = fitz.get_text_length(num, fontname="hebo", fontsize=9.5)
            page.insert_text((x_pg - nw, base), num, fontsize=9.5, fontname="hebo",
                             color=(0.08, 0.34, 0.55))
            page.draw_line(fitz.Point(MARGIN_X, y + TOC_ROW_H - 1),
                           fitz.Point(PAGE_W - MARGIN_X, y + TOC_ROW_H - 1),
                           color=(0.88, 0.86, 0.82), width=0.4, dashes="[1 2] 0")
            page.insert_link({"kind": fitz.LINK_GOTO, "page": body_offset + body_idx,
                              "to": fitz.Point(0, a["y"] if a else TOP_Y),
                              "from": fitz.Rect(MARGIN_X, y, PAGE_W - MARGIN_X,
                                                y + TOC_ROW_H)})
            y += TOC_ROW_H
        if has_difficulty and i == n - 1:
            lx = MARGIN_X
            for level, colour in DIFFICULTY_COLOURS.items():
                page.draw_circle(fitz.Point(lx + 3, BOTTOM_Y - 4), 3.2, color=None, fill=colour)
                page.insert_text((lx + 10, BOTTOM_Y - 1), DIFFICULTY_NAMES[level],
                                 fontsize=7.5, fontname="helv", color=GREY)
                lx += 60
        footer_band(page, right_text="Contents")
    return n


def set_outline(doc, anchors, qmeta, body_offset: int, toc_page: int | None):
    """PDF bookmarks mirroring the contents, so any viewer's sidebar navigates."""
    by_seq = {m["seq"]: m for m in qmeta}
    toc = [[1, "Contents", toc_page + 1]] if toc_page is not None else []
    in_section = False
    for a in anchors:
        page_no = body_offset + a["page"] + 1
        if a["kind"] == "section":
            toc.append([1, a["label"], page_no])
            in_section = True
        elif a["seq"] in by_seq:
            m = by_seq[a["seq"]]
            toc.append([2 if in_section else 1, f"Q{a['seq']}  ·  {m['ref']}", page_no])
    if toc:
        doc.set_toc(toc)


def write_page_map(path, booklet, qmeta, body_offset: int):
    """Where each question landed (1-based page numbers of the final PDF), so
    the web viewer can put Explain / Hint / Mark scheme chips on the right page."""
    q_anchors = [a for a in booklet.anchors if a["kind"] == "question"]
    last_body = body_offset + booklet.body_pages          # 1-based
    out = []
    for i, (m, a) in enumerate(zip(qmeta, q_anchors)):
        page = body_offset + a["page"] + 1
        if i + 1 < len(q_anchors):
            nxt = q_anchors[i + 1]
            end = body_offset + nxt["page"] + 1
            if nxt["y"] <= TOP_Y + TOPIC_HEADER_H + 1:
                end -= 1                   # next one starts a fresh page
            end = max(end, page)
        else:
            end = last_body
        out.append({**m, "page": page, "page_end": end, "y": round(a["y"], 1)})
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"body_offset": body_offset, "pages": booklet.doc.page_count,
                   "questions": out}, f, indent=1, default=str)


def _board_label(code: str) -> str:
    return ("Cambridge IGCSE" if code.startswith("0") else
            "Cambridge International A Level" if code.startswith("9") else
            "Cambridge O Level")


def _owl_pixmap():
    """The owl from the logo (no wordmark), full colour, on its cream ground."""
    if "owl_rgb" not in _WM_CACHE:
        clip = fitz.IRect(*config.LOGO_OWL_CLIP)
        src = fitz.Pixmap(str(config.LOGO_PATH))
        owl = fitz.Pixmap(fitz.csRGB, clip, False)
        owl.copy(src, clip)
        _WM_CACHE["owl_rgb"] = owl
    return _WM_CACHE["owl_rgb"]


def _link(page, rect, url=None):
    page.insert_link({"kind": fitz.LINK_URI, "uri": url or config.BRAND_WEBSITE_URL,
                      "from": fitz.Rect(rect)})


COVER_PANEL_H = 318.0


def build_cover(doc, args, subject, sections, contents=None):
    """Branded PrepWithTee cover.

    Navy header panel (brand, board, big title) with a cream owl medallion
    riding its bottom edge, stat tiles, the contents card and fillable
    Name / Class / Date fields above the footer band. The wordmark and the
    medallion link to the website.

    The title always names the TOPICS - that is what the booklet is - while
    `contents` is however the pages are actually grouped, so a session-ordered
    booklet lists its sittings without the cover claiming to be about them.
    """
    page = doc.new_page(pno=0, width=PAGE_W, height=PAGE_H)
    page.draw_rect(page.rect, color=None, fill=CREAM)
    codes_list = getattr(args, "syllabuses", None) or [args.syllabus]
    codes = ", ".join(codes_list)

    # ── Navy header panel with a gold arc motif in the corner ────────────────
    page.draw_rect(fitz.Rect(0, 0, PAGE_W, COVER_PANEL_H), color=None, fill=ACCENT)
    for i, rad in enumerate(range(60, 360, 34)):
        page.draw_circle(fitz.Point(PAGE_W + 10, -20), rad, color=GOLD,
                         width=0.8, stroke_opacity=max(0.06, 0.34 - i * 0.035))
    page.draw_rect(fitz.Rect(0, COVER_PANEL_H - 5, PAGE_W, COVER_PANEL_H),
                   color=None, fill=GOLD)

    # Brand line (clickable)
    bx, by = MARGIN_X + 16, 52
    page.insert_text((bx, by), config.BRAND_NAME, fontsize=17, fontname="hebo",
                     color=(1, 1, 1))
    bw = fitz.get_text_length(config.BRAND_NAME, fontname="hebo", fontsize=17)
    page.insert_text((bx, by + 14), config.BRAND_WEBSITE, fontsize=8.5,
                     fontname="helv", color=GOLD)
    _link(page, (bx - 2, by - 16, bx + max(bw, 90) + 2, by + 18))

    # Kind pill (top right)
    kind = "TOPICAL PAST PAPERS"
    kw = fitz.get_text_length(kind, fontname="hebo", fontsize=7.5) + 22
    pill = fitz.Rect(PAGE_W - MARGIN_X - 16 - kw, by - 13, PAGE_W - MARGIN_X - 16, by + 4)
    page.draw_rect(pill, color=GOLD, width=0.9, radius=0.5)
    page.insert_text((pill.x0 + 11, pill.y1 - 5.5), kind, fontsize=7.5,
                     fontname="hebo", color=GOLD)

    # Eyebrow + title + subtitle, left aligned
    y = 120
    eyebrow = f"{_board_label(codes_list[0]).upper()}   ·   {codes}"
    page.insert_text((bx, y), eyebrow, fontsize=8.5, fontname="hebo", color=GOLD)
    y += 36
    title = " · ".join(name for name, _ in sections)
    size = 30 if len(title) < 26 else (24 if len(title) < 48 else 19)
    for line in _wrap(title, "hebo", size, PAGE_W - 2 * bx - 60)[:3]:
        page.insert_text((bx, y), line, fontsize=size, fontname="hebo", color=(1, 1, 1))
        y += size + 5
    sub = subject
    papers_active = getattr(args, "papers_list", None) or (
        [args.paper] if getattr(args, "paper", None) else [])
    if papers_active:
        sub += "   ·   Paper " + " + ".join(str(p) for p in sorted(papers_active))
    page.insert_text((bx, y + 6), sub, fontsize=13, fontname="tiit",
                     color=(0.86, 0.88, 0.94))
    all_qs = [q for _, qs in sections for q in qs]
    n_mcq = sum(1 for q in all_qs if config.is_mcq(q["syllabus"], q["paper"], q["year"]))
    if args.no_ms:
        answers_note = "Questions only"
        answers_blurb = ", cropped straight from the original papers."
    elif n_mcq == len(all_qs):
        answers_note = "Answer grid at the back"
        answers_blurb = ", with a tick-in answer sheet and an answer grid at the back."
    else:
        answers_note = "Mark scheme follows each question"
        answers_blurb = ", each followed by its official mark scheme."
    subtopics_active = getattr(args, "subtopics", None)
    blurb = ("Real Cambridge past-paper questions on "
             + (", ".join(subtopics_active) if subtopics_active else "these chapters")
             + answers_blurb)
    ly = y + 34
    for line in _wrap(blurb, "helv", 9.5, PAGE_W - 2 * bx - 170)[:3]:
        page.insert_text((bx, ly), line, fontsize=9.5, fontname="helv",
                         color=(0.72, 0.76, 0.86))
        ly += 13

    # ── Owl medallion on the panel edge (clickable) ──────────────────────────
    mc = fitz.Point(PAGE_W - MARGIN_X - 16 - 62, COVER_PANEL_H)
    page.draw_circle(mc, 66, color=GOLD, fill=CREAM, width=3)
    if config.LOGO_PATH.exists():
        owl = _owl_pixmap()
        h = 96.0
        w = h * owl.width / owl.height
        page.insert_image(fitz.Rect(mc.x - w / 2, mc.y - h / 2 - 2,
                                    mc.x + w / 2, mc.y + h / 2 - 2), pixmap=owl)
    _link(page, (mc.x - 66, mc.y - 66, mc.x + 66, mc.y + 66))

    # ── Stat tiles ───────────────────────────────────────────────────────────
    total_q = sum(len(qs) for _, qs in sections)
    total_m = sum(q["marks"] or 0 for _, qs in sections for q in qs)
    years = sorted({q["year"] for _, qs in sections for q in qs})
    # Plain hyphen: the base-14 Helvetica has no en dash (it renders as a dot).
    span = (f"{years[0]}-{years[-1]}" if years and years[0] != years[-1]
            else str(years[0]) if years else f"{args.year_from}-{args.year_to}")
    mins = max(5, int(round(total_m * 1.2 / 5.0)) * 5) if total_m else None
    if not mins:
        est = "–"
    elif mins >= 60:
        est = f"{mins // 60}h {mins % 60:02d}m"
    else:
        est = f"{mins} min"
    tiles = [("QUESTIONS", str(total_q)), ("MARKS", str(total_m or "–")),
             ("PAST PAPERS", span), ("SUGGESTED TIME", est)]
    ty0 = COVER_PANEL_H + 84
    gap = 10
    tile_w = (PAGE_W - 2 * MARGIN_X - 3 * gap) / 4
    for i, (label, value) in enumerate(tiles):
        x0 = MARGIN_X + i * (tile_w + gap)
        r = fitz.Rect(x0, ty0, x0 + tile_w, ty0 + 58)
        page.draw_rect(r, color=(0.90, 0.86, 0.74), fill=(1, 1, 1), width=0.8, radius=0.12)
        vs = 20 if len(value) < 8 else 15
        page.insert_text((r.x0 + 12, r.y0 + 30), value, fontsize=vs, fontname="hebo",
                         color=ACCENT)
        page.insert_text((r.x0 + 12, r.y1 - 12), label, fontsize=6.5, fontname="hebo",
                         color=(0.66, 0.44, 0.06))

    # ── Contents card ────────────────────────────────────────────────────────
    listing = contents if contents is not None else [
        (name, [(name, q) for q in qs]) for name, qs in sections]
    y = ty0 + 58 + 22
    name_row_y = PAGE_H - 62 - 58                 # the fillable Name/Class/Date row
    max_rows = max(1, int((name_row_y - 34 - (y + 42)) // 17))
    shown, hidden = listing[:max_rows], listing[max_rows:]
    rows_h = (len(shown) + (1 if hidden else 0)) * 17
    card = fitz.Rect(MARGIN_X, y, PAGE_W - MARGIN_X, y + 40 + rows_h)
    page.draw_rect(card, color=None, fill=(1, 1, 1), radius=0.04)
    page.draw_rect(fitz.Rect(card.x0, card.y0, card.x0 + 4, card.y1), color=None, fill=GOLD)
    cy = card.y0 + 22
    page.insert_text((card.x0 + 18, cy), "WHAT'S INSIDE", fontsize=8, fontname="hebo",
                     color=(0.66, 0.44, 0.06))
    note = answers_note
    nw = fitz.get_text_length(note, fontname="tiit", fontsize=9.5)
    page.insert_text((card.x1 - 18 - nw, cy), note, fontsize=9.5, fontname="tiit", color=GREY)
    cy += 20
    for name, questions in shown:
        marks = sum(q["marks"] or 0 for _t, q in questions)
        page.insert_text((card.x0 + 18, cy), name, fontsize=10, fontname="hebo", color=ACCENT)
        tail = f"{len(questions)} questions  ·  {marks} marks"
        tl = fitz.get_text_length(tail, fontname="helv", fontsize=9)
        page.insert_text((card.x1 - 18 - tl, cy), tail, fontsize=9, fontname="helv", color=GREY)
        cy += 17
    if hidden:
        more = sum(len(qs) for _n, qs in hidden)
        page.insert_text((card.x0 + 18, cy), f"+ {len(hidden)} more  ·  {more} questions",
                         fontsize=9, fontname="helv", color=GREY)

    # ── Name / Class / Date (fillable on screen, a write-in line on paper) ───
    fields = (("Name", MARGIN_X, 250), ("Class", MARGIN_X + 262, 132),
              ("Date", MARGIN_X + 408, PAGE_W - 2 * MARGIN_X - 408))
    for label, x, w in fields:
        page.insert_text((x, name_row_y), label.upper(), fontsize=6.5, fontname="hebo",
                         color=(0.66, 0.44, 0.06))
        page.draw_line(fitz.Point(x, name_row_y + 24), fitz.Point(x + w - 8, name_row_y + 24),
                       color=ACCENT, width=0.8)
        wd = fitz.Widget()
        wd.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        wd.field_name = f"cover_{label.lower()}"
        wd.rect = fitz.Rect(x, name_row_y + 6, x + w - 8, name_row_y + 23)
        wd.text_font, wd.text_fontsize, wd.text_color = "Helv", 11, ACCENT
        wd.border_width, wd.fill_color = 0, None
        page.add_widget(wd)

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
        SELECT q.id, q.number, q.sub_part, q.marks, q.rects_json, q.text, c.topic, c.difficulty,
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


def fetch_by_ids(con, ids: list[int], topics: list[str]):
    """Exact questions in the exact order given (the web builder shuffles them).

    Returns (sections, ordered): `sections` groups by the selected topic each
    question is filed under (for the cover), `ordered` is [(topic, row)] in
    the caller's order. A question's home is the first selected topic it
    matches (primary, then secondary), else its own primary topic.
    """
    if not ids:
        return [], []
    ph = ",".join("?" for _ in ids)
    rows = {r["id"]: r for r in con.execute(
        f"""SELECT q.id, q.number, q.sub_part, q.marks, q.rects_json, q.text,
                   c.topic, c.difficulty, c.secondary_topic, c.subtopic,
                   p.syllabus, p.rel_path, p.filename,
                   p.year, p.session, p.paper, p.variant
            FROM questions q
            JOIN classifications c ON c.question_id = q.id
            JOIN papers p ON p.id = q.paper_id
            WHERE q.id IN ({ph}) AND q.status IS NOT 'excluded'""", ids)}
    ordered = []
    for qid in ids:
        r = rows.get(qid)
        if r is None:
            continue
        home = (next((t for t in topics if r["topic"] == t), None)
                or next((t for t in topics if r["secondary_topic"] == t), None)
                or r["topic"])
        ordered.append((home, r))
    # Sections follow the order the topics were PICKED (it names the cover),
    # not the order they first appear in the shuffled paper.
    by_topic: dict[str, list] = {t: [] for t in topics}
    for home, r in ordered:
        by_topic.setdefault(home, []).append(r)
    return [(t, rows) for t, rows in by_topic.items() if rows], ordered


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


def main(argv=None):
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
    p.add_argument("--order", choices=("session", "topic", "given"), default="session",
                   help="session: newest sitting first, topics grouped inside "
                        "each (default). topic: all of one chapter, then the next. "
                        "given: exactly the --ids order (implied by --ids).")
    p.add_argument("--ids", help="comma-separated question ids, in booklet order "
                                 "(the web builder's shuffled pick); filters are ignored")
    p.add_argument("--page-map", metavar="JSON",
                   help="also write where every question landed (for the web viewer)")
    p.add_argument("--no-contents", action="store_true",
                   help="skip the clickable contents page")
    p.add_argument("--no-ms", action="store_true", help="omit mark schemes")
    p.add_argument("--out", help="output path (default: data/output/...)")
    args = p.parse_args(argv)

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
    ordered = None
    if args.ids:
        ids = [int(x) for x in args.ids.split(",") if x.strip().isdigit()]
        sections, ordered = fetch_by_ids(con, ids, topics)
        args.order = "given"
    else:
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

    if ordered is not None:
        # One continuous run in the builder's shuffled order - no section
        # headings, the chapter tag on each question header says what it is.
        groups = [(None, ordered)]
    else:
        groups = render_groups(sections, getattr(args, "order", "session"))
    qmeta = []   # one entry per placed question, for contents + page map
    total_q = sum(len(qs) for _h, qs in groups)
    # The web builder's loader reads these lines from stdout (PWT_PROGRESS=1).
    progress = bool(os.environ.get("PWT_PROGRESS"))

    def report(stage: str, done: int | None = None):
        if progress:
            print(f"PROGRESS {stage} {done if done is not None else ''} {total_q}".rstrip(),
                  flush=True)
    for heading, questions in groups:
        if heading:
            first = json.loads(questions[0][1]["rects_json"] or "[]")
            first_h = (first[0]["y1"] - first[0]["y0"]) if first else 40.0
            booklet.topic_header(heading, keep_with=Q_HEADER_H + first_h)
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
            report("question", seq)
            rects = json.loads(q["rects_json"])
            if syl in _ESSAY_SYLLABUSES:
                rects = _trim_essay_rects(src(q["rel_path"]), rects)
            if syl in _TOTAL_MARKER_SYLLABUSES and q["sub_part"]:
                rects = _trim_total_marker_rects(src(q["rel_path"]), rects)
            rects = [_fit_rect_to_text(src(q["rel_path"]), r)
                     for r in _drop_answer_only_rects(src(q["rel_path"]), rects)]
            code = f"{q['paper']}{q['variant']}"
            syl = q["syllabus"]
            ref = config.source_ref(syl, code, q["session"],
                                    q["year"], q["number"], q["sub_part"] or "")
            plain_ref = ref
            if q["marks"]:
                ref += f"   [{q['marks']} mark{'' if q['marks'] == 1 else 's'}]"
            if q["topic"] != topic:
                ref += f"   (also covers {q['topic']})"
            first_h = (rects[0]["y1"] - rects[0]["y0"]) if rects else 40.0
            # In session order the section heading is a sitting, so the chapter
            # has to ride on the question itself or it is nowhere on the page.
            booklet.question_header(seq, ref, first_h, topic=topic)
            qmeta.append({"seq": seq, "qid": q["id"], "ref": plain_ref,
                          "topic": topic, "subtopic": q["subtopic"],
                          "marks": q["marks"], "difficulty": q["difficulty"],
                          "section": heading})
            if rects:
                booklet.place_rects(src(q["rel_path"]), rects)

            # Multiple choice: the answer is a single letter, so it goes in the
            # grid at the back rather than under the question where it would
            # spoil the attempt.
            if config.is_mcq(syl, q["paper"], q["year"]):
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
                    ms_rects = [_fit_rect_to_text(src(ms["rel_path"]), r)
                                for r in json.loads(ms["rects_json"])]
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
    build_cover(booklet.doc, args, subject, sections,
                contents=None if ordered is not None else groups)
    n_front = 1                                # the cover
    if mcq_answers:
        # Built last but moved to sit straight after the cover, so the sheet(s)
        # can be detached and used while working.
        base = booklet.doc.page_count          # sheets are appended here...
        sheets = bubble_sheet(booklet.doc, [s for s, _, _ in mcq_answers],
                              f"{subject} {codes}  ·  multiple choice")
        for i in range(len(sheets)):           # ...then moved to follow the cover
            booklet.doc.move_page(base + i, 1 + i)
        n_front += len(sheets)
    report("contents")
    n_toc = 0
    if not args.no_contents:
        n_toc = contents_pages(booklet.doc, qmeta, booklet.anchors,
                               insert_at=n_front, subject=f"{subject} {codes}")
    body_offset = n_front + n_toc
    set_outline(booklet.doc, booklet.anchors, qmeta, body_offset,
                toc_page=n_front if n_toc else None)
    if args.page_map:
        write_page_map(args.page_map, booklet, qmeta, body_offset)

    slug = re.sub(r"[^a-z0-9]+", "-", ",".join(topics).lower()).strip("-")
    if getattr(args, "subtopics", None):
        sub_slug = re.sub(r"[^a-z0-9]+", "-", ",".join(args.subtopics).lower()).strip("-")
        slug = slug + "_" + sub_slug
    out = config.ROOT / (args.out or
                         f"data/output/{'-'.join(args.syllabuses)}_{slug}_"
                         f"{args.year_from}-{args.year_to}.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)
    report("saving")
    save_small(booklet.doc, out)
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
