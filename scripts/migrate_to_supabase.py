#!/usr/bin/env python3
"""Migrate SQLite data into Supabase Postgres.

Prerequisites:
  1. supabase/schema.sql has been applied (scripts/apply_schema.py does this)
  2. .env has DATABASE_URL pointing at the Supabase pooler

Usage:
    .venv\\Scripts\\python scripts/migrate_to_supabase.py
"""

import sqlite3
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

import os

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    sys.exit("ERROR: DATABASE_URL must be set in .env")

pg = psycopg2.connect(DATABASE_URL, connect_timeout=20)
pg.autocommit = False
cur = pg.cursor()


def _scrub(v):
    # Postgres text cannot hold NUL; some PDF text extractions contain them.
    return v.replace("\x00", "") if isinstance(v, str) else v


def copy_table(sq, sq_sql: str, pg_table: str, cols: list[str], conflict: str):
    rows = [tuple(_scrub(v) for v in r) for r in sq.execute(sq_sql).fetchall()]
    if not rows:
        print(f"  {pg_table}: 0 rows")
        return
    execute_values(
        cur,
        f"INSERT INTO {pg_table} ({','.join(cols)}) VALUES %s "
        f"ON CONFLICT ({conflict}) DO NOTHING",
        rows,
        page_size=1000,
    )
    pg.commit()
    print(f"  {pg_table}: {len(rows)} rows")


# ── Pipeline tables ───────────────────────────────────────────────────────────
DB = ROOT / "data" / "index.db"
if not DB.exists():
    print(f"WARNING: {DB} not found — skipping pipeline data")
else:
    sq = sqlite3.connect(DB)
    print("Migrating pipeline tables...")

    copy_table(sq,
        "SELECT id,syllabus,year,session,paper,variant,kind,filename,rel_path,"
        "page_count,fetched_at FROM papers",
        "papers",
        ["id","syllabus","year","session","paper","variant","kind","filename",
         "rel_path","page_count","fetched_at"], "id")

    copy_table(sq,
        "SELECT id,paper_id,number,sub_part,text,marks,crop_path,debug_png,"
        "rects_json,status FROM questions",
        "questions",
        ["id","paper_id","number","sub_part","text","marks","crop_path",
         "debug_png","rects_json","status"], "id")

    copy_table(sq,
        "SELECT question_id,topic,secondary_topic,subtopic,difficulty,confidence,"
        "rationale,backend,classified_at FROM classifications",
        "classifications",
        ["question_id","topic","secondary_topic","subtopic","difficulty",
         "confidence","rationale","backend","classified_at"], "question_id")

    copy_table(sq,
        "SELECT id,paper_id,question_number,sub_part,crop_path,rects_json "
        "FROM ms_entries",
        "ms_entries",
        ["id","paper_id","question_number","sub_part","crop_path","rects_json"],
        "id")

    copy_table(sq,
        "SELECT id,question_id,paper_id,reason,created_at,resolved FROM review_queue",
        "review_queue",
        ["id","question_id","paper_id","reason","created_at","resolved"], "id")

    sq.close()

# ── Runtime form-submission DBs ───────────────────────────────────────────────
print("\nMigrating runtime databases:")
for db_path, sq_table, pg_table, cols in [
    (ROOT / "data" / "leads.db", "leads", "leads",
     ["parent_name","student_name","contact","grade","subjects","message"]),
    (ROOT / "data" / "feedback.db", "feedback", "feedback",
     ["rating","message","name","page","type"]),
    (ROOT / "data" / "subject_requests.db", "requests", "subject_requests",
     ["subject","board","message"]),
]:
    if not db_path.exists():
        print(f"  {db_path.name}: not found, skipping")
        continue
    sq = sqlite3.connect(db_path)
    avail = {r[1] for r in sq.execute(f"PRAGMA table_info({sq_table})").fetchall()}
    use = [c for c in cols if c in avail]
    if not use:
        print(f"  {db_path.name}: no matching columns, skipping")
        sq.close()
        continue
    rows = [tuple(r) for r in sq.execute(
        f"SELECT {','.join(use)} FROM {sq_table}").fetchall()]
    sq.close()
    if rows:
        execute_values(cur,
            f"INSERT INTO {pg_table} ({','.join(use)}) VALUES %s", rows)
        pg.commit()
    print(f"  {db_path.name} ({sq_table}): {len(rows)} rows")

# ── Seed the founder's teacher row ────────────────────────────────────────────
cur.execute("SELECT count(*) FROM teachers")
if cur.fetchone()[0] == 0:
    cur.execute("""
        INSERT INTO teachers (name, role, subjects_json, bio, qualifications,
                              experience_years, display_order, active)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        ("Muhammad Taahaa", "Head Tutor & Founder",
         '["4024","0580","5054","0625","2210","0478"]',
         "Founder of PrepWithTee. I believe every student can master Cambridge "
         "exams with the right guidance and past-paper practice. "
         "Book a free demo to see how.",
         "Cambridge O Level & IGCSE specialist · 5+ years one-on-one teaching",
         5, 0, True))
    pg.commit()
    print("\nSeeded 1 teacher (Muhammad Taahaa).")

# ── Verify ────────────────────────────────────────────────────────────────────
print("\nVerification:")
for tbl in ["papers","questions","classifications","ms_entries","review_queue",
            "teachers","leads","feedback","subject_requests"]:
    cur.execute(f"SELECT count(*) FROM {tbl}")
    print(f"  {tbl}: {cur.fetchone()[0]}")

pg.close()
print("\nMigration complete.")
