"""Stage 6: generate a topic TEST (mock) and a SEPARATE mark-scheme file.

    python -m pipeline.testgen --syllabus 0625 --topics "Motion,Forces" --count 6
    python -m pipeline.testgen --syllabus 5054 --topics Radioactivity --marks 30 --seed 7

Differs from `compose` in exactly the two ways the tutor asked for (2026-07):
  1. It selects a RANDOM subset of the matching questions, not all of them
     (--count N questions, or --marks M to fill to a target mark total).
  2. Mark schemes are written to a SEPARATE file (`..._ms.pdf`), so a student
     can attempt the paper without the answers in front of them.

Question numbering (Q1, Q2, ...) is identical in both files, so the mark
scheme lines up with the test. Selection is reproducible with --seed.
Questions are still original vector crops - never re-typeset.
"""

import argparse
import json
import random
import re
from datetime import date

import fitz

from . import config, db, heuristics, setup_logging
from .compose import (Booklet, brand_backdrop, footer_band, fetch_sections,
                      answer_key, bubble_sheet,
                      _centre, _wrap, PAGE_W, PAGE_H, MARGIN_X, CONTENT_W,
                      ACCENT, GOLD, GREY, CREAM,
                      _trim_essay_rects, _ESSAY_SYLLABUSES,
                      _trim_total_marker_rects, _TOTAL_MARKER_SYLLABUSES,
                      _p2_insert_question_pages, _needs_insert)

log = setup_logging("testgen")


def _random_order(pool, rng, uniform):
    """Random ordering of the pool; by default biased towards recent years.

    Weighted shuffle (Efraimidis-Spirakis: sort by rand()**(1/w)). Weight
    grows 1.5x per year, so a 2025 question is ~7.6x more likely to surface
    early than a 2020 one - recent papers get priority (tutor, 2026-07-20)
    but older ones still appear. --uniform restores the unweighted draw.
    """
    if uniform:
        order = pool[:]
        rng.shuffle(order)
        return order
    def key(q):
        w = 1.5 ** ((q["year"] or config.YEAR_MIN) - config.YEAR_MIN)
        return rng.random() ** (1.0 / w)
    return sorted(pool, key=key, reverse=True)


def select(con, args, topics):
    """Random subset of the matching question pool (deduped, one row each)."""
    pool = [q for _, qs in fetch_sections(con, args, topics) for q in qs]
    if not pool:
        raise SystemExit("no classified questions match these filters")

    rng = random.Random(args.seed)   # seed=None -> system entropy
    order = _random_order(pool, rng, args.uniform)
    if args.marks:
        chosen, total = [], 0
        for q in order:
            chosen.append(q)
            total += q["marks"] or 0
            if total >= args.marks:
                break
    else:
        k = min(args.count, len(pool))
        if k < args.count:
            log.warning("only %d questions available; asked for %d", k, args.count)
        chosen = order[:k]

    # Stable order so the test reads paper-by-paper and the MS lines up.
    chosen.sort(key=lambda q: (q["year"], q["session"], q["variant"], q["number"]))
    return chosen


