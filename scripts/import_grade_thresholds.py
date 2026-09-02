"""Import grade threshold seed files into Supabase.

Reads supabase/grade_thresholds_seed.json and supabase/grade_options_seed.json,
flattens the nested thresholds structure to match the DB schema, and upserts
into grade_thresholds and grade_options tables.

Run ONLY after reviewing the seed files:
    python scripts/import_grade_thresholds.py --dry-run      # preview counts
    python scripts/import_grade_thresholds.py                # live import

Requires SUPABASE_URL and SUPABASE_SERVICE_KEY in .env (or environment).
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def load_env():
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def flatten_component(rec: dict) -> dict:
    """Map seed JSON structure → grade_thresholds table columns."""
    t = rec.get("thresholds", {})
    return {
        "syllabus":    rec["syllabus"],
        "subject":     rec["subject"],
        "level":       rec["level"],
        "board":       rec.get("board", "CAIE"),
        "year":        rec["year"],
        "session":     rec["session"],
        "paper":       rec["paper"],
        "variant":     str(rec.get("variant", "")),
        "max_mark":    rec["max_mark"],
        "grade_astar": t.get("A*"),
        "grade_a":     t["A"],
        "grade_b":     t["B"],
        "grade_c":     t["C"],
        "grade_d":     t["D"],
        "grade_e":     t["E"],
        "grade_f":     t.get("F"),     # IGCSE only; None for O Level / A Level
        "grade_g":     t.get("G"),     # IGCSE only
        "status":      rec.get("status", "official"),
    }


def flatten_option(rec: dict) -> dict:
    """Map options seed JSON → grade_options table columns."""
    t = rec.get("thresholds", {})
    components = rec.get("components", "")
    # Normalise: '11, 21, 31' → '11,21,31'
    components = ",".join(c.strip() for c in components.split(",") if c.strip())
    # AS Level detection: option codes starting with S, P, or having max_mark < 200
    # (heuristic — 9702 AS options are S1-S5 and P1)
    opt = rec.get("option_code", "")
    is_as = opt.upper().startswith(("S", "P")) and rec.get("max_mark", 999) <= 150
    return {
        "syllabus":    rec["syllabus"],
        "subject":     rec["subject"],
        "level":       rec["level"],
        "board":       rec.get("board", "CAIE"),
        "year":        rec["year"],
        "session":     rec["session"],
        "option_code": opt,
        "components":  components,
        "max_mark":    rec["max_mark"],
        "is_as_level": is_as,
        "grade_astar": t.get("A*"),
        "grade_a":     t["A"],
        "grade_b":     t["B"],
        "grade_c":     t["C"],
        "grade_d":     t["D"],
        "grade_e":     t["E"],
        "grade_f":     t.get("F"),
        "grade_g":     t.get("G"),
        "status":      rec.get("status", "official"),
    }


def chunked(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="count rows only, do not write to Supabase")
    ap.add_argument("--components-only", action="store_true")
    ap.add_argument("--options-only", action="store_true")
    ap.add_argument("--batch-size", type=int, default=200)
    args = ap.parse_args()

    load_env()

    comp_seed = ROOT / "supabase" / "grade_thresholds_seed.json"
    opts_seed  = ROOT / "supabase" / "grade_options_seed.json"

    comp_rows = [flatten_component(r) for r in json.loads(comp_seed.read_text())]
    opts_rows  = [flatten_option(r)    for r in json.loads(opts_seed.read_text())] \
                 if opts_seed.exists() else []

    print(f"Component rows: {len(comp_rows)}")
    print(f"Option rows   : {len(opts_rows)}")

    if args.dry_run:
        # spot-check a few rows
        for r in comp_rows[:3]:
            print(" ", r)
        print(" ...")
        print("Dry run — nothing written.")
        return

    from supabase import create_client
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
        sys.exit(1)

    sb = create_client(url, key)

    if not args.options_only:
        print(f"Upserting {len(comp_rows)} component rows into grade_thresholds ...")
        ok = 0
        for batch in chunked(comp_rows, args.batch_size):
            res = sb.table("grade_thresholds").upsert(
                batch,
                on_conflict="syllabus,year,session,paper,variant"
            ).execute()
            ok += len(res.data)
        print(f"  → {ok} rows upserted")

    if not args.components_only and opts_rows:
        print(f"Upserting {len(opts_rows)} option rows into grade_options ...")
        ok = 0
        for batch in chunked(opts_rows, args.batch_size):
            res = sb.table("grade_options").upsert(
                batch,
                on_conflict="syllabus,year,session,option_code"
            ).execute()
            ok += len(res.data)
        print(f"  → {ok} rows upserted")

    print("Done.")


if __name__ == "__main__":
    main()
