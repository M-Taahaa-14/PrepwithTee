# PrepWithTee — Curriculum Notes System: Implementation Plan

> **Goal:** Build a curated, hierarchical study-notes experience (like igcsezone.com) woven
> into the existing PrepWithTee dashboard. Students navigate Subject → Chapter → Subtopic
> and read exam-ready notes with diagrams, tables, exam tips, and weightage context.
>
> **Pilot scope:** One subject, one chapter — validate the full stack before scaling.

---

## 1. Vision & Design Principles

| Principle | What it means here |
|---|---|
| Hierarchy first | Subject → Chapter → Subtopic, reflected in the URL and the sidebar |
| Never retypeset | Images (diagrams, graphs) are PNG/SVG crops from the official syllabus, not re-drawn |
| Exam-aware | Every page shows paper code, tier (Core/Extended/OL), topic weightage, and command words |
| Linked ecosystem | Each subtopic page deep-links to: topical past papers, flashcards, AI Tutor, and "My Notes" |
| Static content, dynamic wrapper | Notes content = authored HTML fragments served by Flask; no CMS, no database for content |
| PrepWithTee brand | Cream/navy/gold palette, Playfair headers, same sidebar/nav as the dashboard |

---

## 2. Information Architecture

```
/subject/<code>/                          Subject landing page
/subject/<code>/chapter/<slug>/           Chapter index page
/subject/<code>/chapter/<slug>/<subtopic-slug>/   Subtopic note page
```

### Subject codes supported (phased)

| Phase | Code | Subject |
|---|---|---|
| Pilot | `0625` | Physics IGCSE |
| Phase 2 | `5054` | Physics O Level |
| Phase 3 | `4024` / `0580` | Maths |
| Phase 4 | `2210` / `0478` | Computer Science |

---

## 3. Page Types (3 templates)

### 3A — Subject Landing Page (`/subject/0625/`)

Sections (top to bottom):

1. **Hero** — Subject name, board (Cambridge), level (IGCSE / O Level), brief description
2. **Paper guide card** — Table: Paper number | Type | Duration | Marks | % of grade | Tier
   - e.g. 0625: P2 Core MCQ 45 min / P3 Ext MCQ 45 min / P4 Core Structured 1 h 15 min / P6 Ext Alternative to Practical
   - Call-out: "You are studying **Extended** (Papers 3 + 6)" — pulled from the student's profile syllabus choice
3. **How to use these notes** — 3-step visual: Read the note → Try the past paper Qs → Flashcard drill
4. **Chapter grid** — Cards, one per taxonomy chapter; each card shows: chapter number, name, subtopic count, completion ring (% of subtopics visited)
5. **Quick links strip** — Formula sheet, Definitions, Past Papers (topical), AI Tutor

### 3B — Chapter Index Page (`/subject/0625/chapter/forces/`)

1. **Breadcrumb** — Home > Physics > Forces
2. **Chapter header** — Name, syllabus reference (e.g. "Section 1.5"), approximate exam weighting, typical mark allocation
3. **Syllabus checklist** — Every official learning outcome from the syllabus, tick-boxed (stored in `localStorage`, not server)
4. **Subtopic list** — Ordered list of subtopics with one-line descriptions; each is a link to the subtopic note
5. **Exam insight** — "This chapter typically contributes 8–12 marks across P4"; command words used; common mistakes panel
6. **Related resources strip** — Link to topical paper for this chapter, flashcard deck for this chapter

### 3C — Subtopic Note Page (`/subject/0625/chapter/forces/weight-and-mass/`)

Layout: **two-column** on desktop (sidebar left, content right); single column on mobile.

**Left sidebar (fixed, scrollable)**
- Back link to chapter
- Full chapter subtopic tree — all subtopics listed, current one highlighted
- "On this page" anchor list (H2 headings from the current note)

