"""Push fc_* flashcard tables from local SQLite → Supabase.

Run once after import_flashcards populates data/index.db:
    python push_fc_to_supabase.py

Idempotent: existing rows are updated on code/name conflict.
"""

import os
import sqlite3
from pathlib import Path

SQLITE_DB = Path(__file__).parent / "data" / "index.db"

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    raise SystemExit("psycopg2 not installed. Run: pip install psycopg2-binary")

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    raise SystemExit("DATABASE_URL not set.")

src = sqlite3.connect(SQLITE_DB)
src.row_factory = sqlite3.Row
dst = psycopg2.connect(DATABASE_URL)
dst.autocommit = False
cur = dst.cursor()

# ── 1. Boards ─────────────────────────────────────────────────────────────
board_id_map: dict[int, int] = {}
for row in src.execute("SELECT * FROM fc_boards ORDER BY id"):
    cur.execute(
        "INSERT INTO fc_boards (name, code) VALUES (%s, %s) "
        "ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name RETURNING id",
        (row["name"], row["code"]),
    )
    board_id_map[row["id"]] = cur.fetchone()[0]
print(f"  boards:   {len(board_id_map)}")

# ── 2. Subjects ───────────────────────────────────────────────────────────
subject_id_map: dict[int, int] = {}
for row in src.execute("SELECT * FROM fc_subjects ORDER BY id"):
    pg_board_id = board_id_map[row["board_id"]]
    cur.execute(
        "INSERT INTO fc_subjects (board_id, name, code, level, alt_codes_json) "
        "VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (code) DO UPDATE SET "
        "  board_id = EXCLUDED.board_id, name = EXCLUDED.name, "
        "  level = EXCLUDED.level, alt_codes_json = EXCLUDED.alt_codes_json "
        "RETURNING id",
        (pg_board_id, row["name"], row["code"], row["level"], row["alt_codes_json"]),
    )
    subject_id_map[row["id"]] = cur.fetchone()[0]
print(f"  subjects: {len(subject_id_map)}")

# ── 3. Papers ─────────────────────────────────────────────────────────────
paper_id_map: dict[int, int] = {}
for row in src.execute("SELECT * FROM fc_papers ORDER BY id"):
    pg_subject_id = subject_id_map[row["subject_id"]]
    cur.execute(
        "INSERT INTO fc_papers (subject_id, name, code) VALUES (%s, %s, %s) "
        "ON CONFLICT (subject_id, code) DO UPDATE SET name = EXCLUDED.name "
        "RETURNING id",
        (pg_subject_id, row["name"], row["code"]),
    )
    paper_id_map[row["id"]] = cur.fetchone()[0]
print(f"  papers:   {len(paper_id_map)}")

# ── 4. Chapters ───────────────────────────────────────────────────────────
chapter_id_map: dict[int, int] = {}
for row in src.execute("SELECT * FROM fc_chapters ORDER BY id"):
    pg_paper_id = paper_id_map[row["paper_id"]]
    cur.execute(
        "INSERT INTO fc_chapters (paper_id, name, order_index) VALUES (%s, %s, %s) "
        "ON CONFLICT (paper_id, name) DO UPDATE SET order_index = EXCLUDED.order_index "
        "RETURNING id",
        (pg_paper_id, row["name"], row["order_index"]),
    )
    chapter_id_map[row["id"]] = cur.fetchone()[0]
print(f"  chapters: {len(chapter_id_map)}")

# ── 5. Blocks ─────────────────────────────────────────────────────────────
# Blocks use a partial unique index: (chapter_id, type, source_hash) WHERE source_hash IS NOT NULL
# ON CONFLICT on partial indexes requires repeating the WHERE in Postgres.
inserted = skipped = 0
batch: list[tuple] = []
for row in src.execute("SELECT * FROM fc_blocks ORDER BY id"):
    pg_chapter_id = chapter_id_map[row["chapter_id"]]
    batch.append((
        pg_chapter_id,
        row["type"],
        row["topic_label"],
        row["payload_json"],
        row["source_hash"],
    ))

# Insert in batches of 500
BATCH = 500
for i in range(0, len(batch), BATCH):
    chunk = batch[i : i + BATCH]
    # For blocks with source_hash: use ON CONFLICT on the partial index
    hashed = [(r, r[4]) for r in chunk if r[4] is not None]
    unhashed = [r for r in chunk if r[4] is None]

    if hashed:
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO fc_blocks (chapter_id, type, topic_label, payload_json, source_hash) "
            "VALUES %s "
            "ON CONFLICT (chapter_id, type, source_hash) WHERE source_hash IS NOT NULL "
            "DO UPDATE SET topic_label = EXCLUDED.topic_label, payload_json = EXCLUDED.payload_json",
            [r for r, _ in hashed],
        )
        inserted += len(hashed)

    if unhashed:
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO fc_blocks (chapter_id, type, topic_label, payload_json, source_hash) VALUES %s",
            unhashed,
        )
        inserted += len(unhashed)

print(f"  blocks:   {inserted}")

dst.commit()
dst.close()
src.close()
print("Done.")
