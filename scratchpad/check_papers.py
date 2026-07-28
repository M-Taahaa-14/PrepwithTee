import sqlite3
con = sqlite3.connect("data/index.db")
rows = con.execute("""
    SELECT syllabus, paper, COUNT(*) as cnt
    FROM papers
    WHERE syllabus IN ('5054','0625')
    GROUP BY syllabus, paper ORDER BY syllabus, paper
""").fetchall()
for r in rows:
    print(r)

# Also check a few 0625 P2 question IDs
print("\nSample 0625 P2 questions:")
rows2 = con.execute("""
    SELECT q.id, p.syllabus, p.paper, p.session, p.year, p.variant, q.number
    FROM questions q JOIN papers p ON p.id=q.paper_id
    WHERE p.syllabus='0625' AND p.paper=2
    LIMIT 5
""").fetchall()
for r in rows2:
    print(r)
con.close()
