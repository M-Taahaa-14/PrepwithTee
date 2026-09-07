"""Sync index.db papers + classifications to Supabase.

Run from project root with .env loaded:
    export $(grep -v '^#' .env | grep '=' | xargs -d '\n')
    .venv/Scripts/python scratchpad/sync_to_supabase.py
"""
import sqlite3, os, sys
from pathlib import Path

INDEX_DB = Path("E:/NexGen Tutors Topicals/data/index.db")

try:
    import psycopg2
    from psycopg2.extras import execute_values
except ImportError:
    sys.exit("pip install psycopg2-binary")

DB_URL = os.environ.get("DATABASE_URL")
if not DB_URL:
    sys.exit("DATABASE_URL not set")

local = sqlite3.connect(INDEX_DB)
local.row_factory = sqlite3.Row

pg = psycopg2.connect(DB_URL)
pg.autocommit = False
cur = pg.cursor()

# ── 1. Papers ─────────────────────────────────────────────────────────────
print("=== Syncing papers ===")
local_papers = local.execute(
    "SELECT id, syllabus, year, session, paper, variant, kind, filename, rel_path, page_count, fetched_at "
    "FROM papers ORDER BY id"
).fetchall()
print(f"Local papers: {len(local_papers)}")
cur.execute("SELECT COUNT(*) FROM papers")
print(f"Supabase papers before: {cur.fetchone()[0]}")

# Normalize Windows-style rel_path separators
papers_data = [
    (r["id"], r["syllabus"], r["year"], r["session"], r["paper"], r["variant"],
     r["kind"], r["filename"],
     r["rel_path"].replace("\\", "/") if r["rel_path"] else r["rel_path"],
     r["page_count"], r["fetched_at"])
    for r in local_papers
]

execute_values(cur,
    """INSERT INTO papers (id, syllabus, year, session, paper, variant, kind, filename, rel_path, page_count, fetched_at)
       VALUES %s
       ON CONFLICT (syllabus, year, session, paper, variant, kind)
       DO UPDATE SET filename=EXCLUDED.filename, rel_path=EXCLUDED.rel_path,
                     page_count=EXCLUDED.page_count, fetched_at=EXCLUDED.fetched_at""",
    papers_data, page_size=500)

pg.commit()
cur.execute("SELECT COUNT(*) FROM papers")
print(f"Supabase papers after: {cur.fetchone()[0]}")

# ── 2. Classifications ─────────────────────────────────────────────────────
print("\n=== Syncing classifications ===")
local_cls = local.execute(
    "SELECT question_id, topic, secondary_topic, subtopic, difficulty, confidence, rationale, backend, classified_at "
    "FROM classifications"
).fetchall()
print(f"Local classifications: {len(local_cls)}")
cur.execute("SELECT COUNT(*) FROM classifications")
print(f"Supabase classifications before: {cur.fetchone()[0]}")

# question_id values match between local SQLite and Supabase (verified)
cls_data = [
    (r["question_id"], r["topic"], r["secondary_topic"], r["subtopic"],
     r["difficulty"], r["confidence"], r["rationale"], r["backend"], r["classified_at"])
    for r in local_cls
]

execute_values(cur,
    """INSERT INTO classifications
       (question_id, topic, secondary_topic, subtopic, difficulty, confidence, rationale, backend, classified_at)
       VALUES %s
       ON CONFLICT (question_id) DO UPDATE SET
         topic=EXCLUDED.topic, secondary_topic=EXCLUDED.secondary_topic,
         subtopic=EXCLUDED.subtopic, difficulty=EXCLUDED.difficulty,
         confidence=EXCLUDED.confidence, rationale=EXCLUDED.rationale,
         backend=EXCLUDED.backend, classified_at=EXCLUDED.classified_at""",
    cls_data, page_size=500)

pg.commit()
cur.execute("SELECT COUNT(*) FROM classifications")
print(f"Supabase classifications after: {cur.fetchone()[0]}")

local.close()
cur.close()
pg.close()
print("\nDone.")