def cover(doc, args, subject, topics, chosen, *, is_ms):
    """Cambridge O Level style front cover — modelled on PrepWithTee tutor papers."""
    page = doc.new_page(pno=0, width=PAGE_W, height=PAGE_H)

    total_m = sum(q["marks"] or 0 for q in chosen)
    mins = max(1, round(total_m))
    yrs = sorted(q["year"] for q in chosen)
    span = f"{yrs[0]}" if yrs[0] == yrs[-1] else f"{yrs[0]}–{yrs[-1]}"
    papers_used = sorted({q["paper"] for q in chosen})
    paper_str = "/".join(str(p) for p in papers_used)

    # ── Top navy strip ────────────────────────────────────────────────────────
    page.draw_rect(fitz.Rect(0, 0, PAGE_W, 26), color=None, fill=ACCENT)
    top_lbl = (f"{subject}  ·  {args.syllabus}"
               + (f" / Paper {paper_str}" if paper_str else ""))
    page.insert_text((MARGIN_X, 17), top_lbl,
                     fontsize=7.5, fontname="helv", color=CREAM)
    doc_kind = "Mark Scheme" if is_ms else "Topic Test"
    kw = fitz.get_text_length(doc_kind, fontname="hebo", fontsize=7.5)
    page.insert_text((PAGE_W - MARGIN_X - kw, 17), doc_kind,
                     fontsize=7.5, fontname="hebo", color=GOLD)

    # ── Decorative heading (Cambridge "style mock" label) ─────────────────────
    y = 48
    brand_line = ("P R E P W I T H T E E   ·   T O P I C   T E S T"
                  if not is_ms else
                  "P R E P W I T H T E E   ·   M A R K   S C H E M E")
    _centre(page, brand_line, y, 12, "hebo", ACCENT)
    y += 15
    # Detect O Level vs IGCSE by syllabus prefix: 4-digit starting with 0 → IGCSE
    level = ("Cambridge IGCSE" if args.syllabus.startswith("0")
             else "Cambridge O Level")
    _centre(page, level, y, 9, "helv", (0.35, 0.35, 0.35))

    # ── Syllabus badge (top-right, like the Cambridge paper sidebar) ───────────
    bx0 = PAGE_W - MARGIN_X - 82
    page.draw_rect(fitz.Rect(bx0, 30, PAGE_W - MARGIN_X, 82),
                   color=None, fill=(0.95, 0.95, 0.95))
    page.draw_line(fitz.Point(bx0, 30), fitz.Point(bx0, 82),
                   color=ACCENT, width=2.5)
    page.insert_text((bx0 + 7, 44),
                     "S Y L L A B U S / P A P E R",
                     fontsize=5.5, fontname="hebo", color=GREY)
    page.insert_text((bx0 + 7, 62),
                     f"{args.syllabus} / {paper_str or '–'}",
                     fontsize=11, fontname="hebo", color=ACCENT)
    page.insert_text((bx0 + 7, 76), span,
                     fontsize=8, fontname="helv", color=GREY)

    # ── Gold rule ─────────────────────────────────────────────────────────────
    y = 90
    page.draw_line(fitz.Point(MARGIN_X, y), fitz.Point(PAGE_W - MARGIN_X, y),
                   color=GOLD, width=1.5)

    # ── Subject + topics ──────────────────────────────────────────────────────
    y = 107
    page.insert_text((MARGIN_X, y), subject.upper(),
                     fontsize=14, fontname="hebo", color=ACCENT)
    y += 20
    prefix = "Topics: " if len(topics) > 1 else "Topic: "
    topic_str = "  ·  ".join(topics)
    if fitz.get_text_length(prefix + topic_str, fontname="helv", fontsize=9.5) > CONTENT_W:
        topic_str = topics[0] + (f"  ·  +{len(topics) - 1} more" if len(topics) > 1 else "")
    page.insert_text((MARGIN_X, y), prefix + topic_str,
                     fontsize=9.5, fontname="helv", color=(0.15, 0.15, 0.15))
    y += 14
    meta = (f"{len(chosen)} question{'s' if len(chosen) != 1 else ''}  ·  "
            f"{total_m} marks  ·  Past papers {span}")
    page.insert_text((MARGIN_X, y), meta, fontsize=8.5, fontname="helv", color=GREY)

    # ── Candidate information table ───────────────────────────────────────────
    y += 22
    row_h = 24
    col_mid = PAGE_W / 2
    CFILL = (0.93, 0.93, 0.93)
    CBORD = (0.25, 0.25, 0.25)

    def _cell(x0, cy, x1, label, value=""):
        page.draw_rect(fitz.Rect(x0, cy, x1, cy + row_h),
                       color=CBORD, fill=CFILL, width=0.5)
        page.insert_text((x0 + 5, cy + 10),
                         label, fontsize=6.5, fontname="hebo", color=(0.35, 0.35, 0.35))
        page.insert_text((x0 + 5, cy + row_h - 4),
                         value, fontsize=9.5, fontname="helv", color=ACCENT)

    _cell(MARGIN_X, y, col_mid - 1, "Candidate name")
    _cell(col_mid + 1, y, PAGE_W - MARGIN_X, "Marks obtained")
    y += row_h
    _cell(MARGIN_X, y, col_mid - 1, "Date")
    _cell(col_mid + 1, y, PAGE_W - MARGIN_X, "Maximum marks", str(total_m))
    y += row_h
    _cell(MARGIN_X, y, col_mid - 1, "Time allowed", f"{mins} minutes (approx.)")
    _cell(col_mid + 1, y, PAGE_W - MARGIN_X, "Instructor / Tutor")
    y += row_h + 18

    # ── Light rule ────────────────────────────────────────────────────────────
    page.draw_line(fitz.Point(MARGIN_X, y), fitz.Point(PAGE_W - MARGIN_X, y),
                   color=(0.78, 0.78, 0.78), width=0.7)
    y += 16

    # ── Instructions ─────────────────────────────────────────────────────────
    page.insert_text((MARGIN_X, y), "READ THESE INSTRUCTIONS FIRST",
                     fontsize=10, fontname="hebo", color=ACCENT)
    y += 16

    if is_ms:
        instrs = [
            "This mark scheme is for tutor and self-assessment use only.",
            "It should not be seen by students before or during their attempt.",
            "Questions are numbered to match the test paper exactly.",
            "Award marks only for responses that clearly meet the descriptors.",
        ]
    else:
        instrs = [
            "Answer all questions in the spaces provided or in your answer booklet.",
            "Write in dark blue or black pen.",
            "Do not use correction fluid; cross out neatly any work you do not wish to mark.",
            "Show all necessary working; marks may be awarded for correct method even if "
            "the final answer is wrong.",
            "Calculators may be used unless a question specifically restricts their use.",
        ]

    for line in instrs:
        for ln in _wrap(line, "helv", 9, CONTENT_W - 12):
            page.insert_text((MARGIN_X + 12, y), f"•  {ln}" if ln == _wrap(line, "helv", 9, CONTENT_W - 12)[0] else f"    {ln}",
                             fontsize=9, fontname="helv", color=(0.15, 0.15, 0.15))
            y += 13

    y += 8
    page.insert_text((MARGIN_X, y), "INFORMATION",
                     fontsize=10, fontname="hebo", color=ACCENT)
    y += 14

    info = [
        f"The total mark for this {'mark scheme' if is_ms else 'paper'} is {total_m}.",
        "The number of marks is given in brackets [  ] at the end of each question or part.",
    ]
    if not is_ms:
        info.append(
            f"Questions are drawn from Cambridge past papers: {args.syllabus} ({span}).")
    for line in info:
        page.insert_text((MARGIN_X + 12, y), f"•  {line}",
                         fontsize=9, fontname="helv", color=(0.15, 0.15, 0.15))
        y += 13

    y += 10
    page.draw_line(fitz.Point(MARGIN_X, y), fitz.Point(PAGE_W - MARGIN_X, y),
                   color=(0.78, 0.78, 0.78), width=0.7)

    # ── PrepWithTee footer band ───────────────────────────────────────────────
    page.draw_rect(fitz.Rect(0, PAGE_H - 44, PAGE_W, PAGE_H),
                   color=None, fill=ACCENT)
    page.insert_text((MARGIN_X, PAGE_H - 22), "PrepWithTee",
                     fontsize=11, fontname="hebo", color=GOLD)
    disc = "© Tutor practice paper  ·  Not an official Cambridge Assessment paper"
    page.insert_text((MARGIN_X + 102, PAGE_H - 22), disc,
                     fontsize=7, fontname="helv", color=(0.65, 0.72, 0.82))
    stamp = f"{doc_kind}  ·  generated {date.today().isoformat()}"
    sw = fitz.get_text_length(stamp, fontname="helv", fontsize=8)
    page.insert_text((PAGE_W - MARGIN_X - sw, PAGE_H - 22), stamp,
                     fontsize=8, fontname="helv", color=(0.65, 0.72, 0.82))


