# Topical Past-Paper Engine

Internal teaching tool for a Cambridge O-Level/IGCSE tutor (Lahore). Ingests
official past-paper PDFs, splits them into per-question **vector region crops**
(never re-typeset - diagrams, graphs and answer lines must survive perfectly),
classifies each question by syllabus topic, and composes topical PDFs
(questions + matching mark scheme) on demand.

**No web app, no auth, no Docker, no Supabase/R2 yet, no fine-tuning, no
silent OCR.** SQLite schema is kept Postgres-portable for a later Supabase
migration.

## Scope (approved)

| Syllabus | Subject | Papers | Notes |
|---|---|---|---|
| 5054 | Physics O Level | P2 | structured theory |
| 0625 | Physics IGCSE | P4 | extended structured (P2 is MCQ - out of scope) |
| 4024 | Maths D O Level | P1 + P2 | non-calc + calc |
| 0580 | Maths IGCSE | P2 + P4 | extended tier only |
| 2210 | Computer Science | P1 + P2 | theory + algorithms/programming |

Years 2015-2025, all sessions, **all variants**. No MCQ papers anywhere, so
mark schemes never need answer-key-grid parsing.

## Source site (verified 2026-07-15)

- `GET https://papers.fastpapers.uk/api/bucket` -> JSON tree of the whole
  archive (~4 MB), cached at `data/manifest.json`. **Single source of truth**
  for what exists; never construct paths.
- `GET https://papers.fastpapers.uk/api/pdf?path=<url-encoded>` ->
  `{"url": "<signed GCS URL>"}` (bucket `allqpms`, ~1 h validity). It signs
  paths that don't exist, so existence checks must use the bucket tree.
- Subject folders are inconsistently named - see `SUBJECT_FOLDERS` in
  `pipeline/config.py`. Some child folder names have stray leading spaces.
- Layout per subject: `past papers/{year}/{May-Jun|Oct-Nov|Feb-March}/` plus a
  `Syllabus/` folder with official syllabus PDFs (taxonomy source).
- Filenames: `5054_s25_qp_22.pdf` = syllabus_sessionYY_kind_paperVariant.
  Sessions: s = May/Jun, w = Oct/Nov, m = Feb/Mar. Kinds kept: qp, ms
  (gt/er/ci/ir are ignored). Rate limit: 1 request / 2 s (`REQUEST_DELAY_S`).

## Layout

- `pipeline/` - one CLI module per stage (`python -m pipeline.<stage>`), all
  idempotent. `config.py` holds paths + `PAPER_MATRIX`; `db.py` the SQLite
  schema; `manifest.py` the bucket-tree cache/query.
- `taxonomy/{syllabus}.json` - topics + heuristic keywords. 0625 and 4024 are
  `alias_of` 5054/0580 respectively (resolved in `heuristics.load_taxonomy`).
- `data/` (gitignored): `raw/{syllabus}/{year}/` original PDFs under original
  names; `crops/{paper_key}/qNN.pdf` per-question vector crops;
  `debug/{paper_key}/qNN.png` **mandatory** visual-check renders;
  `index.db` metadata. `paper_key` = e.g. `5054_s25_22`.

## Running

```
.venv\Scripts\python -m pipeline.fetch    --syllabus 5054 --from 2023 --to 2025
.venv\Scripts\python -m pipeline.segment  --syllabus 5054 --only 5054_s25_qp_22
.venv\Scripts\python -m pipeline.classify --syllabus 5054 --backend heuristic
.venv\Scripts\python -m pipeline.link_ms  --syllabus 5054            (stub)
.venv\Scripts\python -m pipeline.mcq      --syllabus 9702 --paper 1
.venv\Scripts\python -m pipeline.compose  --syllabus 5054 --topic "Electric circuits" --from 2018 --to 2025   (stub)
.venv\Scripts\python -m pipeline.validate --tracker <xlsx>           (stub)
```

