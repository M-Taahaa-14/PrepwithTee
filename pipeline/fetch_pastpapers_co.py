"""
Downloader for pastpapers.co — used for syllabuses not on fastpapers.uk.

Currently supported: 2059 (Pakistan Studies), 2058 (Islamiyat)

Download URL pattern: https://pastpapers.co/caie/{relPath}
Directory listing: RSC protocol — GET page URL with Accept: text/x-component, RSC: 1
"""

import json
import logging
import re
import time
import argparse
from pathlib import Path

import requests

from . import db
from .config import DATA_DIR

log = logging.getLogger(__name__)

SUPPORTED = {"2059", "2058"}
BASE_SITE = "https://pastpapers.co"

SUBJECT_SLUGS = {
    "2059": "o-level/pakistan-studies-2059",
    "2058": "o-level/islamiyat-2058",
}

SUBJECT_PATHS = {
    "2059": "O-Level/Pakistan-Studies-2059",
    "2058": "O-Level/Islamiyat-2058",
}

SESSION_MAP = {
    "may-june": "s",
    "oct-nov":  "w",
    "feb-mar":  "m",
    "feb-march": "m",
    "march":    "m",
}

PAPER_KINDS = {"qp", "ms", "in"}

# ── RSC helpers ─────────────────────────────────────────────────────────────

def _rsc_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/x-component",
        "RSC": "1",
    })
    return s


def _rsc_get(session: requests.Session, path: str) -> str:
    """Fetch a page via the RSC protocol and return the raw payload."""
    url = f"{BASE_SITE}/{path}"
    session.headers["Next-Url"] = f"/{path}"
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def _extract_entries(rsc_text: str) -> list[dict]:
    """Extract file/folder entries from an RSC payload."""
    entries = []
    # RSC lines are like: N:{"entries":[...]} or embedded in arrays
    for chunk in re.split(r'\n(?=\d+:)', rsc_text):
        idx = chunk.find(":")
        if idx < 0:
            continue
        payload = chunk[idx + 1:]
        # Try to find JSON objects containing an "entries" array
        for m in re.finditer(r'\{[^{}]*"entries"\s*:\s*\[', payload):
            start = m.start()
            # Walk forward to find matching closing brace
            depth = 0
            end = start
            for i, ch in enumerate(payload[start:], start):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            fragment = payload[start:end]
            try:
                obj = json.loads(fragment)
                if isinstance(obj.get("entries"), list):
                    entries.extend(obj["entries"])
            except json.JSONDecodeError:
                pass
    return entries


def _extract_dir_names(rsc_text: str) -> list[str]:
    """Extract directory names from the top-level subject page RSC."""
    dirs = []
    entries = _extract_entries(rsc_text)
    for e in entries:
        if isinstance(e, dict) and e.get("isDir") and e.get("name"):
            dirs.append(e["name"])
    return dirs


# ── Filename parsing ─────────────────────────────────────────────────────────

def _parse_filename(fname: str, syllabus: str) -> dict | None:
    """
    Parse Cambridge filename for non-standard syllabuses (2058/2059).

    Pattern: {syllabus}_{sess}{yy}_{kind}_{paper_code}.pdf
    Examples:
        2059_s23_qp_01.pdf  → session=s year=2023 kind=qp paper=1 variant=''
        2059_s23_ms_1.pdf   → session=s year=2023 kind=ms paper=1 variant=''
        2058_w22_qp_12.pdf  → session=w year=2022 kind=qp paper=1 variant='2'
    """
    m = re.fullmatch(
        rf'{re.escape(syllabus)}_([swm])(\d{{2}})_(qp|ms)_(\d+)\.pdf',
        fname, re.IGNORECASE
    )
    if not m:
        return None
    sess_code, yy, kind, paper_str = m.groups()
    year = 2000 + int(yy)
    paper_int = int(paper_str)
    # Two-digit paper code: tens digit = paper, units = variant
    if paper_int >= 10:
        paper  = paper_int // 10
        variant = str(paper_int % 10)
    else:
        paper   = paper_int
        variant = ""
    return {
        "syllabus": syllabus,
        "session":  sess_code.lower(),
        "year":     year,
        "kind":     kind.lower(),
        "paper":    paper,
        "variant":  variant,
        "filename": fname,
    }


# ── Download ─────────────────────────────────────────────────────────────────

