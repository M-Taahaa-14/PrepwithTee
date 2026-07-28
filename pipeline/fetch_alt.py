"""
Alternative downloader for subjects not available on fastpapers.uk.

Usage (from repo root):
    python -m pipeline.fetch_alt --syllabus 2058 --from 2020 --to 2025
    python -m pipeline.fetch_alt --syllabus 2059 --from 2020 --to 2025

Downloads from papacambridge.com and registers papers in the DB.
Files land in data/raw/{syllabus}/{year}/ using standard Cambridge naming.
"""

import argparse
import logging
import time
from pathlib import Path

import requests

from .config import (
    DATA_DIR, DB_PATH, RAW_DIR, REQUEST_DELAY_S,
    PAPER_MATRIX, YEAR_MIN, YEAR_MAX, USER_AGENT,
)
from . import config
from . import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# Subjects supported by this downloader
SUPPORTED = {"2058", "2059"}

# All files sit in one flat upload/ directory — filename encodes all metadata.
BASE_URL = "https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload"

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/pdf,*/*",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def _build_url(syllabus: str, year: int, session_code: str,
               kind: str, paper_code: str) -> str:
    filename = f"{syllabus}_{session_code}{year % 100:02d}_{kind}_{paper_code}.pdf"
    return f"{BASE_URL}/{filename}"


INSERTS_FOR = {"2059"}  # syllabuses that have source-material inserts

def _candidates(syllabus: str, year: int, session_code: str):
    """Yield (kind, paper_code, paper_num, variant_num, url) for every plausible file."""
    papers = PAPER_MATRIX.get(syllabus, (1, 2))
    for paper in papers:
        # Cambridge variants: 11, 12, 21, 22, etc.
        for variant in (1, 2):
            code = f"{paper}{variant}"
            for kind in ("qp", "ms"):
                yield kind, code, paper, variant, _build_url(syllabus, year, session_code, kind, code)
        # Source-material inserts (no variant, code is zero-padded paper num)
        if syllabus in INSERTS_FOR:
            code = f"{paper:02d}"
            yield "in", code, paper, 0, _build_url(syllabus, year, session_code, "in", code)


def fetch_syllabus(syllabus: str, year_from: int, year_to: int):
    if syllabus not in SUPPORTED:
        log.error("Syllabus %s not in SUPPORTED set — add it to fetch_alt.py", syllabus)
        return

    dest_root = RAW_DIR / syllabus
    dest_root.mkdir(parents=True, exist_ok=True)
    con = db.connect()

    fetched = skipped = missing = 0

    for year in range(year_from, year_to + 1):
        for sess_code in ("s", "w", "m"):
            for kind, code, paper_num, variant_num, url in _candidates(syllabus, year, sess_code):
                filename = url.split("/")[-1]

                dest_dir = dest_root / str(year)
                dest_dir.mkdir(exist_ok=True)
                dest_file = dest_dir / filename

                if dest_file.exists() and dest_file.stat().st_size > 1024:
                    skipped += 1
                    log.debug("skipped (exists): %s", filename)
                    rel_path = str(dest_file.relative_to(config.ROOT))
                    db.upsert_paper(con, {
                        "syllabus": syllabus, "year": year, "session": sess_code,
                        "paper": paper_num, "variant": variant_num, "kind": kind,
                        "filename": filename,
                    }, rel_path)
                    continue

                try:
                    time.sleep(REQUEST_DELAY_S)
                    r = SESSION.get(url, timeout=30)
                    if r.status_code == 404:
                        log.debug("missing: %s", filename)
                        missing += 1
                        continue
                    r.raise_for_status()
                    if b"%PDF" not in r.content[:10]:
                        log.warning("not a PDF: %s (status %d)", filename, r.status_code)
                        missing += 1
                        continue
                    dest_file.write_bytes(r.content)
                    rel_path = str(dest_file.relative_to(config.ROOT))
                    db.upsert_paper(con, {
                        "syllabus": syllabus, "year": year, "session": sess_code,
                        "paper": paper_num, "variant": variant_num, "kind": kind,
                        "filename": filename,
                    }, rel_path)
                    log.info("fetched: %s (%d KB)", filename,
                             len(r.content) // 1024)
                    fetched += 1
                except Exception as exc:
                    log.warning("error %s: %s", filename, exc)
                    missing += 1

    con.commit()
    con.close()
    log.info("%s done — fetched %d, skipped %d (already on disk), not found %d",
             syllabus, fetched, skipped, missing)


def main():
    ap = argparse.ArgumentParser(description="Fetch alt-source papers")
    ap.add_argument("--syllabus", required=True, choices=sorted(SUPPORTED))
    ap.add_argument("--from", dest="year_from", type=int, default=YEAR_MIN)
    ap.add_argument("--to", dest="year_to", type=int, default=YEAR_MAX)
    args = ap.parse_args()
    fetch_syllabus(args.syllabus, args.year_from, args.year_to)


if __name__ == "__main__":
    main()
