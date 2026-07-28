"""Stage: classify question difficulty from Cambridge examiner reports.

    python -m pipeline.difficulty --syllabus 9702 --from 2020 --to 2025
    python -m pipeline.difficulty --syllabus 9709 --from 2020 --to 2025 [--force]

Cambridge examiner reports (e.g. 9702_s23_er.pdf) cover every paper in a
session. Each report contains per-question commentary describing how candidates
performed. This stage:

  1. Reads each ER PDF from data/raw/{syllabus}/examiner_reports/{year}/.
  2. Splits the text into paper sections ("Paper N ...") then question sub-
     sections ("Question N").
  3. Scores each paragraph with hard/easy keyword lists to assign difficulty
     1 (easy), 2 (medium), or 3 (hard).
  4. Updates the difficulty column in classifications for the matching questions
     (syllabus, year, session, paper=any variant of paper_number, question_number).

Skips questions already having a non-NULL difficulty unless --force is given.

Run AFTER pipeline.classify (heuristic) so the classifications rows exist.
"""

import argparse
import re

import fitz

from . import config, db, setup_logging

log = setup_logging("difficulty")

# Phrases in examiner language that indicate student difficulty with the question
HARD_SIGNALS = [
    "poorly answered",
    "poorly done",
    "not well answered",
    "few candidates",
    "very few candidates",
    "many candidates were unable",
    "most candidates were unable",
    "candidates were unable to",
    "unable to",
    "failed to",
    "candidates failed",
    "struggled",
    "common error was",
    "common mistake",
    "frequently incorrect",
    "seldom achieved",
    "rarely gained",
    "marks were rarely",
    "many did not",
    "not attempted",
    "proved difficult",
    "found this difficult",
    "discriminating question",
]

EASY_SIGNALS = [
    "well answered",
    "well done",
    "generally well",
    "most candidates scored",
    "most candidates gained",
    "most candidates correctly",
    "majority of candidates scored",
    "majority scored",
    "straightforward",
    "answered correctly",
    "full marks",
    "successfully",
    "candidates generally",
    "able to",
    "all candidates",
    "understood",
    "accessible",
    "good responses",
    "high scores",
]

# Matches "Paper 1", "PAPER 2", "Paper 12" (two-digit codes) etc.
PAPER_RE = re.compile(r"\bpaper\s+(\d{1,2})\b", re.IGNORECASE)
# Matches "Question 1", "Question 10", "Q1", "Q 1" as a paragraph opener
QUESTION_RE = re.compile(
    r"(?:^|\n)\s*(?:question\s+(\d{1,2})|q\.?\s*(\d{1,2}))\b",
    re.IGNORECASE,
)


def _extract_text(pdf_path) -> str:
    with fitz.open(pdf_path) as doc:
        return "\n".join(page.get_text() for page in doc)


def _score_difficulty(text: str) -> int:
    t = text.lower()
    hard = sum(1 for kw in HARD_SIGNALS if kw in t)
    easy = sum(1 for kw in EASY_SIGNALS if kw in t)
    if hard > easy:
        return 3
    if easy > hard:
        return 1
    return 2


def _split_by_paper(text: str) -> dict[int, str]:
    """Return {paper_number: text_of_that_paper_section}."""
    sections: dict[int, str] = {}
    boundaries = []
    for m in PAPER_RE.finditer(text):
        # Only treat as a section header if it's near the start of a line
        line_start = text.rfind("\n", 0, m.start()) + 1
        prefix = text[line_start : m.start()].strip()
        if len(prefix) < 40:  # not buried mid-sentence
            boundaries.append((m.start(), int(m.group(1))))
    for i, (pos, paper_num) in enumerate(boundaries):
        end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(text)
        sections[paper_num] = text[pos:end]
    return sections


def _split_by_question(paper_text: str) -> dict[int, str]:
    """Return {question_number: commentary_text} within one paper section."""
    qs: dict[int, str] = {}
    boundaries = []
    for m in QUESTION_RE.finditer(paper_text):
        qnum = int(m.group(1) or m.group(2))
        boundaries.append((m.start(), qnum))
    for i, (pos, qnum) in enumerate(boundaries):
        end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(paper_text)
        qs[qnum] = paper_text[pos:end]
    return qs


