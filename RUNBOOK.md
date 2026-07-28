# Runbook — how to drive the pipeline yourself

Everything runs from `E:\NexGen Tutors Topicals` in PowerShell. Every stage is
re-runnable and skips work already done, so if a session dies mid-way you just
run the same command again.

## The one thing to understand first

Four stages are **plain commands you run**: `fetch`, `segment`, `link_ms`,
`compose`. One stage is **not**: `classify` needs a model (me) to read each
question and decide its topic. There is no command that classifies well on its
own. So the workflow is:

- **You** can fetch papers, cut them into questions, link mark schemes, and
  build topical PDFs — all without me.
- **I** do the classification step (read the questions, assign topics). This is
  the part that eats a session, so it's the part to hand to me.

---

## Status right now

| Subject | Code | Fetched | Segmented | MS linked | Classified | Compose-ready |
|---|---|---|---|---|---|---|
| Maths O | 4024 | done | done | done | **done** | yes |
| Maths IGCSE | 0580 | done | done | done | **done** | yes |
| Physics O | 5054 | done | done | done | **done (2020–25)** | yes |
| Physics IGCSE | 0625 | done | done | done | **done (2020–25)** | yes |
| A Level Maths | 9709 | fetching (P1 P3 M1 S1) | — | — | — | no |
| A Level Physics | 9702 | pending | — | — | — | no |
| Computer O | 2210 | done | — | — | — | no |
| Computer IGCSE | 0478 | done | — | — | — | no |

9709 fetch started 2026-07-21 (all years 2015–2025). Once it lands, segment
→ link_ms → classify → difficulty. Then 9702 the same way. Computer Science
still needs the same steps.

**Scope for 9709:** P1 (Pure 1), P3 (Pure 3), M1 (Paper 4), S1 (Paper 5).
**Scope for 9702:** P1 (MCQ – no MS crops), P2 (AS), P4 (A2), P5 (Planning).

---

## The five stages

### 1. fetch — download papers
```
# Standard papers:
python -m pipeline.fetch --syllabus 9709 --from 2020 --to 2025
# Include examiner reports (for difficulty classification):
python -m pipeline.fetch --syllabus 9709 --from 2020 --to 2025 --er
# Syllabus PDFs:
python -m pipeline.fetch --syllabus 9709 --syllabus-docs
```
Flags: `--syllabus` (required), `--paper N` (repeatable; default = all papers
per PAPER_MATRIX), `--from YEAR`, `--to YEAR`, `--sessions s,w,m`,
`--refresh-manifest`, `--syllabus-docs`, `--er`.

