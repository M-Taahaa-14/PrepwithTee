# PrepWithTee — Feature & Fix Plan
_Generated 2026-08-29. Tasks ordered easy → hard within each tier._

---

## Tier 1 — Quick Fixes (≤ 1 day each)

### 1. Welcome Email on Signup
**Files:** `website/auth.py` (POST /auth/register + Google callback)  
Both registration paths exist but only teacher-approval sends a welcome email. Add a `send_welcome_email(user)` call in:
- `POST /auth/register` after user is created
- `GET /auth/google/callback` when `is_new_user == True`

Email content: personalised greeting, what they can do on free plan, link to dashboard, upgrade CTA.

---

### 2. Newsletter — What Happens After Signup
**Files:** `website/app.py` (POST /api/newsletter — stores row in `newsletter` table, nothing else)  
Currently a black hole. Fix:
- Send a welcome/confirmation email immediately on signup (e.g. "You're on the list — here's what PrepWithTee can do for you")
- Add `GET /api/admin/newsletter/broadcast` endpoint so admin can compose + send to all confirmed subscribers (Resend batch API, 100/batch)
- Add unsubscribe token column + `/unsubscribe?token=` route so every email has a valid opt-out

---

### 3. Plan Expiry & Retention Emails
**Files:** new `website/reminders.py` additions or a standalone `scripts/email_lifecycle.py` cron script  
Run via cron (daily). Queries:
- `plan_expires_at BETWEEN now() AND now() + 3 days` → "Your plan expires soon" email with payment link
- `plan_expires_at < now() AND plan != 'free'` → "Your trial has ended" downgrade notice + upgrade CTA
- `last_seen > 7 days ago AND plan != 'free'` → "We miss you" re-engagement email
- `created_at = 7 days ago AND plan = 'free'` → "1-week check-in" onboarding nudge

Add cron entry in `deploy/prepwithtee.cron` (already exists). Resend batch for bulk, individual transactional for expiry.

---

### 4. Yearly Progress 500 Error — Grade Thresholds Not Loading
**Files:** `website/users.py` (`GET /api/grade-thresholds`, `POST /api/scores`)  
The explorer found `grade_thresholds` table and `student_scores` table. Likely causes:
- `grade_thresholds` table doesn't exist in Supabase (schema not migrated) — check `supabase/schema.sql` and missing migration
- `student_scores` INSERT missing `set_by` column or wrong column name
- Marks field type mismatch (string vs int)

Debug path: hit `/api/grade-thresholds?syllabus=0625` with auth, read the 500 traceback in logs, patch the column/migration.

---

### 5. Groups — Full Teacher Workflow Fix
**Files:** `website/teacher.py` (POST /api/teacher/groups), `website/static/teacher-dashboard.html`  
Current gaps:
- `POST /api/teacher/groups` creates a group but has no student-add step
- No endpoint to add/remove individual students from a group: add `POST /api/teacher/groups/{id}/members` and `DELETE /api/teacher/groups/{id}/members/{student_id}`
- UI doesn't present a student picker or a "purpose/subject" field

Full desired workflow:
1. Teacher clicks **New Group** → modal asks: name, description, subject (syllabus), max students, schedule
2. After creation, immediately opens a member picker showing teacher's allocated students → multi-select → `POST /api/teacher/groups/{id}/members`
3. Group detail page shows members list, session log (already exists via `POST /api/teacher/groups/{id}/sessions`)
4. Admin `GET /api/admin/groups` already supports viewing all groups — wire PATCH for status changes

---

### 6. Class Log — Calendar Style in Teacher Portal
**Files:** `website/static/teacher-dashboard.html`, teacher JS  
Student-facing calendar (`/calendar.html`) already implements the FullCalendar-style view. When teacher views a student's class log, render the same calendar widget already used on the student's own calendar page — pass the class-log events from `GET /api/teacher/student/{id}/class-log` as event objects. No new endpoints needed.

---

### 7. Student Qualification Update + Archive Flow
**Files:** `website/users.py` (`PATCH /api/profile`), `website/static/profile.html`  
`grade` field (O Level / IGCSE / A Level) is stored on `profiles` but the profile PATCH likely allows any value. Add logic:
- On grade change → move all current `enrollments` rows to `status='archived'` (keep them)
- New enrollments start fresh under the new qualification
- Add a "Restore" button on the profile page to un-archive individual old enrollments
- Show archived enrollments in a collapsed section of the profile page

---

### 8. Chat History Sidebar — Minimizable (AI Tutor)
**Files:** `website/static/tutor.html`, `website/static/tutor.js`  
Add a toggle button that slides the sidebar off-canvas (CSS `transform: translateX(-100%)` with transition). Store collapsed state in `localStorage`. The chat area expands to fill the freed width. One small JS event listener + two CSS classes.

---

## Tier 2 — Medium Features (2–5 days each)