def _download_file(http: requests.Session, rel_path: str, dest: Path) -> bool:
    """Download one PDF from pastpapers.co/caie/{relPath}."""
    if dest.exists() and dest.stat().st_size > 1024:
        log.info("skip (exists)  %s", dest.name)
        return True
    url = f"{BASE_SITE}/caie/{rel_path}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = http.get(url, timeout=60, stream=True)
        if r.status_code != 200:
            log.warning("HTTP %s  %s", r.status_code, url)
            return False
        content = b""
        for chunk in r.iter_content(65536):
            content += chunk
        if not content.startswith(b"%PDF"):
            log.warning("not a PDF (%d bytes)  %s", len(content), url)
            return False
        dest.write_bytes(content)
        log.info("downloaded  %s  (%.0f KB)", dest.name, len(content) / 1024)
        return True
    except requests.RequestException as exc:
        log.warning("fetch error  %s: %s", url, exc)
        return False


# ── Main pipeline ────────────────────────────────────────────────────────────

def fetch_syllabus(syllabus: str, year_from: int = 2010, year_to: int = 2025):
    if syllabus not in SUPPORTED:
        log.error("Syllabus %s not in SUPPORTED set %s", syllabus, SUPPORTED)
        return

    slug      = SUBJECT_SLUGS[syllabus]
    subj_path = SUBJECT_PATHS[syllabus]

    rsc = _rsc_session()
    # Use a plain HTTP session for downloads (no RSC headers)
    http = requests.Session()
    http.headers["User-Agent"] = rsc.headers["User-Agent"]

    con = db.connect()

    log.info("Fetching directory listing for %s …", syllabus)
    try:
        rsc_text = _rsc_get(rsc, f"caie/{slug}")
    except requests.RequestException as exc:
        log.error("Failed to fetch subject index: %s", exc)
        return

    session_dirs = _extract_dir_names(rsc_text)
    if not session_dirs:
        log.warning("No session directories found — dumping first 500 chars of RSC:")
        log.warning(rsc_text[:500])
        return
    log.info("Found %d session directories", len(session_dirs))

    fetched = skipped = failed = 0

    for session_dir in sorted(session_dirs):
        # Determine year — session_dir like "2023-May-June" or "2017"
        year_m = re.search(r'\b(20\d{2})\b', session_dir)
        if not year_m:
            log.debug("Skipping non-year dir: %s", session_dir)
            continue
        year = int(year_m.group(1))
        if not (year_from <= year <= year_to):
            continue

        slug_dir = session_dir.lower().replace(" ", "-")
        try:
            sess_rsc = _rsc_get(rsc, f"caie/{slug}/{slug_dir}")
        except requests.RequestException as exc:
            log.warning("Failed to fetch session %s: %s", session_dir, exc)
            continue
        time.sleep(0.4)

        entries = _extract_entries(sess_rsc)
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("isDir"):
                continue
            fname    = entry.get("name", "")
            rel_path = entry.get("relPath", "")
            if not fname.lower().endswith(".pdf"):
                continue

            rec = _parse_filename(fname, syllabus)
            if rec is None:
                log.debug("Unparseable: %s", fname)
                continue
            if rec["kind"] not in PAPER_KINDS:
                continue

            dest = DATA_DIR / "raw" / syllabus / str(rec["year"]) / fname
            ok = _download_file(http, rel_path, dest)
            time.sleep(0.3)

            if ok:
                db_rel = str(dest.relative_to(DATA_DIR.parent)).replace("\\", "/")
                try:
                    import fitz
                    page_count = len(fitz.open(str(dest)))
                except Exception:
                    page_count = None
                db_id = db.upsert_paper(con, rec, db_rel, page_count)
                log.info("  DB id=%d  %s", db_id, fname)
                fetched += 1
            else:
                failed += 1

    con.close()
    log.info("Done — fetched=%d  skipped=%d  failed=%d", fetched, skipped, failed)


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Fetch past papers from pastpapers.co")
    ap.add_argument("--syllabus", required=True, choices=sorted(SUPPORTED))
    ap.add_argument("--from",  dest="year_from", type=int, default=2010)
    ap.add_argument("--to",    dest="year_to",   type=int, default=2025)
    args = ap.parse_args()
    fetch_syllabus(args.syllabus, args.year_from, args.year_to)


if __name__ == "__main__":
    main()