`mcq` runs after `link_ms` and only for papers in `config.MCQ_PAPERS`
(currently 9702 P1). It reads the option letter out of the mark scheme's
Question/Answer/Marks table into `ms_entries.answer`; compose/testgen then
print a fill-in bubble sheet on page 2 and an answer grid at the back instead
of stamping a one-row table crop under every question.

## Classification backends

`--backend heuristic|session|tracker|api`. Default is keyless:
- **heuristic** (implemented): keyword scoring, conservative confidence
  (<= 0.85) so ambiguous questions land in `review_queue` (< 0.8 threshold).
- **session**: `--prepare` exports pending questions + the valid topic list
  to `data/batches/{syllabus}_questions.json`; a Claude Code session
  classifies them against the syllabus subject content and writes
  `{syllabus}_results.json`; `--ingest` loads it as authoritative labels.
- **api**: Anthropic API (Haiku + prompt caching), needs `ANTHROPIC_API_KEY`
  in `.env`; the SDK is lazy-imported.

There is NO external answer key or Excel tracker (confirmed by the tutor
2026-07-16): topics come from the official syllabus chapters (taxonomy/)
and classification is done by review. `validate` checks internal
consistency (crops exist, everything classified with valid topics, MS
linked), not agreement with any external file.

## Build order / status

