"""Sync mark-scheme entries (crops + MCQ answer letters) from index.db to Supabase.

Why this exists: the 2010-2019 backfill synced papers, questions and
classifications but never `ms_entries`, so production had 223 old mark-scheme
rows against ~16,400 locally and ZERO old MCQ answer keys.

Safe by default:
  * dry run unless --apply is given (prints what would change, writes nothing)
  * idempotent: upsert on (paper_id, question_number, sub_part)
  * paper ids are verified identical in both databases before anything is sent
  * refuses to write if a local row's id is already used in Supabase by a
    DIFFERENT (paper, question, sub_part) - that would clobber another row

Run from the repo root (DATABASE_URL comes from .env):
    .venv\\Scripts\\python scripts\\sync_ms_to_supabase.py            # dry run
    .venv\\Scripts\\python scripts\\sync_ms_to_supabase.py --apply    # write

After --apply, upload the crop files (scripts/bundle_crops.py) and POST
/api/meta/refresh.
"""

import argparse
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import psycopg2  # noqa: E402
from psycopg2.extras import execute_values  # noqa: E402

PAPER_KEY = "syllabus, year, session, paper, variant, kind"


def _norm(path):
    return path.replace("\\", "/") if path else path


def load_local(db_path: Path):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    papers = {r["id"]: tuple(r)[1:] for r in con.execute(
        f"SELECT id, {PAPER_KEY} FROM papers")}
    rows = con.execute(
        """SELECT m.id, m.paper_id, m.question_number, m.sub_part, m.crop_path,
                  m.rects_json, m.answer, p.year, p.syllabus
           FROM ms_entries m JOIN papers p ON p.id = m.paper_id""").fetchall()
    con.close()
    return papers, rows


def plan(local_papers, local_rows, cur):
    """Compare against Supabase. Returns (to_upsert, report) - no writes."""
    cur.execute(f"SELECT id, {PAPER_KEY} FROM papers")
    pg_papers = {r[0]: tuple(r[1:]) for r in cur.fetchall()}
    mismatched = [pid for pid, key in local_papers.items()
                  if pg_papers.get(pid) != key]
    if mismatched:
        raise SystemExit(f"ABORT: {len(mismatched)} paper ids differ between "
                         f"index.db and Supabase (e.g. {mismatched[:5]}). "
                         f"Sync papers first.")

    cur.execute("SELECT id, paper_id, question_number, sub_part, crop_path, "
                "rects_json, answer FROM ms_entries")
    pg_by_id = {r[0]: r for r in cur.fetchall()}
    pg_by_key = {(r[1], r[2], r[3]): r for r in pg_by_id.values()}

    to_upsert, report = [], Counter()
    clashes = []
    for r in local_rows:
        key = (r["paper_id"], r["question_number"], r["sub_part"] or "")
        era = "2010-19" if r["year"] < 2020 else "2020+"
        new = (r["id"], *key, _norm(r["crop_path"]), r["rects_json"], r["answer"])
        existing = pg_by_key.get(key)
        if existing is None:
            other = pg_by_id.get(r["id"])
            if other is not None and (other[1], other[2], other[3]) != key:
                clashes.append((r["id"], key, other[1:4]))
                continue
            report[(era, "insert")] += 1
            to_upsert.append(new)
        elif (_norm(existing[4]), existing[5], existing[6]) != new[4:]:
            report[(era, "update")] += 1
            to_upsert.append((existing[0], *new[1:]))   # keep Supabase's id
        else:
            report[(era, "unchanged")] += 1
    if clashes:
        raise SystemExit(f"ABORT: {len(clashes)} id clashes, e.g. {clashes[:3]}")
    return to_upsert, report


def apply(cur, rows):
    execute_values(cur, """
        INSERT INTO ms_entries (id, paper_id, question_number, sub_part,
                                crop_path, rects_json, answer)
        VALUES %s
        ON CONFLICT (paper_id, question_number, sub_part) DO UPDATE SET
            crop_path = EXCLUDED.crop_path,
            rects_json = EXCLUDED.rects_json,
            answer = EXCLUDED.answer""", rows, page_size=1000)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="actually write")
    ap.add_argument("--index-db", default=str(ROOT / "data" / "index.db"))
    args = ap.parse_args(argv)

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")

    local_papers, local_rows = load_local(Path(args.index_db))
    pg = psycopg2.connect(url)
    pg.autocommit = False
    cur = pg.cursor()
    try:
        rows, report = plan(local_papers, local_rows, cur)
        for (era, action), n in sorted(report.items()):
            print(f"  {era:8} {action:10} {n:6}")
        print(f"  total to write: {len(rows)}")
        if not args.apply:
            print("DRY RUN - nothing written. Re-run with --apply.")
            return 0
        apply(cur, rows)
        pg.commit()
        cur.execute("""SELECT COUNT(*), COUNT(answer) FROM ms_entries m
                       JOIN papers p ON p.id = m.paper_id WHERE p.year < 2020""")
        n, answers = cur.fetchone()
        print(f"APPLIED. Supabase 2010-19 ms_entries now {n} ({answers} MCQ keys).")
    except Exception:
        pg.rollback()
        raise
    finally:
        pg.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
