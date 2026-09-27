"""Stage 2: split question papers into per-question vector crops with PyMuPDF.

    python -m pipeline.segment --syllabus 5054 --only 5054_s25_qp_22
    python -m pipeline.segment --syllabus 5054 --year 2025

Never re-typesets text: each question becomes a PDF assembled from region
crops of the original pages (show_pdf_page), so diagrams, graphs and answer
lines survive vector-perfect. Every crop is also rendered to a debug PNG in
data/debug/{paper_key}/ for mandatory visual verification.

Question boundaries are question-number anchors: numeric spans at a
consistent left-margin x (x < 60pt; body text starts ~66pt), forming the
ascending sequence 1, 2, 3... Boldness is not required - Oct/Nov papers
print question numbers regular-weight. A merged first sub-part ('10 (a)')
is tolerated, but standalone sub-part labels like (a) or (b)(ii) never
match.
"""

import argparse
import json
import re
from collections import Counter

import fitz

from . import config, db, setup_logging

log = setup_logging("segment")

# Syllabuses where questions must be split into (a)/(b)/(c)/(d) sub-parts.
# Each sub-part gets its own DB row and independent classification.
SUB_PART_SYLLABUSES = {"2058", "2059"}

ANCHOR_MAX_NUM = 40         # sanity ceiling for question numbers
ANCHOR_X_TOLERANCE = 3.0    # pt around the learned left-margin x
ANCHOR_MAX_X = 60.0         # question numbers sit at x~50; body text starts ~66
CONTENT_TOP = 61.0          # header band (barcode, corner marks, page no.) ends ~y59; body starts ~y64
CONTENT_BOTTOM = 52.0       # footer (© UCLES / paper ref / [Turn over) starts ~y793 on 842pt pages
CONTENT_X0 = 24.0
CONTENT_X1_MARGIN = 24.0
PAD_ABOVE_ANCHOR = 4.0
MIN_RECT_HEIGHT = 10.0
STITCH_GAP = 6.0            # visual gap between page-break segments
DEBUG_DPI = 150


def _line_start_spans(page):
    """Yield the first non-empty span of every text line on the page."""
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            spans = [s for s in line["spans"] if s["text"].strip()]
            if spans:
                yield spans[0]


def find_anchors(doc):
    """Return question-number anchors: [{'page', 'y', 'n'}, ...] for Q1, Q2, ..."""
    candidates = []
    for pno in range(doc.page_count):
        page = doc[pno]
        if not _is_content_page(page):
            continue
        for span in _line_start_spans(page):
            t = span["text"].strip()
            # Usually the number is its own span ('9'), but PDFs sometimes
            # merge it with what follows: '10 (a)' (physics) or the whole
            # first line, '11 The mass of a small box is x kg.' (maths).
            # Require a whitespace/end boundary so '228 as a product' can
            # never match as 22; the modal-x column and ascending-sequence
            # checks below guard against stray margin numbers.
            # Older O Level Chemistry prefixes the section: 'A1'..'A5', 'B6'..'B9'.
            m = re.match(r"[AB]?(\d{1,2})(?:\s|$)", t)
            if not m:
                continue
            n = int(m.group(1))
            if not 1 <= n <= ANCHOR_MAX_NUM:
                continue
            # Position is the reliable signal: question numbers hug the left
            # margin. Boldness is NOT required (Oct/Nov papers print them
            # regular-weight), and bold digits appear in figures elsewhere.
            if span["bbox"][0] > ANCHOR_MAX_X:
                continue
            candidates.append({
                "page": pno,
                "x": span["bbox"][0],
                "y": span["bbox"][1],
                "n": n,
            })
    if not candidates:
        return []

    # Learn the anchor column: modal x of the left-margin numeric candidates.
    modal_x = Counter(round(c["x"]) for c in candidates).most_common(1)[0][0]
    at_margin = [c for c in candidates if abs(c["x"] - modal_x) <= ANCHOR_X_TOLERANCE]

    # Keep the run 1, 2, 3, ... in reading order; anything else is page
    # numbers, data values or sub-part noise.
    anchors, expected = [], 1
    for c in sorted(at_margin, key=lambda c: (c["page"], c["y"])):
        if c["n"] == expected:
            anchors.append({"page": c["page"], "y": c["y"], "n": c["n"]})
            expected += 1
    leftovers = [c["n"] for c in at_margin if c["n"] >= expected]
    if leftovers:
        log.warning("anchor column had unmatched numbers %s after Q%d - check "
                    "the debug PNGs for a missed boundary",
                    sorted(set(leftovers)), expected - 1)
    return anchors


def acknowledgements_top(page) -> float | None:
    """y where the copyright acknowledgements block starts, if present."""
    hits = page.search_for("Permission to reproduce")
    return min(r.y0 for r in hits) if hits else None