### 9. AI Tutor — Response Formatting & LaTeX Fix
**Files:** `website/static/tutor.js`, `website/static/tutor.html`  
Current issues: LaTeX shows raw `\frac{}{}` code; response width too narrow; step-by-step unclear.  
Fix plan:
- Load KaTeX (or MathJax) — self-host the CSS/JS in `static/`, no CDN — and call `renderMathInElement` after each assistant message is inserted into the DOM
- Ensure the markdown renderer (marked.js) runs first, then KaTeX on the result
- Widen the message bubble: `max-width: min(80ch, 90%)` instead of the current constrained width
- Add a CSS class `.step-block` for numbered steps (AI system prompt instructs it to wrap steps in `<step>` tags); render them as numbered cards
- System prompt addition: "Always wrap LaTeX in `$...$` for inline and `$$...$$` for display math. For fractions always use `\dfrac`. For step-by-step, number each step clearly."

---

### 10. Referral Code System
**Files:** `website/users.py`, `website/static/profile.html`, new DB migration  
Schema additions (new migration file `website/migrations/013_referrals.sql`):
```sql
ALTER TABLE profiles ADD COLUMN referral_code TEXT UNIQUE;
CREATE TABLE referral_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  referrer_id UUID REFERENCES profiles(id),
  referee_id  UUID REFERENCES profiles(id),
  status TEXT DEFAULT 'pending',  -- pending|rewarded
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE user_points (
  user_id UUID PRIMARY KEY REFERENCES profiles(id),
  points INT DEFAULT 0,
  updated_at TIMESTAMPTZ DEFAULT now()
);
```
Flow:
1. Every new profile gets a unique referral code generated on creation (e.g. `TAAHAA-XK42`)
2. Marketing/signup pages accept `?ref=CODE` query param → stored in a cookie
3. On `POST /auth/register` or Google callback: if referral cookie exists, resolve referrer → insert `referral_events` row + award 50 points to referrer
4. Student profile page shows their referral code + copy link button + points balance + how many friends joined
5. Points are cosmetic for now (display only) — future: redeem for extra AI quota days

---

### 11. Teacher ↔ Parent Connectivity
**Files:** `website/teacher.py`, `website/users.py`, `website/static/teacher-dashboard.html`  
Current state: `parent_student_links` table exists; parents can view their child's progress. Teachers have no visibility of who the parent is.

Add:
- `GET /api/teacher/student/{id}/parent` — returns linked parent's name + email (if any)
- `POST /api/teacher/student/{id}/parent-message` — sends message into the same `messages` conversation table but with the parent as recipient (conversation_id keyed by `teacher_id + parent_id`)
- Teacher dashboard student card shows a "Parent" badge if linked, with a "Message Parent" button
- Parent portal (`/parent-dashboard.html`) gains a **Messages** tab — mirrors student messages UI but scoped to parent_id — so parent can ask teacher questions and receive updates
- Teacher also gets a notification when parent sends a message (joins the existing `/api/teacher/notifications` response)

---

### 12. Student Analytics — Topical & Yearly Progress (Editable)
**Files:** `website/users.py`, `website/teacher.py`, `website/admin.py`, relevant HTML pages  
Currently `topic_progress` and `paper_progress` exist with full CRUD. The issue is UI consistency — the same data is shown differently (or not at all) in each portal.

Standardise into a shared `ProgressWidget` HTML+JS component (one file: `static/progress-widget.js`) that takes:
- `apiBase` (e.g. `/api`, `/api/teacher/student/123`, `/api/admin/students/123`)
- `readOnly` flag
- `syllabus` filter

Render the same chapter-by-chapter ring + subtopic status table everywhere. Admin and teacher views get an **Edit** button per row (inline status dropdown + notes field). The student view is also editable (they can self-report confidence). All writes go through the same DB table via whichever API prefix is appropriate for the caller's role.

Yearly progress (paper_progress): same idea — a `PaperProgressWidget` showing paper grid with score entry. Grade auto-calculated from thresholds.

---

### 13. Plans — Strict Enforcement + Admin Plan Update
**Files:** `website/access.py`, `website/admin.py`, `website/static/pricing.html`, `website/static/admin.js`  
Current state: `require_plan()` and `check_quota()` exist but plan upgrade only happens via payment proof approval.

Additions:
- Admin students table gains a **Plan** column with an inline dropdown → `PATCH /api/admin/students/{id}` with `{plan: "three"}` already exists; wire the UI
- Admin student detail page shows current plan + expiry with an **Override Plan** form (plan + expiry date)
- `plan_expires_at` is already in the DB; ensure every `check_quota()` call re-reads it from DB (not JWT) — `access.py` `require_plan` already does a fresh fetch, verify this is true for quota checks too
- Payment proof approval flow: on approval in admin UI, show a modal to confirm which plan tier and expiry to set before submitting — currently it auto-sets from the `plan` field on the proof, which may differ from what admin wants
- Pricing page plans must exactly match the constants in `access.py` (`PLAN_RANK`, `MONTHLY_QUOTAS`) — audit and align

---

## Tier 3 — Large Features (1–2 weeks each)

