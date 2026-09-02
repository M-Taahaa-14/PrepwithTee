"""Stage: download and parse Cambridge grade threshold PDFs.

Downloads GT files from fastpapers.uk for all in-scope syllabuses,
parses component-level and option-level (overall) threshold tables,
and writes two reviewed seed files:

  supabase/grade_thresholds_seed.json   — component rows (→ grade_thresholds table)
  supabase/grade_options_seed.json      — overall-option rows (→ grade_options table)

Gaps:
  - 2058 / 2059 are NOT on fastpapers.uk (see --help for manual download instructions).
  - Years not present in the manifest are listed in the quality summary at the end.

Usage:
    python -m pipeline.fetch_gt                         # download + parse all subjects
    python -m pipeline.fetch_gt --syllabus 5054         # one subject
    python -m pipeline.fetch_gt --from 2018 --to 2025
    python -m pipeline.fetch_gt --parse-only            # skip download, re-parse cached

Schema context (grade_thresholds table already exists in Supabase):
    syllabus TEXT, subject TEXT, level TEXT, year INT, session TEXT,
    paper INT, variant TEXT, max_mark INT,
    grade_astar INT (null=not awarded), grade_a INT, grade_b INT,
    grade_c INT, grade_d INT, grade_e INT, status TEXT.
    board TEXT column proposed (always 'CAIE') — add via ALTER TABLE.

grade_options table is NEW — proposed schema in supabase/schema_gt_options.sql.
"""

import argparse
import json
import logging
import re
import time
from pathlib import Path

import fitz  # PyMuPDF
import requests

from . import config, manifest, setup_logging

log = setup_logging("fetch_gt")

GT_DIR = config.DATA_DIR / "gt"
SEED_COMPONENTS = config.ROOT / "supabase" / "grade_thresholds_seed.json"
SEED_OPTIONS = config.ROOT / "supabase" / "grade_options_seed.json"
MISSING_LOG = config.ROOT / "supabase" / "grade_thresholds_gaps.json"

# GT files: syllabus_s25_gt.pdf  (no paper/variant suffix)
GT_RE = re.compile(r"^(\d{4})_([smw])(\d{2})_gt\.pdf$", re.I)

SUBJECT_META = {
    "5054": ("Physics",         "O Level"),
    "0625": ("Physics",         "IGCSE"),
    "4024": ("Mathematics D",   "O Level"),
    "0580": ("Mathematics",     "IGCSE"),
    "2210": ("Computer Science","O Level"),
    "0478": ("Computer Science","IGCSE"),
    "5070": ("Chemistry",       "O Level"),
    "0620": ("Chemistry",       "IGCSE"),
    "9709": ("Mathematics",     "A Level"),
    "9702": ("Physics",         "A Level"),
    "9618": ("Computer Science","A Level"),
    "2058": ("Islamiyat",       "O Level"),   # NOT on fastpapers
    "2059": ("Pakistan Studies","O Level"),   # NOT on fastpapers
}

# These are not on fastpapers.uk but their GT PDFs are on PapaCambridge
# using the same flat-upload URL pattern as pipeline/fetch_alt.py.
NOT_ON_FASTPAPERS = {"2058", "2059"}
PAPACAMBRIDGE_BASE = (
    "https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload"
)

SESSION_MAP = {"s": "May/Jun", "w": "Oct/Nov", "m": "Feb/Mar"}


# ── download helpers ─────────────────────────────────────────────────────────

def _http() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = config.USER_AGENT
    return s


def _signed_url(http, bucket_path: str) -> str:
    time.sleep(config.REQUEST_DELAY_S)
    r = http.get(config.PDF_API, params={"path": bucket_path}, timeout=30)
    r.raise_for_status()
    return r.json()["url"]


def _download_pdf(http, bucket_path: str, dest: Path) -> bool:
    """Download one GT PDF to dest. Returns True on success."""
    try:
        url = _signed_url(http, bucket_path)
        time.sleep(config.REQUEST_DELAY_S)
        r = http.get(url, timeout=300)
        if r.status_code == 404:
            log.warning("404 on server: %s", bucket_path)
            return False
        r.raise_for_status()
        if not r.content.startswith(b"%PDF"):
            log.error("non-PDF response for %s", bucket_path)
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.content)
        return True
    except Exception as e:
        log.error("download failed for %s: %s", bucket_path, e)
        return False