def _is_content_page(page) -> bool:
    text = page.get_text()
    if "BLANK PAGE" in text:
        return False
    if not text.strip():
        return False
    ack_top = acknowledgements_top(page)
    if ack_top is None:
        return True
    # A short final question can share the last page with the
    # acknowledgements block - the page is non-content only when nothing
    # but that block (and the running header) is on it.
    for block in page.get_text("blocks"):
        x0, y0, x1, y1 = block[:4]
        if y0 > CONTENT_TOP and y1 < ack_top - 5 and str(block[4]).strip():
            return True
    return False


def build_regions(doc, anchors):
    """Per question, the list of page-region rects it occupies."""
    regions = []
    for i, a in enumerate(anchors):
        nxt = anchors[i + 1] if i + 1 < len(anchors) else None
        end_page = nxt["page"] if nxt else doc.page_count - 1
        rects = []
        for pno in range(a["page"], end_page + 1):
            page = doc[pno]
            if not _is_content_page(page):
                continue
            top = max(a["y"] - PAD_ABOVE_ANCHOR, CONTENT_TOP) if pno == a["page"] else CONTENT_TOP
            bottom = page.rect.height - CONTENT_BOTTOM
            ack_top = acknowledgements_top(page)
            if ack_top is not None:   # last question sharing the final page
                bottom = min(bottom, ack_top - 6)
            clipped_by_next = nxt and pno == nxt["page"] and nxt["y"] - PAD_ABOVE_ANCHOR < bottom
            if clipped_by_next:
                bottom = nxt["y"] - PAD_ABOVE_ANCHOR
            if bottom - top < MIN_RECT_HEIGHT:
                continue
            rect = {
                "page": pno,
                "x0": CONTENT_X0,
                "y0": round(top, 2),
                "x1": round(page.rect.width - CONTENT_X1_MARGIN, 2),
                "y1": round(bottom, 2),
            }
            if not clipped_by_next:
                trim_rect_bottom(page, rect)
            if rect["y1"] - rect["y0"] < MIN_RECT_HEIGHT:
                continue
            rects.append(rect)
        regions.append(rects)
    return regions


def trim_rect_bottom(page, rect, pad=8.0):
    """Clip trailing whitespace: lower rect['y1'] to the last content inside.

    Considers text/image blocks and vector drawings that overlap the rect,
    ignoring anything confined to the outer 20pt side strips (margin
    decorations like the vertical 'DO NOT WRITE IN THIS MARGIN' bars).
    """
    inner_x0, inner_x1 = rect["x0"] + 20, rect["x1"] - 20
    lowest = None
    for x0, y0, x1, y1, *_ in page.get_text("blocks"):
        if y1 > rect["y0"] and y0 < rect["y1"] and x0 < inner_x1 and x1 > inner_x0:
            y = min(y1, rect["y1"])
            lowest = y if lowest is None else max(lowest, y)
    for d in page.get_drawings():
        r = d["rect"]
        if (r.y1 > rect["y0"] and r.y0 < rect["y1"]
                and r.x0 < inner_x1 and r.x1 > inner_x0):
            y = min(r.y1, rect["y1"])
            lowest = y if lowest is None else max(lowest, y)
    if lowest is not None and lowest + pad < rect["y1"]:
        rect["y1"] = round(lowest + pad, 2)
    return rect