**Main content area**
- Eyebrow: Chapter name + syllabus code
- Heading (Playfair, large)
- **Tier badge** — `Extended only` / `Core & Extended` (gold / teal pill)
- **Content blocks** (authored as HTML fragments, see Section 5):
  - Key definition box (navy border left)
  - Explanation paragraphs (prose)
  - Diagrams / images (PNGs, max-width 100%, with alt text and figure caption)
  - Tables (styled, responsive)
  - Worked example (collapsible, shows step-by-step solution)
  - Exam tip box (gold background, ⚡ icon — command word, mark scheme language)
  - Common mistake box (red tinted)
  - Summary / key points (bulleted, bold terms)
- **Bottom action strip**
  - ← Previous subtopic / Next subtopic →
  - "Practice past paper Qs on this subtopic" (links to topical papers filtered)
  - "Add a note" (opens notes.html composer pre-filled with this subtopic as context)
  - "Start flashcard drill" (links to flashcards filtered by topic)
  - "Ask AI Tutor" (links to tutor.html with this subtopic pre-filled)

---

## 4. Navigation & Routing

### URL Design

Flask routes (add to `app.py`):

```python
@app.route("/subject/<code>/")
@app.route("/subject/<code>/chapter/<chapter_slug>/")
@app.route("/subject/<code>/chapter/<chapter_slug>/<subtopic_slug>/")
```

