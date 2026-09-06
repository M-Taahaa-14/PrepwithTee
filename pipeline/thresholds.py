"""Stage: parse grade threshold PDFs into the grade_thresholds table.

    python -m pipeline.thresholds --syllabus 5054
    python -m pipeline.thresholds --syllabus 4024 --from 2015 --to 2026

Grade threshold PDFs (e.g. 5054_s25_gt.pdf) are CAIE documents with one row
per component and columns for the maximum mark and each grade (A*, A, B, C,
D, E, U). This stage extracts those tables and stores them per-row so
compose/testgen can annotate questions with grade-boundary context.

Idempotent: rows with the same (syllabus, year, session, component, grade) key
are overwritten. Files not yet downloaded are silently skipped.
"""

import argparse
import re
from pathlib import Path

import fitz

from . import config, db, setup_logging

log = setup_logging("thresholds")

GRADE_LETTERS = {"A*", "A", "B", "C", "D", "E", "F", "G", "U"}
NUMBER_RE = re.compile(r"^\d+$")
_Y_TOL = 3.0   # points: words within this y-range belong to the same row


def _group_rows(words: list) -> list[list]:
    """Group word tuples by y-coordinate into visual rows.

    Each group is sorted left-to-right by x0.  Words within Y_TOL of each
    other are treated as the same row.
    """
    rows: list[list] = []
    for w in words:
        x0, y0 = w[0], w[1]
        placed = False
        for row in rows:
            if abs(row[0][1] - y0) <= _Y_TOL:
                row.append(w)
                placed = True
                break
        if not placed:
            rows.append([w])
    for row in rows:
        row.sort(key=lambda w: w[0])   # sort left-to-right
    rows.sort(key=lambda r: r[0][1])   # sort top-to-bottom
    return rows


def _find_gt_files(syllabus: str, year_from: int, year_to: int) -> list[Path]:
    base = config.GT_DIR / syllabus
    files = []
    if not base.exists():
        return files
    for year_dir in sorted(base.iterdir()):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        year = int(year_dir.name)
        if not (year_from <= year <= year_to):
            continue
        for f in sorted(year_dir.glob("*.pdf")):
            files.append(f)
    return files


def _parse_filename(path: Path) -> tuple[str, int, str] | None:
    """Return (syllabus, year, session) from filename like 4024_s25_gt.pdf."""
    m = re.match(r"^(\d{4})_([smw])(\d{2})_gt\.pdf$", path.name, re.I)
    if not m:
        return None
    syllabus, session, yy = m.groups()
    year = 2000 + int(yy)
    return syllabus, year, session