def parse_er(pdf_path) -> dict[int, dict[int, int]]:
    """Return {paper_number: {question_number: difficulty (1|2|3)}}."""
    text = _extract_text(pdf_path)
    results: dict[int, dict[int, int]] = {}
    paper_sections = _split_by_paper(text)
    if not paper_sections:
        # Fall back: treat the whole document as one undifferentiated paper
        paper_sections = {0: text}
    for paper_num, paper_text in paper_sections.items():
        q_sections = _split_by_question(paper_text)
        if not q_sections:
            continue
        results[paper_num] = {q: _score_difficulty(t) for q, t in q_sections.items()}
    return results


def apply_difficulty(con, syllabus: str, year: int, session: str,
                     parsed: dict[int, dict[int, int]], force: bool = False) -> int:
    """Write difficulty values to classifications for matched questions."""
    updated = 0
    for paper_num, q_map in parsed.items():
        if not q_map:
            continue
        # Match all QP variants for this paper (e.g. paper_num=2 matches 21,22,23)
        paper_ids = con.execute(
            """SELECT id FROM papers
               WHERE syllabus=? AND year=? AND session=? AND paper=? AND kind='qp'""",
            (syllabus, year, session, paper_num),
        ).fetchall()
        if not paper_ids:
            log.debug("no QP found for %s %s%02d paper %d",
                      syllabus, session, year % 100, paper_num)
            continue
        for row in paper_ids:
            pid = row["id"]
            for q_num, diff in q_map.items():
                if force:
                    n = con.execute(
                        """UPDATE classifications
                           SET difficulty=?
                           WHERE question_id IN (
                               SELECT id FROM questions WHERE paper_id=? AND number=?
                           )""",
                        (diff, pid, q_num),
                    ).rowcount
                else:
                    n = con.execute(
                        """UPDATE classifications
                           SET difficulty=?
                           WHERE difficulty IS NULL
                             AND question_id IN (
                               SELECT id FROM questions WHERE paper_id=? AND number=?
                             )""",
                        (diff, pid, q_num),
                    ).rowcount
                updated += n
    con.commit()
    return updated


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--syllabus", required=True, choices=sorted(config.SUBJECT_FOLDERS))
    p.add_argument("--from", dest="year_from", type=int, default=config.YEAR_MIN)
    p.add_argument("--to", dest="year_to", type=int, default=config.YEAR_MAX)
    p.add_argument("--force", action="store_true",
                   help="overwrite existing difficulty values")
    p.add_argument("--dry-run", action="store_true",
                   help="print parsed difficulty without writing to DB")
    args = p.parse_args()

    er_dir = config.RAW_DIR / args.syllabus / "examiner_reports"
    if not er_dir.exists():
        log.error("No examiner reports found at %s — run: python -m pipeline.fetch "
                  "--syllabus %s --er --from %d --to %d",
                  er_dir, args.syllabus, args.year_from, args.year_to)
        raise SystemExit(1)

    con = db.connect()
    total_updated = 0

    for year_dir in sorted(er_dir.iterdir()):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        year = int(year_dir.name)
        if not (args.year_from <= year <= args.year_to):
            continue
        for er_pdf in sorted(year_dir.glob(f"{args.syllabus}_*_er.pdf")):
            # Derive session from filename: 9702_s23_er.pdf -> session 's', year 2023
            m = re.match(r"\d{4}_([smw])(\d{2})_er\.pdf$", er_pdf.name, re.I)
            if not m:
                continue
            session = m.group(1).lower()
            yr = 2000 + int(m.group(2))
            if yr != year:
                continue

            log.info("parsing %s", er_pdf.name)
            try:
                parsed = parse_er(er_pdf)
            except Exception as e:
                log.error("failed to parse %s: %s", er_pdf.name, e)
                continue

            if args.dry_run:
                for paper_num, q_map in sorted(parsed.items()):
                    for q_num, diff in sorted(q_map.items()):
                        label = {1: "easy", 2: "medium", 3: "hard"}[diff]
                        log.info("  %s p%d Q%d → %s", er_pdf.name, paper_num, q_num, label)
                continue

            n = apply_difficulty(con, args.syllabus, year, session, parsed,
                                 force=args.force)
            log.info("  %s: updated %d question difficulty values", er_pdf.name, n)
            total_updated += n

    con.close()
    log.info("done: %d difficulty values written", total_updated)


if __name__ == "__main__":
    main()
