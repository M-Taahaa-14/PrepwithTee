import sqlite3
import sys

db_path = sys.argv[1] if len(sys.argv) > 1 else "data/index.db"

con = sqlite3.connect(db_path)
cur = con.cursor()

# Replace Windows backslashes with Linux forward slashes
cur.execute("UPDATE papers SET rel_path = REPLACE(rel_path, '\\', '/')")
rows_updated = cur.rowcount
con.commit()

sample = cur.execute("SELECT rel_path FROM papers LIMIT 1").fetchone()
print(f"Updated {rows_updated} paper paths in {db_path}.")
if sample:
    print(f"Sample path: {sample[0]}")

con.close()