def iter_gt_paths(tree, syllabus: str, year_from: int, year_to: int,
                  sessions: tuple) -> list[dict]:
    """Return [{year, session, filename, bucket_path}] for GT files."""
    results = []
    try:
        subj = manifest.subject_node(tree, syllabus)
    except LookupError as e:
        log.error("manifest lookup failed for %s: %s", syllabus, e)
        return results

    pp = manifest._find_child(subj.get("children", []), "past papers")
    if pp is None:
        log.error("'past papers' folder missing for %s", syllabus)
        return results

    for year_node in pp.get("children", []):
        name = year_node["name"].strip()
        if year_node.get("type") != "folder" or not name.isdigit():
            continue
        year = int(name)
        if not (year_from <= year <= year_to):
            continue
        for sess_node in year_node.get("children", []):
            session = config.folder_to_session(sess_node["name"])
            if session is None or session not in sessions:
                continue
            for f in sess_node.get("children", []):
                if f.get("type") != "file":
                    continue
                m = GT_RE.match(f["name"].strip())
                if not m or m.group(1) != syllabus:
                    continue
                results.append({
                    "syllabus": syllabus,
                    "year": year,
                    "session": session,
                    "filename": f["name"].strip(),
                    "bucket_path": f["path"],
                })
    return results


# ── PDF parsing ──────────────────────────────────────────────────────────────

def _safe_int(s) -> int | None:
    if s is None:
        return None
    s = str(s).strip()
    if re.match(r"^-?\d+$", s):
        return int(s)
    return None


def _nums_from_row(row: list) -> list[int]:
    """Extract all integer strings from a table row (skip None / dashes / letters)."""
    return [int(c.strip()) for c in row if c and re.match(r"^\d+$", str(c).strip())]


def _parse_component_table(tab_rows: list) -> list[dict]:
    """Parse the component-level threshold table.

    O Level / A Level row (5 grades: A B C D E):
        ['Component 11', '', '40', '', '28', '23', '17', '15', '14']
    IGCSE row (7 grades: A B C D E F G):
        ['Component 11', '', '75', '', '45', '35', '24', '21', '18', '15', '12']

    A* is never awarded at the individual component level — only overall.
    """
    results = []
    for row in tab_rows:
        # Cell may have "C" cut off by the table-border detector: "omponent 12"
        first = (row[0] or "").strip()
        if not re.match(r"(?:C?omponent)\s+\d+", first, re.I):
            continue
        comp_str = re.search(r"\d+", first).group(0)
        if len(comp_str) == 1:
            # Single digit: "Component 1" → paper=1, no explicit variant (single-variant paper)
            paper = int(comp_str)
            variant = "1"
        elif len(comp_str) == 2 and comp_str[0] == "0":
            # Zero-padded single: "Component 01" → paper=1, single variant
            paper = int(comp_str[1]) if comp_str[1].isdigit() else int(comp_str)
            variant = "1"
        else:
            # Normal two-digit: "Component 11" → paper=1, variant=1
            paper = int(comp_str[0])
            variant = comp_str[1]
        nums = _nums_from_row(row[1:])
        # IGCSE: max_mark + A B C D E F G = 8 numbers
        # OL/AL: max_mark + A B C D E     = 6 numbers
        if len(nums) == 8:
            result = {"paper": paper, "variant": variant, "max_mark": nums[0],
                      "A": nums[1], "B": nums[2], "C": nums[3],
                      "D": nums[4], "E": nums[5], "F": nums[6], "G": nums[7]}
        elif len(nums) >= 6:
            result = {"paper": paper, "variant": variant, "max_mark": nums[0],
                      "A": nums[1], "B": nums[2], "C": nums[3],
                      "D": nums[4], "E": nums[5]}
        else:
            log.debug("component row too short: %s -> %s", first, nums)
            continue
        results.append(result)
    return results


