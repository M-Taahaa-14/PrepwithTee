"""Push AI explanations (question_explanations) from index.db to Supabase.

    .venv\\Scripts\\python scripts\\sync_explanations_to_supabase.py            # dry run
    .venv\\Scripts\\python scripts\\sync_explanations_to_supabase.py --apply    # write

Run after `python -m pipeline.explain --collect`. Idempotent (upsert on
question_id); only real generations are sent (prompt_version >= 1 - the e2e
tests seed prompt_version 0 sample rows locally). Question ids are identical
in both databases (verified by scripts/sync_ms_to_supabase.py).
"""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
import psycopg2  # noqa: E402
from psycopg2.extras import Json, execute_values  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    local = sqlite3.connect(ROOT / "data" / "index.db")
    rows = local.execute(
        """SELECT question_id, content_json, model, prompt_version, input_tokens,
                  output_tokens, flagged, created_at
           FROM question_explanations WHERE prompt_version >= 1""").fetchall()
    print(f"{len(rows):,} explanations to sync")
    if not args.apply or not rows:
        print("DRY RUN - nothing written. Re-run with --apply.")
        return 0
    pg = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        with pg, pg.cursor() as cur:
            execute_values(cur, """
                INSERT INTO question_explanations
                    (question_id, content_json, model, prompt_version, input_tokens,
                     output_tokens, flagged, created_at)
                VALUES %s
                ON CONFLICT (question_id) DO UPDATE SET
                    content_json = EXCLUDED.content_json, model = EXCLUDED.model,
                    prompt_version = EXCLUDED.prompt_version,
                    input_tokens = EXCLUDED.input_tokens,
                    output_tokens = EXCLUDED.output_tokens""",
                [(r[0], Json(json.loads(r[1])), r[2], r[3], r[4], r[5], r[6], r[7])
                 for r in rows], page_size=500)
        print("APPLIED.")
    finally:
        pg.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
