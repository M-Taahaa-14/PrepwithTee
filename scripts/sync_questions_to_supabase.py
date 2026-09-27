"""Sync papers, questions and classifications from index.db to Supabase.

Why this exists: migrate_to_supabase.py only INSERTs (ON CONFLICT DO NOTHING),
so it never carries later changes - new topic labels, status='excluded',
re-cropped rects - and it cannot remove a classification that was dropped
locally (an excluded question must not keep its old topic in production).

Safe by default:
  * dry run unless --apply is given (prints what would change, writes nothing)
  * papers are matched on id AND (syllabus, year, session, paper, variant, kind);
    any id whose key differs aborts the whole run
  * questions are matched on id AND (paper_id, number, sub_part); a clash aborts
  * production questions missing locally are only REPORTED, never deleted
    (user progress / annotations may point at them) - use --prune to see ids

Run from the repo root (DATABASE_URL comes from .env):
    .venv\\Scripts\\python scripts\\sync_questions_to_supabase.py            # dry run
    .venv\\Scripts\\python scripts\\sync_questions_to_supabase.py --apply    # write

Afterwards run scripts/sync_ms_to_supabase.py, upload the crop bundle
(scripts/bundle_crops.py) and POST /api/meta/refresh.
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

P_COLS = ["id", "syllabus", "year", "session", "paper", "variant", "kind",
          "filename", "rel_path", "page_count", "fetched_at"]
Q_COLS = ["id", "paper_id", "number", "sub_part", "text", "marks", "crop_path",
          "debug_png", "rects_json", "status"]
C_COLS = ["question_id", "topic", "secondary_topic", "subtopic", "difficulty",
          "confidence", "rationale", "backend", "classified_at"]


def _path(v):
    return v.replace("\\", "/") if isinstance(v, str) else v


def _rows(con, sql):
    return [tuple(r) for r in con.execute(sql).fetchall()]


def _fetch(cur, table, cols):
    cur.execute(f"SELECT {','.join(cols)} FROM {table}")
    return {r[0]: tuple(r) for r in cur.fetchall()}


def _same(a, b):
    """Row equality tolerant of float/str noise from the two drivers."""
    for x, y in zip(a, b):
        if isinstance(x, float) or isinstance(y, float):
            if x is None or y is None or abs(float(x) - float(y)) > 1e-6:
                if x != y:
                    return False
        elif (str(x) if x is not None else None) != (str(y) if y is not None else None):
            return False
    return True


def plan(con, cur):
    rep = Counter()
    # papers
    loc_p = {r[0]: r for r in _rows(con, f"SELECT {','.join(P_COLS)} FROM papers")}
    loc_p = {k: tuple(_path(v) if i == 8 else v for i, v in enumerate(r))
             for k, r in loc_p.items()}
    pg_p = _fetch(cur, "papers", P_COLS)
    bad = [k for k, r in loc_p.items() if k in pg_p and pg_p[k][1:7] != r[1:7]]
    if bad:
        raise SystemExit(f"ABORT: {len(bad)} paper ids name different papers "
                         f"in Supabase, e.g. {bad[:5]}")
    pg_keys = {r[1:7]: k for k, r in pg_p.items()}
    dup = [k for k, r in loc_p.items() if k not in pg_p and r[1:7] in pg_keys]
    if dup:
        raise SystemExit(f"ABORT: {len(dup)} local papers exist in Supabase under "
                         f"another id, e.g. {dup[:5]}")
    papers = [r for k, r in loc_p.items() if k not in pg_p]
    rep["papers insert"] = len(papers)

    # questions
    loc_q = {}
    for r in _rows(con, f"SELECT {','.join(Q_COLS)} FROM questions"):
        r = tuple(_path(v) if i in (6, 7) else (v.replace("\x00", "") if isinstance(v, str) else v)
                  for i, v in enumerate(r))
        loc_q[r[0]] = r
    pg_q = _fetch(cur, "questions", Q_COLS)
    clash = [k for k, r in loc_q.items()
             if k in pg_q and (pg_q[k][1], pg_q[k][2], pg_q[k][3] or "") != (r[1], r[2], r[3] or "")]
    if clash:
        raise SystemExit(f"ABORT: {len(clash)} question ids point at a different "
                         f"question in Supabase, e.g. {clash[:5]}")
    questions = []
    for k, r in loc_q.items():
        if k not in pg_q:
            questions.append(r); rep["questions insert"] += 1
        elif not _same(r, pg_q[k]):
            questions.append(r); rep["questions update"] += 1
    orphans = sorted(set(pg_q) - set(loc_q))
    rep["questions only in Supabase (kept)"] = len(orphans)

    # classifications
    loc_c = {r[0]: r for r in _rows(con, f"SELECT {','.join(C_COLS)} FROM classifications")}
    pg_c = _fetch(cur, "classifications", C_COLS)
    cls = []
    for k, r in loc_c.items():
        if k not in pg_c:
            cls.append(r); rep["classifications insert"] += 1
        elif not _same(r[:8], pg_c[k][:8]):
            cls.append(r); rep["classifications update"] += 1
    drop = sorted(k for k in pg_c if k in loc_q and k not in loc_c)
    rep["classifications delete"] = len(drop)
    return papers, questions, cls, drop, orphans, rep


def apply(cur, papers, questions, cls, drop):
    if papers:
        execute_values(cur, f"INSERT INTO papers ({','.join(P_COLS)}) VALUES %s",
                       papers, page_size=1000)
    if questions:
        sets = ",".join(f"{c}=EXCLUDED.{c}" for c in Q_COLS[1:])
        execute_values(cur, f"INSERT INTO questions ({','.join(Q_COLS)}) VALUES %s "
                            f"ON CONFLICT (id) DO UPDATE SET {sets}",
                       questions, page_size=1000)
    if cls:
        sets = ",".join(f"{c}=EXCLUDED.{c}" for c in C_COLS[1:])
        execute_values(cur, f"INSERT INTO classifications ({','.join(C_COLS)}) VALUES %s "
                            f"ON CONFLICT (question_id) DO UPDATE SET {sets}",
                       cls, page_size=1000)
    if drop:
        cur.execute("DELETE FROM classifications WHERE question_id = ANY(%s)", (drop,))
    # keep sequences ahead of the ids we inserted explicitly
    for t in ("papers", "questions"):
        cur.execute(f"SELECT setval(pg_get_serial_sequence('{t}','id'), "
                    f"(SELECT MAX(id) FROM {t}))")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="actually write")
    ap.add_argument("--prune", action="store_true",
                    help="list the question ids that exist only in Supabase")
    ap.add_argument("--index-db", default=str(ROOT / "data" / "index.db"))
    args = ap.parse_args(argv)
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")

    con = sqlite3.connect(args.index_db)
    pg = psycopg2.connect(url, connect_timeout=20)
    pg.autocommit = False
    cur = pg.cursor()
    try:
        papers, questions, cls, drop, orphans, rep = plan(con, cur)
        for k, n in rep.items():
            print(f"  {k:40} {n:7}")
        if args.prune and orphans:
            print("  only-in-Supabase question ids:", orphans[:200])
        if not args.apply:
            print("DRY RUN - nothing written. Re-run with --apply.")
            return 0
        apply(cur, papers, questions, cls, drop)
        pg.commit()
        print("APPLIED.")
    except Exception:
        pg.rollback()
        raise
    finally:
        pg.close()
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
