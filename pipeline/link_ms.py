"""Stage 4: segment mark schemes and join entries to questions by number.

    python -m pipeline.link_ms --syllabus 5054 [--year 2025] [--only 5054_s25_ms_22]

Modern Cambridge mark schemes (2020+) are landscape tables with a repeated
'Question | Answer | Marks' header; the Question column holds refs like
1(a)(ii). A new top-level integer prefix marks a question boundary. Each
question's rows are cropped (vector, via segment.make_crop) into
data/crops/{paper_key}/qNN_ms.pdf with a debug PNG alongside the QP ones.

All papers in scope are structured, so there is no MCQ answer-key grid to
parse. Mark schemes with no recognisable table (older prose-style MS) are
flagged to review_queue rather than guessed at.

After segmenting, entries are linked to questions of the matching QP
(same syllabus/year/session/paper/variant); number mismatches go to
review_queue.
"""

import argparse
import json
import re

import fitz

from . import config, db, setup_logging
from .segment import make_crop, render_debug_png, trim_rect_bottom

log = setup_logging("link_ms")

# A Question-column ref: 3, 3(b), 10(a)(ii), 18 (a), and merged forms like
# '5(b)(ii)(b) 41.2'. Loose on purpose: the vertical table borders confine
# matching to the Question column, and the ascending-run check filters noise.
REF_RE = re.compile(r"(\d{1,2})(?!\d)")
# Sub-part label inside the Question column: '1(a)', '(b)', '1 (c)' etc.
# Matches the FIRST (non-sub-sub-part) letter only; '(a)(i)' → 'a'.
SUBPART_RE = re.compile(r"\(\s*([a-d])\s*\)", re.I)
FALLBACK_REF_X = (50.0, 118.0)   # used only when no table borders are found
# MCQ answer table: "1\nC\n1\n" / "1 C 1" — matches question-number + A-D letter
MCQ_ANSWER_RE = re.compile(r"^\s*(\d{1,2})\s+([A-D])\s*[\n\r1 ]", re.M)
HEADER_FALLBACK_BOTTOM = 72.0
ROW_PAD_ABOVE = 8.0                  # include the row's top border line
CONTENT_BOTTOM_MARGIN = 52.0   # footer ('© Cambridge... / Page x of y') top is ~y550 on 595pt pages
SIDE_MARGIN = 56.0
MIN_RECT_HEIGHT = 6.0

# Syllabuses where MS entries should be split by sub-part (a/b/c/d).
SUB_PART_MS_SYLLABUSES = {"2059"}


def table_pages(doc) -> list[int]:
    pages = []
    for pno in range(doc.page_count):
        try:
            t = doc[pno].get_text()
        except RuntimeError:
            continue
        if (("Question" in t and "Answer" in t and "Marks" in t)
                or ("Qu" in t and "Answers" in t and "Mark" in t)):
            pages.append(pno)
    # Older MS format (pre-2022): header repeats on some but not all pages;
    # or Section B starts without a header. Extend coverage from the first
    # detected header page to the end of the document so we don't miss questions.
    if pages:
        first = pages[0]
        pages = list(range(first, doc.page_count))
    return pages


def header_bottom(page) -> float:
    """y just below the repeated 'Question | Answer | Marks' header row."""
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        for l in b["lines"]:
            for s in l["spans"]:
                if s["text"].strip() in ("Answer", "Answers", "Mark", "Marks") and s["bbox"][1] < 260:
                    return s["bbox"][3] + 4.0
    return HEADER_FALLBACK_BOTTOM


