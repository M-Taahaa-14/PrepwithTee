import sqlite3
con = sqlite3.connect("data/index.db")

for syl, paper in [("5054", 1), ("0625", 1), ("0625", 2)]:
    total = con.execute("""
        SELECT COUNT(*) FROM questions q
        JOIN papers p ON p.id=q.paper_id
        WHERE p.syllabus=? AND p.paper=?
    """, (syl, paper)).fetchone()[0]

    classified = con.execute("""
        SELECT COUNT(*) FROM questions q
        JOIN papers p ON p.id=q.paper_id
        JOIN classifications c ON c.question_id=q.id
        WHERE p.syllabus=? AND p.paper=?
    """, (syl, paper)).fetchone()[0]

    unclassified = total - classified

    print(f"{syl} P{paper}: {classified}/{total} classified ({unclassified} remaining)")

    # Topic distribution
    rows = con.execute("""
        SELECT c.topic, COUNT(*) n FROM classifications c
        JOIN questions q ON q.id=c.question_id
        JOIN papers p ON p.id=q.paper_id
        WHERE p.syllabus=? AND p.paper=?
        GROUP BY c.topic ORDER BY n DESC
    """, (syl, paper)).fetchall()
    for r in rows:
        print(f"   {r[0]}: {r[1]}")
    print()

con.close()