Each route renders a Jinja2 template, passing:
- The subject metadata (from a `subjects.json` content manifest)
- The chapter/subtopic data (from the chapter's content file)

### Static vs. dynamic

Content files live in `website/content/notes/<code>/<chapter-slug>/<subtopic-slug>.html`.
These are **authored HTML fragments** — no Markdown conversion step needed.
Flask renders them inside the subtopic template via `{{ content | safe }}`.

The subject/chapter metadata (names, slugs, syllabus refs, weightage) lives in
`website/content/notes/manifest.json` — one JSON file per subject, or a combined file.

---

## 5. Content Authoring Format

Each subtopic is a **plain HTML fragment** (no `<html>/<body>` wrapper), placed at:
`website/content/notes/0625/forces/weight-and-mass.html`

Authors use a small set of CSS classes already in `styles.css` (or added to it):

| Block | Class | Renders as |
|---|---|---|
| Definition | `<div class="note-def">` | Left border (navy), italic term, definition |
| Key point | `<div class="note-key">` | Gold accent, bullet summary |
| Exam tip | `<div class="note-tip">` | Gold background box, ⚡ prefix |
| Common mistake | `<div class="note-warn">` | Red-tinted box, ✗ prefix |
| Worked example | `<details class="note-example">` | Collapsible, step-by-step |
| Figure | `<figure class="note-fig">` | Image + `<figcaption>` |
| Table | standard `<table class="note-table">` | Striped, responsive wrapper |

This keeps authoring approachable — no build step, no MDX compiler.

---

## 6. Pilot Chapter Content Plan — 0625 Forces (Chapter 1.5)

Subtopics to author first (maps to syllabus 1.5):

1. Weight and mass — definition, W=mg, difference between weight and mass, g values
2. Density — ρ=m/V, measurement method, floating/sinking rule
3. Forces — types (contact vs. non-contact), resultant, free-body diagrams
4. Turning effect (moments) — principle of moments, calculations, levers
5. Centre of gravity — definition, stability (low CoG / wide base), practical
6. Momentum — p=mv, conservation, collisions
7. Newton's laws — 1st, 2nd (F=ma), 3rd (action-reaction pairs)
8. Energy, work, power — definitions, formulae, efficiency

Each subtopic note should include:
- At least one diagram (hand-drawn or syllabus-sourced PNG)
- One exam tip with exact command-word guidance
- One common mistake
- One worked example
- Syllabus learning outcome(s) it satisfies

Estimated authoring time: ~2 hours per subtopic (8 subtopics = ~16 h total for pilot chapter).

---

## 7. Integration with Existing Pages

| Existing page | Integration |
|---|---|
| `notes-view.html` | Becomes the **entry point** to the notes system; redirects to `/subject/<code>/` |
| `papers.html` | "Notes for this topic" link added to each topical paper card |
| `flashcards.html` | "Notes" button added to each deck card |
| `tutor.html` | "View notes on this topic" quick-link |
| `dashboard.html` | New "Notes" widget showing last-visited subtopic + % completion |
| `study-hub.html` | Notes card added to study tools grid |

---

## 8. Progress Tracking (client-side only, no DB)

`localStorage` key: `pwt_notes_visited` — object keyed by subtopic path, value = timestamp.
Completion rings on the chapter grid are computed from this in JS.
Syllabus checklist checkboxes write to `pwt_checklist_<code>`.

No server state required for Phase 1 — keeps it simple and offline-capable.

---

## 9. Exam-Context Features (per page)

Every subtopic page header shows:

```
[Physics IGCSE 0625]  [Chapter 1.5 — Forces]  [Extended: Papers 3 & 6]  [~10 marks / paper]
```

A collapsible "Exam strategy for this subtopic" panel contains:
- Typical question formats (structured, show-that, practical)
- Mark scheme language to use (e.g. "use of F = ma; correct substitution; correct answer")
- Past paper question count for this subtopic (pulled from the pipeline DB via a Flask endpoint)

---

## 10. Build Sequence

### Phase 0 — Foundation (1–2 days)
- [ ] Add Flask routes for 3 templates
- [ ] Create `manifest.json` for 0625 with all chapters + subtopics listed (slugs, names, syllabus refs)
- [ ] Build the 3 Jinja2 templates (landing, chapter index, subtopic) with placeholder content
- [ ] Add `note-def`, `note-tip`, `note-warn`, `note-example`, `note-fig`, `note-table` CSS classes to `styles.css`
- [ ] Wire up `notes-view.html` to redirect / link to the new subject landing page

### Phase 1 — Pilot Chapter (3–5 days)
- [ ] Author all 8 Forces subtopic HTML fragments for 0625
- [ ] Source / create diagrams for each subtopic (PNG, optimised)
- [ ] Populate chapter index with real weightage and syllabus checklist items
- [ ] Connect "past paper Qs" links to `papers.html?subject=0625&topic=Forces`
- [ ] Add `pwt_notes_visited` tracking + completion rings to the chapter grid

### Phase 2 — Full 0625 Subject (ongoing)
- [ ] Author all remaining 0625 chapters (~24 chapters × avg 5 subtopics = ~120 subtopics)
- [ ] Add the sidebar "On this page" anchor scroll-spy
- [ ] Add prev/next subtopic navigation
- [ ] Add "Ask AI Tutor" deep-link

### Phase 3 — Second Subject (5054 or 4024)
- [ ] Create `manifest.json` for 5054
- [ ] Re-use all 3 templates (they are subject-agnostic)
- [ ] Author pilot chapter for 5054

---

## 11. What Is NOT in Scope (Phase 1)

- Server-side progress persistence (Phase 2 or later)
- Community notes / comment threads
- Video embeds (links to YouTube are fine; embedding is a future feature)
- MCQ quizzes embedded inside notes (possible later via the existing quiz engine)
- Mobile app (the web is responsive; native app is out of scope)
- Admin CMS for authoring (authors edit HTML files directly for now)

---

## 12. Open Questions for the Tutor

1. **Which subject first?** Recommendation: **0625 Physics IGCSE** — largest student base, most
   demand, and taxonomy is already verified and complete.
2. **Which chapter first?** Recommendation: **Forces** (Chapter 1.5) — central to the syllabus,
   high exam weighting, lots of diagrams (good for testing the image workflow).
3. **Diagrams:** Hand-drawn on a tablet and exported as PNG? Or recreated in Canva/Inkscape?
   The site should not use copyrighted CIE artwork directly.
4. **Tier context:** Should the site detect the student's tier from their profile and
   highlight/grey-out Core-only vs. Extended-only content automatically?
5. **Language:** Should notes be written in British English (Cambridge standard)?

---

*Last updated: 2026-09-04 — initial plan draft*
