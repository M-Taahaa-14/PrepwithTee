"""Export MCQ questions (5054 P1, 0625 P1, 0625 P2) for session classification.
Writes data/batches/{syl}_p{paper}_questions.json with all question texts.
"""
import json, sqlite3, sys

con = sqlite3.connect("data/index.db")
con.row_factory = sqlite3.Row

targets = [("5054", 1), ("0625", 1), ("0625", 2)]

for syllabus, paper in targets:
    rows = con.execute("""
        SELECT q.id, q.number, q.text, p.year, p.session, p.variant,
               c.topic, c.confidence, c.backend
        FROM questions q
        JOIN papers p ON q.paper_id = p.id
        LEFT JOIN classifications c ON c.question_id = q.id
        WHERE p.syllabus = ? AND p.paper = ?
        ORDER BY p.year, p.session, p.variant, q.number
    """, (syllabus, paper)).fetchall()

    total = len(rows)
    no_cls = sum(1 for r in rows if r["topic"] is None)
    heuristic = sum(1 for r in rows if r["backend"] == "heuristic")
    in_review = sum(1 for r in rows if r["backend"] == "heuristic"
                    and r["confidence"] is not None and r["confidence"] < 0.8)
    confident = heuristic - in_review

    print(f"\n{syllabus} P{paper}: {total} questions")
    print(f"  No classification: {no_cls}")
    print(f"  Heuristic (confident >=0.8): {confident}")
    print(f"  Heuristic (in review <0.8):  {in_review}")

    # Export ALL questions (need to check everything for MCQ since heuristic is weaker)
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "ref": f"{syllabus}/P{paper}/{r['session']}{r['year'] % 100:02d}/v{r['variant']}/Q{r['number']}",
            "text": (r["text"] or "").strip()[:600],
            "heuristic_topic": r["topic"],
            "heuristic_conf": round(r["confidence"], 3) if r["confidence"] else None,
        })

    path = f"data/batches/{syllabus}_p{paper}_questions.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"  Written {len(out)} rows -> {path}")

con.close()
