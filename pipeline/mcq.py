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


def _key_pairs(text: str) -> dict[int, str] | None:
    """Older (2010-2016) keys are a two-column "Question Number | Key" table with
    no marks column: the text reads 1 D 21 C 2 A 22 B ... Pair every number with
    the single letter straight after it. None if a number gets two letters."""
    tokens = text.split()
    out: dict[int, str] = {}
    for a, b in zip(tokens, tokens[1:]):
        if a.isdigit() and 1 <= int(a) <= 80 and b in ("A", "B", "C", "D"):
            n = int(a)
            if out.get(n, b) != b:
                return None
            out[n] = b
    return out


REMOVED = re.compile(r"(?<!\d)(\d{1,2})\s+Question\s+(?:removed|discounted)", re.I)
_REMOVED_CACHE: dict[str, set[int]] = {}


def removed_questions(pdf_path) -> set[int]:
    """Questions Cambridge struck out of the key ("Question Removed/Discounted")."""
    key = str(pdf_path)
    if key not in _REMOVED_CACHE:
        doc = fitz.open(pdf_path)
        _REMOVED_CACHE[key] = {int(m.group(1)) for page in doc
                               for m in REMOVED.finditer(page.get_text())}
        doc.close()
    return _REMOVED_CACHE[key]


def parse_answers(pdf_path) -> dict[int, str]:
    """{question number: option letter} for one MCQ mark-scheme PDF."""
    doc = fitz.open(pdf_path)
    answers: dict[int, str] = {}
    pages = [page.get_text() for page in doc]
    doc.close()
    removed = removed_questions(pdf_path)
    contiguous_ = lambda a: contiguous({**a, **{n: "-" for n in removed}})
    for text in pages:
        for m in ANSWER_ROW.finditer(text):
            answers[int(m.group(1))] = m.group(2)
    if contiguous_(answers):
        return answers
    # Fall back to the marks-less layout, only on pages that are the key table.
    paired: dict[int, str] = {}
    for text in pages:
        if "Key" not in text and "Answer" not in text:
            continue
        got = _key_pairs(text)
        if got is None:
            return answers
        for n, letter in got.items():
            if paired.get(n, letter) != letter:
                return answers
            paired[n] = letter
    return paired if contiguous_(paired) and len(paired) >= len(answers) else answers


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
        path = config.ROOT / row["rel_path"]
        answers = parse_answers(path)
        # Numbers Cambridge struck out still count as present for the check.
        whole = {**answers, **{n: "-" for n in removed_questions(path)}}
        # A real key has 40 (at least 20) answers; a handful of "1 A 2 A" hits
        # come from pre-2016 Paper 2 theory schemes, which were not MCQ then.
        if not contiguous(whole) or len(answers) < 20:
            log.warning("%s: answer key is not contiguous (%d rows) - skipped",
                        row["filename"], len(answers))
            skipped += 1
            continue
        for number, letter in answers.items():
            n = con.execute(
                """UPDATE ms_entries SET answer = ?
                   WHERE paper_id = ? AND question_number = ?""",
                (letter, row["id"], number)).rowcount
            if not n:
                # link_ms never made a row for it (the old two-column keys lost
                # questions 10-19): an MCQ row needs no crop, only the letter.
                con.execute(
                    """INSERT INTO ms_entries (paper_id, question_number, sub_part, answer)
                       VALUES (?, ?, '', ?)""", (row["id"], number, letter))
                n = 1
                unmatched += 1
            stored += n
        log.info("%s: %d answers", row["filename"], len(answers))
    con.commit()

    have = con.execute(
        """SELECT COUNT(*) n FROM ms_entries m JOIN papers p ON p.id = m.paper_id
           WHERE p.syllabus = ? AND p.paper = ? AND m.answer IS NOT NULL""",
        (args.syllabus, args.paper)).fetchone()["n"]
    log.info("stored %d answers across %d mark schemes (%d skipped, "
             "%d ms_entries rows created); %d answers on file",
             stored, len(papers) - skipped, skipped, unmatched, have)
    con.close()


if __name__ == "__main__":
    main()
