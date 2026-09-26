# PrepWithTee — Improvements Plan (Sept 2026)

Status: **PLAN, nothing built yet.** Covers the 16 requested improvements, ranked,
with DB / endpoint / frontend / routing changes and a test plan per module.
Stack stays **FastAPI + vanilla HTML/JS/CSS** (no Next.js migration) — we
improvise within it.

Visual mockups of the new routes/pages:
https://claude.ai/artifact/NFEwqkcYXzgg2wuRGnXy1b

---

## 0. Decisions already made (from our Q&A, 2026-09-24)

| Topic | Decision |
|---|---|
| Subject lock 🔒 | **Enrolling is free.** Lock = "not enrolled yet". One click enrols. Plan quotas still cap how many papers/AI calls they can use. |
| Boards | **Multiple boards per student** (e.g. O Level + A Level). Picker shows a tab per chosen board. |
| AI for explain/hint/follow-up | **Claude, cached per question.** One official explanation per question, generated once, reused for every student. Follow-ups billed per message. |
| Landing + guide videos | **Animated HTML "video"** — real site screenshots in a CSS iPad frame, scripted pan/zoom/cursor/captions. No MP4 hosting. |
| SEO pages (logged out) | **Landing text only** — description text public & indexable; no question images. Building papers, AI, tracking need login + enrolment. |
| Where a built paper opens | **New page with shareable URL** `/papers/view/<id>` — viewer + AI side panel + annotation bar; download is a button. |
| Pick limit | **Max 4 chapters, no subtopic cap** inside them. |
| Test DB | **Separate Supabase staging project**, `.env.test`. |
| AI Tutor vs Solver | **Solver does both modes**: "Solve this question" (photo → worked solution) and "Check my working" (photo of student's working → marks + where marks were lost). Tutor = ChatGPT-style concept chat. |
| MCQ solver gaps | Real exam-paper look, timer + review mode, explanations in the shared side panel, mobile layout — **plus "Something else" (you ticked it but left no text — please tell me).** |

---

## 1. What I found in the codebase (facts the plan is built on)

- **Backend**: `website/app.py` (4.3k lines, FastAPI) + routers `auth`, `users`,
  `admin`, `teacher`, `blog`, `flashcards`. Static pages are served by
  `app.mount("/", StaticFiles(...))` — every page is a flat `*.html` file, so
  there are **no clean URLs** today (bad for SEO).
- **DB**: dual mode (`website/db.py`) — Supabase Postgres when `DATABASE_URL` is
  set, else `data/index.db`. **Your local `.env` has `DATABASE_URL` set → local
  runs hit the LIVE database today.** Must fix before any testing (Phase 0).
- **Tests**: none exist. No pytest, no Playwright installed.
- **Topical papers** (`papers.html` + `app.js`): `/api/generate` runs
  `pipeline.compose` in a subprocess *synchronously* and streams a download
  (`a.download = name`). No in-site viewer, no loader stages, questions are
  ordered by sitting (`ORDER BY p.year DESC, p.session…`) → topic 1's questions
  cluster, never mixed.
- **Yearly + MCQ** are tabs inside `papers.html` (`data-tab="yearly|mcq"`);
  `library.html` is only a redirect stub to `papers.html?tab=yearly`.
- **Boards**: hard-coded `BOARDS` list in `app.py`; `profiles` has **no board
  column**; `enrollments(user_id, syllabus, status)` exists.
- **AI**: Groq is primary for chat (`_chat_complete`, gpt-oss-120b / qwen vision),
  Anthropic is used only in `/api/solve` (`claude-sonnet-4-6`). MCQ explanations
  are cached in `mcq_explanations(q_key, html, provider)`.
- **Tutor**: `tutor_sessions(title, subject, topic, mode…)`; titles are the subject
  code. `ask.html` redirects to `tutor.html?tab=solver` (solver is a tab).
- **Annotation**: `annotation-toolbar.js` — laser, pen, highlighter, line, arrow,
  rect, ellipse, eraser (screen overlay, skips iframes → it cannot draw on the
  yearly PDF iframe). `pdf_annotations` table exists.
- **Graph plotter** (`tools-graph.js`): expression → `new Function`. Concrete bugs:
  `-x^2` becomes `-x**2` which is a **JS SyntaxError**; whitespace is stripped so
  `sin x` → `sinx` (ReferenceError); `x(x+1)` → calls `x` as a function;
  `2^-1`, `|x|`, `sin^2(x)`, `log_2(x)` unsupported; errors shown are raw JS messages.
- **Calculator** (`tools-calculator.js`): history is an in-memory array capped at
  12, memory `state.mem` — **both lost on reload**, nothing saved per account.
- **Notes**: `notes-content/manifest.json` + hand-written HTML per subtopic, only
  0625 (partial), 2058, 4024 (3 notes). `notes-view.html` is a single page.

### Root cause of #5 (2010-2019 mark schemes "missing")

The crops **were made** and are linked locally — they were **never synced to
Supabase**:

| | Local `index.db` | Supabase (prod) |
|---|---|---|
| `ms_entries` for 2010-19 | ~16,400 | **223** |
| MCQ answer letters 2010-19 | ~10,600 | **0** |

So the MCQ solver shows no key for any 2010-19 question, and topical PDFs have
no MS for those years. Separately, the pre-2020 linker is weak on some
structured papers (prose-style mark schemes, CLAUDE.md item 19b):

| Syllabus (2010-19) | Linked | | Syllabus | Linked |
|---|---|---|---|---|
| 9709 structured | **31%** | | 0478 | 60% |
| 9702 structured | **33%** | | 2210 | 60% |
| 5054 structured | **29%** | | 0620 structured | 60% |
| 2058 | 58% | | 0580 | 73% |
| MCQ (all) | 77-83% | | 4024 | 85% |

---

## 2. Priority ranking (the order we build in)

Principle: **fix data → build test harness → foundation (routes/boards) → core
paper experience → AI layer → tools polish → marketing videos last** (videos
show the final UI, so recording them earlier means re-recording).

| Rank | Item(s) | Why here | Size |
|---|---|---|---|
| **P0-a** | **Test harness + staging DB** (prereq for your "nothing live until tested") | Every later module depends on it; also stops local dev writing to prod | M |
| **P0-b** | **#5** Old mark schemes + MCQ keys | Pure data bug, huge visible value, root cause known | S (sync) + L (parser) |
| **P0-c** | **#8** PDF layout: clipping, blank pages, clickable contents | Core product quality; every paper a student builds today is affected | M |
| **P1-a** | **#2** Boards + subject catalogue + free enrol/lock + clean SEO routes | Foundation for #3, #9, #13 | L |
| **P1-b** | **#3** Topical builder v2 (chapter→subtopic, ≤4 chapters, counts, max-Q, shuffle) + viewer page with loader | The main product | L |
| **P1-c** | **#4 + #6** AI side panel: Explain / Hint (guide-me) / follow-up / select-to-ask — one component for topical AND MCQ | Built once, used by #3, #6, #7 | L |
| **P1-d** | **#9** Yearly papers + MCQ solver as their own pages/routes | Mostly moving code out of tabs; unblocks #7 | M |
| **P1-e** | **#7** MCQ solver paper view (exam look, timer, review, mobile) | Builds on #9 + #6 | M |
| **P2-a** | **#12** Annotation bar redesign (floating, neat; pen/marker/ink/highlighter/eraser/ruler/protractor/text) — **must work on the PDF viewer** | Viewer from #3 needs it | M |
| **P2-b** | **#14** Graph plotter parser fixes | Quick win, isolated | S |
| **P2-c** | **#15** Calculator memory + history per account | Quick win, isolated | S |
| **P2-d** | **#13** Notes: per-subject SEO routes, subject cards → chapter breakdown → notes pages (scaffold for all subjects) | Content framework; content added over time | M |
| **P2-e** | **#10 + #11** AI Tutor ChatGPT-style redesign + separate Solver page | Standalone; reuses streaming + panel pieces from #4 | L |
| **P3-a** | **#1** Landing page animated iPad "video" | Needs final UI | M |
| **P3-b** | **#16** How-to videos (notes view, resources, misconceptions) | Needs final UI | M |
| Later | Difficulty easy/medium/hard colouring in contents | `pipeline/difficulty.py` already exists — wire into TOC after #8 | S |

S ≈ 1 session, M ≈ 2-3 sessions, L ≈ 4+ sessions.

---

## 3. Routing — new URL map

All new routes are FastAPI handlers that serve an HTML shell with
**server-injected `<title>`, meta description, canonical, JSON-LD and the
public description text** (so Google sees real text without JS). Old `*.html`
URLs get **301 redirects** so no bookmarks/backlinks break. Sitemap is
generated from boards × subjects × chapters.

| New route | Replaces | Indexed? | Public content |
|---|---|---|---|
| `/` | `index.html` | yes | landing + iPad demo |
| `/papers` | `papers.html` | yes | board picker (redirects logged-in users to their board) |
| `/papers/{board}` e.g. `/papers/o-level` | — | yes | subject cards (description text) |
| `/papers/{board}/{subject-code}` e.g. `/papers/o-level/physics-5054` | builder in `papers.html` | yes | subject description + chapter/subtopic **names** (text) |
| `/papers/{board}/{subject-code}/{chapter}` | — | yes | chapter description text |
| `/papers/view/{booklet_id}` | download | **noindex** | viewer (login) |
| `/yearly/{board}/{subject-code}` (+ `/{year}`) | `papers.html?tab=yearly`, `library.html` | yes | sitting list text |
| `/yearly/view/{paper_id}` | iframe in library | noindex | viewer (login) |
| `/mcq/{board}/{subject-code}` | `mcq-solver.html`, `papers.html?tab=mcq` | yes | text |
| `/mcq/session/{id}` | — | noindex | solver (login) |
| `/notes` → `/notes/{board}/{subject-code}` → `/…/{chapter}` → `/…/{chapter}/{subtopic}` | `notes-view.html`, `note.html` | **yes (notes are the best SEO content)** | full note text |
| `/tutor`, `/tutor/c/{session_id}` | `tutor.html` | `/tutor` yes | landing text |
| `/solver`, `/solver/c/{id}` | `tutor.html?tab=solver`, `ask.html` | `/solver` yes | landing text |

Slugs: board `o-level | igcse | a-level`; subject `physics-5054`,
`mathematics-4024`… (name + code — people search both); chapter = slugified
chapter name, stored in taxonomy JSON as `slug` so it never changes when a
display name changes.

> ❓ Q-A: "Landing text only" — I plan to include the **chapter and subtopic
> names as plain text** on public subject pages (that's syllabus info, not your
> content, and it's the main SEO value). Confirm, or should even those be hidden?

---

## 4. Database changes (new migrations `019+`, Postgres; SQLite mirror in `users_db.py`)

```sql
-- 019_student_boards.sql  (#2)
CREATE TABLE IF NOT EXISTS student_boards (
  user_id    TEXT REFERENCES profiles(id) ON DELETE CASCADE,
  board      TEXT NOT NULL CHECK (board IN ('o-level','igcse','a-level')),
  is_primary BOOLEAN DEFAULT FALSE,
  added_at   TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (user_id, board)
);
-- backfill: infer boards from existing enrollments (syllabus -> board map)

-- 020_booklets.sql  (#3, #8)
CREATE TABLE IF NOT EXISTS booklets (
  id            TEXT PRIMARY KEY,            -- short random id, used in URL
  user_id       TEXT REFERENCES profiles(id) ON DELETE CASCADE,
  syllabus      TEXT NOT NULL,
  title         TEXT,
  params_json   JSONB NOT NULL,              -- chapters, subtopics, years, papers, max_q, include_ms
  question_ids  INTEGER[] NOT NULL,          -- final shuffled order
  seed          BIGINT,
  status        TEXT DEFAULT 'queued',       -- queued|selecting|cropping|composing|ready|failed
  progress      INTEGER DEFAULT 0,           -- 0-100 for the loader
  page_map_json JSONB,                       -- [{qid, seq, page_from, page_to, y}] for viewer chips + TOC
  storage_key   TEXT,                        -- where the PDF lives (server disk / Supabase Storage)
  error         TEXT,
  created_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON booklets(user_id, created_at DESC);

-- 021_ai_explanations.sql  (#4, #6)
CREATE TABLE IF NOT EXISTS question_explanations (   -- SHARED cache, one per question+kind
  question_id  INTEGER NOT NULL,
  kind         TEXT NOT NULL CHECK (kind IN ('full','hint1','hint2','hint3','mcq_why')),
  content_md   TEXT NOT NULL,                -- markdown + LaTeX, rendered with KaTeX
  model        TEXT, prompt_version INTEGER, -- bump version => regenerate
  input_tokens INTEGER, output_tokens INTEGER,
  flagged      INTEGER DEFAULT 0,            -- students can report a wrong explanation
  created_at   TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (question_id, kind)
);
CREATE TABLE IF NOT EXISTS explanation_threads (     -- per-student follow-up chats
  id          TEXT PRIMARY KEY,
  user_id     TEXT REFERENCES profiles(id) ON DELETE CASCADE,
  question_id INTEGER NOT NULL,
  booklet_id  TEXT,
  created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS explanation_messages (
  id          BIGSERIAL PRIMARY KEY,
  thread_id   TEXT REFERENCES explanation_threads(id) ON DELETE CASCADE,
  role        TEXT NOT NULL,               -- user|assistant
  quoted_text TEXT,                        -- the highlighted part being asked about
  content     TEXT NOT NULL,
  created_at  TIMESTAMPTZ DEFAULT now()
);
-- migrate existing mcq_explanations rows -> question_explanations(kind='mcq_why')

-- 022_calculator.sql  (#15)
CREATE TABLE IF NOT EXISTS calc_history (
  id BIGSERIAL PRIMARY KEY,
  user_id TEXT REFERENCES profiles(id) ON DELETE CASCADE,
  expr TEXT NOT NULL, result TEXT NOT NULL, angle_mode TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);   -- keep last 200 per user (trim on insert)
CREATE TABLE IF NOT EXISTS calc_state (
  user_id TEXT PRIMARY KEY REFERENCES profiles(id) ON DELETE CASCADE,
  memory  DOUBLE PRECISION DEFAULT 0, vars_json JSONB DEFAULT '{}',  -- M, A-F, Ans
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- 023_tutor_v2.sql  (#10, #11)
ALTER TABLE tutor_sessions ADD COLUMN IF NOT EXISTS kind TEXT DEFAULT 'tutor'; -- tutor|solver
ALTER TABLE tutor_sessions ADD COLUMN IF NOT EXISTS title_source TEXT DEFAULT 'auto'; -- auto|user
ALTER TABLE tutor_sessions ADD COLUMN IF NOT EXISTS archived BOOLEAN DEFAULT FALSE;
-- (full-text search over titles: GIN index on to_tsvector(title))

-- 024_notes_index.sql  (#13) — optional; can stay in manifest.json
-- 025_annotations: reuse pdf_annotations, paper_key = 'booklet:<id>' or 'paper:<id>'
```

Pipeline tables (`papers`, `questions`, `ms_entries`) — no schema change for #5,
only a data sync. Later: `questions.difficulty` (easy/medium/hard) for the TOC
colouring.

---

## 5. Backend endpoints (new / changed)

**Boards & catalogue (#2)**
- `GET  /api/boards` → boards with subject lists (from `BOARDS`, moved to one shared module).
- `GET  /api/me/boards` · `PUT /api/me/boards` `{boards:[…], primary}`.
- `GET  /api/catalogue?board=o-level` → subjects with `{enrolled, locked, question_count, chapters}`; enrolled first.
- `POST /api/enrollments` (exists) — one-click enrol from the lock card.
- Server guard `require_enrolled(syllabus)` dependency on every paper/MCQ/AI/progress endpoint.

**Topical builder + viewer (#3, #8)**
- `GET  /api/topical/{syllabus}/tree?year_from&year_to&papers` → chapters → subtopics with live counts.
- `POST /api/booklets` `{syllabus, chapters[≤4], subtopics[], years, papers, max_questions, include_ms}` → validates, selects + **shuffles** ids, inserts row, starts a background job → `{id}`.
- `GET  /api/booklets/{id}/status` → `{status, progress, stage_label}` (polled every 700 ms, or SSE) — drives the loader ("Picking questions… Cropping… Adding mark schemes… Building contents…").
- `GET  /api/booklets/{id}` → metadata + `page_map` (for per-question chips in the viewer).
- `GET  /api/booklets/{id}/pdf` → inline PDF (`Content-Disposition: inline`); `?download=1` for attachment.
- `GET  /api/booklets` → my history.
- Job runs `pipeline.compose --ids … --order given --toc-links` in a worker thread (bounded pool of 2) instead of blocking the request.

**Shuffle algorithm** (in a pure function `select_mixed()` — unit-testable):
1. Pool = matching questions per selected *bucket* (a bucket = subtopic if picked, else chapter).
2. Quota per bucket = proportional to pool size, **min 1 each** so every bucket is represented, total = `max_questions`.
3. Within each bucket, weighted-random by recency (existing `1.5**year` weighting).
4. Interleave round-robin, then random-swap pass so **no two consecutive questions share a bucket** where avoidable.
5. Seed stored → same booklet reproducible.

**AI panel (#4, #6)** — Claude via the Anthropic SDK
- `POST /api/questions/{id}/explain` → SSE stream. If `question_explanations(id,'full')` exists, stream it from cache (instant, free). Else call Claude with **question crop PNG + official MS crop PNG + syllabus topic**, store, stream.
- `POST /api/questions/{id}/hint` `{level:1|2|3}` → "Guide me": 1 = what is being asked / which concept, 2 = first step, 3 = next step with a check-question. Cached per level.
- `POST /api/questions/{id}/ask` `{thread_id?, message, quoted_text?}` → SSE follow-up (per-student thread, not cached, quota-counted).
- `POST /api/questions/{id}/explain/report` → flag a bad explanation (admin queue).
- MCQ "why is my answer wrong": `POST /api/mcq/explain` becomes a thin wrapper → `kind='mcq_why'` + the chosen option.
- Models: **`claude-sonnet-5`** for the cached full explanation (quality matters, paid once per question); **`claude-haiku-4-5`** for hints and follow-ups (cheap, fast). Prompt caching on the system prompt + question images within a thread. Optional nightly **Batch API** pre-generation for the most-used questions.
- Grounding rule in the prompt: the explanation must reach the **official mark-scheme answer**; if the model disagrees with the MS it must say so, not silently override.

**Yearly & MCQ (#9, #7)**: existing `/api/library*`, `/api/mcq/*` stay; add `GET /api/mcq/papers/{paper_id}/layout` (page images + question boxes for the exam-paper view) and `POST /api/mcq/sessions` / `…/{id}/submit` to store attempts for review mode.

**Calculator (#15)**: `GET/POST/DELETE /api/calc/history`, `GET/PUT /api/calc/state`. Offline-first: write localStorage immediately, sync to server debounced; guests keep localStorage only.

**Tutor/Solver (#10, #11)**: `POST /api/tutor/sessions` `{kind}`; auto-title = after the first exchange, Haiku writes a 3-6 word title from the content (like ChatGPT); `PATCH` rename/pin/archive; `GET /api/tutor/sessions?kind=&q=` search; `POST /api/tutor/messages/{id}/regenerate`; branch-edit of a user message; share-to-notes. Solver: `POST /api/solver/solve` and `POST /api/solver/check` (image + optional text).

**Notes (#13)**: `GET /api/notes-tree/{syllabus}` (chapters → subtopics → note available?/slug), server-rendered note pages for SEO.

**MS sync (#5)**: admin-only `POST /api/meta/refresh` already exists — call it after sync.

---

## 6. Module-by-module plan

### P0-a · Test harness + staging (do first)
1. Create Supabase **staging** project → run `supabase/schema.sql` + all `website/migrations/*.sql`.
2. `.env.test` (gitignored) with staging `DATABASE_URL`, `SUPABASE_*`, a test `SECRET_KEY`, **no real `ANTHROPIC_API_KEY`** by default (LLM calls mocked).
3. `scripts/seed_staging.py`: copies pipeline tables (papers/questions/classifications/ms_entries — maybe 2 syllabi only to stay in free tier), creates fake users: `student_free@test`, `student_multi@test` (O Level + A Level), `teacher@test`, `admin@test`.
4. **Safety guard in `db.py`**: when `APP_ENV=test` or `local`, refuse to start if `DATABASE_URL` host == the production host. This alone prevents the "local writes to prod" accident.
5. `launch.json`: add `prepwithtee-staging` config that loads `.env.test`.
6. Install: `pip install pytest pytest-playwright pytest-xdist` → `playwright install chromium` (Python only — **no Node needed**).
7. Layout: `tests/unit/`, `tests/api/`, `tests/pdf/`, `tests/e2e/`, `tests/conftest.py`.

### P0-b · #5 Old mark schemes & MCQ keys
1. `scripts/sync_ms_entries.py` — idempotent upsert of `ms_entries` (incl. `answer`) from local `index.db` → Supabase for **all** years. Papers are matched by **filename**, not by `id` (ids differ between the two DBs). Dry-run mode prints counts per syllabus/era first.
2. Verify the MS crop PDFs for 2010-19 exist on the server (`data/crops/*/q*_ms.pdf`); rsync the missing ones via the existing /tmp staging deploy pattern.
3. Improve the pre-2020 linker (CLAUDE.md 19b): second parser for **prose-style** mark schemes, targeting 9709 (31%), 9702 structured (33%), 5054 structured (29%), then 2058/0478/2210/0620 (~60%). One-paper debug-PNG check per syllabus before bulk runs (existing ground rule).
4. MCQ 77-83% → inspect the unparsed ones (probably a different table layout pre-2016); extend the regex in `pipeline/mcq.py`.
5. Bust `/api/meta` cache.
- **Tests**: `tests/pdf/test_ms_coverage.py` asserts per-syllabus link rate ≥ target (e.g. ≥95% MCQ, ≥90% structured) against the staging DB; a parity test compares local vs Supabase counts; a spot-check test opens 20 random old MS crops and renders them to PNG for your review.

### P0-c · #8 PDF layout
Suspected causes found in `pipeline/compose.py`:
- `place_rects()` never **scales down** a rect taller than the usable page (`BOTTOM_Y - TOP_Y`) → it overflows into the 62-pt footer band → bottom lines/powers are hidden. Fix: scale-to-fit or split at whitespace rows.
- Segment crop `y0` may sit too tight on the first line → **superscripts/powers clipped at the top**. Fix: pad crops by ~4 pt and clip against the neighbour question's y1 instead of the text baseline.
- Blank pages: `topic_header().ensure(30+80)` and `place_insert_pages()` setting `y = BOTTOM_Y` can create a page that then receives nothing when the next group starts with a tall question that forces another page. Fix: a final **empty-page sweep** (drop any page whose only content is the watermark + footer) and remember page breaks lazily.
- **Contents page**: new page after the cover listing `Q# · Paper ref (e.g. 0625/42/M/J/19 Q3) · chapter · page`, each row a **clickable PDF link** (`page.insert_link` with `LINK_GOTO`) + PDF outline/bookmarks (`doc.set_toc`) so the viewer's sidebar also works. Difficulty dot (green/amber/red) column reserved, filled once difficulty is classified.
- Same fixes applied to `testgen.py` (shared `Booklet`).
- **Tests** (`tests/pdf/`): generate booklets for ~15 fixture selections (every syllabus, maths + physics + MCQ + inserts), then assert: (1) no page is "empty" (text/drawings beyond watermark+footer), (2) no placed rect bottom > `BOTTOM_Y`, (3) every TOC link targets the page where that question's header is, (4) page count ≤ previous baseline. Plus PNG renders of every page to `data/debug/booklets/` for your eyes (you sign off, like the crop gate).

### P1-a · #2 Boards, catalogue, free enrolment, SEO routes
- Signup/onboarding: board step (multi-select chips). Existing users with no board → a blocking modal on `/papers` ("Which boards are you studying?"), pre-ticked from their enrolments.
- `/papers/{board}`: **Your subjects** row (enrolled) on top, then **All subjects** with 🔒 + "Enrol free" button. Enrolled unlocks: topical, yearly, MCQ, topical & yearly progress, AI.
- Clean routes + 301s + server-injected meta + sitemap (Section 3).
- **Tests**: API — non-enrolled user gets 403 on `/api/booklets` for that syllabus; enrol → 200. E2E — new user → board prompt → enrol Physics → lock disappears. SEO — `curl /papers/o-level/physics-5054` returns the `<title>`, description and canonical **without JS**; old `papers.html` returns 301.

### P1-b · #3 Topical builder v2 + viewer
- Subject page: chapter accordion, each with question count; tick chapter = all subtopics, or tick individual subtopics; counts update live with year/paper filters. Counter "3 / 4 chapters" and the 5th chapter disabled with a tooltip.
- "How many questions?" slider (max = pool size), marks estimate, "Include mark scheme" toggle.
- **Build** → opens `/papers/view/{id}` in a **new tab** → loader with real stages → PDF renders in-site (PDF.js from cdnjs, canvas per page + text layer) → toolbar: download, print, contents drawer, annotation bar, and a **chip on every question** ("Explain · Hint · Mark scheme") positioned from `page_map`.
- **Tests**: unit — `select_mixed()` (≤4 chapters enforced, every bucket represented, no adjacent same-bucket when possible, deterministic with seed, respects max). API — create → status progresses → PDF bytes start with `%PDF`. E2E — pick 2 chapters → build → new tab → loader → first page canvas visible → contents link jumps.

### P1-c · #4 + #6 AI side panel (shared component `ai-panel.js`)
- Layout like Claude artifacts: **paper stays on the left**, panel slides in on the right (resizable divider; on mobile it's a bottom sheet).
- Tabs: **Explain** (full worked solution, big font, KaTeX maths, step cards, "Mark scheme says…" box) · **Guide me** (hint levels 1→3, each a button, never reveals the answer until the student asks) · **Ask** (chat thread).
- **Select-to-ask**: highlight any text in the explanation → floating "Ask about this" pill → quoted block goes into the chat input.
- MCQ (#6): same panel; "Why is B wrong?" per option, the correct option highlighted, misconception explained.
- **Tests**: API with a **mocked Anthropic client** — cache miss calls model once, cache hit calls zero times; quota counted only for follow-ups; unenrolled 403. Prompt snapshot tests (the prompt includes the MS crop). E2E — click Explain → panel opens, stream renders, KaTeX renders; select text → pill → quoted message sent. One opt-in `@pytest.mark.live` test hits the real API for 3 fixture questions (run by hand, never in the default suite).

### P1-d · #9 Yearly & MCQ as separate pages — ✅ built locally 2026-09-26 (not deployed)
- `/yearly/{board}/{subject}` — year grid → sitting → QP/MS/Insert/ER side-by-side in the same viewer component as topical (annotation + AI chips work there too because we have `questions` rows per paper).
- `/mcq/{board}/{subject}` — own page, no tab switcher.
- **Tests**: routes 200 + 301s; E2E open a 2016 paper and toggle QP↔MS.

### P1-e · #7 MCQ solver paper view — ✅ built locally 2026-09-26 (not deployed)
- **Exam mode**: real paper pages (PDF.js) on the left, sticky answer-bubble strip (1-40, A-D) on the right; timer (official duration, pause off by default); flag-for-review.
- **Review mode** after submit: score, grid of ✓/✗, click → jumps to the question and opens the AI panel with "why".
- Mobile: one question per screen with swipe, bubble bar collapses to a bottom drawer.
- **Tests**: unit — scoring; E2E — answer 3, submit, review grid shows correct marks against the stored keys (incl. a 2016 paper — proves #5).

### P2-a · #12 Annotation bar — ✅ built locally 2026-09-26 with P1-e; ruler + protractor 2026-09-26
- One floating **horizontal pill** bar (draggable, snaps to top/bottom centre, collapses to a single pen icon). Groups separated by thin dividers: **Pen · Marker · Highlighter · Eraser** | **Ruler · Protractor · Shapes** | **Text** | colour dot + size dot (open small popovers, not inline swatches) | undo/redo | clear.
- Draws on a canvas layer **per PDF page** (so it scrolls with the page and works in the viewer — the old one skips iframes), saved to `pdf_annotations` per `booklet:<id>`/`paper:<id>` + page.
- Pressure/smoothing (perfect-freehand-style algorithm, inline), palm rejection for stylus (`pointerType`).
- **Tests**: E2E — draw a stroke, reload, stroke persists; eraser removes; keyboard shortcuts; visual snapshot of the bar at 375 px and 1440 px.

### P2-b · #14 Graph plotter — ✅ built locally 2026-09-26 (not deployed)
- Replace the regex→`new Function` path with a small **tokenizer + Pratt parser** (unary minus precedence, implicit multiplication `2x`, `x(x+1)`, `sin x`, `sin^2 x`, `|x|`, `log_2(x)`, `√`, `π`, `e`) → safe AST evaluator (also removes `new Function` on user input).
- Friendly inline error under the input ("Missing ')' after sin(") instead of raw JS errors; keeps the previous good graph drawn while typing.
- Equation type icons (𝑦=, 𝑥=, parametric, inequality later) on each row, colour swatch, show/hide eye.
- **Tests**: unit table of ~60 expressions → expected value at x=2 (runs in the browser via Playwright `page.evaluate`, no Node). Includes every bug listed in Section 1.

### P2-c · #15 Calculator memory/history per account — ✅ built locally 2026-09-26
- Save every `=` to `calc_history`; M, M+, M−, MR, MC, Ans and variables A-F to `calc_state`. History panel: unlimited scroll (last 200), tap to reuse, clear. Works as a guest via localStorage and merges when the guest logs in.
- **Tests**: API round-trip; E2E — compute, reload, history and memory still there; second device (new browser context, same user) sees it.

### P2-d · #13 Notes — ✅ built locally 2026-09-26 (notes attach to taxonomy CHAPTERS; each note names its subtopic)
- `/notes` → board → **subject cards** → subject page = chapter/subtopic tree (from the same taxonomy as topical) with "Notes ✓" / "Coming soon" per subtopic → note page `/notes/o-level/physics-5054/forces/hookes-law`.
- Notes pages server-rendered (full text in HTML → indexable), breadcrumb JSON-LD, "Practise this topic" button → pre-filled topical builder, prev/next subtopic.
- Adding a note = drop an HTML/MD file in `notes-content/{syllabus}/{chapter}/{subtopic}.html`; the tree picks it up automatically.
- **Tests**: every manifest entry resolves; every taxonomy subtopic produces a page (coming-soon allowed); sitemap includes only notes that exist.

### P2-e · #10 + #11 AI Tutor & Solver
- **Tutor** (`/tutor`): ChatGPT/Claude-like — left sidebar with searchable, date-grouped chats ("Today / Previous 7 days"), auto titles from content, rename/pin/archive/delete, new chat; centred message column, streaming markdown + KaTeX + code, copy / regenerate / edit-and-resend / thumbs; subject selector chip; attach image; voice note (Groq Whisper exists). Background: subtle animated **maths-symbol pattern** (∑ π √ ∫ drawn faintly, CSS only, respects reduced-motion).
- **Solver** (`/solver`): two big modes — **📷 Solve a question** and **✅ Check my working** — drag/paste/camera upload, crop box, then a structured worked solution / marking report; short follow-up allowed.
- On both pages an "How to get the best out of this" card (when to use Tutor vs Solver vs the in-paper Explain).
- **Tests**: API — title generation mocked; session CRUD; kind filter. E2E — new chat → title appears after first reply; search finds it; solver upload → result card.

### P3-a/b · #1 + #16 Animated "videos"
- A reusable `demo-player.js`: iPad frame (CSS), a timeline JSON of **real screenshots** (captured with Playwright from staging so they're always current) + steps: `{shot, zoom, pan, cursor:[x,y], click, caption, duration}`. Autoplays muted-style when scrolled into view, pause on hover, chapter dots.
- Landing: "How PrepWithTee works" (pick board → enrol → build topical → Explain panel → track progress).
- Guides: Notes View, Resources, "Common misconceptions" series.
- Regenerating screenshots is a script (`scripts/capture_demo_shots.py`), so when the UI changes you re-run one command.
- **Tests**: visual snapshot; Lighthouse performance on `/` (the player must not hurt LCP — lazy-load below the fold).

---

## 7. How testing works (and how to write tests)

**Rule: nothing is deployed until (1) the automated suite passes on staging and
(2) you've clicked through the module locally and said "ship it".**

### 7.1 Test pyramid
| Layer | Tool | What | Hits |
|---|---|---|---|
| Unit | `pytest` | pure functions: `select_mixed`, scoring, parsers, slugify | nothing |
| API | `pytest` + FastAPI `TestClient` | endpoints, auth, enrol guard, quotas | staging DB, **LLM mocked** |
| PDF | `pytest` + PyMuPDF | booklet invariants (no blank pages, no overflow, TOC links) | local `index.db` |
| E2E / UI | `pytest-playwright` (Python) | real browser flows, mobile + desktop, screenshots | local server → staging DB |
| Live AI (opt-in) | `pytest -m live` | 3 real Claude calls, printed for human review | Anthropic API |

### 7.2 Example tests (to show the style)

```python
# tests/unit/test_select_mixed.py
from website.selection import select_mixed

def pool(bucket, n):
    return [{"id": f"{bucket}{i}", "bucket": bucket, "year": 2020 + i % 5} for i in range(n)]

def test_every_bucket_represented_and_mixed():
    qs = pool("A", 30) + pool("B", 3) + pool("C", 10)
    out = select_mixed(qs, max_questions=12, seed=1)
    assert len(out) == 12
    assert {q["bucket"] for q in out} == {"A", "B", "C"}
    adj = sum(a["bucket"] == b["bucket"] for a, b in zip(out, out[1:]))
    assert adj <= 3                       # A dominates, but it can't be one long run

def test_seed_is_reproducible():
    qs = pool("A", 20) + pool("B", 20)
    assert select_mixed(qs, 10, seed=7) == select_mixed(qs, 10, seed=7)
```

```python
# tests/api/test_booklets.py
def test_unenrolled_student_is_blocked(client, login):
    login("student_free@test")
    r = client.post("/api/booklets", json={"syllabus": "9709", "chapters": ["Vectors"], "max_questions": 5})
    assert r.status_code == 403

def test_more_than_four_chapters_rejected(client, login, enrol):
    login("student_free@test"); enrol("5054")
    r = client.post("/api/booklets", json={"syllabus": "5054",
                    "chapters": ["Motion", "Forces", "Momentum", "Pressure", "Density"]})
    assert r.status_code == 422
```

```python
# tests/pdf/test_layout.py
import fitz
from pipeline.compose import BOTTOM_Y

def test_no_blank_pages(built_booklet):          # fixture builds a real PDF
    doc = fitz.open(built_booklet)
    for i, page in enumerate(doc):
        if i == 0: continue                       # cover
        words = [w for w in page.get_text("words") if w[1] < BOTTOM_Y]
        assert words or page.get_images(), f"page {i+1} is empty"
```

```python
# tests/e2e/test_topical_flow.py   (pytest-playwright)
def test_build_and_explain(page, logged_in_as):
    logged_in_as("student_multi@test")
    page.goto("/papers/o-level/physics-5054")
    page.get_by_role("checkbox", name="Motion").check()
    with page.context.expect_page() as viewer:
        page.get_by_role("button", name="Build paper").click()
    v = viewer.value
    v.get_by_text("Picking questions").wait_for()
    v.locator("canvas.pdf-page").first.wait_for(timeout=60_000)
    v.get_by_role("button", name="Explain").first.click()
    assert v.locator(".ai-panel .katex, .ai-panel p").first.is_visible()
```

### 7.3 Running tests locally
```bash
.venv/Scripts/pip install pytest pytest-playwright pytest-xdist
```
```bash
.venv/Scripts/python -m playwright install chromium
```
```bash
.venv/Scripts/python -m pytest tests/unit tests/api tests/pdf -q
```
```bash
.venv/Scripts/python -m pytest tests/e2e --headed --base-url http://localhost:8017
```
(`--headed` lets you watch the browser; drop it for speed. `-m live` runs the real-Claude checks.)

### 7.4 Testing the frontend yourself locally
1. Start the site against **staging**: in this app I start the `prepwithtee-staging`
   config from `.claude/launch.json` (it loads `.env.test`); from a terminal it's
   `.venv/Scripts/python -m uvicorn website.app:app --port 8017 --env-file .env.test`.
2. Open `http://localhost:8017`, log in as a seeded test user (credentials in
   `.env.test`, never real students).
3. Walk the module's checklist (each module PR includes one, e.g. "Build a
   4-chapter paper → 5th chapter disabled → loader shows stages → contents link
   jumps → Explain opens on the right").
4. Check mobile: browser devtools → iPhone 12 size (I also run this in the
   preview pane and send you screenshots).
5. Your sign-off → merge → deploy (existing `/tmp` staging deploy pattern) →
   smoke test on production (`/api/health`, one booklet build, one Explain).

### 7.5 Definition of done per module
- [ ] Unit + API + PDF tests written and green
- [ ] E2E happy path + one failure path green, desktop **and** 375 px
- [ ] No console errors, no 4xx/5xx in network log on the flow
- [ ] Asset `?v=` bumped on every page referencing changed JS/CSS (immutable caching rule)
- [ ] Old URLs still work (301)
- [ ] You tested it locally and signed off
- [ ] CLAUDE.md "Build order / status" updated

---

## 8. Open questions for you

1. **Q-A (SEO)**: OK to show chapter/subtopic *names* as public text on subject pages? (Section 3.)
2. **MCQ "Something else"** — what else is missing in the MCQ solver? (You ticked it without text.)
3. **AI cost guardrails**: how many AI follow-up messages per day per plan (Free / Solo / 3 / All)? The cached Explain is free to serve, so I'd make **Explain unlimited for enrolled students** and meter only Ask/Guide-me. OK?
4. **Pre-generating explanations**: should I batch-generate the cached explanation for *every* question up front (one-time bulk cost, instant for students), or only generate on first click (pay as used)?
5. **Booklet PDFs storage**: keep generated PDFs on the server disk for 30 days (regenerate on demand from the stored ids after that), or keep forever in Supabase Storage?
6. **Free-plan limits after enrolment**: is enrolling in *all* subjects fine for a Free user (the lock is only about enrolling), with quotas as the only limit? (Matches your answer; confirming because today the "3 Subjects" plan implies a subject cap.)
7. **Board list**: just O Level / IGCSE / A Level (Cambridge) for now, or do you also want Edexcel/AS as separate boards later (affects slugs)?
8. **Difficulty colours** (later): classify by AI, or by your judgement in an admin screen, or both (AI suggests, you confirm)?

### Answers (tutor, 2026-09-26)
- **MCQ "Something else"**: nothing extra - a mis-tick while adding a note.
- **Explanations**: one per question, first one free for free users, then a plan; generated
  in bulk on FREE providers only and served to everyone; every explanation must agree with
  the official Cambridge mark scheme (enforced: pipeline/explain_check.py + a verifier model).
- **Difficulty**: primarily from the **examiner reports** (ER) - parse and analyse each
  yearly paper's ER, store a difficulty against every question; the tutor can override it
  from the admin side. Colours in the booklet contents page come from that.
- **Booklet PDFs**: Claude's call - keep each built PDF on the server for **30 days after it
  was last opened**, then delete the file only; the booklet row keeps its question ids, so
  opening an old link rebuilds the same paper (same order) in ~20 s.
- **Boards**: Cambridge only (O Level / IGCSE / A Level) for now.