### 2. segment — cut each paper into per-question crops + debug PNGs
```
# ALWAYS verify one paper first and LOOK at its debug PNG before bulk:
python -m pipeline.segment --syllabus 0478 --only 0478_s25_qp_22
# then the whole subject:
python -m pipeline.segment --syllabus 0478
```
Flags: `--syllabus` (required), `--paper N`, `--year YEAR`, `--only <key>`.
Debug PNGs land in `data\debug\<paper_key>\`. **Open a few** — this is where
layout problems show up (Computer Science has code listings, which is new).

### 3. link_ms — attach mark schemes to the questions
```
python -m pipeline.link_ms --syllabus 0478
```
Flags: same shape as segment (`--syllabus`, `--paper`, `--year`, `--only`).

### 4. classify — assign a topic to each question  ← THE STEP THAT NEEDS ME
Rough first pass you can run (keyword guess, flags most for review):
```
python -m pipeline.classify --syllabus 9709 --backend heuristic
```
The good pass is the `session` backend, which is me reading a digest of the
questions and writing topic JSON that gets ingested. You don't run this alone —
you ask me: *"classify A Level Maths 9709."*

### 4b. difficulty — classify question difficulty from examiner reports
Run AFTER classify. Requires ERs fetched with `--er` first.
```
# Fetch ERs:
python -m pipeline.fetch --syllabus 9709 --from 2020 --to 2025 --er
# Dry run (no DB writes, just prints what it finds):
python -m pipeline.difficulty --syllabus 9709 --from 2020 --to 2025 --dry-run
# Write difficulty values:
python -m pipeline.difficulty --syllabus 9709 --from 2020 --to 2025
```
This parses Cambridge examiner reports to find which questions students found
hardest (difficulty=3), easiest (difficulty=1), or average (difficulty=2).

### 5. compose — build a topical PDF (run this yourself any time)
```
python -m pipeline.compose --syllabus 0625 --topics "Momentum" --from 2020 --to 2025
```
Flags:
- `--syllabus` (required)
- `--topics "A,B,C"` (required, **comma-separated**, exact topic names — note
  it's `--topics`, plural, not `--topic`)
- `--from YEAR`, `--to YEAR`
- `--paper N`, `--variant N` (e.g. `--paper 4`, `--variant 42`)
- `--no-ms` (leave the mark schemes out)
- `--out path.pdf` (default: `data\output\<syllabus>_<topic>_<years>.pdf`)

Output goes to `data\output\`. The mark scheme follows each question by default.

To see the exact topic names for a subject:
```
python -c "import json; print('\n'.join(t['name'] for t in json.load(open('taxonomy/0625.json',encoding='utf-8'))['topics']))"
```

### 6. testgen — build a mock TEST + a SEPARATE mark-scheme file
```
python -m pipeline.testgen --syllabus 0625 --topics "Forces,Momentum" --count 6 --seed 7
```
Works for **every subject in the pipeline** (4024, 0580, 5054, 0625 today;
any future subject automatically once classified). Picks a **random** subset
(not every question) and writes **two** files: the test paper (blank answer
spaces, no answers) and `..._ms.pdf` (the answers), numbered so Q1 in the
test = Q1 in the scheme. Every page of every generated PDF (topicals and
tests alike) carries the faint PrepWithTee owl watermark behind the content —
no flag needed, it's automatic.
Flags:
- `--syllabus`, `--topics "A,B"` (required, same as compose)
- `--count N` — number of questions (default 6), **or**
- `--marks M` — instead of count, keep adding questions until the total marks
  reach ~M
- `--seed N` — fix the random pick so you get the same paper again
- `--from`, `--to`, `--paper`, `--variant` — same filters as compose
- `--out name.pdf` — base name; `_ms` is added for the scheme

---

## Recipes you'll actually use

**A Physics topical, one topic, recent years:**
```
python -m pipeline.compose --syllabus 5054 --topics "Radioactivity" --from 2023 --to 2025
```

**Several related topics in one booklet:**
```
python -m pipeline.compose --syllabus 0625 --topics "Radioactivity,Nuclear model of the atom" --from 2020 --to 2025
```

**Just one paper/variant:**
```
python -m pipeline.compose --syllabus 5054 --topics "Forces" --paper 2 --variant 22
```

**Questions only, no mark schemes:**
```
python -m pipeline.compose --syllabus 0625 --topics "Light" --no-ms
```

**A 40-mark timed mock on one topic, answers in a separate file:**
```
python -m pipeline.testgen --syllabus 5054 --topics "Electric circuits" --marks 40 --seed 3
```

**The same mock again, identical questions:** re-run with the same `--seed`.
A different `--seed` (or none) gives a fresh random pick.

---

## Doing A Level Maths 9709 — the order

Papers are fetching (P1 P3 M1 S1, all sessions 2015–2025). Once the download
completes (takes ~90 min total):

1. Spot-check one paper from each component:
   ```
   python -m pipeline.segment --syllabus 9709 --only 9709_s25_qp_11
   python -m pipeline.segment --syllabus 9709 --only 9709_s25_qp_31
   python -m pipeline.segment --syllabus 9709 --only 9709_s25_qp_41
   python -m pipeline.segment --syllabus 9709 --only 9709_s25_qp_51
   ```
   Open `data\debug\9709_s25_{11|31|41|51}\` — check question numbers and
   boundaries. A Level maths usually has 8–10 questions per paper.

2. If PNGs look good, bulk segment 2020–2025:
   ```
   python -m pipeline.segment --syllabus 9709 --from 2020 --to 2025
   ```

3. Link mark schemes:
   ```
   python -m pipeline.link_ms --syllabus 9709 --from 2020 --to 2025
   ```

4. Heuristic pre-classify (runs offline, ~80% lands in review):
   ```
   python -m pipeline.classify --syllabus 9709 --backend heuristic
   ```

5. Tell me *"session-classify 9709"* — I'll read the review queue digest and
   write the final classifications JSON.

6. Fetch and apply difficulty from examiner reports:
   ```
   python -m pipeline.fetch --syllabus 9709 --from 2020 --to 2025 --er
   python -m pipeline.difficulty --syllabus 9709 --from 2020 --to 2025
   ```

7. Test it works:
   ```
   python -m pipeline.testgen --syllabus 9709 --topics "P1 Differentiation,P1 Integration" --marks 50
   ```

**Then do the same sequence for 9702**, starting with a 9702 fetch:
```
python -m pipeline.fetch --syllabus 9702 --from 2020 --to 2025
python -m pipeline.fetch --syllabus 9702 --from 2020 --to 2025 --er
```

---

## Doing Computer Science (2210, 0478) — the order

Papers are already fetched. Remaining steps:

1. `python -m pipeline.segment --syllabus 2210 --only 2210_s25_qp_22`
   → **open the debug PNG** in `data\debug\`. Code listings are a new layout;
   confirm question numbers and boundaries look right before bulk.
2. Repeat the one-paper check for `0478`.
3. If the PNGs look right: `python -m pipeline.segment --syllabus 2210` then
   `--syllabus 0478`.
4. `python -m pipeline.link_ms --syllabus 2210` and `--syllabus 0478`.
5. Ask me to classify each (the session step).
6. Then `compose` works for Computer Science exactly like Physics.

If a debug PNG looks wrong at step 1, **stop and tell me** — segmentation needs
a code-tweak, not a re-run.

---

## Gotchas (learned the hard way)

- **Don't classify before all the years you want are segmented.** Re-segmenting
  a paper deletes and re-inserts its questions, and that cascade-deletes their
  classifications. Segment the full year range first, then classify once.
- **pymupdf must be installed** (`python -c "import fitz"` should print a
  version). If it errors: `python -m pip install pymupdf`.
- **`--topics` is plural and comma-separated.** `--topic "Light"` fails;
  `--topics "Light"` works.
- **Check per-subject review counts** with
  `python -m pipeline.validate --syllabus 0625` — "open review items" are
  deliberate low-confidence flags, not errors.
