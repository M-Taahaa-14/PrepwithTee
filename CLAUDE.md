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

24. **CS COMPLETE 2026-07-31: 2210 + 0478 classified.**
    - 2210: 410 questions, 12 hard failures (all from 2210_s20_qp_22 over-segmentation artifact).
    - 0478: 659 questions, 12 hard failures (8 from 0478_m20_ms_12 prose-style MS, 4 from w20
      over-segmentation). Fixed 0478_s23_qp_23 duplicate (was stored twice: once as session='m',
      once as session='s'; deleted the m-duplicate).
    - link_ms fix: `table_pages()` now extends from the first header page to end-of-doc, fixing
      pre-2022 MSs where the "Question | Answer | Marks" header only appears on the first page.
      This also fixed 0478_m21_ms_12 (was 1 entry, now 8) and 0478_m21_ms_22 (1→5).
    - Taxonomy: 10 parent topics + 22 subtopics per syllabus. Both 0478/2210 are standalone
      files (not alias) matching the official 2026-2028 syllabus structure.
    - Classification done via in-session rule-based classifier (`scratchpad/classify_cs_rules.py`)
      — keyword rules with hard P1/P2 paper constraints; ingested as backend='session'.
    - **CS traps:** Older P2 papers (m20/m21) have a Section A / Section B structure that can
      confuse the table parser; the table_pages fix covers this. Some P2 papers over-segment
      (one long pseudocode question → many row fragments); those fragments get classified as
      Programming or Algorithm but have no MS link — acceptable, they show the question crop.