def find_sub_part_anchors(doc, q_rects):
    """Return [{sub_part, page, y}] for (a)/(b)/(c)/(d) labels inside a question region.

    Only the FIRST occurrence of each letter is kept (avoids picking up repeated
    labels in answer-line tables). Sub-part labels sit at a modest indent — never
    at the far-left question-number margin, never deep into body text.
    """
    found: dict[str, dict] = {}
    for rect in q_rects:
        page = doc[rect["page"]]
        clip = fitz.Rect(rect["x0"], rect["y0"], rect["x1"], rect["y1"])
        for block in page.get_text("dict", clip=clip)["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block["lines"]:
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                first = spans[0]
                m = re.match(r"^\(([a-d])\)(?:\s|$)", first["text"].strip())
                if m:
                    letter = m.group(1)
                    if letter not in found:
                        found[letter] = {
                            "sub_part": letter,
                            "page": rect["page"],
                            "y": first["bbox"][1],
                        }
    return [found[k] for k in sorted(found.keys())]


def split_question_by_sub_parts(q_rects, sub_anchors):
    """Slice a question's rects into per-sub-part rect lists.

    Sub-part 'a' begins from the very top of the question (so it captures any
    stem/preamble before the (a) label). Each subsequent sub-part begins at its
    anchor y on its anchor page. Returns {letter: [rects]}.
    """
    if not sub_anchors:
        return {}

    result: dict[str, list] = {}
    q_end_page = q_rects[-1]["page"]
    q_end_y = q_rects[-1]["y1"]

    for i, anchor in enumerate(sub_anchors):
        is_first = i == 0
        nxt = sub_anchors[i + 1] if i + 1 < len(sub_anchors) else None

        start_page = q_rects[0]["page"] if is_first else anchor["page"]
        start_y = q_rects[0]["y0"] if is_first else anchor["y"]
        end_page = nxt["page"] if nxt else q_end_page
        end_y = nxt["y"] if nxt else q_end_y

        part_rects = []
        for r in q_rects:
            if r["page"] < start_page or r["page"] > end_page:
                continue
            top = max(r["y0"], start_y) if r["page"] == start_page else r["y0"]
            bot = min(r["y1"], end_y) if r["page"] == end_page else r["y1"]
            if bot - top < MIN_RECT_HEIGHT:
                continue
            part_rects.append({
                "page": r["page"],
                "x0": r["x0"],
                "y0": round(top, 2),
                "x1": r["x1"],
                "y1": round(bot, 2),
            })
        if part_rects:
            result[anchor["sub_part"]] = part_rects

    return result


def make_crop(doc, rects, out_path):
    """Assemble one question's rects into a single vector PDF page (stitched)."""
    width = max(r["x1"] - r["x0"] for r in rects)
    height = sum(r["y1"] - r["y0"] for r in rects) + STITCH_GAP * (len(rects) - 1)
    out = fitz.open()
    page = out.new_page(width=width, height=height)
    y = 0.0
    for r in rects:
        h = r["y1"] - r["y0"]
        clip = fitz.Rect(r["x0"], r["y0"], r["x1"], r["y1"])
        target = fitz.Rect(0, y, r["x1"] - r["x0"], y + h)
        page.show_pdf_page(target, doc, r["page"], clip=clip)
        y += h + STITCH_GAP
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.save(out_path)
    out.close()


def render_debug_png(crop_path, png_path):
    png_path.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open(crop_path) as crop:
        crop[0].get_pixmap(dpi=DEBUG_DPI).save(png_path)


def extract_text_and_marks(doc, rects):
    text = "\n".join(
        doc[r["page"]].get_text(clip=fitz.Rect(r["x0"], r["y0"], r["x1"], r["y1"]))
        for r in rects
    ).strip()
    # Strip whole-question [Total: N marks] trailers before looking for part
    # marks — for sub-parts the total belongs to the parent question and would
    # produce a wildly wrong marks value for the sub-part.
    text_no_total = re.sub(r"\[\s*Total\s*:[^\]]*\]", "", text)
    part_marks = re.findall(r"\[\s*(\d{1,2})\s*\]", text_no_total)
    if part_marks:
        return text, (sum(int(x) for x in part_marks) or None)
    m = re.search(r"\[\s*Total\s*:\s*(\d+)\s*\]", text)
    return text, (int(m.group(1)) if m else None)


def flag_textless_pages(con, doc, paper_id, filename):
    """No silent OCR: pages with images but no text layer go to review."""
    for pno in range(doc.page_count):
        page = doc[pno]
        if not page.get_text().strip() and page.get_images(full=True):
            reason = f"{filename} p{pno + 1}: no text layer (possible scan) - not OCRed"
            log.warning(reason)
            db.add_review(con, reason, paper_id=paper_id)


def segment_paper(con, paper_row) -> int:
    src = config.ROOT / paper_row["rel_path"]
    key = config.paper_key(paper_row["syllabus"], paper_row["session"],
                           paper_row["year"], f"{paper_row['paper']}{paper_row['variant']}")
    doc = fitz.open(src)
    for page in doc:  # normalise rotated pages so coords match visual layout
        if page.rotation:
            page.remove_rotation()
    con.execute("UPDATE papers SET page_count = ? WHERE id = ?",
                (doc.page_count, paper_row["id"]))
    flag_textless_pages(con, doc, paper_row["id"], paper_row["filename"])

    anchors = find_anchors(doc)
    if not anchors:
        db.add_review(con, f"{paper_row['filename']}: no question anchors found",
                      paper_id=paper_row["id"])
        log.error("%s: no question anchors found - skipped", paper_row["filename"])
        doc.close()
        return 0

    regions = build_regions(doc, anchors)
    con.execute("DELETE FROM questions WHERE paper_id = ?", (paper_row["id"],))
    # stale complaints from previous runs of this stage no longer apply
    con.execute("DELETE FROM review_queue WHERE paper_id = ? AND resolved = 0",
                (paper_row["id"],))
    use_sub_parts = paper_row["syllabus"] in SUB_PART_SYLLABUSES

    inserted = 0
    for a, rects in zip(anchors, regions):
        if not rects:
            db.add_review(con, f"{paper_row['filename']}: Q{a['n']} produced "
                               "an empty region (anchor at page bottom?)",
                          paper_id=paper_row["id"])
            log.warning("%s: Q%d produced an empty region - skipped",
                        paper_row["filename"], a["n"])
            continue

        # For SUB_PART_SYLLABUSES, try to detect and split (a)/(b)/(c)/(d)
        if use_sub_parts:
            sub_anchors = find_sub_part_anchors(doc, rects)
            sub_map = split_question_by_sub_parts(rects, sub_anchors)
        else:
            sub_map = {}

        if sub_map:
            for letter, sub_rects in sub_map.items():
                slug = f"q{a['n']:02d}{letter}"
                crop_path = config.CROPS_DIR / key / f"{slug}.pdf"
                png_path = config.DEBUG_DIR / key / f"{slug}.png"
                make_crop(doc, sub_rects, crop_path)
                render_debug_png(crop_path, png_path)
                text, marks = extract_text_and_marks(doc, sub_rects)
                con.execute(
                    """INSERT INTO questions
                           (paper_id, number, sub_part, text, marks,
                            crop_path, debug_png, rects_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (paper_row["id"], a["n"], letter, text, marks,
                     str(crop_path.relative_to(config.ROOT)),
                     str(png_path.relative_to(config.ROOT)),
                     json.dumps(sub_rects)),
                )
                inserted += 1
            log.debug("%s Q%d → sub-parts: %s",
                      paper_row["filename"], a["n"], ", ".join(sub_map.keys()))
        else:
            # Whole-question row (all non-SUB_PART or questions with no detected parts)
            crop_path = config.CROPS_DIR / key / f"q{a['n']:02d}.pdf"
            png_path = config.DEBUG_DIR / key / f"q{a['n']:02d}.png"
            make_crop(doc, rects, crop_path)
            render_debug_png(crop_path, png_path)
            text, marks = extract_text_and_marks(doc, rects)
            con.execute(
                """INSERT INTO questions
                       (paper_id, number, sub_part, text, marks,
                        crop_path, debug_png, rects_json)
                   VALUES (?, ?, '', ?, ?, ?, ?, ?)""",
                (paper_row["id"], a["n"], text, marks,
                 str(crop_path.relative_to(config.ROOT)),
                 str(png_path.relative_to(config.ROOT)),
                 json.dumps(rects)),
            )
            inserted += 1
    con.commit()
    spans = sum(1 for r in regions if len({x["page"] for x in r}) > 1)
    log.info("%s: %d questions (Q1-Q%d), %d span page breaks, debug PNGs in %s",
             paper_row["filename"], inserted, anchors[-1]["n"], spans,
             config.DEBUG_DIR / key)
    doc.close()
    return inserted


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--syllabus", required=True, choices=sorted(config.SUBJECT_FOLDERS))
    p.add_argument("--paper", type=int)
    p.add_argument("--year", type=int)
    p.add_argument("--from", dest="year_from", type=int, default=None)
    p.add_argument("--to", dest="year_to", type=int, default=None)
    p.add_argument("--only", help="single paper by key or filename stem, "
                                  "e.g. 5054_s25_22 or 5054_s25_qp_22")
    args = p.parse_args()

    con = db.connect()
    q = "SELECT * FROM papers WHERE kind = 'qp' AND syllabus = ?"
    params: list = [args.syllabus]
    if args.paper:
        q += " AND paper = ?"
        params.append(args.paper)
    if args.year:
        q += " AND year = ?"
        params.append(args.year)
    if args.year_from:
        q += " AND year >= ?"
        params.append(args.year_from)
    if args.year_to:
        q += " AND year <= ?"
        params.append(args.year_to)
    rows = con.execute(q + " ORDER BY year, session, paper, variant", params).fetchall()
    if args.only:
        stem = args.only.replace("_qp", "").replace(".pdf", "")
        rows = [r for r in rows
                if config.paper_key(r["syllabus"], r["session"], r["year"],
                                    f"{r['paper']}{r['variant']}") == stem
                or r["filename"].startswith(args.only)]
    if not rows:
        log.error("no fetched QP papers match - run pipeline.fetch first")
        raise SystemExit(1)

    total = 0
    skipped = 0
    for row in rows:
        try:
            total += segment_paper(con, row)
        except RuntimeError as exc:
            log.error("%s: MuPDF error, skipping — %s", row["filename"], exc)
            db.add_review(con, f"{row['filename']}: MuPDF crash ({exc}), skipped",
                          paper_id=row["id"])
            con.commit()
            skipped += 1
    con.close()
    log.info("done: %d papers, %d questions segmented, %d skipped (MuPDF error)",
             len(rows), total, skipped)


if __name__ == "__main__":
    main()
