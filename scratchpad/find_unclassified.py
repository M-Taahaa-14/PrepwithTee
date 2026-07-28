import sqlite3
con = sqlite3.connect("data/index.db")
rows = con.execute("""
    SELECT q.id, q.number, p.session, p.year, p.variant, q.text
    FROM questions q
    JOIN papers p ON p.id=q.paper_id
    LEFT JOIN classifications c ON c.question_id=q.id
    WHERE p.syllabus='0625' AND p.paper=1 AND c.question_id IS NULL
""").fetchall()
for r in rows:
    print(f"id={r[0]} Q{r[1]} {r[2]}{r[3]:02d} v{r[4]}")
    print(f"  {(r[5] or '').strip()[:300]}")
    print()
con.close()