def _parse_option_table(tab_rows: list) -> list[dict]:
    """Parse the overall/option threshold table (second table in GT PDF).

    O Level / A Level (A* through E):
        ['AX', '200', '11, 21, 31', '153', '125', '97', '69', '58', '47']   → 6 nums → astar present
        ['S1', '130', '11, 21, 31', '–',   '94',  '85', '73', '62', '51']   → 5 nums → no astar
    IGCSE (A* through G):
        ['AX', '150', '11, 21', '116', '94', '72', '50', '42', '35', '28', '21'] → 8 nums
        ['P1', '90',  '50',     '80',  '71', '59', '48', '39', '31', '23', '15'] → 8 nums
    """
    results = []
    for row in tab_rows:
        option = (row[0] or "").strip()
        if not option or re.match(r"^[\d,\s]+$", option) or option.lower() in (
            "option", "maximum", "mark", "weighting", "combination", "grade"
        ):
            continue
        # "–" or "—" is used as option code when there is only one combination
        # (common in 2059/2058 which have no variant choice)
        if option in ("–", "—", "-"):
            option = "OVERALL"
        max_mark = _safe_int(row[1]) if len(row) > 1 else None
        if max_mark is None:
            continue
        combo = (row[2] or "").strip() if len(row) > 2 else ""
        nums = _nums_from_row(row[3:])

        if len(nums) == 8:      # IGCSE A* + A B C D E F G
            astar, a, b, c, d, e, f, g = nums
            entry = {"grade_astar": astar, "A": a, "B": b, "C": c, "D": d,
                     "E": e, "F": f, "G": g}
        elif len(nums) == 7:    # IGCSE no A*, just A B C D E F G
            a, b, c, d, e, f, g = nums
            entry = {"grade_astar": None, "A": a, "B": b, "C": c, "D": d,
                     "E": e, "F": f, "G": g}
        elif len(nums) == 6:    # OL/AL with A*: A* A B C D E
            astar, a, b, c, d, e = nums
            entry = {"grade_astar": astar, "A": a, "B": b, "C": c, "D": d, "E": e}
        elif len(nums) == 5:    # OL/AL no A*: A B C D E
            a, b, c, d, e = nums
            entry = {"grade_astar": None, "A": a, "B": b, "C": c, "D": d, "E": e}
        else:
            log.debug("option row wrong length for %s: %s -> %s", option, row, nums)
            continue

        results.append({
            "option": option,
            "max_mark": max_mark,
            "components": combo,
            **entry,
        })
    return results


def _parse_option_table_nocode(tab_rows: list) -> list[dict]:
    """Fallback for Feb/Mar PDFs where find_tables() misses the option-code column.

    In this layout the detected table starts at the "Combination of Components"
    column — the option code ("AY", "BY", …) sits in the left margin and is
    invisible to find_tables().  We synthesise sequential option codes
    ("OPT1", "OPT2", …) so the grade thresholds are still stored.
    """
    results = []
    opt_idx = 0
    for row in tab_rows:
        first = str(row[0] or "").strip()
        # Data rows start with a digit (component code, e.g. "12, 22, 33, 42,")
        if not re.match(r"^\d", first):
            continue
        # Continuation rows (e.g. "52" — the rest of a multiline combo) have no grades
        nums = _nums_from_row(row[1:])
        if not nums:
            continue
        combo = re.sub(r"\s+", " ", first.rstrip(",")).strip()
        if len(nums) == 6:
            astar, a, b, c, d, e = nums
            entry = {"grade_astar": astar, "A": a, "B": b, "C": c, "D": d, "E": e}
        elif len(nums) == 5:
            a, b, c, d, e = nums
            entry = {"grade_astar": None, "A": a, "B": b, "C": c, "D": d, "E": e}
        else:
            log.debug("nocode option row unexpected length: %s -> %s", first, nums)
            continue
        opt_idx += 1
        results.append({
            "option": f"OPT{opt_idx}",
            "max_mark": 0,       # unknown — option code column was outside table
            "components": combo,
            **entry,
        })
    return results


