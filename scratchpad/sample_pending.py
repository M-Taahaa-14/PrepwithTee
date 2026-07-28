"""Show samples of questions needing review for MCQ session classification."""
import json, sqlite3

con = sqlite3.connect("data/index.db")
con.row_factory = sqlite3.Row

for syllabus, paper in [("5054", 1), ("0625", 1), ("0625", 2)]:
    rows = con.execute("""
        SELECT q.id, q.number, q.text, p.year, p.session, p.variant,
               c.topic, c.confidence, c.backend
        FROM questions q
        JOIN papers p ON q.paper_id = p.id
        LEFT JOIN classifications c ON c.question_id = q.id
        WHERE p.syllabus = ? AND p.paper = ?
          AND (c.topic IS NULL OR c.confidence < 0.8)
        ORDER BY c.topic NULLS FIRST, q.id
        LIMIT 10
    """, (syllabus, paper)).fetchall()
    print(f"\n=== {syllabus} P{paper} - first 10 uncertain ===")
    for r in rows:
        txt = (r["text"] or "").strip()[:150].replace("\n", " ")
        print(f"  id={r['id']} Q{r['number']} [{syllabus}/{r['session']}{r['year']%100:02d}/v{r['variant']}]")
        print(f"  heur={r['topic']} ({r['confidence']}) | {txt}")
        print()

# Also check topic distribution of heuristic-confident 5054 P1
print("\n=== 5054 P1 topic distribution (heuristic confident) ===")
rows = con.execute("""
    SELECT c.topic, COUNT(*) n FROM classifications c
    JOIN questions q ON q.id = c.question_id
    JOIN papers p ON p.id = q.paper_id
    WHERE p.syllabus='5054' AND p.paper=1 AND c.confidence >= 0.8
    GROUP BY c.topic ORDER BY n DESC
""").fetchall()
for r in rows:
    print(f"  {r['topic']}: {r['n']}")

con.close()