def question_column_bounds(page) -> tuple[float, float]:
    """(x0, x1) of the Question column, from the table's vertical borders.

    Column headers can be centered anywhere, but the vertical border lines
    are exact: the Question column lies between the two leftmost ones.
    Ignores margin decorations near the page edge (x < 30).
    """
    # Borders may be drawn as one long line or as many short per-row
    # segments; cluster vertical segments by x and sum their heights.
    heights: dict[float, float] = {}
    for d in page.get_drawings():
        r = d["rect"]
        if r.width < 2 and r.height > 5 and r.x0 > 30:
            key = next((x for x in heights if abs(x - r.x0) < 3), None)
            if key is None:
                key = r.x0
                heights[key] = 0.0
            heights[key] += r.height
    xs = sorted(x for x, h in heights.items() if h > 100)
    if len(xs) >= 2:
        return xs[0] + 1, xs[1] - 1
    return FALLBACK_REF_X


def find_boundaries(doc, pages) -> list[dict]:
    """First table row of each top-level question: [{'page','y','n'}, ...]."""
    # Candidate refs: REF_RE spans inside the Question column, whose bounds
    # come from the table's own vertical border lines on each page.
    rows = []   # (pno, y, n)
    for pno in pages:
        col_x0, col_x1 = question_column_bounds(doc[pno])
        for b in doc[pno].get_text("dict")["blocks"]:
            if b.get("type") != 0:
                continue
            for l in b["lines"]:
                spans = [s for s in l["spans"] if s["text"].strip()]
                if not spans:
                    continue
                s = spans[0]
                m = REF_RE.match(s["text"].strip())
                if m and col_x0 <= s["bbox"][0] <= col_x1:
                    rows.append((pno, s["bbox"][1], int(m.group(1))))
    if not rows:
        return []

    boundaries, current = [], 0
    for pno, y, n in sorted(rows):
        if n == current:
            continue
        if n == current + 1:
            boundaries.append({"page": pno, "y": y, "n": n})
            current = n
        elif n > current + 1:
            log.warning("question refs jump from %d to %d on page %d - "
                        "check the MS debug PNGs", current, n, pno + 1)
            boundaries.append({"page": pno, "y": y, "n": n})
            current = n
        # n < current: out-of-order digit, not a boundary
    return boundaries


def find_sub_part_rows(doc, pages: list[int], q_page: int, q_y: float,
                       end_page: int, end_y: float) -> dict[str, tuple[int, float]]:
    """Scan the Question column for sub-part labels within one question's range.

    Returns {letter: (page, y)} for the first row of each sub-part detected.
    Letter is the lowercase a/b/c/d.  Only the first occurrence of each letter
    is kept (subsequent continuation rows are not boundaries).
    """
    found: dict[str, tuple[int, float]] = {}
    for pno in [p for p in pages if q_page <= p <= end_page]:
        col_x0, col_x1 = question_column_bounds(doc[pno])
        for b in doc[pno].get_text("dict")["blocks"]:
            if b.get("type") != 0:
                continue
            for line in b["lines"]:
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                s = spans[0]
                y = s["bbox"][1]
                if pno == q_page and y < q_y:
                    continue
                if pno == end_page and y >= end_y:
                    continue
                if not (col_x0 <= s["bbox"][0] <= col_x1):
                    continue
                m = SUBPART_RE.search(s["text"].strip())
                if m:
                    letter = m.group(1).lower()
                    if letter not in found:
                        found[letter] = (pno, y)
    return found


def build_sub_part_region(doc, pages: list[int],
                           start_page: int, start_y: float,
                           end_page: int, end_y: float) -> list[dict]:
    """Build rects from (start_page, start_y) to (end_page, end_y), same
    logic as build_ms_regions but for a single sub-range."""
    rects = []
    for pno in [p for p in pages if start_page <= p <= end_page]:
        page = doc[pno]
        top = (start_y - ROW_PAD_ABOVE) if pno == start_page else header_bottom(page)
        bottom = end_y - ROW_PAD_ABOVE if pno == end_page else (
            page.rect.height - CONTENT_BOTTOM_MARGIN)
        if bottom - top < MIN_RECT_HEIGHT:
            continue
        rect = {
            "page": pno,
            "x0": SIDE_MARGIN,
            "y0": round(top, 2),
            "x1": round(page.rect.width - SIDE_MARGIN, 2),
            "y1": round(bottom, 2),
        }
        if pno != end_page:
            trim_rect_bottom(page, rect)
        if rect["y1"] - rect["y0"] < MIN_RECT_HEIGHT:
            continue
        rects.append(rect)
    return rects


