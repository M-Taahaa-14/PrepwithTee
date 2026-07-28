"""Extract answer letters from multiple-choice mark schemes.

    python -m pipeline.mcq --syllabus 9702 --paper 1

An MCQ mark scheme is a three-column table - Question | Answer | Marks - with
one row per question, so there is no prose to crop. `link_ms` already stores a
row crop per question; this stage reads the letter out of the same PDFs and
stores it on `ms_entries.answer`, which is what compose/testgen use to build
the answer grid and the bubble sheet.

Idempotent: re-running overwrites the same rows with the same letters.
"""

import argparse
import re

import fitz

from . import config, db, setup_logging

log = setup_logging("mcq")

# "12  B  1" - question number, option letter, one mark. The trailing mark is
# what keeps page furniture out: "9702/11", "Page 2 of 3" and the year in the
# footer never present as number/letter/1.
ANSWER_ROW = re.compile(r"(?<!\d)(\d{1,2})\s+([A-D])\s+1(?!\d)")


def parse_answers(pdf_path) -> dict[int, str]:
    """{question number: option letter} for one MCQ mark-scheme PDF."""
    doc = fitz.open(pdf_path)
    answers: dict[int, str] = {}
    for page in doc:
        for m in ANSWER_ROW.finditer(page.get_text()):
            answers[int(m.group(1))] = m.group(2)
    doc.close()
    return answers


def contiguous(answers: dict[int, str]) -> bool:
    """A clean key numbers 1..N with nothing missing."""
    nums = sorted(answers)
    return bool(nums) and nums == list(range(1, len(nums) + 1))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--syllabus", required=True, choices=sorted(config.SUBJECT_FOLDERS))
    p.add_argument("--paper", type=int, required=True)
    args = p.parse_args()

    if not config.is_mcq(args.syllabus, args.paper):
        raise SystemExit(
            f"{args.syllabus} paper {args.paper} is not a multiple-choice paper; "
            f"MCQ papers are {sorted(config.MCQ_PAPERS)}")

    con = db.connect()
    cols = {r["name"] for r in con.execute("PRAGMA table_info(ms_entries)")}
    if "answer" not in cols:
        con.execute("ALTER TABLE ms_entries ADD COLUMN answer TEXT")
        con.commit()
        log.info("added ms_entries.answer column")

    papers = con.execute(
        """SELECT id, filename, rel_path FROM papers
           WHERE syllabus = ? AND paper = ? AND kind = 'ms'
           ORDER BY year, session, variant""",
        (args.syllabus, args.paper)).fetchall()
    if not papers:
        raise SystemExit("no mark schemes fetched for that syllabus/paper")

    stored = skipped = unmatched = 0
    for row in papers:
        answers = parse_answers(config.ROOT / row["rel_path"])
        if not contiguous(answers):
            log.warning("%s: answer key is not contiguous (%d rows) - skipped",
                        row["filename"], len(answers))
            skipped += 1
            continue
        for number, letter in answers.items():
            n = con.execute(
                """UPDATE ms_entries SET answer = ?
                   WHERE paper_id = ? AND question_number = ?""",
                (letter, row["id"], number)).rowcount
            if n:
                stored += n
            else:
                unmatched += 1
        log.info("%s: %d answers", row["filename"], len(answers))
    con.commit()

    have = con.execute(
        """SELECT COUNT(*) n FROM ms_entries m JOIN papers p ON p.id = m.paper_id
           WHERE p.syllabus = ? AND p.paper = ? AND m.answer IS NOT NULL""",
        (args.syllabus, args.paper)).fetchone()["n"]
    log.info("stored %d answers across %d mark schemes (%d skipped, "
             "%d had no matching ms_entries row); %d answers on file",
             stored, len(papers) - skipped, skipped, unmatched, have)
    con.close()


if __name__ == "__main__":
    main()