25. **Improvements plan (IMPROVEMENTS_PLAN.md, approved 2026-09-24) - P0 done
    locally, NOT deployed:**
    - **Environments**: `APP_ENV=local|test|staging` makes `website/env_guard.py`
      refuse any DB setting that points at the production Supabase project.
      Local dev = `--env-file .env.local` (SQLite: data/index.db + data/users.db,
      no email). `.claude/launch.json`: `prepwithtee-local` (safe default),
      `prepwithtee-staging` (8021), `prepwithtee-PROD-DATA` (8018, explicit).
      **Local dev runs on http://localhost:8017 - always** (tutor, 2026-09-27): Google
      sign-in only accepts that redirect (`APP_BASE_URL=http://localhost:8017` in
      .env.local), and the e2e tests default to it (`E2E_BASE_URL` overrides).
    - **Tests**: `pytest` (unit/api/pdf; LLM + email keys blanked, throwaway
      users DB). `-m e2e` / `-m live` are opt-in. Nothing ships until green.
    - **Old mark schemes**: production lacked 16,173 of the 2010-19 `ms_entries`
      rows (every MCQ key) and 6,136 crop PDFs. Fix is ready but awaits the
      tutor's go-ahead: `scripts/sync_ms_to_supabase.py --apply`, then upload
      `data/output/missing_crops.tar.gz` (`scripts/bundle_crops.py`).
    - **compose layout**: crops too tall for the page are scaled to fit (they
      used to run under the footer band); crop edges grow up to 14 pt to take in
      any text line they slice (`_fit_rect_to_text` - this was cutting fraction
      numerators and powers); section/insert headings stay with what follows;
      answer-line-only continuation rects are dropped (topical only - testgen
      keeps them); clickable contents pages + PDF outline; `--ids` (exact order)
      and `--page-map` for the web viewer.
    - **Old mark schemes SYNCED to production 2026-09-24** (tutor approved):
      16,383 ms_entries rows (10,937 old MCQ keys) + 6,136 crop PDFs; server now
      has 58,794 crops. Verified live: 2016 MCQ answers + 2015 MS previews.
    - **PDF extras**: navy/cream redesigned cover (clickable wordmark + owl
      medallion, stat tiles, fillable Name/Class/Date); body-page watermark
      wordmark links to the site (not the whole owl - it would hijack clicks);
      MCQ answer sheet is fillable: one radio group per question built by
      `_group_radio_fields` (PyMuPDF alone makes 4 linked "Yes" boxes; keys must
      be removed by rewriting the object - "null" breaks pdf.js).
    - **P1-a (local, not deployed)**: `website/catalog.py` = board/subject
      registry (BOARDS moved here from app.py), `/api/boards`, `/api/me/boards`,
      `/api/catalogue`, and server-rendered SEO pages `/papers`,
      `/papers/{board}`, `/papers/{board}/{subject}`, `/papers/{b}/{s}/{chapter}`
      (+ sitemap). Students pick multiple boards (modal, pre-ticked from their
      enrolments). Nav "Past Papers" now points at /papers.
    - **P1-b (local, not deployed)**: topical builder + viewer.
      `website/selection.py` (pure: quotas + recursive interleave + guarded
      shake = every picked chapter/subtopic present, optimal max run),
      `website/booklets.py` (tree/count/create/status/pdf API, thread-pool job
      running `compose --ids --page-map` with PROGRESS lines -> status in DB),
      `static/builder.js` (on the subject page for enrolled students; <=4
      chapters, any subtopics, years/paper filters, live pool count, opens a new
      tab), `/papers/view/{id}` + `static/viewer.js` (loader with real stages,
      PDF.js lazy pages + annotation layer so contents links and the answer
      sheet work, contents drawer, per-question chips -> side panel with the
      official MS / MCQ letter; Explain + Guide me are stubs for P1-c).
      `/papers.html` 302s to the new builder except `?tab=yearly|mcq` and
      `?mode=test`. E2E: `pytest -m e2e tests/e2e` against prepwithtee-local
      (screenshots in e2e-shots/). NOTE pytest-playwright wipes test-results/.
    - **P1-c (local, not deployed)**: AI help panel. **FREE PROVIDERS ONLY** (tutor,
      2026-09-25: paid Claude ruled out on cost). `pipeline/explain.py` writes ONE
      structured explanation per question (parts/steps/answer/marking, 3 Guide-me
      hints, MCQ option reasons, common mistakes) from the question crop + official
      MS crop/letter, on Groq `qwen/qwen3.8-27b` (vision; Gemini drops in with
      GEMINI_API_KEY). Free Groq = 1000 requests/day + 8000 tokens/min PER MODEL,
      shared with the live site, so: `--drip --per-day 600 --reserve 300` works
      newest-first inside the quota, and `website/ai_help.py` generates on demand
      the first time anyone opens a question, then stores it for everyone. Output
      is NOT requested in strict JSON mode (it 400s on LaTeX backslashes);
      `parse_text` doubles single-backslash LaTeX commands (`rac` would decode as
      form-feed+"rac") and validates. Follow-ups stream from Groq
      `openai/gpt-oss-120b` (text-only; context = question text + stored solution).
      Rules: free = ONE explanation (reopenable, explanation_unlocks; a busy provider
      never spends it), hints + follow-ups need a plan; trial 5/20/20; paid
      unlimited explain+hints, follow-ups capped FOLLOWUP_MONTHLY_CAP (300).
      **Drip (2026-09-25)**: `python -m pipeline.explain --drip --loop --per-day 1500
      --reserve 300` runs one thread per provider (Groq + Gemini `gemini-3.8-flash`;
      2.0/2.5-flash are retired) off one shared queue, log in data/logs/. Groq free
      also caps **7000 INPUT tokens/min** and a question is ~4.5k (images), so the
      drip paces itself to HALF of that - the local .env GROQ key IS the production
      key, and the live Photo Solver uses the same model. Prod hotfix applied:
      `GROQ_VISION_MODEL=qwen/qwen3.8-27b` in /etc/prepwithtee.env (backup
      .bak-20260925). Explanations are generated locally; push them with
      `scripts/sync_explanations_to_supabase.py` at deploy time (migration 021 applied).
      `static/ai-panel.js` (+css) = shared panel (KaTeX + marked + DOMPurify, math
      lifted out with a letters-only placeholder). Pilot 2026-09-25: 3 x 5054
      explanations matched the official MS. **Groq retired qwen3.6-27b** (live
      Photo Solver/tutor vision default) - app.py now defaults to qwen3.8-27b.
    - **Groq blocks this PC's network (403 "Access denied. Please check your
      network settings", 2026-09-26)** - the server reaches it fine. The drip
      must therefore run ON THE SERVER after deploy (explain.store writes the
      local SQLite pipeline DB today; needs a Postgres path for that).
    - **P1-d (local, not deployed)**: `website/yearly.py` = `/yearly`,
      `/yearly/{board}`, `/yearly/{board}/{subject}[/{year}]` (SSR, every sitting
      as text, year chips open the collapsed `<details>`), `/yearly/view/{paper_id}`
      (login + enrolled, noindex; `?doc=qp|ms|in`), `/mcq` + `/mcq/{board}/{subject}`
      landing pages (solver itself is still mcq-solver.html until P1-e). Old
      `/papers.html?tab=yearly|mcq` and `/library.html` 301 there. Viewer =
      `static/paper-viewer.js` on the shared `static/pdf-pane.js` (viewer.js uses it
      too): QP/MS/Insert tabs, side by side >=1280px with the MS following the
      question being read (ms_entries.rects_json, ~2017+), chips from
      questions.rects_json (page is 0-based there), Mark done + marks + official
      thresholds (default "out of" = threshold max_mark - summing question marks
      overcounts papers with optional sections). PdfPane sizes pages individually:
      mark schemes are a portrait cover + landscape (rotate=90) pages.
    - **P1-e + P2-a (local, not deployed)**: MCQ solver rebuilt. `website/mcq.py`:
      `/api/mcq/topics`, `/api/mcq/sessions` (start: full paper `paper_id` or topical
      `topics`+count, mode paper|single, live_check, timer official|none|custom),
      `GET/PUT answer/PUT clock/POST submit`, page `/mcq/session/{id}`, old
      `/mcq-solver.html` 301s to `/mcq/{b}/{s}`. Keys are NEVER sent up front: one is
      revealed per question by live check (then locked) or all after submit; submit
      records paper_progress for full papers. Official MCQ times in `EXAM_MINS`
      (topical = same pace per question). Frontend `static/mcq-session.js/.css`
      (intro -> paper view [original PDF + gutter markers, or stacked vector crops for
      topical] / one-by-one / results + review; answer sheet = bottom drawer < 1000px;
      keys A-D/1-4, arrows, F) and `static/mcq-setup.js` (start card on the MCQ subject
      page; `?paper=` / `?topics=A|B` preselect). Crop PDFs served by
      `/api/question/{id}/crop.pdf`. **Annotations**: `static/annotate.js/.css` =
      floating pill (pen, highlighter, eraser, line, arrow, rect, ellipse, text,
      colours, sizes, undo/redo, clear, drag to top/bottom, collapses to a pen FAB,
      palm rejection once a stylus is seen), strokes as page fractions, saved per page
      to `/api/annotations` (doc keys `paper:<id>`, `booklet:<id>`, `mcq:<sid>:q<qid>`,
      `mcq:<sid>:q0` for a session's full PDF). Wired into the booklet viewer, the
      yearly viewer and both MCQ views via `PdfPane({onPageEl})`. PDF.js needs
      `PDF_OPTS` (standardFontDataUrl) or symbol fonts go missing. NOTE the pane in
      the desktop app doesn't render while hidden (rAF/IntersectionObserver) - verify
      rendering with the Playwright e2e tests, not the hidden pane.
    - **MCQ keys 2010-16 (2026-09-26)**: every old two-column "Question Number | Key"
      scheme had lost questions 10-19 (link_ms never made the rows). `pipeline.mcq`
      now pairs number+letter, inserts missing ms_entries rows, tolerates Cambridge
      "Question removed/discounted", and ignores pre-2016 Paper 2 THEORY schemes
      (0620/0625 P2 were not MCQ then; require >= 20 answers). Local 99.3% keyed.
      **Production NOT yet synced**: run `scripts/sync_ms_to_supabase.py --apply`
      (dry run: 1,949 inserts, 0 changes) - blocked for the agent, the tutor runs it.
    - **P2-b (local, not deployed)**: `static/math-expr.js` (window.PWTMath) =
      tokenizer + Pratt parser + closure evaluator, no eval/new Function; implicit
      multiplication, `sin x`, `sin^2 x`, `sin^-1 x`, `|x|`, `log_2`, `√ ∛ π e ² ³ !`,
      `-x^2 = -(x^2)`, friendly MathError messages with position; `relation()` gives
      explicit / vertical / implicit (F(x,y)=0, drawn by marching squares). The graph
      plotter keeps the last good curve (faded) while an expression is half-typed,
      shows a y= / x= / relation chip per row, equal axis scales by default.
      tools-core SOURCES entries may be arrays (loaded in order); tools-core.js and
      tools.css versions bumped on every page. Tests: tests/unit/test_math_expr.py
      (Node, ~60 values at x=2 + errors + relations), tests/e2e/test_graph_plotter.py.
    - **Free explanation providers + official-answer gate (2026-09-26)**. Groq's free
      vision model is capped at **200k tokens/DAY (~30 explanations)** and is the live
      Photo Solver's budget, so it is OUT of the background job. `pipeline/ai_providers.py`
      = registry (mistral [workhorse, vision], nvidia, openrouter, groq_text [gpt-oss,
      capped 40/day - shared with live follow-up chat], gemini, groq [site only],
      cloudflare, ollama), each enabled by its key in .env, model overridable with
      EXPLAIN_<NAME>_MODEL. `pipeline/explain_check.py`: route() text vs vision (maths
      4024/0580/9709 always vision; figures, "Fig./diagram" wording, drawn MCQ options,
      image-only mark schemes -> vision); pdf_text() keeps ^superscripts/_subscripts;
      check() = MCQ exactly one correct option == key; structured = mark-scheme values
      (ignoring question refs, mark codes, "M1 for ..." partial credit; "a to b" ranges as
      intervals; en-dash minus) present in the working. Then a second model must agree
      (mark-scheme IMAGE for maths). Failing explanations are retried elsewhere, never
      stored. `python -m pipeline.explain --probe` tests every configured provider.
    - **DEPLOY PREREQUISITES**: run `website/migrations/019_student_boards.sql`
      (done 2026-09-24), `020_booklets.sql` (done 2026-09-25) and
      `021_ai_help.sql` (done 2026-09-25) and `022_mcq_sessions_annotations.sql`
      (done - verified present) on Supabase BEFORE deploying code. **Branch deployed 2026-09-27**
      (code-only tar of website/ + pipeline/ via /tmp/stage; backup /srv/backup-code-20260925-1550.tgz);
      the server runs **Python 3.10** - no 3.12-only f-string syntax
      (py_compile new files with the server venv).

26. **UI overhaul (2026-09-27) - DEPLOYED with the whole improvements branch (commit 5ccef91)** - tutor: "ui isn't that good,
    dark mode is just dark purple on purple".
    - **Dark mode** = neutral slate surfaces (`--page #0f1117`, `--white #1c212b` cards),
      near-white headings, colour kept for accents. New semantic tokens `--accent`,
      `--on-accent`, `--accent-soft` (filled buttons/selected chips in BOTH themes - never
      `background: var(--purple)`, which is near-white in dark).
    - **Components registry**: `catalog.COMPONENTS` (short label, full title, AS/A2 level
      per paper) is the one table; app.py's `PAPER_LABELS` derives from it.
      `catalog.paper_groups(code)` groups chapters by the paper that examines them
      (from taxonomy `papers`; identical chapter sets merge, e.g. 9702 P1+P2 = AS).
    - **Builder** (`builder.js` + new `builder.css`): chapters grouped by paper with AS/A2
      badges and a jump bar; **free mixing across papers** (tutor's choice); subtopics shown
      as chips (tap chips = part of a chapter; the box then shows partly, ticking it = whole
      chapter); search highlights chips. **Practice booklet / Mock test** switch - the old
      papers.html Test Builder moved here: `kind:"test"` runs `pipeline.testgen --ids`,
      writes `{id}.pdf` + `{id}_ms.pdf`, quota `topic_test`; the viewer shows Test / 🔒 Mark
      scheme tabs, a 1-min-per-mark timer, and "Finish test" unlocks the scheme
      (localStorage `test-done:{id}`). `?mode=test` flows /papers -> board -> subject.
    - **Yearly subject page**: each year is a grid (rows = paper components, columns =
      sessions, tiles = variants with QP/MS/Insert/▶ Practise), sticky filter bar
      (component + session chips + search), year rail, "n done" per year.
      `/yearly/open?syllabus&year&session&paper&variant` or `?key=5054_s23_22` resolves a
      sitting to its viewer (progress page + old deep links use it).
    - **Header/footer**: `partials/nav.html` + new `partials/footer.html`, all links absolute;
      `sync_nav.py` stamps BOTH (NAV / FOOT markers); `blog._nav()/_foot()` serve them to the
      SSR pages. Mega-menu CSS moved from dashboard-hub.css into styles.css (SSR pages never
      loaded it). Footer newsletter handler lives inside the partial.
    - **Deleted**: library.html/.js, mcq-solver.html/.js, papers.html, app.js, papers-ui.css,
      and APIs only they used (`/api/mcq/questions`, `/api/mcq/preview-pdf`,
      `/api/mcq/explain`, `/api/library/search`, `/api/library/check-quota`). Old URLs 301
      (`/papers.html?...` maps syllabus/topic/mode=test/key/tab onto the new pages).
      `/api/library/pdf` + `/api/library/tree` stay (viewer + progress pages use them).
    - Tests blank every provider key (MISTRAL/NVIDIA/... too) - a real key in .env made
      test_ai_help call out. 258 unit/API + 13 e2e green.

27. **Since the deploy (2026-09-27/28, committed, staged on the server via /tmp/stage):**
    booklet viewer range-loads PDFs (`PdfPane({ranged, uniform})` - page 1 in ~1 s
    instead of downloading 5-10 MB); compose/testgen `save_small()` = lossless dedup only
    (**never `subset_fonts()`** - MuPDF drops the space glyph from Cambridge fonts); MCQ
    sessions preload every question before Start; colourful Marks & grades panel;
    annotations rewritten (touch-action none for pens - Wacom strokes used to turn into
    scrolls; Select tool; partial / whole-object eraser with sizes on the bar; editable
    text); scratch pen on every non-PDF page (`scratch-pen.js`, never saved); Tools nav
    two-column; **P2-c calculator**: `website/calc.py` + `calc_state` table
    (**migration 023 must be run on Supabase before deploying it**) - memory M+/M−/MR/MC,
    Ans, variables A-F (STO), DEG/RAD, last 200 calculations per account; guests keep
    the same in localStorage `pwt-calc`, merged in on sign-in.
    **Booklet retention**: built PDFs are deleted 30 days after they were last OPENED
    (`booklets.sweep()`, every 6 h in each worker; opening = `os.utime`); the row keeps
    the ids, so an old link's status call queues a rebuild of the same paper. Builds
    write `{id}.tmp-<pid>-<thread>.pdf` and `os.replace` it in (two workers can rebuild
    at once). `BOOKLET_RETENTION_DAYS` overrides.
    **Ruler + protractor** (annotation bar, never saved): real scale from the page width
    (A4 210 mm, landscape 297 mm; CSS mm on web pages); drag / rotate handle (1°, Shift 15°);
    a pen/highlighter press within 14 px of a ruler edge is handed to the page canvas and
    snaps to the edge line (`rulerSnap`), the ruler's middle strip still drags it.
    **P2-d Notes** (`website/notes.py`, SSR): `/notes` -> board -> subject (chapters grouped
    by paper like the builder) -> chapter (learning outcomes, notes, subtopic checklist) ->
    note (full text in the HTML, KaTeX, TOC, sidebar, prev/next, "Practise this chapter" =
    builder `?pick=`). Notes attach to TAXONOMY chapters: `static/notes-content/{syl}/
    {chapter-slug}/{note}.html` with a `<!--note {"title","order","subtopic","tier"} -->`
    header; `_chapter.json` / `_subject.json` optional; new files appear by themselves.
    `manifest.json` is gone (archived to data/notes-manifest.old.json by
    scripts/migrate_notes_to_taxonomy.py); note.html / chapter.html / subject.html deleted,
    301 via `notes-content/_redirects.json`. Chapters/subjects without notes are noindex and
    out of the sitemap. Nav "Notes" -> /notes.
    **P2-e**: `/solver` (static solver.html/js/css) = Photo Solver with two modes -
    "Solve a question" (SOLVER_SYSTEM) and "Check my working" (CHECK_SYSTEM: question photo
    + working photo or typed text -> estimated mark, per-step ✓/✗); drop / paste / camera,
    crop box, JPEG <=1600 px client-side; `/api/solve` takes `mode`, `working`,
    `working_text`, `syllabus` (vision helper takes extra images); `/api/solve/followup`
    (text-only, answer as context). ask.html + tutor.html?tab=solver -> /solver. Tutor:
    server message ids adopted from the stream's done event; regenerate + new ✏️
    edit-and-resend call `DELETE /api/tutor/sessions/{sid}/messages/{mid}` (drops that
    message and all later - they used to stay in the DB); chat search; "which AI help"
    card; drifting maths-symbol background. **tests/conftest.py now deletes its temp dir
    at exit** - 120 leftover 90 MB copies had filled C: (2026-09-26).
    **P3 landing demo**: "See it in action" section on index.html (after the numbers
    band) = `static/demo-player.js/.css` playing `static/demos/how-it-works/timeline.json`
    (9 real screenshots in a tablet frame; crossfade, zoom about the cursor, click
    ripple, captions, 5 chapter buttons; plays only on screen, pauses on hover/focus/
    hidden tab, reduced motion = manual frames; poster <img> without JS). **Re-capture
    after UI changes**: `.venv\Scripts\python scripts\capture_demo_shots.py` against the
    local server (demo student "Ayesha Khan", paper 37 for stored explanations); it
    asserts every cursor target is on screen. Viewer stages scroll, not the window.
    **Pre-2017 mark schemes (2026-09-27)**: the linker only read table-style schemes, so
    ~470 old structured schemes (9709, 9702, 5054, 5070, 0620, 2210/0478 2015-16, parts of
    0580...) had NO ms_entries anywhere - booklets said "Mark scheme: not available".
    `link_ms.legacy_boundaries()` now reads the margin layout: question number alone at the
    left margin (x ~ 50, +16 tolerance), optional Section prefix `A1`/`B7` (5070), pages
    count once they carry mark codes or Question/Answer headings; cuts on the ruled line
    above a question when there is one (tall maths rises above its number); continuation
    pages start below any repeated table header. Used when the table parser finds fewer
    questions than the QP; capped at the QP's last number; 9702 P5's numbered marking
    points are ignored in favour of the largest "(N marks)" headers. +4,103 entries
    (37,082 -> 40,985 of 42,154 questions have a scheme). Still unlinked: 0478_m20_ms_12,
    0580_m16_ms_22, 9709_s17_41/s19_41/w19_42 (+ 0580_s17_21 Q15, broken text layer).
    Tests: tests/unit/test_legacy_ms.py. Production needs sync_ms_to_supabase --apply +
    the crop bundle + deleting built booklet PDFs (they rebuild on open).
    **Paper eras (2026-09-27)**: component numbers meant different things before the
    syllabus changes. `config.is_mcq(syl, paper, year)` - 0620/0625 P2 is MCQ only from
    2016 (`MCQ_FROM_YEAR`; earlier P2 is Core theory); MCQ pickers use
    `not_old_theory_sql()`. `config.PAPER_YEARS` + `paper_in_scope()` limit components
    to their era (0625 P3 = old Extended theory 2010-15; 9709 P6 = old Statistics
    2010-19); `catalog.OLD_COMPONENTS` / `component(code, paper, year)` label them
    per year. Segment + link_ms accept `A1`/`B7` numbering (5070 P2). **Every question is
    now classified** (all 10+ syllabi, 2010-2025) except 9702 P5 (practical planning,
    tutor: leave out of topicals). Deliberate `status='excluded'`: 0580/4024 matrices +
    genuine loci; old 9709 P5 = Mechanics 2 (not in the current syllabus, 442 q); old
    9702 P4 op-amp/sensor/communication questions (removed from 9702 in 2022, ~133 q).
    Classify chunks live in the scratchpad pattern of item 17 (id + T-code lines).

28. **Section pages + navigation (2026-09-28, local, not yet deployed).**
    - `website/ui.py` = shared SSR blocks: `subject_tabs(code, active)` (Topical / By year /
      MCQ / Mock test / Notes / Resources on every subject page), `steps`, `mode_card`,
      `faq` (+FAQPage JSON-LD), `callout`, `back_link`. `catalog._shell` adds a "← Back to
      <parent crumb>" pill automatically.
    - Routes: `/papers` = hub (no redirect any more), `/papers/topical`, `/papers/mock-tests`
      (`?mode=test` 301s there), `/my-papers` (booklets.py), `/resources...` (new
      `resources.py`, the data/resources folder: subjects, shelves, folders,
      `/resources/view?f=` viewer), `/explore` (every page). `resources.html` and
      `notes-view.html` are deleted and 301 to `/resources` / `/notes`.
    - **Yearly papers are open to everyone** - no login, no enrolment (tutor). Guests get
      scratch ink; saving ink/marks/done asks them to sign in.
    - **Booklet retention REVERSED**: a paper not opened for 30 days is a RECORD only
      (status `expired`, PDF 410, record page, "Build it again" = builder `?pick=A&pick=B`),
      never rebuilt. `?annotated=1` burns the student's ink into the download (`annot_pdf.py`).
    - PDF viewers: White/Dark paper toggle (`paper-theme.js`, `<html data-paper>`, inverts only
      `canvas.vw-pdf`). Annotation inks are TOKENS (`@blue` ...) with a light and a pastel
      shade - `annotate.js` PALETTE and `annot_pdf.PALETTE` must match; custom colours = hex.
      Old `annotation-toolbar.js` deleted (scratch-pen covers every page).
    - Static pages: `sync_nav.py` also stamps a breadcrumb bar (`CRUMBS` table,
      CRUMB markers, BreadcrumbList JSON-LD) under the header. New static page = add it to
      CRUMBS, run `python sync_nav.py`.

29. **UI + speed pass (2026-09-27, local, not yet deployed).**
    - **Speed**: `website/db.py` keeps a pool of open Postgres connections (own idle
      list, NOT psycopg2.pool - it closes everything above minconn); every query used
      to pay a fresh TLS connect to the Supabase pooler (~1-2 s). `yearly._all_years()`
      = one cached query for every subject's year/paper counts (was one per subject:
      /yearly took 14 s on production). `_student_state` reads run via `udb.gather`.
    - **One picker** (`ui.picker` + `ui.tile`, CSS `.pk-*` in catalog.css, behaviour
      in catalog.js): board tabs + search + a coloured band per board + equal tiles
      (icon, flag, name, code/years, 2 stats, "Also" links, max 2 buttons). Used by
      topical, mock tests, board pages, yearly, MCQ, notes, resources.
    - **Site search**: header button + Ctrl K / "/" (inline hook in partials/nav.html,
      palette = static/site-search.js) over `GET /api/search/index` (website/search.py:
      pages, subject sections, every chapter, every note; cached 10 min).
    - Dark mode lifted to a "dimmed" slate (page #1c2130, cards #293043); colour pass
      (tinted heroes, tone-cycled steps, centred FAQ/"which one"). Profile redesigned
      (hero + stats, section nav, subject tiles from /api/boards `links`; Board field
      pre-fills from student_boards).
    - Booklets/mock tests print **newest paper first** (`selection.order_recent_first`),
      still covering every picked chapter.

30. **Round 2 UI + streak fix (2026-09-28, local, not yet deployed).**
    - **Streaks were broken for everyone**: `/api/dashboard` called
      `users_db.get_time_spent_range`, which did not exist (AttributeError swallowed), so
      tracked time never counted; best streak lived in localStorage and was reset to the
      server's 0 on each visit. Now `website/streaks.py` (pure, tests/unit/test_streaks.py):
      a day counts for ANY activity (time, quizzes, booklets, MCQ sessions, marked papers,
      flashcard reviews), in the student's timezone (`?tz=` from the browser, default
      Asia/Karachi); returns `streak`, `streak_best`, `week_active`. `/api/time-spent` takes
      the browser's local `day`; the pagehide beacon is sent as JSON (was text/plain -> 422).
    - **Multi-board profile**: Board dropdown -> board chips (PUT /api/me/boards, first =
      main; hidden `grade` select follows). `save_profile` no longer archives every subject
      when the main board changes - only subjects of boards the student dropped.
      Dashboard "Add a subject" lists all the student's boards.
    - Header: full width, logo hard left, `.header-end` (search + account) hard right.
      Dashboard section tabs (`sync_nav.DASH_TABS`, stamped in the CRUMB block;
      `ui.dash_tabs()` on /my-papers). `ui.page_search()` filter box (notes chapters,
      resources folders incl. files deep inside, explore). Explore rebuilt. Notes chapter
      cards: numbered, colour-cycled, subtopics always shown. Builder chapters colour-cycled.
      Profile: formula cards per subject (ring + due today), feedback form (-> /api/feedback),
      photo cropper `static/avatar-crop.js` (drag / zoom / pinch -> 512 px JPEG).
    - Dashboard tabs = ONE sticky row under the header (the crumb strip is hidden on those
      pages). **Progress tracking is free for every subject** (tutor): the free-plan
      "first subject only" blur in topical-progress.js is gone - don't re-add plan gates
      to topical/yearly progress.

31. **Home hero v2 (2026-09-28, local).** Tagline "You already work hard. Let's make it
    count." + a MacBook-style laptop (`demo-player.js` `data-frame="laptop"`: lid opens on first
    view) playing `static/demos/hero/timeline.json`: an intro title card ("Not sure where to
    start?"), 10 real screenshots (pick board -> subject -> chapters -> booklet -> mark scheme ->
    Explain -> marks -> dashboard) and an "Ask Tee" card with WhatsApp + free-demo buttons.
    Timeline steps may be `{card: {...}}` instead of `shot`. The player fetches only the next
    two screenshots. Replaced the three.js hero (hero3d.js no longer loaded) and the lower
    "See it in action" section (demos/how-it-works deleted). **Re-capture after UI changes**:
    `.venv\Scripts\python scripts\capture_demo_shots.py --base http://localhost:8017`.

