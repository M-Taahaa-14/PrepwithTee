"""Bundle the crop PDFs the server is missing into one tar.gz for upload.

    .venv\\Scripts\\python scripts\\bundle_crops.py --server-list server_crops.txt

`server_crops.txt` is the output of, on the server:
    cd /srv/prepwithtee && find data/crops -name "*.pdf"

It writes data/output/missing_crops.tar.gz containing every question and
mark-scheme crop referenced by index.db that the server does not have, with
repo-relative paths, so on the server:
    sudo tar -xzf /tmp/missing_crops.tar.gz -C /srv/prepwithtee
"""

import argparse
import sqlite3
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def needed_crops(con) -> set[str]:
    paths = set()
    for table in ("questions", "ms_entries"):
        for (p,) in con.execute(f"SELECT crop_path FROM {table} WHERE crop_path IS NOT NULL"):
            paths.add(p.replace("\\", "/"))
    return paths


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--server-list", required=True)
    ap.add_argument("--out", default=str(ROOT / "data" / "output" / "missing_crops.tar.gz"))
    args = ap.parse_args(argv)

    have = {l.strip() for l in open(args.server_list, encoding="utf-8") if l.strip()}
    con = sqlite3.connect(ROOT / "data" / "index.db")
    missing = sorted(needed_crops(con) - have)
    absent_locally = [p for p in missing if not (ROOT / p).exists()]
    if absent_locally:
        print(f"WARNING: {len(absent_locally)} crops missing locally too, skipped "
              f"(e.g. {absent_locally[:3]})")
    missing = [p for p in missing if (ROOT / p).exists()]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out, "w:gz") as tar:
        for p in missing:
            tar.add(ROOT / p, arcname=p)
    print(f"{len(missing)} crops -> {out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
