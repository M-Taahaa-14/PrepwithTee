# Onboarding System — PrepWithTee

## What Was Built

### Phase A — Backend Infrastructure

| File | Change |
|---|---|
| `website/users_db.py` | Added `flags_json TEXT NOT NULL DEFAULT '{}'` to SQLite schema + `_safe_alters` migration list; added `merge_flags(user_id, key, value)` function |
| `website/auth.py` | Added `"flags_json"` to `_FAST_FIELDS` so it travels in the JWT (no extra DB round-trip on every request) |
| `website/users.py` | Added `PATCH /api/flags` endpoint — validates key format, merges one flag into `flags_json`, degrades gracefully if DB column missing |
| `website/migrations/006_onboarding_flags.sql` | Supabase migration — **run this once in Supabase SQL Editor** (see below) |

**⚠️ Required action:** Run in Supabase Dashboard → SQL Editor:
```sql
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS flags_json
    TEXT NOT NULL DEFAULT '{}';
```
Until this runs the tour still works (flags held in localStorage), but won't sync across devices.

---

### Phase B — Get Started Checklist Panel

| File | Change |
|---|---|
| `website/static/onboarding.js` | Shared ES module — `getFlag()`, `getAllFlags()`, `setFlag()`. localStorage write-cache with background `PATCH /api/flags` sync. |
| `website/static/onboarding-panel.js` | Self-contained panel + `?` help button. Mounts into the nav next to the bell. Auto-shows once for new users (empty flags). |
| `website/static/auth.js` | Added `import("/onboarding-panel.js").then(m => m.mountOnboarding(user))` at the end of the signed-in nav setup. |
| `website/static/styles.css` | Added `.ob-` prefixed styles for the panel and `?` button (bottom of file). |

**Behaviour:**
- `?` button appears in the nav for all signed-in users
- Panel lists 6 platform areas: Dashboard, Chapter Tracker, Topical Papers, AI Tutor, Resources, Study Tools
- Gold progress bar shows how many areas are "explored"
- "Explore →" marks the item explored + navigates to `<page>?tour=1`
- "Remind me later" sets `onboarding_dismissed` flag and won't auto-show again
- "Full guide →" links to the existing `/walkthrough.html` article
- Checklist row turns green ✓ when the corresponding `tour_<key>` flag is set

---

### Phase C — Dashboard Walkthrough

| File | Change |
|---|---|
| `website/static/tour.js` | Vanilla spotlight tour engine. 4-panel overlay, tooltip with label pill + dots + caret arrow. Matches Cambridge Assistant reference design. |
| `website/static/tour-dashboard.js` | Dashboard-specific steps (6 steps). Sets `tour_dashboard` flag on complete or skip. |
| `website/static/dashboard.html` | Added `<script type="module">` that calls `initDashboardTour()` — fires when `?tour=1` is in the URL. |
| `website/static/styles.css` | Added `.tour-` prefixed styles: overlay masks, tooltip card, amber highlight ring, caret arrow, dot indicators, mobile overrides. |

**Dashboard tour steps:**
1. `.dash-greeting` — Welcome intro
2. `#ring-row` — Subject confidence rings
3. `.dash-actions` — Quick actions
4. `#quiz-history` — Recent practice
5. `#dash-homework` — Homework section
6. `#enrol-grid` — Add a subject

**Tooltip anatomy (per reference):**
```
┌──────────────────────────────────────────┐
│  [DASHBOARD · STEP 2 OF 6]         [✕]  │
│  Bold heading                             │
│  Body description text                    │
│  ●●○○○○   [Skip tour]   [Next ›]         │
└──────────────────────────────────────────┘
       ▲ amber caret pointing at element
```

---

## What Still Needs to Be Done

### Per-page tours (Phase D)

Each tour is ~30–40 lines following the exact same pattern as `tour-dashboard.js`. Add the import to each page's HTML with the same one-liner.

| Page | Tour file to create | Key elements to highlight |
|---|---|---|
| `revise.html` | `tour-revise.js` | `#revise-subjects`, mode toggle `.revise-modes`, chapter row in `#topic-list`, quiz button |
| `papers.html` | `tour-papers.js` | Subject selector, topic filter, year range, generate button (action: click) |
| `ask.html` | `tour-ask.js` | Subject context selector, question input, submit button (action: click), response area |
| `resources.html` | `tour-resources.js` | Resource category cards |
| `formulas.html` | `tour-tools.js` | Formula search, subject filter, derivation expand |

**Template for each new tour:**
```javascript
import { startTour, autoStartTour } from "/tour.js";
import { setFlag }                   from "/onboarding.js";
import { getUser }                   from "/auth.js";

const STEPS = [
  { element: "#some-id", title: "...", body: "..." },
  // ...
];

async function _markSeen() {
  const user = await getUser();
  if (user) setFlag(user, "tour_<key>");
}

export function initPageTour() {
  autoStartTour(STEPS, { label: "PAGE NAME", onComplete: _markSeen, onSkip: _markSeen });
}
```

Add to the page's HTML:
```html
<script type="module">
  import { initPageTour } from "/tour-<page>.js";
  initPageTour();
</script>
```

---

### Admin plan management (Phase 1 remainder)

Plan dropdown in the admin student-detail panel so the tutor can set Free / Pro / Premium / Tutoring without touching the DB directly. Route `PATCH /api/admin/students/{user_id}/plan` exists in the plan but isn't built yet.

### Re-trigger from the panel

Currently `mountOnboarding()` in `onboarding-panel.js` only auto-starts the tour for brand-new users. For returning users who want to replay a tour, the "Explore →" button on an already-explored item should change to "Replay tour →" and re-trigger the tour on the current page if already on it, or navigate with `?tour=1` if not. Minor UX improvement.

### Supabase migration

Run `website/migrations/006_onboarding_flags.sql` in Supabase to persist flags server-side.
