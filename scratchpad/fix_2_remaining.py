import json, sqlite3
con = sqlite3.connect("data/index.db")

records = [
    {"id": 22760, "topic": "Mass & weight", "secondary_topic": None,
     "difficulty": None, "confidence": 0.85, "rationale": "MCQ manual: bottle mass subtraction → Mass & weight"},
    {"id": 23484, "topic": "Kinetic particle model of matter", "secondary_topic": None,
     "difficulty": None, "confidence": 0.85, "rationale": "MCQ manual: sphere falling through oil warms → Kinetic particle model"},
]

path = "data/batches/0625_p1_fix2.json"
with open(path, "w", encoding="utf-8") as f:
    json.dump(records, f, indent=1)
print(f"Wrote {len(records)} records to {path}")
con.close()