def build_ms_regions(doc, boundaries, pages) -> list[list[dict]]:
    regions = []
    last_page = pages[-1]
    for i, b in enumerate(boundaries):
        nxt = boundaries[i + 1] if i + 1 < len(boundaries) else None
        end_page = nxt["page"] if nxt else last_page
        rects = []
        for pno in [p for p in pages if b["page"] <= p <= end_page]:
            page = doc[pno]
            top = (b["y"] - ROW_PAD_ABOVE) if pno == b["page"] else header_bottom(page)
            bottom = page.rect.height - CONTENT_BOTTOM_MARGIN
            clipped_by_next = (nxt and pno == nxt["page"]
                               and nxt["y"] - ROW_PAD_ABOVE < bottom)
            if clipped_by_next:
                bottom = nxt["y"] - ROW_PAD_ABOVE
            if bottom - top < MIN_RECT_HEIGHT:
                continue
            rect = {
                "page": pno,
                "x0": SIDE_MARGIN,
                "y0": round(top, 2),
                "x1": round(page.rect.width - SIDE_MARGIN, 2),
                "y1": round(bottom, 2),
            }
            if not clipped_by_next:
                trim_rect_bottom(page, rect)
            if rect["y1"] - rect["y0"] < MIN_RECT_HEIGHT:
                continue
            rects.append(rect)
        regions.append(rects)
    return regions


def extract_mcq_answers(doc) -> dict[int, str]:
    """Parse 'Question Answer Marks' table; return {q_number: letter}."""
    answers: dict[int, str] = {}
    for pno in range(doc.page_count):
        text = doc[pno].get_text()
        if "Question" not in text and "Answer" not in text:
            continue
        for m in MCQ_ANSWER_RE.finditer(text):
            q_num = int(m.group(1))
            if q_num not in answers:
                answers[q_num] = m.group(2).upper()
    return answers