def _src(cache, rel_path):
    if rel_path not in cache:
        d = fitz.open(config.ROOT / str(rel_path).replace("\\", "/"))
        for pg in d:
            if pg.rotation:
                pg.remove_rotation()
        cache[rel_path] = d
    return cache[rel_path]


def _get_insert(con, cache, syl, year, session, paper):
    """Return (ins_doc, p2_page_map | None) or None if no insert exists."""
    row = con.execute(
        "SELECT rel_path FROM papers "
        "WHERE syllabus=? AND year=? AND session=? AND paper=? AND kind='in' "
        "LIMIT 1", (syl, year, session, paper)).fetchone()
    if not row:
        return None
    idoc = _src(cache, row["rel_path"])
    p2map = _p2_insert_question_pages(idoc) if (syl == "2059" and paper == 2) else None
    return (idoc, p2map)


def render_test(con, args, subject, topics, chosen, cache):
    b = Booklet()
    shown_inserts: set = set()
    ins_cache: dict = {}

    for seq, q in enumerate(chosen, 1):
        syl = args.syllabus
        year, session, paper = q["year"], q["session"], q["paper"]
        sd = config.session_display(session)
        ins_ref = f"{syl}/{paper:02d}/{sd}/{year % 100:02d}"

        ins_key = (syl, year, session, paper)
        if ins_key not in ins_cache:
            ins_cache[ins_key] = _get_insert(con, cache, syl, year, session, paper)
        ins_result = ins_cache[ins_key]

        if ins_result and syl == "2059":
            ins_doc, p2map = ins_result
            q_text = q["text"] or ""
            if paper == 1 and q["number"] == 1 and _needs_insert(q_text, 1):
                dedup_key = (syl, year, session, paper)
                if dedup_key not in shown_inserts:
                    shown_inserts.add(dedup_key)
                    source_pages = list(range(1, len(ins_doc)))
                    if source_pages:
                        b.insert_header(f"Sources (Insert)  —  {ins_ref}")
                        b.place_insert_pages(ins_doc, source_pages)
            elif paper == 2 and p2map and _needs_insert(q_text, 2):
                dedup_key = (syl, year, session, paper, q["number"])
                q_pages = p2map.get(q["number"], [])
                if q_pages and dedup_key not in shown_inserts:
                    shown_inserts.add(dedup_key)
                    b.insert_header(f"Insert figures for Q{q['number']}  —  {ins_ref}")
                    b.place_insert_pages(ins_doc, q_pages)

        rects = json.loads(q["rects_json"])
        if syl in _ESSAY_SYLLABUSES:
            rects = _trim_essay_rects(_src(cache, q["rel_path"]), rects)
        if syl in _TOTAL_MARKER_SYLLABUSES and q["sub_part"]:
            rects = _trim_total_marker_rects(_src(cache, q["rel_path"]), rects)
        code = f"{q['paper']}{q['variant']}"
        ref = config.source_ref(syl, code, q["session"], q["year"],
                                q["number"], q["sub_part"] or "")
        if q["marks"]:
            ref += f"   [{q['marks']} marks]"
        first_h = (rects[0]["y1"] - rects[0]["y0"]) if rects else 40.0
        b.question_header(seq, ref, first_h)
        if rects:
            b.place_rects(_src(cache, q["rel_path"]), rects)
        b.divider()
    cover(b.doc, args, subject, topics, chosen, is_ms=False)
    if all(config.is_mcq(args.syllabus, q["paper"]) for q in chosen):
        # Multiple-choice test: the student needs somewhere to record answers,
        # so the bubble sheet ships with the test itself (page 2), while the
        # letters stay in the separate mark-scheme file.
        base = b.doc.page_count
        sheets = bubble_sheet(b.doc, list(range(1, len(chosen) + 1)),
                              f"{subject} {args.syllabus}  ·  Paper 1 Multiple Choice")
        for i in range(len(sheets)):
            b.doc.move_page(base + i, 1 + i)
    return b.doc


