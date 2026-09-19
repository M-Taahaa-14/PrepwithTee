# Staged Commits — PrepWithTee Platform Build

Run each block in order in **PowerShell**. Every `git add` is followed immediately by its `git commit`.
**Do not commit the `.bak` files** — they are taxonomy backups and are excluded below.

---

## Commit 1 — Infrastructure & deploy scripts

```powershell
git add .gitignore requirements.txt README.md PLAN.md
git add deploy/Caddyfile deploy/prepwithtee.service
git add deploy/backup.sh deploy/prepwithtee.cron deploy/run-digest.sh
git commit -m @'
Update deploy config and add server maintenance scripts

Refresh Caddyfile and systemd service for latest routes. Add backup,
cron, and digest runner scripts for the production server.
'@
```

---

## Commit 2 — Database schema & Supabase migrations

```powershell
git add supabase/schema.sql supabase/schema_gt_options.sql
git add supabase/grade_options_seed.json supabase/grade_thresholds_seed.json supabase/grade_thresholds_gaps.json
git add website/migrations/
git add website/db.py
git add scripts/migrate_to_supabase.py scripts/import_grade_thresholds.py
git add set_admin.py push_fc_to_supabase.py
git commit -m @'
Extend schema: groups, flashcards, notes, grade thresholds, referrals

18 incremental migrations cover teaching tables, topic progress,
enrolment, onboarding flags, flashcards, notes, grade thresholds,
paper progress extra cols, and email log. Seed files for grade
thresholds and options added; admin helper and Supabase push scripts
included.
'@
```

---

## Commit 3 — Taxonomy: new syllabi & topic updates

```powershell
git add taxonomy/0620.json taxonomy/5070.json taxonomy/9618.json taxonomy/9709.json
git add taxonomy/0625.json taxonomy/5054.json taxonomy/9702.json
git commit -m @'
Add four new syllabus taxonomies and update existing ones

0620 (Biology OL), 5070 (Chemistry OL), 9618 (Computer Science AL),
9709 (Maths AL) added as standalone files. 0625, 5054, 9702 updated
to align with 2026-2028 syllabus structures.
'@
```

---

## Commit 4 — Pipeline: compose, testgen & grade-threshold fetch

```powershell
git add pipeline/compose.py pipeline/testgen.py
git add pipeline/fetch_gt.py pipeline/import_flashcards.py
git commit -m @'
Pipeline: watermark all body pages, add grade-threshold and flashcard fetchers

compose/testgen now stamp a faint PrepWithTee watermark on every body
page (not cover only). fetch_gt.py downloads grade-threshold tables
from the source site. import_flashcards.py seeds the flashcards DB
from a JSON dump.
'@
```

---

## Commit 5 — Auth, users & access control

```powershell
git add website/auth.py website/users.py website/users_db.py website/access.py
git add website/static/auth.js
git add website/static/login.html website/static/forgot-password.html
git add website/static/reset-password.html website/static/set-password.html
git add website/static/profile.html
git commit -m @'
Auth: JWT role routing, forgot/reset-password flow, access guards

Role-aware JWT middleware routes students, teachers, parents and admin
to their own dashboards. Forgot-password sends a time-limited reset
link; set-password handles first-login and reset. access.py enforces
per-route permission checks.
'@
```

---

## Commit 6 — Admin dashboard

```powershell
git add website/admin.py
git add website/static/admin.css website/static/admin.html website/static/admin.js
git add website/static/admin-student.js website/static/analytics.html
git commit -m @'
Add admin dashboard: forms, students, teachers, Calendly and analytics

Admin panel surfaces pending teacher applications, student/group
management, Calendly booking links, and a basic analytics view.
admin-student.js drives the student detail side-panel.
'@
```

---

## Commit 7 — Teacher portal

```powershell
git add website/teacher.py
git add website/static/teacher-apply.html website/static/teacher-dashboard.html
git add website/static/teacher-student.js website/static/teachers.html
git commit -m @'
Add teacher portal: application flow and teacher dashboard

Teachers apply via teacher-apply.html (pending admin approval).
Approved teachers see their student list, session history, and
homework assignments in teacher-dashboard.html.
'@
```

---

## Commit 8 — Student dashboard & progress tracking

```powershell
git add website/static/dashboard.html website/static/dashboard.js
git add website/static/dashboard-hub.css website/static/dashboard-hub.js
git add website/static/study-hub.html website/static/study.html
git add website/static/achievements.html website/static/calendar.html
git add website/static/homework.html website/static/homework.js
git add website/static/progress-shared.js website/static/progress-widget.js
git add website/static/paper-progress-widget.js
git add website/static/topical-progress.html website/static/topical-progress.js
git add website/static/yearly-progress.html website/static/yearly-progress.js
git add website/static/parent-dashboard.html website/static/messages.html
git add website/reminders.py website/scripts/
git commit -m @'
Student dashboard: progress widgets, homework, calendar, parent view

Unified dashboard hub with topical and yearly progress charts,
homework tracker, achievement badges, and a calendar. Parent
dashboard exposes their child's progress read-only. reminders.py
and scripts/ handle digest emails and homework notifications.
'@
```

---

## Commit 9 — Flashcards, quiz & MCQ solver