32. **SEO pass (2026-09-28, local).** Share images: `website/og_image.py` serves
    `/og/{section}[/{board}[/{subject}]].png` (1200x630, PyMuPDF, cached in data/og/v{VERSION};
    bump VERSION to redraw); `catalog._shell` picks it from the page path (chapter/year pages
    use their subject's). Only real sections/boards/subjects render - no free text. Sitemap
    `<lastmod>` = real file mtimes (static pages, notes via `notes.sitemap_lastmod()`,
    resources via `resources.sitemap_lastmod()`); papers/yearly pages have no trustworthy
    date, so they carry none. robots.txt must NOT disallow redirect stubs (Google then never
    sees the redirect) - /notes.html stays disallowed because it is the private "My notes".

33. **Student feedback fixes (2026-09-30, local, not yet deployed).**
    - **Viewer lag / slow booklets**: `pdf-pane.js` now draws at most 2 pages at a time
      (nearest first), releases the canvas of any page >1200 px off screen (a 167-page
      booklet used to keep every drawn page, ~14 MB each at DPR 2), caps DPR at 2 and a
      page at 12 MP. Ranged loads use 1 MB chunks WITH auto-fetch (was 256 KB, fetched only
      on scroll: ~1.7 s per request from Pakistan = the "minute or two"). `booklets.py`
      caches a ready booklet's row 5 min so range requests skip the Supabase lookup.
      `annotate.js` ink canvases hold pixels only while the page is near the screen AND has
      ink / is being drawn on (were two full-page canvases on every page).
    - **Text tool v2 (PDF-editor style)**: text object = `{t:"text", x, y, s, c, txt, bw?,
      f? (sans|serif|hand|mono), b? i? u?, al? (c|r), bg? ("paper" = cover, or an ink token =
      tint), bd?}`; boxes WITHOUT `f` are pre-v2 and keep their semi-bold look. The editing
      box is a textarea styled exactly like the canvas text (same font metrics/baseline via
      fontBoundingBox), with side handles for the wrap width and a formatting bar (`.an-tb`:
      move grip, font, size in pt = s*595, B/I/U, align, colour, fill, border, duplicate,
      delete, Done). **Enter = new line; Esc / Ctrl+Enter / click outside = done** (a click
      outside only ends the edit - `A.swallow`). Text tool: drag a box = move, click = edit.
      Selected objects get handles (text: 4 corners scale, 2 sides wrap width; rect/ellipse 8;
      line/arrow ends), arrows nudge (Shift 10 px), Ctrl+C/X/V/D, Enter/F2 edits. Last-used
      text style lives in localStorage `pwt-annot-text`. `annot_pdf._draw_text` burns the same
      (base-14 fonts; handwriting -> Helvetica oblique).
    - **Search**: builder.js re-rendered its search box on every keystroke and refocused a
      fresh copy with the caret at 0 ("circles" -> "selcric"); render() now moves the SAME
      input element across. `ui.page_search(..., deep=[ui.deep_entry...])` = search covers the
      whole subtree BELOW the current folder (never outside it): results list with paths,
      ranked, highlighted, ?q= in the URL, arrows/Enter. Used on resources subject/folder/shelf
      pages (`resources._subtree`) and the notes subject page (chapters, subtopics, notes).
      Wrap the normal listing in `data-ps-browse`. Tests: tests/e2e/test_search.py.
    - **Feedback**: `/api/feedback` requires name + email (format + the domain must resolve;
      the signed-in account's own email skips the lookup); both forms prefill from the
      account, editable; typo hint (gmial.com). **Run `website/migrations/024_feedback_email.sql`
      on Supabase before deploying** (save_feedback falls back to putting the email in the
      message if the column is missing). Admin feedback table shows Email (mailto).

34. **fx-991ES-style calculator + Tools tab on papers (2026-09-30, local, not deployed).**
    - `static/calc-engine.js` = the maths, no DOM, UMD (browser `PWTCalcEngine`, Node for
      tests/unit/test_calc_engine.py). Input is a TREE (items + templates frac/mixed/sqrt/root/
      pow/logab/abs/integ/deriv/sum with slots) edited by `Editor` (cursor = path into slots).
      Casio precedence (implicit × binds tighter than ÷: 1÷2π = 1/(2π); (−)2² = −4). `evaluate`
      returns {v, ex}; `exact()` finds 5/6, a√b/c, (p+q√b)/d, nπ/d - tolerances matter: an
      irrational must never pass for a fraction (fraction() uses 1e-13 with d<=1e5). Also SOLVE,
      ∫ (adaptive Simpson), d/dx, Σ, stats1/stats2, linear/quadratic/cubic, BASE-N (32-bit).
      Errors carry the Casio names (Math/Syntax ERROR) + a hint.
    - `static/tools-calculator.js` = the keypad (fx-991ES layout: SHIFT gold / ALPHA red labels,
      replay pad), LCD (natural display, S⇔D, SHIFT = decimal, ENG, °′″), MODE (COMP, STAT,
      BASE-N, EQN, TABLE; CMPLX/MATRIX/VECTOR deliberately off - not on the syllabuses), SETUP,
      CONST (Cambridge data-sheet values), CONV, FUNC (SHIFT 6: GCD/LCM/Int/Intg/RanInt/Rnd),
      CLR, CALC, SOLVE, STO/RCL into A-F X Y M (M = the memory). `/api/calc` vars now allow X, Y.
      Keyboard: digits, + - * ^, / = fraction, s c t l n r p, x y m, Enter, Esc, arrows.
    - `tools-core.js` loads tools by ABSOLUTE path (they open on /papers/view/... too) and the
      calculator as [calc-engine.js, tools-calculator.js]; VERSION 20260930c = `ui.TOOLS_V`.
    - **Tools tab on paper viewers**: `ui.tools_dock(syllabus)` -> `<body data-syllabus
      data-dock="push">` + tools-core/tools-dock scripts, on the booklet, yearly and MCQ
      viewers. The dock shows the subject's tools (maths: calculator, graph, formulas; physics:
      calculator, formulas, graph; chemistry: calculator, periodic table; CS: bases/logic,
      pseudocode) and, >= 1100 px wide, moves the paper over (`body.pwt-docked`, a resize event
      refits the PDF) instead of covering it. In the dock the calculator only takes keys while it
      has focus; annotate.js ignores keys inside `.pwt-dock`. Phone: the Tools tab sits above
      the quick-note button (they used to overlap on every page).

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

35. **Admin console v2 (plan approved 2026-10-01: `~/.claude/plans/can-you-see-the-gentle-flute.md`).**
    Full redesign of the admin side (Google + role=admin sign-in, shared DataTable with
    sort/filter/saved views/bulk, full student activity timeline, payment verification with
    automatic checks, one Inbox, background newsletter, AI blog/course/newsletter drafting on
    the free providers). **Phase 1 (audit bug fixes) done, local, not deployed:**
    - admin.js is a `type=module`: inline `onclick="fn()"` can never reach module functions -
      that is why Allocations Remove, proof Approve/Reject and group Publish did nothing. Use
      `data-*` + addEventListener (tests/api/test_admin_fixes.py enforces it).
    - teacher_students has ONE removal style: soft (`status='removed'`). `get_allocations`
      lists active only by default, `create_allocation` = the same upsert as the drawer
      (re-assign re-activates the row), `remove_teacher_student(t, s, syllabus=None)` drops
      every subject (the old 2-arg duplicate was shadowed -> teacher drop 500'd).
    - `_teacher_profile_id` uses teachers.profile_id, else a case-insensitive email match
      (then saves profile_id); approval saves profile_id. `get_user_by_email` is
      case-insensitive; `get_user` uses `.limit(1)` (`.single()` raised -> 500 not 404).
    - admin paper write passed `note` positionally into the `grade` slot - use keywords.
    - payment_proofs.reviewer_note (own column); Supabase proof rows flattened (name/email).
    - **Migration `025_admin_v2.sql` must run on Supabase before deploying** (grows with
      each phase).
    - Deferred to phase 2 auth: removing the hard-coded ADMIN_KEY fallback (.env.local has
      no key; the current key-gated UI would lock out locally).
    - **"3 Subjects" plan enforced strictly (tutor, 2026-10-01).** `access.PLAN_SUBJECT_LIMITS
      = {"three": 3}`; `profiles.plan_subjects_json` holds the set. The pricing picker sends
      `subjects` with the proof (exactly 3 known codes, `clean_plan_subjects`), approval
      applies them, only the admin can change them (plan editor ticks exactly 3).
      `_plan_active(user, syllabus)` = 'free' for a subject outside the set; every quota call
      passes the subject (`check_quota[_gate]/record_quota(user, event, syllabus)`), and
      `usage_events.syllabus` lets the free allowance for outside subjects count only outside
      usage. Pre-existing 'three' accounts with no set get their first 3 enrolments (saved).
      **Solo is enforced the same way (exactly 1 subject)** - `{"solo": 1, "three": 3}`;
      legacy Solo accounts get their first enrolment. The pricing pickers list every
      catalog subject (all 13, incl. Chemistry, Islamiyat, Pak Studies, 9709, 9618 - a test
      compares them with `catalog.BOARDS`). The free-plan "track 1 subject" gate in
      `/api/progress` is gone: progress tracking is free for every subject.
      Tests: tests/api/test_plan_subjects.py.
    - **Phase 2 done (local, not deployed): the new console lives at `/admin`**
      (`static/admin/`: index.html + app.js shell/router/Ctrl K palette, core.js, datatable.js,
      sections/overview|students|student|audit.js). Sections not rebuilt yet open the classic
      page (`/admin.html?tab=<name>`, `?student=<id>`), marked "classic" in the sidebar.
      - **Sign-in = site session of a role='admin' account, role read from the DB on every
        request** (`website/admin_auth.py`). ADMIN_KEY: env only, `X-Admin-Key` header only
        (no `?key=`, no cookie, no built-in default) - for scripts and the classic page's key
        gate. Give an account the role with `scripts/set_admin.py <email> --apply`.
        **Before deploying, run it for the tutor's production account** or /admin shows the
        sign-in card. Admin Google login now lands on /admin.
      - Every admin POST/PUT/PATCH/DELETE writes `admin_audit` (a route that logs its own,
        more specific row sets `request.state.audited`). `admin_views` = saved table views,
        `admin_notes` = private notes on a student, `profiles.last_seen_at` stamped by the
        time-spent beacon. All in migration 025.
      - `website/admin_students.py`: `/students/table` (filters, WHITELISTED sorts, paging,
        facets; enriched rows cached 60 s, cleared by any admin mutation), `/students/export.csv`,
        `/students/bulk` (plan incl. the subject rule, assign/unassign teacher, email with
        {first_name}), `/students/{id}/activity` (one timeline from 12 tables + streak/time
        summary), notes, `/views`, `/me`, `/audit`, `/overview/stats`. Its router is
        included BEFORE admin.router (else `/students/{user_id}` swallows `/students/table`).
      - `users_db.fetch_all()` pages Supabase reads in 1000-row blocks - **PostgREST silently
        caps an unpaged select at 1000 rows**; the old `list_students` counts were truncated.
      - Front-end rules (tests/api/test_admin_assets.py): colours only as tokens in admin.css
        (light + dimmed-slate dark), no inline `style=""`/`onclick=""`, and **every admin ES
        module is listed in index.html's import map at ONE version** (static JS is immutable
        for a year on Caddy; an unversioned `import "./core.js"` would never update). Bump the
        version string in index.html (css link, import map, app.js) on every change.
      - Tests: tests/api/test_admin_console.py, tests/e2e/test_admin_console.py (admin fixture
        promotes a fresh account in data/users.db).
    - **Phase 3 done (local, not deployed): every classic section except Blog is rebuilt in
      /admin** - Inbox (+ Calendly), Payments, Teachers (cards / applications / who teaches
      whom), Homework, Groups, Courses, Newsletter, Emails, and a Manage card on the student
      page (chapter progress, past-paper marks, class log, homework). Only Blog still opens
      the classic page (Phase 4 = AI blog/course/newsletter writing).
      - `website/billing.py` = periods + prices (monthly / octnov / mayjun / yearly; a test
        checks pricing.html shows the same numbers - yearly sends the YEAR total now), expiry
        maths (`new_expiry`: renewing early adds to the current end date; session packages run
        to their fixed date), automatic checks (amount vs plan+period, duplicate transaction id,
        duplicate screenshot by sha256, subjects for Solo/3 Subjects), student emails, and
        `reminder_due` (EXP7/EXP3/EXP1/EXPIRED ids carry the expiry date) used by the daily
        `website/scripts/email_lifecycle.py`. Proofs store `period`, `expected_pkr`,
        `screenshot_sha256`. Approval REQUIRES `received: true` ("I've seen the money").
      - **Payment screenshots are private**: `/uploads/payments/*` is only served to an admin
        or the student who sent it (route registered before the /uploads mount); the console
        reads them via `/api/admin/payments/{id}/screenshot`.
      - `website/admin_ops.py`: `/inbox` (leads, contacts, feedback, subject requests; status
        new/replied/handled/archived in `inbox_status`, reply-by-email logged on the item),
        `/payments` (+ approve/reject/screenshot/expiring), `/students/{id}/renewal-reminder`,
        newsletter subscribers + broadcasts. The classic page's review and broadcast buttons
        call the same functions (`approve_proof`, `reject_proof`, `nl_create`).
      - **Newsletter broadcasts are a background job** (`newsletter_broadcasts` +
        `newsletter_sends`): batches of NEWSLETTER_BATCH with NEWSLETTER_PAUSE_S between,
        branded HTML + working unsubscribe link, resumable, cancellable, schedulable. Each web
        worker runs a 60 s scheduler, so a broadcast is taken with an atomic
        `claim_broadcast` (queued, or 'sending' with a heartbeat older than 5 min).
        Newsletter fixes: resubscribing works; rows with NULL status count as subscribed
        (Supabase `status != 'unsubscribed'` dropped them); missing tokens are backfilled.
      - More unpaged Supabase reads fixed with `fetch_all`: email-activity (+ time limited to
        90 days) and the lifecycle cron's student list.
      - Admin front end: after ANY change under static/admin/ run
        `.venv\Scripts\python scripts\bump_admin_assets.py` (rebuilds the import map, bumps
        the one version). Tests: tests/api/test_admin_ops.py, tests/e2e/test_admin_phase3.py
        (the `admin_page` fixture now lives in tests/e2e/conftest.py; register test students
        over a SEPARATE http session - doing it in the admin's browser context swaps its cookie).
    - **Phase 4 done (local, not deployed): Blog studio + AI writing.** `website/content_ai.py`
      = one `generate()` over the free providers (`configured("site")` order, never `groq`
      vision, `groq_text` LAST - its daily cap is shared with the live follow-up chat; a short
      per-minute limit is waited out once, otherwise the next provider), JSON validated with one
      retry, prompts grounded in `site_facts()` (prices from billing.PERIODS, subjects, features)
      and `internal_links()` (real URLs from the site search index). Tasks: blog outline ->
      draft (markdown, excerpt, slug, meta, FAQ), inline edits (rewrite/simplify/shorten/expand/
      add example/continue), idea polish, course page fields (`clean_html` keeps p/strong/em/
      ul/ol/li/a/br/h3 only), newsletter draft. `website/admin_blog.py` = posts CRUD with
      `blog_revisions` on every save/AI write (restore), publish/schedule/unpublish
      (`blog.publish_due()` thread every 60 s), `/blog/ideas` from site data (subject requests,
      weak AI-quiz topics, most-built booklet chapters), `/courses/ai`, `/newsletter/ai`.
      Blog posts and course pages carry FAQ + FAQPage JSON-LD; `/course.html?slug=` now gets
      its title/description/canonical/OG/Course JSON-LD written in on the server.
      Verified live locally: outline in 6 s, ~530-word draft with 6 real internal links.
    - **Admin theme (tutor, 2026-10-01)**: light = cool white with violet/sky glow; dark =
      GRAPHITE (#121317 / #1b1c22), not navy ("the dark blue made it dull"). Violet->indigo
      gradient for the active nav item and primary buttons, tone tokens (--t-violet/teal/amber/
      rose/sky) for KPI icon badges. Tokens only - see admin.css.
    - **Deploy guide: `deploy/ADMIN_V2_DEPLOY.md`** (migrations 023/024/025, set_admin.py,
      code-only tar via /tmp/stage with `compileall` on the server's Python 3.10 first).
    - **Forms + homework + marks round (tutor feedback 2026-10-01):** `modal({size})` = md 600 /
      lg 860 / xl 1100; the body scrolls and the footer stays (`.modal-form` is a flex column with
      `min-height: 0`). The old `wide` reused `.palette` (borderless inputs) - never style modals with
      it. Homework form: drag-and-drop file upload (server checks file CONTENT matches the
      extension: `admin.content_matches`), Resources search, and "Topical paper built for each
      student" -> `POST /api/admin/students/{id}/booklets` builds a booklet OWNED by the student
      (no quota, no enrolment needed) and the assignment gets `{"type": "paper", booklet_id}`;
      static/homework.js shows it as "Open your paper" (/papers/view/{id}). Student page "Past
      papers and marks" now mirrors the student Yearly page: rings (completion / average / best /
      touched), per-paper filter, years grouped by paper, Not done / Started / Done, marks modal
      with the sitting's official thresholds (`/api/grade-thresholds`) and the grade worked out
      live (`core.gradeFor`, same rule as static/progress-shared.js).

36. **Booklet builds failing silently - root cause + fix (2026-10-01, DEPLOYED 15:00 UTC,
    commit 04e3b36; code-only, backup /srv/backup-code-20261001-1458-prefix.tgz).**
    - **Production DATABASE_URL now uses the TRANSACTION pooler, port 6543** (tutor approved;
      env backup /etc/prepwithtee.env.bak-20261001-1501). The 248 missing source PDFs below
      were uploaded the same day (service user = `prepwithtee`; some data/raw year folders
      are root-owned - extract with sudo + chmod 644).
    - **Root cause**: production logs showed 136 of 252 builds failed in the week since
      the 2026-09-27 DB pool went live; 134 were `EMAXCONNSESSION max clients reached in
      session mode - pool_size: 15`. DATABASE_URL uses Supabase's SESSION pooler (port
      5432) = 15 seats for the whole project; `website/db.py` kept up to 12 idle
      connections PER worker (2 workers = 24) and never waited, so the compose/testgen
      subprocess (its own connection) found no seat and died. The student only saw "We
      couldn't build this paper"; the cause went to journalctl. Other pages hit the same
      error (~1,400 log lines).
    - **Pool**: now a HARD cap per worker (`PG_POOL_MAX`, default 4, idle + in use), requests
      wait up to `PG_POOL_WAIT_S` (20 s) then get an unpooled connection (logged), idle
      connections close after `PG_IDLE_CLOSE_S` (120 s), `_new_conn` waits out a full
      pooler. Budget: 2 x 4 + 4 build subprocesses <= 15 - **never raise PG_POOL_MAX
      without moving to the transaction pooler (port 6543)**. `pipeline/db.connect` backs
      off up to ~60 s on a full pooler.
    - **Builds** (`booklets.py`): `_build_safely` wraps everything (the executor swallowed
      exceptions -> rows stuck 'queued'); busy/out-of-memory failures retry twice
      (`BUSY_RETRIES`); a failure stores JSON in `error` = {code, detail, skipped}; codes
      busy / interrupted / timeout / too_big / missing_source / internal map to
      `FAILURES` (title, message, retryable, attention). The student never sees `detail`.
      Status writes are retried. A row with no progress for BUILD_TIMEOUT+3 min (building)
      or 15 min (queued) is failed as `interrupted` when polled. `POST
      /api/booklets/{id}/retry` rebuilds the same ids (no quota). Questions whose original
      PDF is missing are never offered (`_source_exists` in question_pool), and
      compose/testgen print `SKIPPED <id> missing-source` and carry on instead of crashing
      (`config.source_exists`); the viewer notes how many were left out.
    - **Viewer**: failure card with cause + Try again / Change my selection (builder
      `?pick=`) / Report this problem (prefilled name+email, posts /api/feedback type
      `issue` with booklet id + cause; opens by itself for `attention` codes). A status-poll
      blip no longer ends the page (gives up after ~45 s). My papers: failed cards link to
      "See why · try again". `auth.js` `api()` no longer shows "[object Object]" for object /
      list `detail`s (all 58 references bumped to 20261001a).
    - **Missing source PDFs on the server** (2026-10-01): 129 QPs / 898 questions in the DB
      have no file under /srv/prepwithtee/data/raw (mostly 9709, 0625 P3 2010-15, the
      Feb/March 2026 papers). They are now hidden from the builder; uploading them brings
      them back automatically (10-min cache).
    - Tests: tests/api/test_booklet_failures.py, tests/e2e/test_booklet_failure.py.

37. **Booklet quota loophole + student countries (2026-10-04).**
    - Free students got a 4th booklet by clicking Build while earlier builds were still
      running (a build only counts once it succeeds). `check_quota_gate(..., pending=)` now
      adds the student's queued/building booklets (`booklets._inflight`; tutor-set papers and
      dead builds per `_fail_if_stuck`'s rule excluded), gate + insert run under a per-user
      lock, quota is recorded BEFORE the row says ready, and Retry needs room too.
      Free = **3 topical booklets + 3 mock tests a month, separate allowances** (tutor).
      Trial exists only as the admin "7-day trial" tick (nobody has one).
    - Admin Students table: country from the WhatsApp number (`website/countries.py`, ITU
      prefix table, local Pakistani formats; unplaceable = unknown, never guessed),
      "All countries" filter with counts, sortable, CSV column. DataTable `options(counts, meta)`.

38. **Keyboard shortcuts on every page (2026-10-05, local, not deployed).** `static/shortcuts.js`
    (+ `shortcuts.css`, injected) is loaded from `partials/nav.html` (stamp with `python sync_nav.py`)
    and directly on the header-less shells (messages, teacher/parent dashboards, revise - they get a
    corner ⌨ button). Header ⌨ button or `?` = panel (filterable, every row clickable, plus "On this
    page" groups for MCQ / paper viewers / pen bar / calculator). `G` then a letter = go to a page
    (`PAGES` table). `Alt`+C calculator, G graph, S formula sheet, T tools panel, P pen, H highlighter,
    X eraser - matched by `e.code` (Mac Option types characters). Tools go through
    `window.pwtDock` (tools-dock.js, now opens ANY catalogue tool; loaded on demand where a page has no
    dock), ink through `window.pwtInk` (annotate.js, newest annotator). Listener is window CAPTURE, so
    the second key of a chord never reaches the MCQ answer keys. Single-key shortcuts can be switched
    off in the panel (localStorage `pwt-keys-single-off`, WCAG 2.1.4); Alt ones stay. Avoid Alt+D/E/F
    (browser menus on Windows). Pages add rows with `pwtShortcuts.register(title, items)`.
    Tests: tests/e2e/test_shortcuts.py.

38. **Ink rail v3 + PrepWithTee Board (2026-10-05, local, not deployed).** Plan:
    `~/.claude/plans/alright-so-i-m-thinking-crispy-barto.md`; deploy steps:
    `deploy/WHITEBOARD_DEPLOY.md` (**migration 026 + data/ink_assets first**).
    - **annotate.js** = engine + a LEFT rail (`.an-bar.ink-rail`; pinned = open and pushes `.vw` over at
      >=1100 px, unpinned = `.an-tab` on the left edge; undo/redo in `.ink-rail-foot`, never scrolled
      away). Options open in `.ink-fly` beside the rail (tap an active tool again, or hold / right-click).
      `ink/color.js` (SV field, hue, opacity, hex, eyedropper, Recent + My colours), `ink/shapes.js`
      (POLY kinds, arcs, shape recognition = hold still at the end of a pen stroke), `ink/stickers.js`
      reading `ink/stickers.json` (built by `scripts/build_stickers.py`; annot_pdf embeds the same SVGs).
      New objects: pen `k` (fine/fountain/pencil/dash), `d` dashed, `fl` fill, arrow `two`, rect `rr`,
      `poly` (box `k` or explicit closed `pts`), `arc` {o, r, a0, sw}, `stk`, `note`, `img` {src}; every
      object has an `id`. Compass instrument: needle/pencil snap to ends + line/arc intersections, hinge
      turns relative to the grab point, radius lock. Instruments follow a page that gets re-rendered.
      Options `store` / `upload` / `pasteText` / `push`; attach(..., {camera:true}) = infinite canvas.
      Ctrl+V pastes images (uploaded to `/api/ink/assets`, private: owner, their teacher, a share token).
    - **Whiteboard** (`whiteboard.py`, `wb_store.py`, `static/board/` - NOT /whiteboard/* static paths,
      the editor route would swallow them): dashboard /whiteboard (guests: SEO product page on the
      site shell), editor /whiteboard/{id}, share /whiteboard/s/{token}, /whiteboard/new?q=<qid> (the
      🖊️ Whiteboard chip on every booklet question). Free = 3 live boards + 50 MB images; any paid plan
      unlimited + PDF import. Pages save with an optimistic `version` (409 -> merged by object id);
      offline saves retry and keep a localStorage draft. annot_pdf.render_board exports boards.
    - **Discovery** (tutor: "students mostly only use topical papers"): `/features` (features.py,
      every feature + one tip, FAQ JSON-LD), `static/whats-new.js` (loaded by auth.js: one spotlight
      card per announcement, one coach mark beside the rail on viewers; localStorage `pwt-wn`), nav
      "Whiteboard NEW" + Tools item + Dashboard "All features", footer links. Blog link hides in the
      header between 1201-1440 px to make room. e2e student fixture pre-marks the nudges as seen.
    - Tests: tests/api/test_whiteboard.py, tests/unit/test_annot_pdf_v3.py, tests/e2e/test_whiteboard.py,
      tests/e2e/test_ink_rail.py (+ test_annotations.py updated for the rail).

39. **Free-limit card + self-serve trial + feedback snips (2026-10-05, local, not deployed).**
    - `static/limit-card.js/.css` (loaded from `partials/nav.html` + the header-less shells) wraps
      `window.fetch`: ANY same-origin `/api/` 403/429 whose `detail.code` is `quota_exceeded` or
      `upgrade_required` opens one big card - what ran out (meter, reset date), the 7-day trial if
      the student can still have it, and the 3 plans (prices from `billing.PERIODS`). New gated
      features get it for free; send `event_type` (+ `trial`) in the detail (`ai_help._upgrade` does).
      `PWTLimit.inline(el, detail)` = small copy (builder panel). The old `upgrade-modal.js` is dead
      code (nothing calls its interceptor).
    - **Trial (tutor: instant, once per account)**: `website/upgrade.py` - `GET /api/me/offer`,
      `POST /api/me/trial` -> plan 'all', `plan_trial`, 7 days, `access.TRIAL_QUOTAS`; "once" = a
      `usage_events` row `trial_started` (no schema change). Only free-plan students.
    - **Snips**: `static/snip.js` (+ `snip.css`) renders the viewport with modern-screenshot
      (jsDelivr; NOT html2canvas - it throws on the site's color-mix()), drag-to-select overlay,
      red "Mark it" pen, JPEG <= 1600 px; falls back to getDisplayMedia, plus "Attach image".
      `snipField()` is used by the global Feedback/Report panel (main.js) and the booklet viewer's
      failure report. `/api/feedback` takes `snips` (<= 3 data: URLs, real PNG/JPEG bytes, <= 3 MB),
      stored in `data/feedback-snips/` (NOT the public /uploads mount; `FEEDBACK_SNIPS_DIR`
      overrides, tests use their temp dir), served only by `GET /api/admin/feedback/snips/{name}`,
      shown as thumbnails in the admin Inbox. **Run `website/migrations/027_feedback_attachments.sql`
      on Supabase before deploying** (save_feedback falls back to the message without it).
    - Tests: tests/api/test_limits_and_snips.py, tests/e2e/test_limit_card_snip.py.
    - **Follow-up (same day)**: navbar density pass (styles.css block "Navbar density"; header 60 px,
      .86rem links, borderless icon buttons; shortcuts button hidden < 1700 px and moved into the account
      menu; account name hidden < 1600 px; Blog hidden 1201-1520 px; sticky `.dtabs` / `.yr-bar` at 60 px;
      STYLES_V 20261005b). Broken Google avatar falls back to initials. Instruments rebuilt in one system
      (`instGeo` / `renderInst` / `edgeSnap` in annotate.js): bolder ruler (30 mm deep, 15/30 cm toggle),
      protractor (flip), new **set square** (45° or 30°/60°); pens snap to any straight edge; rotation is
      relative to the grab point; instruments re-render at true scale when the page re-renders.
