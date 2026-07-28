"""Stage 1: download QP + MS PDFs (and optionally syllabus docs) from fastpapers.

    python -m pipeline.fetch --syllabus 5054 --from 2023 --to 2025
    python -m pipeline.fetch --syllabus 0580 --paper 4 --sessions s,w
    python -m pipeline.fetch --syllabus 5054 --syllabus-docs

Idempotent: files already on disk (size > 0) are skipped. Polite: one request
every REQUEST_DELAY_S seconds.
"""

import argparse
import time

import requests

from . import config, db, manifest, setup_logging

log = setup_logging("fetch")


def _http() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = config.USER_AGENT
    return s


def _throttled_get(http, url, **kw):
    time.sleep(config.REQUEST_DELAY_S)
    return http.get(url, timeout=kw.pop("timeout", 120), **kw)


def signed_url(http, bucket_path: str) -> str:
    r = _throttled_get(http, config.PDF_API, params={"path": bucket_path})
    r.raise_for_status()
    return r.json()["url"]


def download(http, bucket_path: str, dest) -> int | None:
    """Download one file. Returns byte count, or None if missing on server."""
    url = signed_url(http, bucket_path)
    r = _throttled_get(http, url, timeout=300)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    if not r.content.startswith(b"%PDF"):
        raise ValueError(f"server returned non-PDF content for {bucket_path}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return len(r.content)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--syllabus", required=True, choices=sorted(config.SUBJECT_FOLDERS))
    p.add_argument("--paper", type=int, action="append",
                   help="paper number(s); default: the syllabus's PAPER_MATRIX entry")
    p.add_argument("--from", dest="year_from", type=int, default=config.YEAR_MIN)
    p.add_argument("--to", dest="year_to", type=int, default=config.YEAR_MAX)
    p.add_argument("--sessions", default=",".join(config.SESSION_CODES),
                   help="comma-separated session codes, e.g. s,w")
    p.add_argument("--refresh-manifest", action="store_true")
    p.add_argument("--syllabus-docs", action="store_true",
                   help="also download the subject's official syllabus PDFs")
    p.add_argument("--er", action="store_true",
                   help="also download examiner report PDFs (used for difficulty classification)")
    args = p.parse_args()

    sessions = tuple(s.strip() for s in args.sessions.split(",") if s.strip())
    if args.paper:
        outside = set(args.paper) - set(config.PAPER_MATRIX[args.syllabus])
        if outside:
            log.warning("paper(s) %s are outside the agreed scope for %s",
                        sorted(outside), args.syllabus)

    tree = manifest.load(refresh=args.refresh_manifest)
    http = _http()
    con = db.connect()
    stats = {"fetched": 0, "skipped": 0, "missing": 0, "failed": 0}

    for rec in manifest.iter_papers(tree, args.syllabus, papers=args.paper,
                                    year_from=args.year_from, year_to=args.year_to,
                                    sessions=sessions):
        dest = config.RAW_DIR / rec["syllabus"] / str(rec["year"]) / rec["filename"]
        rel = str(dest.relative_to(config.ROOT))
        if dest.exists() and dest.stat().st_size > 0:
            log.info("skipped (exists): %s", rec["filename"])
            stats["skipped"] += 1
            db.upsert_paper(con, {k: rec[k] for k in
                                  ("syllabus", "year", "session", "paper", "variant",
                                   "kind", "filename")}, rel)
            continue
        try:
            size = download(http, rec["bucket_path"], dest)
        except Exception as e:
            log.error("failed: %s (%s)", rec["filename"], e)
            stats["failed"] += 1
            continue
        if size is None:
            log.warning("missing on server: %s", rec["bucket_path"])
            stats["missing"] += 1
            continue
        log.info("fetched: %s (%d KB)", rec["filename"], size // 1024)
        stats["fetched"] += 1
        db.upsert_paper(con, {k: rec[k] for k in
                              ("syllabus", "year", "session", "paper", "variant",
                               "kind", "filename")}, rel)

    if args.syllabus_docs:
        dest_dir = config.RAW_DIR / args.syllabus / "syllabus"
        for doc in manifest.iter_syllabus_docs(tree, args.syllabus):
            dest = dest_dir / doc["filename"]
            if dest.exists() and dest.stat().st_size > 0:
                log.info("skipped (exists): %s", doc["filename"])
                stats["skipped"] += 1
                continue
            try:
                size = download(http, doc["bucket_path"], dest)
            except Exception as e:
                log.error("failed: %s (%s)", doc["filename"], e)
                stats["failed"] += 1
                continue
            if size is None:
                log.warning("missing on server: %s", doc["bucket_path"])
                stats["missing"] += 1
            else:
                log.info("fetched: %s (%d KB)", doc["filename"], size // 1024)
                stats["fetched"] += 1

    if args.er:
        dest_dir = config.RAW_DIR / args.syllabus / "examiner_reports"
        for er in manifest.iter_er_files(tree, args.syllabus,
                                          year_from=args.year_from, year_to=args.year_to,
                                          sessions=sessions):
            dest = dest_dir / str(er["year"]) / er["filename"]
            if dest.exists() and dest.stat().st_size > 0:
                log.info("skipped (exists): %s", er["filename"])
                stats["skipped"] += 1
                continue
            try:
                size = download(http, er["bucket_path"], dest)
            except Exception as e:
                log.error("failed: %s (%s)", er["filename"], e)
                stats["failed"] += 1
                continue
            if size is None:
                log.warning("missing on server: %s", er["bucket_path"])
                stats["missing"] += 1
            else:
                log.info("fetched ER: %s (%d KB)", er["filename"], size // 1024)
                stats["fetched"] += 1

    con.close()
    log.info("done: %(fetched)d fetched, %(skipped)d skipped, "
             "%(missing)d missing, %(failed)d failed", stats)
    if stats["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