def render_ms(con, args, subject, topics, chosen, cache):
    # An all-MCQ test has no prose mark scheme - the companion file is the
    # answer grid, nothing else.
    if all(config.is_mcq(args.syllabus, q["paper"]) for q in chosen):
        entries, missing = [], 0
        for seq, q in enumerate(chosen, 1):
            code = f"{q['paper']}{q['variant']}"
            ref = config.source_ref(args.syllabus, code, q["session"],
                                    q["year"], q["number"], q["sub_part"] or "")
            row = con.execute(
                """SELECT m.answer FROM ms_entries m
                   JOIN papers mp ON mp.id = m.paper_id
                   WHERE mp.kind = 'ms' AND mp.syllabus = ? AND mp.year = ?
                     AND mp.session = ? AND mp.paper = ? AND mp.variant = ?
                     AND m.question_number = ?""",
                (args.syllabus, q["year"], q["session"], q["paper"],
                 q["variant"], q["number"])).fetchone()
            answer = row["answer"] if row else None
            if answer is None:
                missing += 1
            entries.append((seq, answer, ref))
        doc = fitz.open()
        answer_key(doc, entries)
        cover(doc, args, subject, topics, chosen, is_ms=True)
        return doc, missing

    b = Booklet()
    missing = 0
    for seq, q in enumerate(chosen, 1):
        code = f"{q['paper']}{q['variant']}"
        ref = config.source_ref(args.syllabus, code, q["session"], q["year"],
                                q["number"], q["sub_part"] or "")
        ms = con.execute(
            """
            SELECT m.rects_json, mp.rel_path FROM ms_entries m
            JOIN papers mp ON mp.id = m.paper_id
            WHERE mp.kind = 'ms' AND mp.syllabus = ? AND mp.year = ?
              AND mp.session = ? AND mp.paper = ? AND mp.variant = ?
              AND m.question_number = ?
              AND (m.sub_part = ? OR m.sub_part = '')
            ORDER BY length(m.sub_part) DESC LIMIT 1
            """, (args.syllabus, q["year"], q["session"], q["paper"],
                  q["variant"], q["number"], q["sub_part"] or "")).fetchone()
        if ms is None:
            missing += 1
            b.question_header(seq, ref, 0)
            b.label(f"Mark scheme not available for {ref}", keep_with=0)
            b.divider()
            continue
        ms_rects = json.loads(ms["rects_json"])
        scale = min(1.0, CONTENT_W / max(r["x1"] - r["x0"] for r in ms_rects))
        b.question_header(seq, ref, (ms_rects[0]["y1"] - ms_rects[0]["y0"]) * scale)
        b.place_rects(_src(cache, ms["rel_path"]), ms_rects, scale)
        b.divider()
    cover(b.doc, args, subject, topics, chosen, is_ms=True)
    return b.doc, missing


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--syllabus", required=True, choices=sorted(config.SUBJECT_FOLDERS))
    p.add_argument("--topics", required=True,
                   help="comma-separated chapter names from taxonomy/")
    p.add_argument("--count", type=int, default=6,
                   help="number of questions in the test (default 6)")
    p.add_argument("--marks", type=int,
                   help="instead of --count, fill to this total mark target")
    p.add_argument("--seed", type=int,
                   help="fix the random selection for a reproducible paper")
    p.add_argument("--uniform", action="store_true",
                   help="disable the default recent-years priority")
    p.add_argument("--ids",
                   help="comma-separated question IDs — bypasses filter/selection "
                        "(used by the web preview-and-curate flow)")
    p.add_argument("--from", dest="year_from", type=int, default=config.YEAR_MIN)
    p.add_argument("--to", dest="year_to", type=int, default=config.YEAR_MAX)
    p.add_argument("--paper", type=int, help="single paper component (legacy; prefer --papers)")
    p.add_argument("--papers", help="comma-separated paper numbers, e.g. 1,2")
    p.add_argument("--variant", type=int)
    p.add_argument("--session")
    p.add_argument("--sessions", help="comma-separated session codes, e.g. s,w")
    p.add_argument("--variants", help="comma-separated variant numbers, e.g. 1,2")
    p.add_argument("--out", help="base path; '_ms' is appended for the scheme "
                   "(default: data/output/...)")
    args = p.parse_args()
    if args.papers:
        args.papers_list = [int(x.strip()) for x in args.papers.split(",") if x.strip()]
    elif args.paper:
        args.papers_list = [args.paper]
    else:
        args.papers_list = []

    taxonomy = heuristics.load_taxonomy(args.syllabus)
    valid = {t["name"].lower(): t["name"] for t in taxonomy["topics"]}
    topics = []
    for raw in args.topics.split(","):
        name = valid.get(raw.strip().lower())
        if name is None:
            raise SystemExit(
                f"unknown topic {raw.strip()!r}; valid topics:\n  "
                + "\n  ".join(t["name"] for t in taxonomy["topics"]))
        topics.append(name)

    con = db.connect()
    if args.ids:
        ids = [int(x.strip()) for x in args.ids.split(",") if x.strip()]
        if not ids:
            raise SystemExit("--ids: no valid IDs supplied")
        ph = ",".join("?" for _ in ids)
        rows = con.execute(
            f"""
            SELECT q.id, q.number, q.sub_part, q.marks, q.rects_json, q.text,
                   c.topic, c.secondary_topic, c.subtopic,
                   p.syllabus, p.rel_path, p.filename,
                   p.year, p.session, p.paper, p.variant
            FROM questions q
            JOIN classifications c ON c.question_id = q.id
            JOIN papers p ON p.id = q.paper_id
            WHERE q.id IN ({ph})
            """, ids
        ).fetchall()
        by_id = {r["id"]: r for r in rows}
        chosen = [by_id[i] for i in ids if i in by_id]
        if not chosen:
            raise SystemExit("--ids: none of the given IDs found in the database")
    else:
        chosen = select(con, args, topics)
    subject = taxonomy.get("subject", args.syllabus)
    cache: dict[str, fitz.Document] = {}

    test_doc = render_test(con, args, subject, topics, chosen, cache)
    ms_doc, missing = render_ms(con, args, subject, topics, chosen, cache)

    slug = re.sub(r"[^a-z0-9]+", "-", ",".join(topics).lower()).strip("-")
    base = config.ROOT / (args.out or f"data/output/{args.syllabus}_{slug}_test.pdf")
    base = base.with_suffix(".pdf")
    ms_path = base.with_name(base.stem + "_ms.pdf")
    base.parent.mkdir(parents=True, exist_ok=True)

    test_doc.save(base, deflate=True, garbage=3)
    ms_doc.save(ms_path, deflate=True, garbage=3)
    total_m = sum(q["marks"] or 0 for q in chosen)
    log.info("test: %s  (%d questions, %d marks, %d pages)",
             base, len(chosen), total_m, test_doc.page_count)
    log.info("mark scheme: %s  (%d pages%s)", ms_path, ms_doc.page_count,
             f", {missing} answers missing" if missing else "")

    for d in cache.values():
        d.close()
    test_doc.close()
    ms_doc.close()
    con.close()


if __name__ == "__main__":
    main()