```powershell
git add website/flashcards.py website/mcq_report.py
git add website/static/flashcards.html website/static/fc-progress.html
git add website/static/quiz.html
git add website/static/mcq-solver.html website/static/mcq-solver.js website/static/mcq-session.css
git commit -m @'
Add flashcard system, quiz engine and MCQ solver

Flashcard deck management with spaced-repetition progress
(fc-progress). Quiz engine supports timed sessions. MCQ solver
renders past-paper multiple-choice questions interactively;
mcq_report.py aggregates attempt data.
'@
```

---

## Commit 10 — Notes & annotations

```powershell
git add website/static/notes.html website/static/notes.js website/static/notes-view.html
git add website/static/note-annotate.js website/static/note-context.js
git commit -m @'
Add notes editor with PDF annotation and context linking

Students create rich notes linked to specific past-paper questions.
note-annotate.js handles PDF overlay drawing; note-context.js
attaches notes to their source question context.
'@
```

---

## Commit 11 — Grade thresholds & calculator

```powershell
git add website/static/grade-calculator.html website/static/grade-calculator.js
git add website/static/grade-trends.html website/static/grade-trends.js
git commit -m @'
Add grade-threshold calculator and trends viewer

Grade calculator maps raw marks to A*-U grades using Cambridge
threshold data. Trends viewer charts a student's grade trajectory
across sessions and subjects.
'@
```

---

## Commit 12 — Study tools panel

```powershell
git add website/static/tools.html website/static/tools.css
git add website/static/tools-core.js website/static/tools-nav.js website/static/tools-dock.js
git add website/static/tools-adaptive.js website/static/tools-calculator.js
git add website/static/tools-graph.js website/static/tools-formulas.js
git add website/static/tools-commandwords.js website/static/tools-logic.js
git add website/static/tools-periodic.js website/static/tools-pseudocode.js
git add website/static/calculator.html website/static/graph.html
git add website/static/formulas.html website/static/definitions.html
git add website/static/pseudocode.html website/static/command-words.html
git add website/static/periodic-table.html website/static/bases-logic.html
git add website/static/graphs-guide.html website/static/islamiat-references.html
git commit -m @'
Add floating study-tools dock with subject-specific panels

Modular tools dock provides scientific calculator, graph plotter,
formula sheets, command-word glossary, logic-gate simulator,
periodic table, pseudocode guide, and bases converter - each
launchable from any page via tools-dock.js.
'@
```

---

## Commit 13 — Chatbot widget, AI ask & core app routes

```powershell
git add website/app.py website/static/app.js
git add website/static/chatbot-widget.css website/static/chatbot-widget.js
git add website/static/ask.html
git add website/blog.py website/static/course.html
git commit -m @'
Add AI chatbot widget, ask page, blog backend and core app routes

Embeddable chatbot widget surfaces Claude-powered answers in-page.
ask.html is a standalone Q&A interface. app.py gains routes for
subjects, library, papers, revise, blog posts, and the ask/chat
endpoints. blog.py manages content entries.
'@
```

---

## Commit 14 — Public marketing & legal pages

```powershell
git add website/static/index.html website/static/pricing.html
git add website/static/subjects.html website/static/contact.html
git add website/static/privacy.html website/static/terms.html
git add website/static/guide.html
git add website/static/resources.html website/static/resources.js
git add website/static/library.html website/static/library.js
git add website/static/papers.html
git add website/static/revise.html website/static/revise.js
git add website/static/tutor.html website/static/tutor.js
git add website/EMAIL_CAMPAIGNS.md website/ONBOARDING.md
git commit -m @'
Update public-facing pages: homepage, pricing, resources, legal

Homepage gains platform-preview imagery section. Pricing, subjects,
contact, privacy, and terms pages updated. Library, papers, and
revise pages refined. EMAIL_CAMPAIGNS.md and ONBOARDING.md added as
internal operational docs.
'@
```

---

## Commit 15 — Onboarding, tours & UX polish

```powershell
git add website/static/onboarding.js website/static/onboarding-panel.js
git add website/static/tour-engine.js website/static/tour-dashboard.js website/static/tour.js
git add website/static/persona-quiz.js website/static/walkthrough.html
git add website/static/upgrade-modal.js website/static/styled-dropdown.js
git add website/static/widgets.js
git commit -m @'
Add guided onboarding tours, persona quiz and reusable UX widgets

Tour engine drives step-by-step walkthroughs for the dashboard and
key features. Persona quiz tailors the onboarding path. Upgrade modal
surfaces plan prompts contextually. styled-dropdown.js and widgets.js
are shared UI primitives.
'@
```

---

## Commit 16 — Global styles, main JS & static assets

```powershell
git add website/static/styles.css website/static/main.js
git add "website/static/images/"
git add website/static/logo-nav.webp
git add website/static/student_study.webp website/static/taahaa.webp
git add website/static/marked_feedback.webp website/static/teaching_whiteboard.webp
git add website/public/
git commit -m @'
Update global stylesheet, shared JS and add marketing imagery

styles.css extended for new dashboard and tool components. main.js
gains shared init logic. Five new hero/preview images added for the
homepage platform-preview section and About page.
'@
```

---

## Files intentionally excluded

| File(s) | Reason |
|---|---|
| `taxonomy/*.json.bak` | Auto-generated backups — not source files |

If `website/public/` is a build-output directory you do not want in git, add it to `.gitignore` before commit 16 and omit it from that `git add`.