def _extract_rows(pdf_path: Path) -> list[dict]:
    """Extract grade boundary rows from a gt PDF using word-position grouping.

    Cambridge GT PDFs render each row as a visual line of words.  Extracting
    plain text mis-places multi-line header cells; the word-position approach
    groups words that share the same y-coordinate into rows and uses x-position
    to identify which column each number belongs to.
    """
    rows = []
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        log.warning("cannot open %s: %s", pdf_path.name, e)
        return rows

    for page in doc:
        words = page.get_text("words")   # (x0,y0,x1,y1,word,block,line,wn)
        grouped = _group_rows(words)

        # Find the header row: the one that contains the most grade letters
        # (IGCSE papers have A-G; A Level has A*,A,B,C,D,E; A*=two chars)
        header_row_idx = None
        col_x: list[tuple[str, float]] = []   # [(grade, x_center), ...]
        max_mark_x: float | None = None

        for ri, row in enumerate(grouped):
            texts = [w[4] for w in row]
            grade_tokens = [t for t in texts if t in GRADE_LETTERS]
            if len(grade_tokens) >= 3:
                # This is the header row — record grade column x-centres
                col_x = [(w[4], (w[0] + w[2]) / 2)
                          for w in row if w[4] in GRADE_LETTERS]
                # Max-mark column: leftmost numeric-ish column header
                # ("Maximum" or "Mark" appears to the left of the grade letters)
                if col_x:
                    left_x = min(x for _, x in col_x)
                    for w in row:
                        wx = (w[0] + w[2]) / 2
                        if wx < left_x - 10:
                            max_mark_x = wx
                            break
                    if max_mark_x is None:
                        # Fall back: look for a "Maximum" word anywhere on page
                        for prev_row in grouped[:ri]:
                            for w in prev_row:
                                if "Maximum" in w[4] or "maximum" in w[4]:
                                    max_mark_x = (w[0] + w[2]) / 2
                                    break
                header_row_idx = ri
                break

        if header_row_idx is None or not col_x:
            continue   # no table on this page

        # Sort grade columns left-to-right
        col_x.sort(key=lambda t: t[1])
        grade_order = [g for g, _ in col_x]
        col_xs = [x for _, x in col_x]

        # Assign a word to the nearest column (max-mark or grade) by x-centre
        def nearest_col(wx: float) -> str | None:
            """Return 'max' or a grade letter for the column closest to wx."""
            if max_mark_x is not None and abs(wx - max_mark_x) < 25:
                if not col_xs or abs(wx - max_mark_x) < min(abs(wx - cx) for cx in col_xs):
                    return "max"
            if not col_xs:
                return None
            dists = [abs(wx - cx) for cx in col_xs]
            best_i = dists.index(min(dists))
            if dists[best_i] < 35:
                return grade_order[best_i]
            return None

        # Parse data rows below the header
        for row in grouped[header_row_idx + 1:]:
            texts = [w[4] for w in row]
            # A data row has a component/paper label starting with a letter
            # followed by numeric values; skip pure-numeric or blank rows
            if not texts:
                continue
            first = texts[0]
            _SKIP = {"learn", "for", "grade", "note", "cambridge", "minimum", "please",
                     "services", "information", "the", "this", "if", "subject", "overall",
                     "combined", "total", "maximum", "see", "note:"}
            if not first[0].isalpha() or first.lower() in _SKIP:
                continue
            # Skip long free-text rows (footnotes); real component names are ≤ 4 words
            if len(texts) > 6 and not any(NUMBER_RE.match(t) or t in {"–", "-", "−"}
                                          for t in texts[:4]):
                continue

            # Determine the data zone: x-position of the leftmost data column
            data_start_x = min(col_xs[0] - 25,
                               (max_mark_x - 25) if max_mark_x else col_xs[0] - 25)

            # Collect component name (words to the left of the data zone)
            name_parts = []
            value_words = []
            for w in row:
                wx = (w[0] + w[2]) / 2
                if wx < data_start_x:
                    name_parts.append(w[4])
                else:
                    value_words.append(w)

            if not name_parts or not value_words:
                continue

            component = " ".join(name_parts)
            # Build grade→mark mapping by nearest column
            marks: dict[str, int | None] = {}
            max_mark: int | None = None
            for w in value_words:
                tok = w[4]
                wx = (w[0] + w[2]) / 2
                col = nearest_col(wx)
                if col is None:
                    continue
                val: int | None = None
                if NUMBER_RE.match(tok):
                    val = int(tok)
                elif tok in {"–", "-", "−"}:
                    val = None
                else:
                    continue
                if col == "max":
                    max_mark = val
                else:
                    marks[col] = val

            if not marks:
                continue

            for grade, mark in marks.items():
                rows.append({
                    "component": component,
                    "grade": grade,
                    "mark": mark,
                    "max_mark": max_mark,
                })

    doc.close()
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--syllabus", required=True, choices=sorted(config.SUBJECT_FOLDERS))
    p.add_argument("--from", dest="year_from", type=int, default=config.YEAR_MIN)
    p.add_argument("--to", dest="year_to", type=int, default=config.YEAR_MAX)
    args = p.parse_args()

    con = db.connect()
    rel_path = lambda f: str(f.relative_to(config.ROOT))
    stats = {"parsed": 0, "rows": 0, "skipped": 0, "failed": 0}

    for gt_file in _find_gt_files(args.syllabus, args.year_from, args.year_to):
        meta = _parse_filename(gt_file)
        if not meta:
            log.warning("unexpected filename: %s", gt_file.name)
            continue
        syllabus, year, session = meta

        rows = _extract_rows(gt_file)
        if not rows:
            log.warning("no rows extracted from %s — may need manual review", gt_file.name)
            stats["failed"] += 1
            continue

        for row in rows:
            try:
                con.execute(
                    """
                    INSERT INTO grade_thresholds
                        (syllabus, year, session, component, grade, mark, max_mark, gt_file)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (syllabus, year, session, component, grade)
                    DO UPDATE SET mark=excluded.mark, max_mark=excluded.max_mark,
                                  gt_file=excluded.gt_file
                    """,
                    (syllabus, year, session, row["component"], row["grade"],
                     row["mark"], row["max_mark"], rel_path(gt_file)),
                )
            except Exception as e:
                log.error("DB error for %s %s: %s", gt_file.name, row, e)
        con.commit()
        log.info("parsed %s: %d rows", gt_file.name, len(rows))
        stats["parsed"] += 1
        stats["rows"] += len(rows)

    con.close()
    log.info("done: %(parsed)d files, %(rows)d rows, %(failed)d failed", stats)


if __name__ == "__main__":
    main()