def segment_ms(con, paper_row) -> list[int]:
    """Crop one MS into per-question PDFs; returns question numbers found."""
    src = config.ROOT / paper_row["rel_path"]
    key = config.paper_key(paper_row["syllabus"], paper_row["session"],
                           paper_row["year"],
                           f"{paper_row['paper']}{paper_row['variant']}")
    doc = fitz.open(src)
    for page in doc:  # 2023-era MS pages carry rotation=90; normalise so
        if page.rotation:  # text coordinates match the visual layout
            page.remove_rotation()
    con.execute("UPDATE papers SET page_count = ? WHERE id = ?",
                (doc.page_count, paper_row["id"]))

    # --- MCQ fast path: extract letter answers, no crops needed ---
    if config.is_mcq(paper_row["syllabus"], paper_row["paper"]):
        answers = extract_mcq_answers(doc)
        doc.close()
        if not answers:
            log.error("%s: MCQ MS - no answers found in text", paper_row["filename"])
            db.add_review(con, f"{paper_row['filename']}: MCQ MS - no answers found",
                          paper_id=paper_row["id"])
            return []
        con.execute("DELETE FROM ms_entries WHERE paper_id = ?", (paper_row["id"],))
        con.execute("DELETE FROM review_queue WHERE paper_id = ? AND resolved = 0",
                    (paper_row["id"],))
        for q_num, letter in sorted(answers.items()):
            con.execute(
                """INSERT INTO ms_entries
                   (paper_id, question_number, sub_part, answer, crop_path, rects_json)
                   VALUES (?, ?, '', ?, NULL, '[]')""",
                (paper_row["id"], q_num, letter),
            )
        con.commit()
        log.info("%s: MCQ - %d answers extracted (Q1-Q%d)",
                 paper_row["filename"], len(answers), max(answers))
        return sorted(answers.keys())

    pages = table_pages(doc)
    if not pages:
        db.add_review(con, f"{paper_row['filename']}: no MS table found "
                           "(older prose-style mark scheme?)",
                      paper_id=paper_row["id"])
        log.error("%s: no MS table found - skipped", paper_row["filename"])
        doc.close()
        return []
    boundaries = find_boundaries(doc, pages)
    if not boundaries:
        db.add_review(con, f"{paper_row['filename']}: table found but no "
                           "question refs recognised", paper_id=paper_row["id"])
        log.error("%s: no question refs recognised - skipped",
                  paper_row["filename"])
        doc.close()
        return []

    regions = build_ms_regions(doc, boundaries, pages)
    con.execute("DELETE FROM ms_entries WHERE paper_id = ?", (paper_row["id"],))
    # stale complaints from previous runs of this stage no longer apply
    con.execute("DELETE FROM review_queue WHERE paper_id = ? AND resolved = 0",
                (paper_row["id"],))

    use_sub_parts = paper_row["syllabus"] in SUB_PART_MS_SYLLABUSES
    total_entries = 0

    for i, (bnd, rects) in enumerate(zip(boundaries, regions)):
        if not rects:
            db.add_review(con, f"{paper_row['filename']}: Q{bnd['n']} produced "
                               "an empty MS region", paper_id=paper_row["id"])
            log.warning("%s: Q%d produced an empty MS region - skipped",
                        paper_row["filename"], bnd["n"])
            continue

        if use_sub_parts:
            # Find the extent of this question in the MS (its end = start of next)
            nxt = boundaries[i + 1] if i + 1 < len(boundaries) else None
            q_end_page = nxt["page"] if nxt else pages[-1]
            q_end_y = nxt["y"] if nxt else float("inf")
            sub_rows = find_sub_part_rows(doc, pages,
                                          bnd["page"], bnd["y"],
                                          q_end_page, q_end_y)
        else:
            sub_rows = {}

        if sub_rows:
            # Build a sub-part region for each detected sub-part letter.
            # Letters are sorted (a < b < c < d); each runs to the next letter's
            # start (or the question end).
            letters = sorted(sub_rows.keys())
            for j, letter in enumerate(letters):
                sp_page, sp_y = sub_rows[letter]
                if j + 1 < len(letters):
                    nxt_letter = letters[j + 1]
                    np, ny = sub_rows[nxt_letter]
                else:
                    np, ny = q_end_page, q_end_y if q_end_y != float("inf") else (
                        doc[q_end_page].rect.height - CONTENT_BOTTOM_MARGIN)
                sub_rects = build_sub_part_region(doc, pages, sp_page, sp_y, np, ny)
                if not sub_rects:
                    log.warning("%s: Q%d(%s) empty sub-part MS region - skipped",
                                paper_row["filename"], bnd["n"], letter)
                    continue
                crop_path = config.CROPS_DIR / key / f"q{bnd['n']:02d}{letter}_ms.pdf"
                png_path = config.DEBUG_DIR / key / f"q{bnd['n']:02d}{letter}_ms.png"
                make_crop(doc, sub_rects, crop_path)
                render_debug_png(crop_path, png_path)
                con.execute(
                    """INSERT INTO ms_entries
                       (paper_id, question_number, sub_part, crop_path, rects_json)
                       VALUES (?, ?, ?, ?, ?)""",
                    (paper_row["id"], bnd["n"], letter,
                     str(crop_path.relative_to(config.ROOT)),
                     json.dumps(sub_rects)),
                )
                total_entries += 1
        else:
            # No sub-parts detected (or syllabus doesn't use sub-parts): one entry.
            crop_path = config.CROPS_DIR / key / f"q{bnd['n']:02d}_ms.pdf"
            png_path = config.DEBUG_DIR / key / f"q{bnd['n']:02d}_ms.png"
            make_crop(doc, rects, crop_path)
            render_debug_png(crop_path, png_path)
            con.execute(
                """INSERT INTO ms_entries
                   (paper_id, question_number, sub_part, crop_path, rects_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (paper_row["id"], bnd["n"], "",
                 str(crop_path.relative_to(config.ROOT)), json.dumps(rects)),
            )
            total_entries += 1

    con.commit()
    numbers = [b["n"] for b in boundaries]
    log.info("%s: %d MS entries (%d questions Q%d-Q%d), debug PNGs in %s",
             paper_row["filename"], total_entries, len(numbers),
             numbers[0], numbers[-1], config.DEBUG_DIR / key)
    doc.close()
    return numbers


def link_to_questions(con, ms_row, ms_numbers):
    """Cross-check MS entries against the matching QP's questions."""
    qp = con.execute(
        """SELECT * FROM papers WHERE kind = 'qp' AND syllabus = ? AND year = ?
           AND session = ? AND paper = ? AND variant = ?""",
        (ms_row["syllabus"], ms_row["year"], ms_row["session"],
         ms_row["paper"], ms_row["variant"])).fetchone()
    if qp is None:
        log.warning("%s: matching QP not fetched yet - link check skipped",
                    ms_row["filename"])
        return
    q_numbers = {r["number"] for r in con.execute(
        "SELECT number FROM questions WHERE paper_id = ?", (qp["id"],))}
    if not q_numbers:
        log.warning("%s: matching QP not segmented yet - link check skipped",
                    ms_row["filename"])
        return
    missing_ms = sorted(q_numbers - set(ms_numbers))
    extra_ms = sorted(set(ms_numbers) - q_numbers)
    if missing_ms:
        db.add_review(con, f"{ms_row['filename']}: no MS entry for QP "
                           f"question(s) {missing_ms}", paper_id=ms_row["id"])
        log.warning("%s: no MS entry for QP question(s) %s",
                    ms_row["filename"], missing_ms)
    if extra_ms:
        db.add_review(con, f"{ms_row['filename']}: MS question(s) {extra_ms} "
                           f"have no QP question", paper_id=ms_row["id"])
        log.warning("%s: MS question(s) %s have no QP question",
                    ms_row["filename"], extra_ms)
    if not missing_ms and not extra_ms:
        log.info("%s: all %d questions linked", ms_row["filename"],
                 len(ms_numbers))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--syllabus", required=True, choices=sorted(config.SUBJECT_FOLDERS))
    p.add_argument("--paper", type=int)
    p.add_argument("--year", type=int)
    p.add_argument("--from", dest="year_from", type=int, default=None)
    p.add_argument("--to", dest="year_to", type=int, default=None)
    p.add_argument("--only", help="single MS by key or filename stem, "
                                  "e.g. 5054_s25_22 or 5054_s25_ms_22")
    args = p.parse_args()

    con = db.connect()
    q = "SELECT * FROM papers WHERE kind = 'ms' AND syllabus = ?"
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
        stem = args.only.replace("_ms", "").replace(".pdf", "")
        rows = [r for r in rows
                if config.paper_key(r["syllabus"], r["session"], r["year"],
                                    f"{r['paper']}{r['variant']}") == stem
                or r["filename"].startswith(args.only)]
    if not rows:
        log.error("no fetched MS papers match - run pipeline.fetch first")
        raise SystemExit(1)

    for row in rows:
        try:
            numbers = segment_ms(con, row)
        except RuntimeError as exc:
            log.error("%s: skipped (corrupt PDF: %s)", row["filename"], exc)
            db.add_review(con, f"{row['filename']}: corrupt PDF skipped ({exc})",
                          paper_id=row["id"])
            con.commit()
            continue
        if numbers:
            link_to_questions(con, row, numbers)
    con.close()
    log.info("done: %d mark schemes processed", len(rows))


if __name__ == "__main__":
    main()
