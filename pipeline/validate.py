"""Stage 6: internal consistency checks across the whole index.

    python -m pipeline.validate --syllabus 5054

There is no external answer key: classification is done in-session against
the syllabus subject content, so validation checks the pipeline's own
invariants instead:

  - every QP question has a crop file on disk, non-empty text, and marks
  - every QP question has a classification with a topic from taxonomy/
  - every QP question has a linked MS entry whose crop file exists
  - open review_queue items are reported (not failures)

Exits non-zero if any hard check fails.
"""

import argparse
import json

from . import config, db, heuristics, setup_logging

log = setup_logging("validate")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--syllabus", required=True, choices=sorted(config.SUBJECT_FOLDERS))
    args = p.parse_args()

    con = db.connect()
    taxonomy = heuristics.load_taxonomy(args.syllabus)
    valid_topics = {t["name"] for t in taxonomy["topics"]}
    failures = 0

    rows = con.execute(
        """
        SELECT q.id, q.number, q.text, q.marks, q.crop_path, p.filename,
               p.year, p.session, p.paper, p.variant,
               c.topic, c.secondary_topic
        FROM questions q
        JOIN papers p ON p.id = q.paper_id
        LEFT JOIN classifications c ON c.question_id = q.id
        WHERE p.syllabus = ? AND p.kind = 'qp'
          AND q.status IS NOT 'excluded'
        ORDER BY p.year, p.session, p.variant, q.number
        """, (args.syllabus,)).fetchall()
    if not rows:
        raise SystemExit("no questions found - run segment first")

    for r in rows:
        ref = f"{r['filename']} Q{r['number']}"
        if not r["crop_path"] or not (config.ROOT / r["crop_path"]).exists():
            log.error("%s: crop file missing (%s)", ref, r["crop_path"])
            failures += 1
        if not (r["text"] or "").strip():
            log.error("%s: empty text extract", ref)
            failures += 1
        if r["marks"] is None:
            log.warning("%s: no marks extracted", ref)
        if r["topic"] is None:
            log.error("%s: not classified", ref)
            failures += 1
        elif r["topic"] not in valid_topics or (
                r["secondary_topic"] and r["secondary_topic"] not in valid_topics):
            log.error("%s: topic not in taxonomy: %r / %r", ref, r["topic"],
                      r["secondary_topic"])
            failures += 1
        ms = con.execute(
            """
            SELECT m.crop_path FROM ms_entries m
            JOIN papers mp ON mp.id = m.paper_id
            WHERE mp.kind = 'ms' AND mp.syllabus = ? AND mp.year = ?
              AND mp.session = ? AND mp.paper = ? AND mp.variant = ?
              AND m.question_number = ?
            """,
            (args.syllabus, r["year"], r["session"], r["paper"], r["variant"],
             r["number"])).fetchone()
        if ms is None:
            log.error("%s: no linked MS entry", ref)
            failures += 1
        elif not ms["crop_path"] or not (config.ROOT / ms["crop_path"]).exists():
            log.error("%s: MS crop file missing (%s)", ref, ms["crop_path"])
            failures += 1

    open_reviews = con.execute(
        """
        SELECT COUNT(*) AS n FROM review_queue r
        JOIN questions q ON q.id = r.question_id
        JOIN papers p ON p.id = q.paper_id
        WHERE r.resolved = 0 AND p.syllabus = ?
        """, (args.syllabus,)).fetchone()["n"]
    topic_counts = con.execute(
        """
        SELECT c.topic, COUNT(*) AS n FROM classifications c
        JOIN questions q ON q.id = c.question_id
        JOIN papers p ON p.id = q.paper_id
        WHERE p.syllabus = ? GROUP BY c.topic ORDER BY n DESC
        """, (args.syllabus,)).fetchall()
    con.close()

    log.info("checked %d questions: %d hard failures, %d open review items",
             len(rows), failures, open_reviews)
    log.info("topics covered: %s",
             json.dumps({r["topic"]: r["n"] for r in topic_counts}))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
