"""Stage 3: classify segmented questions by syllabus topic.

    python -m pipeline.classify --syllabus 5054 --backend heuristic
    python -m pipeline.classify --syllabus 5054 --backend session --prepare
    python -m pipeline.classify --syllabus 5054 --backend session --ingest data/batches/5054_results.json

Backends (all emit the same record: topic, secondary_topic, difficulty,
confidence, rationale; confidence < 0.8 also lands in review_queue):

    heuristic  keyword scoring from taxonomy/{syllabus}.json (default, offline)
    session    two-step: --prepare exports pending questions (text + valid
               topic list) to data/batches/{syllabus}_questions.json for a
               Claude Code session to classify against the syllabus subject
               content; --ingest loads the session's results JSON
               ([{id, topic, secondary_topic, difficulty, confidence,
               rationale}, ...]) as authoritative labels.
    api        Anthropic API (needs ANTHROPIC_API_KEY in .env)

There is no external answer key or tracker: topics come from the official
syllabus chapters (taxonomy/) and questions are classified by review.

Idempotent: already-classified questions are skipped unless --force.
"""

import argparse
import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import fitz

from . import config, db, heuristics, setup_logging

log = setup_logging("classify")

CONFIDENCE_REVIEW_THRESHOLD = 0.8
_SOURCE_MARKERS = ("Insert", "Source A", "Source B", "Source C")


@lru_cache(maxsize=256)
def _insert_text(rel_path: str) -> str:
    """Return plain text of an insert PDF (page 1 onwards, skip the cover)."""
    try:
        doc = fitz.open(config.ROOT / rel_path.replace("\\", "/"))
        return "\n".join(doc[pg].get_text() for pg in range(1, len(doc)))
    except Exception:
        return ""


def _augment_with_insert(con, text: str, syllabus: str, year: int,
                          session: str, paper: int) -> str:
    """If the question text references an Insert, append the insert's text."""
    if not any(m in (text or "") for m in _SOURCE_MARKERS):
        return text
    row = con.execute(
        "SELECT rel_path FROM papers "
        "WHERE syllabus=? AND year=? AND session=? AND paper=? AND kind='in' "
        "LIMIT 1", (syllabus, year, session, paper)).fetchone()
    if not row:
        return text
    extra = _insert_text(row["rel_path"])
    return text + ("\n" + extra if extra else "")


def _pending_questions(con, syllabus: str, force: bool):
    q = """
        SELECT q.id, q.text, q.number, q.sub_part, p.filename, p.paper,
               p.year, p.session, p.syllabus
        FROM questions q JOIN papers p ON p.id = q.paper_id
        WHERE p.syllabus = ? AND p.kind = 'qp'
          AND q.status IS NOT 'excluded'
    """
    if not force:
        q += " AND q.id NOT IN (SELECT question_id FROM classifications)"
    return con.execute(q + " ORDER BY q.id", (syllabus,)).fetchall()


