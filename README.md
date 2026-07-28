# PrepWithTee — Topical Past-Paper Engine

A Cambridge O Level / IGCSE / A Level tutoring platform built by **Muhammad Taahaa** (PrepWithTee, Lahore). The core of the project is an automated pipeline that ingests official Cambridge past-paper PDFs, slices them into per-question vector crops (never re-typeset), classifies every question by syllabus topic, and composes custom topical booklets on demand. The pipeline feeds a FastAPI website that students and parents use for past papers, resources, and an AI tutor.

**Live site:** [prepwithtee.duckdns.org](http://prepwithtee.duckdns.org)

---

## Table of Contents

1. [What this project does](#what-this-project-does)
2. [Subjects in scope](#subjects-in-scope)
3. [Repository layout](#repository-layout)
4. [Database schema](#database-schema)
5. [Pipeline — stage by stage](#pipeline--stage-by-stage)
   - [Stage 1: fetch](#stage-1-fetch)
   - [Stage 2: segment](#stage-2-segment)
   - [Stage 3: classify](#stage-3-classify)
   - [Stage 4: link\_ms](#stage-4-link_ms)
   - [Stage 5: mcq](#stage-5-mcq)
   - [Stage 6: compose](#stage-6-compose)
   - [Stage 7: testgen](#stage-7-testgen)
   - [Stage 8: validate](#stage-8-validate)
6. [Classification backends](#classification-backends)
7. [Taxonomy system](#taxonomy-system)
8. [Website architecture](#website-architecture)
9. [Running the pipeline](#running-the-pipeline)
10. [Running the website locally](#running-the-website-locally)
11. [Deployment](#deployment)
12. [Design decisions & hard-won lessons](#design-decisions--hard-won-lessons)

---

## What this project does

Cambridge past papers are distributed as flat PDFs — a question paper is one big file with no machine-readable topic tags. A student who wants to practice "Electric Circuits" has to manually search through years of papers to find the relevant questions.

This engine solves that:

1. **Fetches** every past-paper PDF and its mark scheme from a source archive.
2. **Segments** each paper into individual questions — vector-perfect region crops so every diagram, graph, dotted answer line and formula survives exactly as in the original.
3. **Classifies** each question against the official Cambridge syllabus topics using keyword heuristics, a session-based Claude classifier, or the Anthropic API.
4. **Links** each question crop to its matching mark-scheme crop.
5. **Composes** A4 topical booklets on demand: filter by topic + year range, and get a PDF with the questions in order, each mark scheme printed immediately underneath.
6. **Generates** randomised mock tests from the classified pool with a separate mark scheme file.

The result: **3,800+ classified Cambridge questions** across 12 syllabuses, all searchable by topic on the website.

---

## Subjects in scope

| Syllabus | Subject | Board | Papers | MCQ? | Status |
|----------|---------|-------|--------|------|--------|
| 5054 | Physics | O Level | P1, P2 | P1 | ✅ Complete (2020–2025) |
| 0625 | Physics | IGCSE | P1, P2, P4 | P1, P2 | ✅ Complete (2020–2025) |
| 4024 | Mathematics D | O Level | P1, P2 | — | ✅ Complete (2020–2025) |
| 0580 | Mathematics | IGCSE | P2, P4 | — | ✅ Complete (2020–2025) |
| 2210 | Computer Science | O Level | P1, P2 | — | ✅ Complete |
| 0478 | Computer Science | IGCSE | P1, P2 | — | ✅ (same papers as 2210) |
| 5070 | Chemistry | O Level | P1, P2 | P1 | In progress |
| 0620 | Chemistry | IGCSE | P1–P4 | P1, P2 | In progress |
| 9709 | Mathematics | A Level | P1, P3, P4, P5 | — | In progress |
| 9702 | Physics | A Level | P1, P2, P4, P5 | P1 | ✅ MCQ parsed |
| 9618 | Computer Science | A Level | P1–P4 | — | In progress |
| 2058 | Islamiyat | O Level | P1, P2 | — | Manual fetch |
| 2059 | Pakistan Studies | O Level | P1, P2 | — | Manual fetch |

All sessions covered: **May/Jun (s), Oct/Nov (w), Feb/Mar (m)**, all variants (e.g. 21, 22, 23).

---

## Repository layout

```
.
├── pipeline/               # One CLI module per stage, all idempotent
│   ├── config.py           # Paths, API endpoints, PAPER_MATRIX, brand colours
│   ├── db.py               # SQLite schema + connection helpers
│   ├── manifest.py         # Bucket-tree cache and query helpers
│   ├── fetch.py            # Stage 1 — download QPs and MSes
│   ├── segment.py          # Stage 2 — slice PDFs into per-question crops
│   ├── classify.py         # Stage 3 — topic classification (multi-backend)
│   ├── heuristics.py       # Keyword scorer used by the heuristic backend
│   ├── link_ms.py          # Stage 4 — match mark-scheme crops to questions
│   ├── mcq.py              # Stage 5 — parse answer letters from MCQ mark schemes
│   ├── compose.py          # Stage 6 — build topical booklets
│   ├── testgen.py          # Stage 7 — randomised mock test generator
│   └── validate.py         # Stage 8 — internal consistency checks
│
├── taxonomy/               # Official syllabus topic lists + keywords
│   ├── 5054.json           # Physics O Level — 25 topics
│   ├── 0625.json           # Physics IGCSE — 24 topics (standalone, not alias)
│   ├── 4024.json           # Maths O Level — 32 chapters + subtopics
│   ├── 0580.json           # Maths IGCSE — same structure as 4024
│   ├── 2210.json           # CS O Level — 10 topics
│   └── *.json / *.pdf      # Other syllabuses + official syllabus PDFs
│
├── website/
│   ├── app.py              # FastAPI application
│   └── static/             # All frontend assets (HTML, CSS, JS, images)
│       ├── index.html       # Home page
│       ├── papers.html      # Topical builder + yearly library
│       ├── resources.html   # Study resources browser
│       ├── subjects.html    # Subjects overview
│       ├── guide.html       # Revision study guide
│       ├── pricing.html     # Fees page
│       ├── tutor.html       # AI tutor (Groq)
│       ├── styles.css       # Design system (CSS custom properties)
│       ├── app.js           # Topical builder logic
│       ├── library.js       # Yearly papers library
│       ├── resources.js     # Resources browser + search
│       └── tutor.js         # AI tutor chat
│
├── deploy/
│   ├── Caddyfile           # Reverse proxy config (HTTPS, www redirect)
│   ├── prepwithtee.service # systemd unit for gunicorn
│   ├── sync.sh             # rsync-based deploy script (Linux/Mac)
│   └── sync_windows.py     # tar+SSH deploy script (Windows)
│
├── scratchpad/             # One-off processing scripts (MCQ classification, etc.)
├── logos/                  # Brand logo variants
├── requirements.txt
├── .gitignore              # Excludes data/, .venv/, .env, *.xlsx
└── CLAUDE.md               # Full project context for Claude Code sessions
```

### What is NOT in this repo (gitignored)

```
data/
├── raw/{syllabus}/{year}/      # ~2 GB of original Cambridge PDFs
├── crops/{paper_key}/          # Per-question vector crops (qNN.pdf)
├── debug/{paper_key}/          # Visual-check PNGs (qNN.png), regenerated each segment run
├── batches/                    # Classification batch JSON files
├── output/                     # Composed topical booklets
└── index.db                    # SQLite database (~70 MB)
```

---

## Database schema

Single SQLite file at `data/index.db`. Schema is Postgres-portable (plain types, no SQLite-isms).

```sql
papers (
  id          TEXT PRIMARY KEY,   -- e.g. '5054_s25_qp_22'
  syllabus    TEXT,               -- '5054'
  year        INTEGER,            -- 2025
  session     TEXT,               -- 's' | 'w' | 'm'
  paper       INTEGER,            -- 2
  variant     TEXT,               -- '2'
  kind        TEXT,               -- 'qp' | 'ms'
  filename    TEXT,               -- '5054_s25_qp_22.pdf'
  rel_path    TEXT,               -- relative path under data/raw/
  page_count  INTEGER,
  fetched_at  TEXT
  UNIQUE(syllabus, year, session, paper, variant, kind)
)

questions (
  id          INTEGER PRIMARY KEY,
  paper_id    TEXT REFERENCES papers(id) ON DELETE CASCADE,
  number      INTEGER,            -- question number in the paper
  text        TEXT,               -- extracted text (for heuristics + search)
  marks       INTEGER,
  crop_path   TEXT,               -- relative path to the per-question PDF crop
  debug_png   TEXT,               -- relative path to the visual-check PNG
  rects_json  TEXT,               -- [{page, x0, y0, x1, y1}, ...] raw region coords
  status      TEXT                -- 'segmented' | 'classified' | 'review' | 'excluded'
  UNIQUE(paper_id, number)
)

classifications (
  question_id INTEGER PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
  topic       TEXT,               -- e.g. 'Electric circuits'
  secondary_topic TEXT,           -- runner-up topic (nullable)
  difficulty  INTEGER,            -- 1–3 (nullable)
  confidence  REAL,               -- 0.0–1.0
  rationale   TEXT,               -- why this topic was assigned
  backend     TEXT,               -- 'heuristic' | 'session' | 'api' | 'tracker'
  classified_at TEXT
)

ms_entries (
  id              INTEGER PRIMARY KEY,
  paper_id        TEXT REFERENCES papers(id) ON DELETE CASCADE,
  question_number INTEGER,
  crop_path       TEXT,
  rects_json      TEXT,
  answer          TEXT            -- populated by mcq.py for multiple-choice papers
)

review_queue (
  question_id INTEGER REFERENCES questions(id) ON DELETE CASCADE,
  reason      TEXT,
  created_at  TEXT,
  resolved    INTEGER DEFAULT 0
)
```

**Paper key** convention: `{syllabus}_{session}{YY}_{code}` — e.g. `5054_s25_22` for Physics O Level May/Jun 2025 Paper 22.

---

## Pipeline — stage by stage

### Stage 1: fetch

```bash
python -m pipeline.fetch --syllabus 5054 --from 2020 --to 2025
python -m pipeline.fetch --syllabus 5054 --from 2020 --to 2025 --refresh-manifest
```

**What it does:**
- Loads `data/manifest.json` — a cached JSON tree of the entire source archive (~4 MB). Use `--refresh-manifest` to re-download it.
- Filters the tree by the `PAPER_MATRIX` entry for the syllabus to find QP and MS filenames.
- Resolves each file via the PDF API (`GET /api/pdf?path=...` → signed GCS URL, valid ~1 hour).
- Downloads the file if not already on disk (idempotent: skips files where `os.path.getsize > 0`).
- Records each file in the `papers` table.
- Respects a 2-second rate limit between requests (`REQUEST_DELAY_S`).

**Source API:**
- `GET https://papers.fastpapers.uk/api/bucket` → full archive tree
- `GET https://papers.fastpapers.uk/api/pdf?path=<encoded>` → `{"url": "<signed GCS URL>"}`
- The API signs any path without checking existence — only the bucket tree tells you what exists.

---

### Stage 2: segment

```bash
python -m pipeline.segment --syllabus 5054
python -m pipeline.segment --syllabus 5054 --only 5054_s25_qp_22
```

**What it does:**
- Opens each QP PDF with PyMuPDF.
- Detects question anchors: numeric spans at a consistent left-margin x-position (x < 60 pts), forming an ascending 1, 2, 3… sequence.
  - Position-based detection, NOT bold-based (Oct/Nov papers are not bold).
  - Sub-parts `(a)`, `(b)(ii)` are excluded (parenthesised, not at anchor x).
  - The "anchor x" is learned per-document as the modal x of numeric line-start spans.
- Computes the bounding region: from anchor top to the next anchor top (or end-of-content).
- Page-spanning questions get multiple rects; crops are stitched vertically using `page.show_pdf_page()` — **no rasterisation, always vector-perfect**.
- Skips cover/instructions pages and trailing blank pages.
- Pages with no text layer are flagged to `review_queue` — never silently OCR'd.
- Writes per-question PDF crops to `data/crops/{paper_key}/qNN.pdf`.
- Writes mandatory debug PNGs to `data/debug/{paper_key}/qNN.png` (regenerated on every run).
- Inserts/updates rows in the `questions` table.
- Logs sanity checks: contiguous numbering, no zero-height rects, last Q number vs expected.

**Hard-won lessons:**
- 2023-era mark scheme pages carry `rotation=90` — call `remove_rotation()` before any coordinate work.
- Question numbers can be merged with first text line (e.g. `10(a)`) — the anchor regex handles this.
- Re-segmenting a paper **deletes and re-inserts** all its question rows. Because `classifications` has `ON DELETE CASCADE`, any existing classification is wiped. Always finish segmenting ALL years before classifying.

---

### Stage 3: classify

```bash
python -m pipeline.classify --syllabus 5054 --backend heuristic
python -m pipeline.classify --syllabus 5054 --backend session --prepare
python -m pipeline.classify --syllabus 5054 --backend session --ingest data/batches/5054_results.json
python -m pipeline.classify --syllabus 5054 --backend api
```

**What it does:**
- Reads all unclassified questions for the syllabus.
- Dispatches to the chosen backend (see [Classification backends](#classification-backends)).
- Writes a row to `classifications` for each question.
- Questions with `confidence < 0.8` are added to `review_queue`.
- Already-classified questions are skipped unless `--force` is passed.

---

### Stage 4: link\_ms

```bash
python -m pipeline.link_ms --syllabus 5054
```

**What it does:**
- For each mark scheme PDF, applies the same anchor-detection logic as `segment` (MS table cells act as anchors).
- Matches each MS question number to the corresponding QP question via `(paper metadata, number)`.
- Writes rows to `ms_entries` with the crop path and region coords.
- Questions with no MS match are flagged to `review_queue`.
- MS headers are centered, answers are numeric — the table's vertical border lines are used to locate the Question column (not text matching).

---

### Stage 5: mcq

```bash
python -m pipeline.mcq --syllabus 9702 --paper 1
```

**What it does (MCQ papers only):**
- Opens each mark scheme in `MCQ_PAPERS` (the set of `(syllabus, paper)` pairs that are multiple choice).
- Parses the answer letter from the Question/Answer/Marks table using the regex `(\d{1,2})\s+([A-D])\s+1`. The trailing `1` (the mark) is essential — it excludes page headers like `9702/11` and `Page 2 of 3`.
- Stores the letter in `ms_entries.answer`.
- Also sets `questions.marks = 1` for MCQ questions (they have no `[1]` bracket in the question text).

---

### Stage 6: compose

```bash
python -m pipeline.compose --syllabus 5054 --topic "Electric circuits" --from 2020 --to 2025
python -m pipeline.compose --syllabus 4024 --topic "Trigonometry" --from 2020 --to 2025 --out my_booklet.pdf
python -m pipeline.compose --syllabus 0625 --topic "Forces" --no-ms
```

**What it does:**
- Queries the classified questions matching the topic/year/syllabus filter.
- Orders by year → session → paper → question number.
- Lays question crops onto A4 pages with consistent margins (scale-to-width, no mid-crop page breaks unless the crop is taller than a full page).
- Immediately after each question, stamps the mark scheme crop (unless `--no-ms`).
- **MCQ questions** get no inline MS crop — instead, the answer letter is collected and printed in a grid at the back. A fill-in bubble sheet is inserted on page 2.
- Each question carries a header: **Q3** `[5054/22/M/J/25 Q6 · 8 marks]`.
- **Cover page:** cream background, PrepWithTee logo, gold rule, topic title, year range, question count, total marks, Cambridge source list.
- **Watermark:** every body page carries a faint PrepWithTee owl watermark, pre-blended onto white in Python at `WM_STRENGTH = 0.12` (pure alpha channels cause premultiplication bugs in PyMuPDF — pre-blending is the reliable route).
- Output goes to `data/output/`.

---

### Stage 7: testgen

```bash
python -m pipeline.testgen --syllabus 0625 --topics "Forces,Momentum" --count 6
python -m pipeline.testgen --syllabus 4024 --topics "Trigonometry" --marks 20 --seed 42
```

**What it does:**
- Same as compose, but picks a **random subset** from the matching questions.
- `--count N`: pick exactly N questions. `--marks M`: fill up to M total marks.
- `--seed`: makes the selection reproducible.
- Produces **two files**: the test paper and a separate mark-scheme file. Students sit the paper without seeing answers; the scheme uses the same Q1/Q2/… numbering so it lines up exactly.
- Mixed MCQ + structured selections are handled per-question: structured questions get an inline MS, MCQ ones go to the answer grid at the back.

---

### Stage 8: validate

```bash
python -m pipeline.validate --syllabus 5054
```

**What it does (internal consistency only — no external tracker):**
- Checks every segmented question has a crop file on disk.
- Checks every classified question has a valid topic in its syllabus taxonomy.
- Checks every QP question has an MS entry linked.
- Reports open `review_queue` items.
- Does NOT compare against any Excel spreadsheet — classification authority is the official syllabus alone.

---

## Classification backends

All backends emit the same record: `{topic, secondary_topic|null, difficulty 1–3|null, confidence 0–1, rationale}`.

### heuristic (keyless, always available)

Keyword/phrase lists per topic in `taxonomy/*.json`. Scores are summed over the full question text (all sub-parts). The best-scoring topic wins; the runner-up becomes `secondary_topic` when its score is a significant fraction of the winner's. Confidence is derived from the score margin — deliberately conservative so ambiguous questions land in `review_queue`. No API key required.

### session (keyless, recommended for bulk classification)

1. `--prepare` exports pending questions + the valid topic list to `data/batches/{syllabus}_questions.json`.
2. Open a Claude Code session, read the batch, write `{syllabus}_results.json` with your classifications.
3. `--ingest` validates the results and loads them as authoritative labels.

Zero API cost. The incremental ingest means a context limit never loses work — prepare → classify a chunk → ingest → repeat.

### api (Anthropic API)

Uses Claude Haiku with prompt caching (taxonomy in the cached system prompt). Image + text per question, strict-JSON response. Requires `ANTHROPIC_API_KEY` in `.env`. The SDK is lazy-imported so the key/package is not needed for other backends.

---

## Taxonomy system

Each syllabus has a `taxonomy/{syllabus}.json`:

```json
{
  "syllabus": "5054",
  "topics": [
    {
      "name": "Electric circuits",
      "keywords": ["resistor", "e.m.f.", "potential difference", "series", "parallel", "ammeter", ...]
    },
    ...
  ]
}
```

**Key points:**
- Topic names are taken verbatim from the official Cambridge syllabus PDFs (stored in `taxonomy/*.pdf`).
- 5054 and 0625 have **diverged** in the 2026–2028 syllabuses — `0625.json` is a standalone file, not an alias.
- 4024 and 0580 share the same chapter structure (derived from the tutor's own breakdown), with 4024 being the authority.
- Maths taxonomies have 32 chapters and subtopics including YouTube revision links per subtopic.
- Excluded from classification: Loci and Matrices (removed from 4024/0580 2026–2028 syllabus).

---

## Website architecture

**Backend:** FastAPI (`website/app.py`) served by gunicorn, proxied by Caddy (HTTPS).

**Key API routes:**

| Route | Description |
|-------|-------------|
| `GET /api/papers` | List available syllabuses, topics, year ranges |
| `POST /api/compose` | Generate a topical booklet — returns a streaming PDF |
| `POST /api/testgen` | Generate a randomised mock test |
| `GET /api/library/tree/{syllabus}` | Yearly paper tree for the library view |
| `GET /api/library/pdf/{id}` | Serve a specific paper or mark scheme PDF |
| `GET /api/resources` | Resource categories and file tree |
| `GET /api/resources/file` | Serve a resource file |
| `POST /api/ask` | AI tutor chat (proxied to Groq) |

**Frontend pages:**

| Page | Description |
|------|-------------|
| `index.html` | Landing page — hero, stats, tutor bio, testimonials, pricing comparison |
| `papers.html` | Two-mode viewer: **Topical Builder** (filter by subject/topic/year → compose PDF) and **Yearly Library** (browse all papers by year/session) |
| `resources.html` | Study resource browser with full-text search across all categories and files |
| `subjects.html` | All subjects with live/coming-soon status for each |
| `tutor.html` | AI chat tutor powered by Groq |
| `guide.html` | Structured Cambridge exam revision guide |
| `pricing.html` | Fee breakdown with comparison table |

**Design system:** CSS custom properties in `styles.css` — `--navy`, `--gold`, `--page`, `--ink`, `--green`, `--lav`, `--pink`, `--teal` etc. Responsive down to 375px mobile. Dark-mode aware.

**Chatbot:** Botpress widget embedded on all pages.

---

## Running the pipeline

### Prerequisites

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt   # Windows
# OR
.venv/bin/pip install -r requirements.txt        # Linux/Mac
```

### Typical workflow for a new syllabus

```bash
# 1. Fetch all papers (QP + MS)
.venv\Scripts\python -m pipeline.fetch --syllabus 0625 --from 2020 --to 2025

# 2. Segment one paper first — visually check debug PNGs before bulk run
.venv\Scripts\python -m pipeline.segment --syllabus 0625 --only 0625_s25_qp_42
# → open data/debug/0625_s25_42/ and verify the crops look correct

# 3. Segment all papers for this syllabus
.venv\Scripts\python -m pipeline.segment --syllabus 0625

# 4. Link mark schemes
.venv\Scripts\python -m pipeline.link_ms --syllabus 0625

# 5. For MCQ papers only — parse answer letters
.venv\Scripts\python -m pipeline.mcq --syllabus 0625 --paper 1
.venv\Scripts\python -m pipeline.mcq --syllabus 0625 --paper 2

# 6a. Heuristic pre-pass (fast, conservative — for review/preview)
.venv\Scripts\python -m pipeline.classify --syllabus 0625 --backend heuristic

# 6b. Session classify (authoritative)
.venv\Scripts\python -m pipeline.classify --syllabus 0625 --backend session --prepare
# → fill data/batches/0625_results.json in a Claude Code session
.venv\Scripts\python -m pipeline.classify --syllabus 0625 --backend session --ingest data/batches/0625_results.json

# 7. Validate
.venv\Scripts\python -m pipeline.validate --syllabus 0625

# 8. Compose a test booklet
.venv\Scripts\python -m pipeline.compose --syllabus 0625 --topic "Forces" --from 2020 --to 2025
```

> **Critical:** Finish segmenting ALL year ranges before classifying. Re-segmenting a paper deletes all its question rows (CASCADE), wiping any existing classifications.

---

## Running the website locally

```bash
cd website
..\.venv\Scripts\python -m uvicorn app:app --reload --port 8017
# → http://localhost:8017
```

---

## Deployment

**Server:** Oracle Cloud (Ubuntu), IP `161.118.190.49`, domain via DuckDNS.

**Stack:** gunicorn → FastAPI → Caddy (HTTPS + www redirect).

```bash
# Deploy static files + app (Windows)
python deploy/sync_windows.py ubuntu@161.118.190.49

# Or individual files via scp
scp -i C:\Users\user\ssh\ssh-key-2026-07-22.key website/static/*.html website/static/styles.css ubuntu@161.118.190.49:/srv/prepwithtee/website/static/

# Restart service after app.py changes
ssh -i C:\Users\user\ssh\ssh-key-2026-07-22.key ubuntu@161.118.190.49 "sudo systemctl restart prepwithtee"
```

**Service file:** `deploy/prepwithtee.service` (systemd)
**Reverse proxy:** `deploy/Caddyfile`
**Project root on server:** `/srv/prepwithtee/`

---

## Design decisions & hard-won lessons

| Decision | Reason |
|----------|--------|
| Vector crops via `page.show_pdf_page()`, never rasterise | Diagrams, dotted answer lines, and circuit symbols must survive perfectly — no pixel artifacts |
| SQLite, Postgres-portable schema | Simple to run locally; ready to migrate to Supabase later without schema rewrites |
| Position-based anchor detection (x < 60), not bold-based | Oct/Nov papers use non-bold question numbers — bold detection silently misses them |
| Debug PNGs regenerated on every segment run | Non-negotiable visual gate; no silent bad crops |
| No OCR on pages with no text layer | Flag to `review_queue` instead — OCR errors in a question crop corrupt the classification |
| Pre-blend watermark onto white in Python | PyMuPDF `Pixmap.set_alpha()` premultiplies colour samples (cream → near-black); pre-blending is reliable |
| Mark schemes immediately after each question in composed PDFs | Tutor's explicit instruction — students check their working question by question, not at the end |
| MCQ answer letters → grid at back + bubble sheet on page 2 | Inline MS crops spoil the answer and look wrong for MCQ; bubble sheet can be detached |
| Classify AFTER full year-range segmentation | `ON DELETE CASCADE` on `classifications` — re-segmenting any paper wipes its classifications |
| Session classify before heuristic pre-pass | `--prepare` only exports questions not yet in `classifications`; running heuristic first empties the export queue |
| 5054 and 0625 are separate taxonomy files | They diverged in 2026–2028 syllabuses — 0625 is no longer an alias of 5054 |
| Loci + Matrices excluded (not just untagged) | Officially removed from 4024/0580 2026–2028 syllabus; `status='excluded'` prevents them appearing in any composed output |

---

## Author

**Muhammad Taahaa** — CS graduate (FAST University), Cambridge specialist tutor, Lahore.
[nexgentutors6@gmail.com](mailto:nexgentutors6@gmail.com) · [+92 320 488 4375](https://wa.me/923204884375) · [prepwithtee.duckdns.org](http://prepwithtee.duckdns.org)