1. [x] Scaffold, schema, taxonomies, CLAUDE.md
2. [x] `fetch` working (5054 P2 2023-2025 test range)
3. [x] `segment` first pass on one paper -> debug PNGs
4. [x] **GATE passed 2026-07-16: tutor signed off the QP crops.** All 12
   papers segmented (111 questions). Hard-won segment lessons: anchor
   detection is position-based (x<60), NOT bold-based (w-session papers
   aren't bold); tolerate merged '10 (a)' anchors; 2023-era MS pages carry
   rotation=90 (remove_rotation() first).
5. [x] `link_ms` working: all 12 mark schemes segmented and linked 1:1 to
   questions (the QP<->MS cross-check caught a real missed Q10). Heuristic
   classify ran over all 111 questions (advisory; 88 queued for review).
6. [ ] **GATE: tutor signs off the `*_ms.png` crops in `data/debug/`.**
7. [x] session classify done 2026-07-16: all 111 questions classified
   in-session against the syllabus topics (backend='session',
   authoritative). `validate` rewritten as internal consistency checker -
   passes with 0 hard failures. 1 open review item (a genuinely mixed
   thermal/EM-induction question, id 393).
8. [x] compose working 2026-07-16: filter-driven A4 booklet (topics, year
   range, paper, variant), original vector crops, mark scheme immediately
   after each question (tutor's choice; --no-ms to suppress; future web app
   wants a show/hide marking key toggle). Verified on
   Motion/Forces/Momentum 2023-2025 (26 questions, 62 pages).
9. [x] taxonomy/4024.json + 0580.json generated from the tutor's own
   chapter breakdown (OL JAN-MAR 2025.xlsx) via pipeline/import_breakdown.py
   - 32 chapters, 137 subtopics, YouTube revision links preserved per
   subtopic for the future website. Chapter names kept verbatim (incl. the
   tutor's spellings).
10. [x] 4024 Maths done 2026-07-16: 24 papers (P1+P2, 2023-2025) fetched,
    segmented (478 questions), all 24 MS linked 1:1, session-classified
    against the tutor's 32 chapters. Maths-specific fixes now general:
    anchor regex accepts number merged with first text line; last question
    can share the final page with the acknowledgements block; MS Question
    column located via the table's vertical border lines (headers are
    centered, answers are numeric). 68 open review items = deliberate
    low-confidence flags.
11. [x] Resolved 2026-07-16: tutor confirmed the latest syllabus drops
    LOCI and MATRICES. The 9 such questions (7 matrices + 2 loci-centric,
    from 2023-24 old-syllabus papers) are questions.status='excluded' -
    no classification, never composed. NOTE: re-segmenting those papers
    resets status; re-apply exclusions afterwards (they are matrices/loci
    questions in 4024 s23_12 Q18, s23_21 Q9, w23_11 Q14+Q20, s24_11 Q20,
    s24_12 Q23, w24_11 Q16, w24_12 Q10+Q21 - identify by content).
    Triangle-construction questions stay in scope under Trigonometry.
12. [x] 0580 IGCSE Maths done 2026-07-16: 41 QPs + 42 MS (2023-2025, P2+P4,
    incl. Feb/March), 806 questions segmented, MS linked (only orphan:
    0580_m24_ms_22 - its QP is missing from the source site), all
    classified against the shared chapter breakdown. Fixes made general:
    session folders may be year-prefixed ('2023 May-Jun') -
    folder_to_session strips it (essential for any pre-2025 fetch); MS
    refs may contain spaces ('18 (a)'); compose keeps question headers
    attached to full-page questions.
13. [x] Resolved 2026-07-16: tutor wants separately studyable topics.
    'Trigonometry' renamed to '2D Trigonometry'; new chapters
    '3D Trigonometry' (both maths syllabi), 'Trigonometric Graphs' and
    'Differentiation' (0580 only). Defined in import_breakdown.py
    (RENAMES / EXTRA_CHAPTERS) so xlsx re-imports keep them. All affected
    questions re-tagged in the DB. CAUTION: data/batches/*_results.json
    predate the rename - re-ingesting them would revert topic names.
    Scope: tutor wants topical coverage AT LEAST 2020-2025 for all five
    syllabi.
14. [x] Branding done 2026-07-17: composed PDFs carry the tutor's
    **PrepWithTee** identity. Cover = cream page (the logo PNG's own
    background colour, so the art sits on it seamlessly), crisp logo,
    gold rule, topic title, contents card, navy footer band. Watermark =
    the owl only (config.LOGO_OWL_CLIP crops out the wordmark, else it
    duplicates the logo above), veiled with a cream rect at 0.955 opacity.
    COVER ONLY - body pages must stay clean behind the question crops
    (tutor's explicit instruction). Crop the pixmap directly; going via
    convert_to_pdf/show_pdf_page rescales the clip by the PNG's DPI.
    Questions are also numbered Q1, Q2, Q3... in booklet order, with the
    Cambridge source ref kept alongside in grey.
15. [x] SYLLABUS VERIFICATION 2026-07-17 - every taxonomy checked against the
    official PDF in taxonomy/ (tutor supplied them). Findings:
    - 0625: 24 topics map 1:1 onto subject content 1.1-6.2. Correct.
    - **5054 and 0625 have DIVERGED** in the 2026-2028 syllabi. 5054 uses
      'Simple magnetism and magnetic fields' + 'Practical electricity' and
      adds '4.6 Uses of an oscilloscope'; 0625 keeps 'Simple phenomena of
      magnetism' + 'Electrical safety' and has no oscilloscope topic.
      0625.json is therefore no longer an alias - it is a standalone file.
      Existing 5054 classifications were migrated to the new names.
    - 4024 p46 states outright: "Topics removed: Loci, Matrices" and "New
      topics added: 1.17 Exponential growth and decay, 1.18 Surds". This
      confirms the tutor's instruction and the status='excluded' questions.
    - **'Exponential Growth And Decay' was missing** from both maths
      taxonomies (the tutor's xlsx predates the syllabus change). Added as
      4024/0580 chapter; 9 real growth/decay questions retagged off
      'Daily Maths'. CAUTION: only real-world growth/decay MODELS belong
      here - questions that merely draw/evaluate an exponential curve are
      Graphs Of Functions / Functions / Indices.
    - 2210/0478: the 10 topics (Data representation ... Boolean logic) match
      the official structure. Sub-topics are 1.1-10.x if finer splits are
      ever wanted.
16. [x] 4024 COMPLETE 2026-07-17: 873 questions, 2020-2025, 0 hard failures.
17. [x] 0580 COMPLETE 2026-07-17: 1528 questions, 2020-2025, 0 hard failures.
    **MATHS IS DONE** (4024 + 0580 = 2405 classified questions).
    Workflow that worked, reuse it for Physics/CS: `classify --backend session
    --prepare` exports only what is still pending -> scratchpad digest.py
    condenses it -> read a ~200-line chunk, write data/batches/<syl>_results_
    b<N>.json, ingest immediately, repeat. Incremental ingest means a
    context/session limit never loses work.
18. [!] CORRECTION 2026-07-17: ruler-and-compasses **constructions are still
    in the syllabus** (4024/0580 4.2 Geometrical constructions) - only LOCI
    and MATRICES were removed. Three construction questions had been wrongly
    excluded (0580 ids 2684, 2734, 2991); they are back in, tagged
    2D Trigonometry at confidence 0.5. **Open gap for the tutor: their
    chapter breakdown has no Constructions/Scale drawings chapter**, so these
    have no proper home - same situation as Exponential Growth And Decay was.
    Only exclude a question if it is genuinely loci ("locus of points",
    region shading) or matrices.
19. [ ] extend to 2016-2025 and remaining subjects (0625; 2210):
    (a) pre-2023 5054 is the old syllabus (Section A/B choice) - re-verify
    segmentation + topic mapping; (b) pre-~2020 MS are prose-style -
    link_ms flags them, second parser needed; (c) each new subject gets
    one-paper debug-PNG verification before bulk runs.

20. **Physics complete (0625 + 5054, 2020-2025).** 0625 = 428 questions across
    all 24 topics; 5054 = 226 questions across all 25 topics. Both 0 hard
    failures. Two traps found while doing it:

    - **Re-segmenting a paper destroys its classifications.** `questions` rows
      are deleted and re-inserted on a re-run, and `classifications` has
      `ON DELETE CASCADE`. The 2020-22 backfill therefore silently wiped the
      111 session classifications 5054 already had for 2023-25, so all 226 had
      to be redone. Classify *after* the full year range is segmented, never
      before a backfill.
    - **Run `--prepare` BEFORE the heuristic pre-pass, or not at all.**
      `_pending_questions` excludes anything already in `classifications`, so
      the heuristic pre-pass empties the pending queue and `--prepare` then
      exports almost nothing. For a subject that already has heuristic rows,
      build the digest straight from the DB filtering
      `c.backend IS NULL OR c.backend = 'heuristic'` (see
      `scratchpad/digest5054.py` pattern) rather than using `--prepare`.

    Also fixed: `validate.py` counted `review_queue` across the **whole DB**
    with no syllabus filter, so every per-subject "open review items" number
    reported before this point was a global total. Real per-subject counts are
    4024=77, 0580=66, 0625=12, 5054=8.

21. **Test-generation engine built (`pipeline/testgen.py`).** Stage 6, the
    tutor's requested mock-test feature. Two differences from compose, both as
    asked: (a) it picks a RANDOM subset - `--count N` questions or `--marks M`
    to fill a mark target - not every matching question; `--seed` makes the
    pick reproducible. (b) The mark scheme is a SEPARATE file (`..._ms.pdf`),
    so a student can sit the paper without the answers. Both files use the same
    sequential Q1/Q2/... numbering, so the scheme lines up with the paper.
    Branding is shared with compose via the extracted `brand_backdrop()` /
    `footer_band()` helpers (one source of truth for the cover). The test cover
    is exam-styled (instructions, Name/Date write-in, suggested time ~1 min per
    mark); the MS cover is its plainer companion. Verified on 0625
    Forces+Momentum: test Q1 = 0625/43/O/N/20 Q2 with blank answer space, MS
    Q1 = the same question's scheme. Command:
    `python -m pipeline.testgen --syllabus 0625 --topics "Forces,Momentum" --count 6 --seed 7`

22. **Every-page watermark (tutor, 2026-07-19 - REVERSES the earlier
    "cover only" instruction).** All body pages of every generated PDF
    (compose AND testgen, questions and mark schemes) now carry a faint
    black-and-white PrepWithTee watermark: grayscale owl + grey wordmark,
    centred, drawn by `page_watermark()` inside `Booklet.new_page()` BEFORE
    any content, so PDF paint order keeps it behind the text layer - it can
    never cover a question. Implementation notes:
    - The owl is pre-blended onto white in Python (`_watermark_owl()`,
      `WM_STRENGTH = 0.12` ink) with light pixels snapped to pure white, so
      the image edge is invisible on the white page.
    - **Pitfall: `Pixmap.set_alpha()` premultiplies the colour samples**
      (cream 242 became ~5 = black); a "real" alpha-channel watermark came
      out mangled. Pre-blending is the reliable route. Tried and reverted.
    - The owl's own silhouette is nearly rectangular - a faint grey block
      with white eyes/T is the CORRECT rendering, not a clipping bug (same
      reason the cover veil needed 0.955).
    - Verified on 4024 test paper, 0625 topical, and 0625 test mark scheme:
      diagrams, dotted answer lines and MS tables all paint over it cleanly.
    Testgen confirmed working for all four live subjects (4024, 0580, 5054,
    0625) - it is syllabus-agnostic, so any future subject registered in
    config + taxonomy + classified gets tests automatically.

23. **MCQ answer grid + bubble sheet (tutor, 2026-07-21).** 9702 Paper 1 is
    multiple choice, and `link_ms` had been cropping one row of the mark
    scheme's Question/Answer/Marks table under each question - which both
    looked wrong and spoiled the answer before the student attempted it. New
    stage `pipeline/mcq.py` parses the letter out of those tables into a new
    `ms_entries.answer` column (regex `(\d{1,2})\s+([A-D])\s+1`; the trailing
    mark is what keeps page furniture like "9702/11" and "Page 2 of 3" out).
    All 44 P1 mark schemes parsed contiguous 1..40 keys, 1760 answers stored,
    spot-checked against the source PDFs. compose/testgen then:
    - print a fill-in **bubble sheet on page 2** (after the cover, so it can be
      detached and kept beside the booklet) and an **answer grid at the back**;
    - decide **per question**, not per booklet, via `config.is_mcq()` - an
      "All papers" selection interleaves MCQ and structured questions, so the
      structured ones keep their inline mark scheme while the MCQ ones go to
      the grid;
    - number the bubble sheet with the **booklet's own question numbers**, not
      1..N, or the rows stop lining up in a mixed booklet (verified: a 33-question
      Superposition booklet gave rows 2,3,5,6,7... skipping the 6 structured ones).
    MCQ questions had `marks IS NULL` (no "[1]" in the question text to parse),
    which made covers read "0 marks"; all 1760 are now `marks = 1`, so
    `testgen --marks` works for MCQ too.

## Ground rules for future sessions

- Never extract-and-retypeset question text for output PDFs; always crop
  regions of the original (`page.show_pdf_page` with `clip`).
- Debug PNGs are regenerated on every segment run - non-negotiable.
- Pages with no text layer are flagged to `review_queue`, never silently
  OCRed.
- Every stage must stay independently re-runnable and skip work already done.
- There is **no** Excel tracker of classifications and there never will be
  (the user ruled this out explicitly). Questions are classified from the
  official syllabus subject content alone. `pipeline/validate.py` is a pure
  internal-consistency check: crops exist, text non-empty, topic is in the
  taxonomy, MS linked. The only xlsx the project consumes is the tutor's
  *syllabus breakdown* for Maths (`OL JAN-MAR 2025.xlsx`), which builds the
  4024/0580 taxonomies.