### 14. Admin UI Overhaul
**Files:** `website/static/admin.html`, `website/static/admin.js`, `website/static/admin.css`, new `website/static/admin-student.js`  
Current state: functional but rough — plain table rows, minimal styling, no data visualisation, no consistent card/panel design language.

Target: professional dashboard aesthetic matching the student dashboard's design system (navy/gold/cream brand colours from `styles.css`). Key changes:
- **Sidebar:** icon + label nav, collapsible, active state highlight, badge counters for pending items (payments, applications)
- **Overview section:** KPI stat cards (total students, active this week, revenue, pending payments) with sparkline charts
- **Student table:** avatar + name + plan badge + last-seen chip; inline search + filter by plan/syllabus; row expands to show quick stats
- **Student detail panel:** full-width drawer/modal replacing the current inline expansion — tabs for: Profile | Progress | Assignments | Class Log | Messages | Scores | Plan
- **Groups page:** card grid instead of table; member count chips; status badges
- **Payments page:** image thumbnail of proof screenshot; approve/reject with one click in a review modal
- **Consistent use of the brand colour tokens** already defined in `styles.css` (--navy, --gold, --cream, --soft-text)

---

### 15. Teacher Portal UI Overhaul + Full Analytics
**Files:** `website/static/teacher-dashboard.html` and related JS  
Same principle as admin overhaul. Teacher-specific additions:
- Student roster with per-student progress summary (% chapters confident) and last class date
- Clicking a student opens a drawer: Progress | Assignments | Class Calendar | Messages | Parent
- Class log is rendered as a FullCalendar (same as student's own calendar — reuse that component)
- Analytics tab for teacher's own teaching stats: classes held this month, assignment completion rates, average student progress gain
- Groups page: card grid; member management; session history timeline

---

### 16. Homepage Dark Mode + Tablet/Study Imagery
**Files:** `website/static/index.html`, `website/static/styles.css`, `website/static/main.js`  
- Add full `prefers-color-scheme: dark` CSS variable overrides (--bg, --text, --card-bg, --border, etc.) throughout `styles.css` — the site currently has no dark mode at all
- Add a manual dark mode toggle (moon/sun icon in nav) storing preference in `localStorage`
- New homepage section **"How It Works"** / **"Study on Any Device"**: 3-panel layout with:
  - iPad mockup frame containing a screenshot of the student dashboard
  - A "studying" lifestyle image (use free Unsplash URLs the user must supply, or placeholder gradients until images are ready)
  - A tablet mockup showing the AI tutor chat
- Use CSS `clip-path` device frames rather than image-based frames so they scale cleanly

---

### 17. Live Help Chatbot Widget
**Files:** new `website/static/chatbot-widget.js`, `website/static/chatbot-widget.css`, add script tag to all HTML pages, new backend route `POST /api/chatbot`  
A floating chat bubble (bottom-right corner) visible on all public pages (index, pricing, subjects, guide) for pre-sale/support questions.

Backend (`POST /api/chatbot`):
- Unauthenticated (or uses session if available)
- Rate-limited: 10 messages / hour per IP
- Context: small system prompt about PrepWithTee — plans, subjects, how to sign up, Calendly link for demos
- Provider: same Groq chain already in place (fast, cheap)
- Stores conversation in `localStorage` (browser-side only; no server persistence needed for anonymous visitors)

Frontend widget:
- Floating button with PrepWithTee owl icon
- Slide-up panel (300×480px) with chat UI matching the brand
- Pre-set quick chips: "What subjects do you offer?", "How much does it cost?", "Book a demo"
- Respects dark mode toggle

---

## Email Infrastructure Summary

All email sends use the existing Resend integration in `app.py` (`send_email()` helper). New email triggers needed:

| Trigger | When | Template |
|---|---|---|
| Welcome | Register / Google signup | Personalised, dashboard link |
| Newsletter confirm | POST /api/newsletter | What to expect, unsubscribe link |
| Plan expiry warning | 3 days before expiry (cron) | Renew CTA with payment link |
| Plan expired | Day of/after expiry (cron) | Downgrade notice, upgrade CTA |
| Re-engagement | 7+ days inactive, paid plan (cron) | "We miss you", recent content highlights |
| Onboarding nudge | Day 7 after signup, free plan (cron) | Feature highlights, upgrade offer |
| Referral reward | When referee completes signup | "Your friend joined! +50 points" |
| Parent message | Teacher sends parent message | Email notification to parent |

---

## Open Questions for Tutor Before Building

1. **Referral points** — what can points be redeemed for? Extra AI quota days? Discount on subscription? Or purely cosmetic (a leaderboard)?
2. **Dark mode homepage images** — do you have brand-consistent photos of students studying with iPads, or should we use illustrated device frames with screenshots?
3. **Newsletter broadcast** — do you want a full compose UI in admin, or just a list export (CSV of emails) to use with a tool like Mailchimp/Brevo?
4. **Live chatbot** — should it also be available inside the student portal (e.g. as a "Help" button) or only on public marketing pages?
5. **Yearly progress 500 error** — can you share the exact error from server logs? (`journalctl -u prepwithtee -n 50` on the server)