def _store(con, question_id: int, rec: dict, backend: str):
    con.execute(
        """
        INSERT INTO classifications (question_id, topic, secondary_topic, subtopic,
                                     difficulty, confidence, rationale,
                                     backend, classified_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (question_id) DO UPDATE SET
            topic = excluded.topic, secondary_topic = excluded.secondary_topic,
            subtopic = excluded.subtopic,
            difficulty = excluded.difficulty, confidence = excluded.confidence,
            rationale = excluded.rationale, backend = excluded.backend,
            classified_at = excluded.classified_at
        """,
        (question_id, rec["topic"], rec.get("secondary_topic"), rec.get("subtopic"),
         rec.get("difficulty"), rec["confidence"], rec.get("rationale"), backend,
         datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )
    status = "review" if rec["confidence"] < CONFIDENCE_REVIEW_THRESHOLD else "classified"
    con.execute("UPDATE questions SET status = ? WHERE id = ?", (status, question_id))
    if status == "review":
        db.add_review(con, f"low confidence {rec['confidence']:.2f} ({rec['topic']})",
                      question_id=question_id)


def run_heuristic(con, syllabus: str, force: bool):
    taxonomy = heuristics.load_taxonomy(syllabus)
    rows = _pending_questions(con, syllabus, force)
    done = reviewed = no_signal = 0
    for row in rows:
        # For source-based questions, augment the text with the insert content
        # so the heuristic can score from the source subject matter, not just
        # the generic "Study the sources" instruction text.
        text = _augment_with_insert(con, row["text"] or "", row["syllabus"],
                                    row["year"], row["session"], row["paper"])
        # paper scopes the topic list: a taxonomy topic carrying a `papers`
        # array is only a candidate for the components that examine it.
        rec = heuristics.classify_text(text, taxonomy, paper=row["paper"])
        if rec is None:
            db.add_review(con, "heuristic: no keyword signal", question_id=row["id"])
            con.execute("UPDATE questions SET status = 'review' WHERE id = ?",
                        (row["id"],))
            no_signal += 1
            continue
        # Subtopic pass: score subtopics within the winning topic
        subtopic = heuristics.classify_subtopic(text, taxonomy, rec["topic"])
        rec["subtopic"] = subtopic
        _store(con, row["id"], rec, "heuristic")
        done += 1
        if rec["confidence"] < CONFIDENCE_REVIEW_THRESHOLD:
            reviewed += 1
    con.commit()
    log.info("heuristic: %d classified (%d of them queued for review), "
             "%d with no keyword signal, out of %d pending questions",
             done, reviewed, no_signal, len(rows))


def run_session_prepare(con, syllabus: str, force: bool):
    """Export questions for in-session review to data/batches/."""
    taxonomy = heuristics.load_taxonomy(syllabus)
    rows = _pending_questions(con, syllabus, force)
    out = {
        "syllabus": syllabus,
        "valid_topics": [t["name"] for t in taxonomy["topics"]],
        "questions": [
            {"id": r["id"], "paper": r["filename"], "number": r["number"],
             "text": r["text"]}
            for r in rows
        ],
    }
    config.BATCHES_DIR.mkdir(parents=True, exist_ok=True)
    path = config.BATCHES_DIR / f"{syllabus}_questions.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    log.info("session prepare: %d questions exported to %s "
             "(classify them and ingest %s_results.json)",
             len(rows), path, syllabus)


def run_session_ingest(con, syllabus: str, results_path):
    taxonomy = heuristics.load_taxonomy(syllabus)
    valid = {t["name"] for t in taxonomy["topics"]}
    records = json.loads(results_path.read_text(encoding="utf-8"))
    known_ids = {r["id"] for r in con.execute(
        """SELECT q.id FROM questions q JOIN papers p ON p.id = q.paper_id
           WHERE p.syllabus = ?""", (syllabus,))}
    done = bad = 0
    for rec in records:
        if rec["id"] not in known_ids:
            log.warning("ingest: unknown question id %s - skipped", rec["id"])
            bad += 1
            continue
        if rec["topic"] not in valid or (
                rec.get("secondary_topic") and rec["secondary_topic"] not in valid):
            log.warning("ingest: invalid topic for id %s: %r / %r - skipped",
                        rec["id"], rec["topic"], rec.get("secondary_topic"))
            bad += 1
            continue
        rec.setdefault("secondary_topic", None)
        rec.setdefault("difficulty", None)
        rec.setdefault("confidence", 1.0)
        rec.setdefault("rationale", "classified in Claude Code session")
        _store(con, rec["id"], rec, "session")
        if rec["confidence"] >= CONFIDENCE_REVIEW_THRESHOLD:
            con.execute("UPDATE review_queue SET resolved = 1 "
                        "WHERE question_id = ? AND resolved = 0", (rec["id"],))
        done += 1
    con.commit()
    log.info("session ingest: %d stored, %d skipped, out of %d records",
             done, bad, len(records))


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--syllabus", required=True, choices=sorted(config.SUBJECT_FOLDERS))
    p.add_argument("--backend", default="heuristic",
                   choices=("heuristic", "session", "api"))
    p.add_argument("--force", action="store_true",
                   help="re-classify questions that already have a classification")
    p.add_argument("--prepare", action="store_true",
                   help="session backend: export pending questions to data/batches/")
    p.add_argument("--ingest", type=Path,
                   help="session backend: results JSON to load")
    args = p.parse_args()

    con = db.connect()
    if args.backend == "heuristic":
        run_heuristic(con, args.syllabus, args.force)
    elif args.backend == "session":
        if args.prepare == bool(args.ingest):
            raise SystemExit("session backend needs exactly one of --prepare / --ingest")
        if args.prepare:
            run_session_prepare(con, args.syllabus, args.force)
        else:
            run_session_ingest(con, args.syllabus, args.ingest)
    else:
        raise SystemExit("the api backend needs ANTHROPIC_API_KEY and is not "
                         "implemented yet; use heuristic or session")
    con.close()


if __name__ == "__main__":
    main()
