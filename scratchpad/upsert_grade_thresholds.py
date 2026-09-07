"""Upsert grade_thresholds_seed.json into the local users.db.

Run on the server after deploying the updated seed JSON:
    python scratchpad/upsert_grade_thresholds.py

Safe to re-run (ON CONFLICT DO UPDATE).
"""
import json, sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "supabase" / "grade_thresholds_seed.json"
DB   = ROOT / "data" / "users.db"

records = json.loads(SEED.read_text(encoding="utf-8"))
con = sqlite3.connect(DB)
inserted = updated = errors = 0

for r in records:
    t = r.get("thresholds", {})
    # Support both old format (grade_a etc.) and new format (thresholds dict)
    grade_astar = t.get("A*") if t else r.get("grade_astar")
    grade_a  = t.get("A",  r.get("grade_a",  0))
    grade_b  = t.get("B",  r.get("grade_b",  0))
    grade_c  = t.get("C",  r.get("grade_c",  0))
    grade_d  = t.get("D",  r.get("grade_d",  0))
    grade_e  = t.get("E",  r.get("grade_e",  0))
    try:
        cur = con.execute(
            """INSERT INTO grade_thresholds
               (syllabus, subject, level, year, session, paper, variant, max_mark,
                grade_astar, grade_a, grade_b, grade_c, grade_d, grade_e, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(syllabus, year, session, paper, variant) DO UPDATE SET
                 max_mark=excluded.max_mark,
                 grade_astar=excluded.grade_astar,
                 grade_a=excluded.grade_a, grade_b=excluded.grade_b,
                 grade_c=excluded.grade_c, grade_d=excluded.grade_d,
                 grade_e=excluded.grade_e, status=excluded.status""",
            (r["syllabus"], r.get("subject",""), r.get("level",""),
             r["year"], r["session"], r["paper"], str(r.get("variant","")),
             r.get("max_mark", 0),
             grade_astar, grade_a, grade_b, grade_c, grade_d, grade_e,
             r.get("status","official"))
        )
        if cur.lastrowid:
            inserted += 1
        else:
            updated += 1
    except Exception as e:
        print(f"  ERR {r['syllabus']} {r['year']}{r['session']} P{r['paper']}: {e}")
        errors += 1

con.commit()
total = con.execute("SELECT COUNT(*) FROM grade_thresholds").fetchone()[0]
con.close()
print(f"Done: {inserted} inserted, {updated} updated, {errors} errors → {total} total rows")