def parse_gt_pdf(pdf_path: Path) -> tuple[list[dict], list[dict]]:
    """Return (component_rows, option_rows) parsed from a GT PDF.

    Raises ValueError if no recognisable data found.
    """
    doc = fitz.open(str(pdf_path))
    all_comp_rows: list[dict] = []
    all_opt_rows:  list[dict] = []

    for page in doc:
        try:
            tabs = page.find_tables()
        except Exception as e:
            log.warning("find_tables failed on %s p%d: %s", pdf_path.name, page.number, e)
            continue

        for tab in tabs.tables:
            rows = tab.extract()
            # Component table: rows starting with "Component XX" (or "omponent XX" – missing C)
            if any(re.match(r"(?:C?omponent)\s+\d+", str(r[0] or ""), re.I) for r in rows):
                all_comp_rows.extend(_parse_component_table(rows))
            elif any("combination" in str(r[0] or "").lower() for r in rows[:4]):
                # Feb/Mar layout: option-code column is outside the detected table
                all_opt_rows.extend(_parse_option_table_nocode(rows))
            else:
                # Standard option table: first data row should be a short option code
                # or a dash (used when there's only one combination, e.g. 2059/2058).
                data_rows = [r for r in rows if r[0] and str(r[0]).strip()
                             and not str(r[0]).strip().lower().startswith(
                                 ("option", "max", "grade", "comb", "mark", "minimum", "learn"))]
                _OPT_RE = re.compile(r"^([A-Z0-9]{1,4}|[–—-])$")
                if data_rows and all(
                    _OPT_RE.match(str(r[0]).strip())
                    for r in data_rows[:3]
                ):
                    all_opt_rows.extend(_parse_option_table(rows))

    doc.close()

    if not all_comp_rows and not all_opt_rows:
        raise ValueError(f"no threshold data found in {pdf_path.name}")
    return all_comp_rows, all_opt_rows


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--syllabus", action="append",
                   choices=sorted(SUBJECT_META), metavar="CODE",
                   help="syllabus code(s); default: all 13 in scope")
    p.add_argument("--from", dest="year_from", type=int, default=config.YEAR_MIN)
    p.add_argument("--to",   dest="year_to",   type=int, default=config.YEAR_MAX)
    p.add_argument("--sessions", default=",".join(config.SESSION_CODES))
    p.add_argument("--parse-only", action="store_true",
                   help="skip download step, re-parse already-cached PDFs")
    p.add_argument("--refresh-manifest", action="store_true")
    args = p.parse_args()

    syllabuses = args.syllabus or sorted(SUBJECT_META)
    sessions = tuple(s.strip() for s in args.sessions.split(",") if s.strip())

    # ── 1. Download ────────────────────────────────────────────────────────
    if not args.parse_only:
        tree = manifest.load(refresh=args.refresh_manifest)
        http = _http()
        dl_stats = {"fetched": 0, "skipped": 0, "missing": 0, "not_available": 0}

        for syl in syllabuses:
            if syl in NOT_ON_FASTPAPERS:
                # Try PapaCambridge flat-upload URL (same pattern as fetch_alt.py)
                log.info("Trying PapaCambridge for %s ...", syl)
                for yr in range(args.year_from, args.year_to + 1):
                    for sess in sessions:
                        if sess == "m":
                            continue  # Islamiyat/Pak Studies have no Feb/Mar session
                        fname = f"{syl}_{sess}{yr % 100:02d}_gt.pdf"
                        dest = GT_DIR / syl / fname
                        if dest.exists() and dest.stat().st_size > 0:
                            dl_stats["skipped"] += 1
                            continue
                        url = f"{PAPACAMBRIDGE_BASE}/{fname}"
                        try:
                            time.sleep(config.REQUEST_DELAY_S)
                            r = http.get(url, timeout=60)
                            if r.status_code == 404:
                                log.debug("missing (404): %s", fname)
                                dl_stats["missing"] += 1
                                continue
                            r.raise_for_status()
                            if not r.content.startswith(b"%PDF"):
                                log.debug("not a PDF: %s", fname)
                                dl_stats["missing"] += 1
                                continue
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            dest.write_bytes(r.content)
                            log.info("fetched from PapaCambridge: %s", fname)
                            dl_stats["fetched"] += 1
                        except Exception as e:
                            log.warning("PapaCambridge fetch failed for %s: %s", fname, e)
                            dl_stats["missing"] += 1
                continue

            gt_records = iter_gt_paths(tree, syl, args.year_from, args.year_to, sessions)
            if not gt_records:
                log.warning("no GT files found in manifest for %s", syl)
            for rec in gt_records:
                dest = GT_DIR / syl / rec["filename"]
                if dest.exists() and dest.stat().st_size > 0:
                    log.info("skipped (exists): %s", rec["filename"])
                    dl_stats["skipped"] += 1
                    continue
                log.info("downloading %s ...", rec["filename"])
                ok = _download_pdf(http, rec["bucket_path"], dest)
                if ok:
                    dl_stats["fetched"] += 1
                else:
                    dl_stats["missing"] += 1

        log.info("download complete: %s", dl_stats)

    # ── 2. Parse cached PDFs ───────────────────────────────────────────────
    component_seed: list[dict] = []
    options_seed:   list[dict] = []
    gaps: list[dict] = []

    # Expected coverage for quality summary
    all_expected = []
    for syl in syllabuses:
        subject, level = SUBJECT_META[syl]
        for yr in range(args.year_from, args.year_to + 1):
            for sess in sessions:
                if syl in ("2058", "2059") and sess == "m":
                    continue  # no Feb/Mar for Islamiyat/Pak Studies
                all_expected.append((syl, yr, sess))

    parsed_keys: set[tuple] = set()

    for syl in syllabuses:
        subject, level = SUBJECT_META[syl]
        syl_dir = GT_DIR / syl
        if not syl_dir.exists():
            if syl not in NOT_ON_FASTPAPERS:
                log.warning("no GT directory for %s — run without --parse-only first", syl)
            for yr in range(args.year_from, args.year_to + 1):
                for sess in sessions:
                    gaps.append({"syllabus": syl, "year": yr, "session": sess,
                                 "reason": "directory_missing"})
            continue

        for yr in range(args.year_from, args.year_to + 1):
            for sess in sessions:
                fname = f"{syl}_{sess}{yr % 100:02d}_gt.pdf"
                pdf = syl_dir / fname
                if not pdf.exists():
                    gaps.append({"syllabus": syl, "year": yr, "session": sess,
                                 "reason": "pdf_not_downloaded"})
                    continue

                try:
                    comp_rows, opt_rows = parse_gt_pdf(pdf)
                except Exception as e:
                    log.error("parse failed %s: %s", fname, e)
                    gaps.append({"syllabus": syl, "year": yr, "session": sess,
                                 "reason": f"parse_error: {e}"})
                    continue

                parsed_keys.add((syl, yr, sess))

                for row in comp_rows:
                    thresh = {"A": row["A"], "B": row["B"], "C": row["C"],
                              "D": row["D"], "E": row["E"]}
                    if "F" in row:
                        thresh["F"] = row["F"]
                    if "G" in row:
                        thresh["G"] = row["G"]
                    component_seed.append({
                        "syllabus": syl,
                        "subject": subject,
                        "level": level,
                        "board": "CAIE",
                        "year": yr,
                        "session": sess,
                        "paper": row["paper"],
                        "variant": row["variant"],
                        "max_mark": row["max_mark"],
                        "thresholds": thresh,
                        "status": "official",
                    })

                for row in opt_rows:
                    thresh = {}
                    if row.get("grade_astar") is not None:
                        thresh["A*"] = row["grade_astar"]
                    thresh.update({"A": row["A"], "B": row["B"], "C": row["C"],
                                   "D": row["D"], "E": row["E"]})
                    if "F" in row:
                        thresh["F"] = row["F"]
                    if "G" in row:
                        thresh["G"] = row["G"]
                    options_seed.append({
                        "syllabus": syl,
                        "subject": subject,
                        "level": level,
                        "board": "CAIE",
                        "year": yr,
                        "session": sess,
                        "option_code": row["option"],
                        "components": row["components"],
                        "max_mark": row["max_mark"],
                        "thresholds": thresh,
                        "status": "official",
                    })

    # ── 3. Write seed files ────────────────────────────────────────────────
    SEED_COMPONENTS.write_text(
        json.dumps(component_seed, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    SEED_OPTIONS.write_text(
        json.dumps(options_seed, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    MISSING_LOG.write_text(
        json.dumps(gaps, indent=2), encoding="utf-8"
    )

    # ── 4. Quality summary ─────────────────────────────────────────────────
    print("\n" + "=" * 68)
    print("GRADE THRESHOLD PIPELINE — QUALITY SUMMARY")
    print("=" * 68)
    print(f"  Component rows extracted : {len(component_seed)}")
    print(f"  Option rows extracted    : {len(options_seed)}")
    print(f"  Session-level files OK   : {len(parsed_keys)}")
    print(f"  Gaps / missing           : {len(gaps)}")
    print()

    if gaps:
        by_reason: dict[str, list] = {}
        for g in gaps:
            by_reason.setdefault(g["reason"], []).append(g)
        for reason, items in sorted(by_reason.items()):
            print(f"  [{reason}]  ({len(items)} items)")
            # Group by syllabus
            by_syl: dict[str, list] = {}
            for g in items:
                by_syl.setdefault(g["syllabus"], []).append(
                    f"{g['year']}{g['session']}"
                )
            for syl, refs in sorted(by_syl.items()):
                subj = SUBJECT_META[syl][0]
                print(f"    {syl} {subj}: {', '.join(refs[:10])}"
                      + (" ..." if len(refs) > 10 else ""))
        print()

    print("  Seed files written:")
    print(f"    {SEED_COMPONENTS}")
    print(f"    {SEED_OPTIONS}")
    print(f"    {MISSING_LOG}  ← gaps log")
    print()
    print("  NEXT STEPS:")
    print("  1. Review supabase/grade_thresholds_seed.json before importing.")
    print("  2. Run the schema migration in supabase/schema_gt_options.sql.")
    print("  3. For 2058 / 2059: download GT PDFs manually from PapaCambridge")
    print("     and place in data/gt/2058/ and data/gt/2059/, then re-run")
    print("     with --parse-only --syllabus 2058 --syllabus 2059.")
    print("=" * 68 + "\n")


if __name__ == "__main__":
    main()
