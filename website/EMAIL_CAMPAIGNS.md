# PrepWithTee — Automated Student Email Campaigns

A retention-first email strategy. Every email should feel like it comes from
a tutor who genuinely cares — not a marketing bot.

---

## Strategy Overview

| Goal | Approach |
|---|---|
| Reduce churn | Inactivity sequences triggered on day 3, 7, 14 |
| Onboard well | 3-email drip over first 3 days |
| Feature adoption | Spotlight emails for AI tutor, topic library, test gen |
| Community feel | Warm, personal tone; never promotional |
| Exam readiness | Seasonal sequences for O/A-level windows |

**Tone rules:**
- Write as Tee (the tutor), not as "the PrepWithTee team"
- Short paragraphs. No bullet-list walls.
- One clear call to action per email
- Never mention "our platform", "our product", "click here"
- Unsubscribe link mandatory in every email footer

---

## Trigger Map

```
SIGNUP
  └─ immediately        → [W1] Welcome
  └─ +24 h              → [W2] Your First Step
  └─ +72 h              → [W3] Meet Your AI Tutor

LAST_ACTIVE
  └─ 3 days ago         → [R1] We Miss You
  └─ 7 days ago         → [R2] Still Procrastinating?
  └─ 14 days ago        → [R3] One Last Nudge

FIRST_TOPIC_COMPLETE    → [M1] Your First Topic Down
FIRST_TEST_GENERATED    → [M2] You Just Made a Mock Test
STREAK_7_DAYS           → [M3] 7 Days Strong

WEEKLY (every Sunday)   → [F1] This Week's Study Tip

SEASONAL
  └─ 8 weeks to O-Level → [S1] Your Exams Are 8 Weeks Away
  └─ 4 weeks to O-Level → [S2] Four Weeks. You've Got This.
  └─ 1 week to O-Level  → [S3] Final Week — How to Use Every Hour
```

---

## Email Drafts

---

### [W1] Welcome — sent immediately on signup

**Subject:** You're in. Let's make sure every mark counts.

---

Hi {first_name},

Welcome to PrepWithTee.

You just joined hundreds of students who are revising smarter — not harder.
Every question in this library is a real Cambridge exam question, sorted by
topic, with the mark scheme right next to it. No hunting through PDFs, no
guessing which papers to use.

Here's where to start:

**Pick your subject → pick a topic → download a question set.**

It takes 30 seconds. The first time you sit with a topical booklet and work
through it question by question, you'll feel the difference.

See you inside,
**Tee**
PrepWithTee

---

P.S. If you're not sure where to start, just reply to this email and tell me
which subject is giving you trouble. I read every reply.

---

### [W2] Your First Step — sent 24 h after signup

**Subject:** The single best thing you can do today (takes 10 minutes)

---

Hi {first_name},

Most students revise by reading their notes.

The problem? Reading feels like progress but it isn't. Your brain needs to
*retrieve* information under pressure — that's what the exam actually tests.

The fix is simple: **practice questions, by topic, from day one.**

Choose one topic you covered this week. Open the Library, filter by that topic,
and download the question set. Work through it with a pen and paper, then check
the mark scheme.

That's it. Ten minutes of active recall beats an hour of passive reading every
time.

Go try it → {library_url}

See you tomorrow,
**Tee**

---

### [W3] Meet Your AI Tutor — sent 72 h after signup

**Subject:** Stuck on a question at midnight? There's someone here.

---

Hi {first_name},

Ever been working through a past paper at 11 PM and hit a question you just
can't crack — with no one to ask?

That's exactly why we built the AI Tutor.

It's not a search engine. It's a tutor that knows the Cambridge syllabus
inside out. Ask it to explain a concept, walk you through a worked example,
or tell you why your answer got the marks wrong. It won't just give you the
answer — it'll help you *understand* it.

Click "Ask AI" on any question page and give it a go.

→ {ask_url}

Best,
**Tee**

---

### [R1] We Miss You — sent when inactive 3 days

**Subject:** Everything okay?

---

Hi {first_name},

I noticed you haven't been on in a few days. That's completely fine — life
gets busy.

But I also know how easy it is for revision to quietly slip off the list.
Before you know it, three days turns into three weeks.

You don't need a big session today. Just open one topic set, do three
questions, check the mark schemes. Literally ten minutes.

Small consistent sessions beat a panic cram every single time — and you
already have everything you need, right here.

Come back when you're ready → {library_url}

— **Tee**

---

### [R2] Still Procrastinating? — sent when inactive 7 days

**Subject:** I'll be honest with you.

---

Hi {first_name},

A week away from revision. I get it — sometimes the hardest part is just
starting again.

Here's what I've seen work for students who get stuck: **don't try to
"catch up"**. Forget the time you've missed. Just open one topic set —
any topic — and do the first question. That's the only goal.

You'll feel the gears start turning. Then do the second question. Then
check your answers against the mark scheme.

By the time you've done five questions you'll have forgotten you were even
putting it off.

The library is right where you left it → {library_url}

You've got this.
**Tee**

---

P.S. If something specific is blocking you — a topic you don't understand,
a question type that keeps tripping you up — reply to this email. I mean that.

---

### [R3] One Last Nudge — sent when inactive 14 days

**Subject:** One thing before I leave you alone

---

Hi {first_name},

I'm not going to keep sending you emails you're not finding useful. This
one's the last one for a while.

But before I go quiet, I want to leave you with this:

Cambridge O-Level and IGCSE exams reward students who have seen **lots of
questions** on a topic, not students who memorised a textbook. Every session
on PrepWithTee builds that pattern recognition — the kind that gets you from
a C to a B, or a B to an A.

When you're ready to come back — whether that's tomorrow or in a month —
everything will be here waiting.

→ {library_url}

Rooting for you,
**Tee**

---

*(You can unsubscribe from these emails below if you'd prefer not to hear
from us. No hard feelings.)*

---

### [M1] Your First Topic Down — milestone trigger

**Subject:** You just finished your first topic set ✓

---

Hi {first_name},

You just worked through a complete topic set. That might not sound like
much, but it's more than most students do in a month.

You've seen how the questions are structured, where the marks sit, what the
mark scheme expects. That knowledge compounds — every topic you do next
will feel a little faster, a little more familiar.

What's next? Pick the topic you're *least* comfortable with. That's where
the marks are hiding.

Keep going → {library_url}

**Tee**

---

### [M2] You Just Made a Mock Test — milestone trigger

**Subject:** Your mock test is ready. Here's how to use it.

---

Hi {first_name},

You've just generated your first mock test. Good move.

A few tips to get the most out of it:

Find a quiet 45 minutes. Put your phone in another room. Work through it
like it's the real thing — no peeking at the mark scheme until you're done.

When you check your answers, don't just mark right/wrong. For every
question you got wrong, read the mark scheme *carefully* and ask yourself
exactly where your answer missed the mark. That gap — between what you
wrote and what Cambridge wanted — is your revision target.

Repeat the same test in a week. You'll be surprised how much sticks.

— **Tee**

---

### [M3] 7-Day Streak — milestone trigger

**Subject:** 7 days in a row. That's not nothing.

---

Hi {first_name},

Seven days of consistent revision. You're building a habit — and that's
harder than any past paper question.

Students who revise in short daily sessions consistently outperform students
who cram in long occasional sessions. The science is clear on this. You're
already doing it right.

Keep the streak going → {library_url}

**Tee**

---

### [F1] Weekly Study Tip — every Sunday

**Subject:** One thing worth trying this week

---

Hi {first_name},

Quick one this week.

**Try "mark scheme first" on one question.**

Pick a question you're unsure about. Before you attempt it, read the mark
scheme. See exactly what Cambridge is looking for. Then close the mark
scheme, answer the question, and compare.

Most students treat mark schemes as answer keys. They're not — they're
blueprints for how to think about the question. Reading them *before*
answering teaches you the examiner's logic, which is half of what the
exam actually tests.

Give it a go this week in whatever topic you're revising.

→ {library_url}

Have a good week,
**Tee**

---

### [S1] Exams 8 Weeks Away — seasonal

**Subject:** 8 weeks. Here's exactly what to do with them.

---

Hi {first_name},

Eight weeks to your Cambridge exams. That's enough time to make a real
difference — if you're deliberate about it.

Here's what the next 8 weeks should look like:

**Weeks 1–4:** Topic-by-topic. Work through every topic in your syllabus
at least once. Don't try to master everything — just expose yourself to
the question types. Use PrepWithTee's Library, one topic per day.

**Weeks 5–6:** Targeted drilling. Go back to the topics where you lost the
most marks. Do more questions. Check every mark scheme carefully.

**Weeks 7–8:** Full mock papers and timed practice. Generate mock tests.
Simulate exam conditions. Review and repeat.

You already have everything you need for every one of those steps.

Let's go → {library_url}

**Tee**

---

### [S2] Exams 4 Weeks Away — seasonal

**Subject:** Four weeks. Every session counts now.

---

Hi {first_name},

Four weeks out, the margin for distraction is gone. But so is the pressure
to do everything — you just need to do the right things.

**If I were sitting your exams, here's what I'd do this week:**

Pick your two weakest topics. Download the full question set for each.
Work through them question by question, mark scheme open beside you —
not to copy, but to check your reasoning in real time.

Then generate a mock test mixing those two topics and do it timed.

That's one week of work that will move your mark more than ten hours of
notes ever could.

→ {library_url}

You're close. Keep going.
**Tee**

---

### [S3] Final Week — seasonal

**Subject:** One week to go. Here's how to use every hour.

---

Hi {first_name},

One week.

This is not the time for learning new material. If something is still
unclear at this point, a crash read of your textbook won't fix it — the
AI Tutor can help you get the gist in 10 minutes instead.

What *will* move your mark this week:

**Exam technique.** Go back to papers you've already done and re-read the
mark schemes for any question where you lost marks. Ask yourself: did I
misread the question? Did I give the right idea in the wrong words? Did I
forget the unit?

Cambridge marks are lost in the details, and the details are all in the
mark schemes you already have access to.

Rest well the night before. Eat before you go in. Read each question twice
before you write a word.

You've put in the work. Trust it.

— **Tee**

---

## Implementation Plan

### Phase 1 — Infrastructure (1–2 days)

**Email service:** [Resend](https://resend.com) — simplest API, generous free
tier (3 000 emails/month), excellent deliverability, Python SDK.

```
pip install resend
```

Env vars needed:
```
RESEND_API_KEY=re_...
EMAIL_FROM=tee@prepwithtee.com        # must be a verified domain
EMAIL_FROM_NAME=Tee @ PrepWithTee
SITE_URL=https://prepwithtee.com
```

**Unsubscribe token:** store a `uuid` per user in `email_preferences` table.
Every email footer links to `{SITE_URL}/unsubscribe?token={uuid}` — one-click,
no login required.

### Phase 2 — Database additions

```sql
-- email_preferences table
CREATE TABLE email_preferences (
    user_id      INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    unsubscribed BOOLEAN DEFAULT FALSE,
    unsub_token  TEXT UNIQUE NOT NULL DEFAULT (lower(hex(randomblob(16)))),
    updated_at   TIMESTAMPTZ DEFAULT now()
);

-- email_log table (idempotency — never send same email twice)
CREATE TABLE email_log (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    template_id TEXT NOT NULL,         -- e.g. 'R1', 'W2', 'M1'
    sent_at     TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, template_id)       -- milestones; for sequences use (user_id, template_id, sent_at::date)
);
```

For re-engagement sequences the UNIQUE constraint needs to be relaxed to allow
resending after a long gap — use `(user_id, template_id, date_trunc('month', sent_at))`.

### Phase 3 — Email renderer (`website/email_sender.py`)

```python
import resend, os, sqlite3
from datetime import datetime

resend.api_key = os.environ["RESEND_API_KEY"]

SITE_URL = os.environ.get("SITE_URL", "https://prepwithtee.com")

TEMPLATES: dict[str, dict] = {
    "W1": {
        "subject": "You're in. Let's make sure every mark counts.",
        "body_file": "email_templates/W1_welcome.html",
    },
    # ... one entry per template ID
}

def send_email(user_id: int, template_id: str, db_path: str):
    con = sqlite3.connect(db_path)
    user = con.execute(
        "SELECT email, name FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    prefs = con.execute(
        "SELECT unsubscribed, unsub_token FROM email_preferences WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    if not user or (prefs and prefs[0]):   # not found or unsubscribed
        return

    already_sent = con.execute(
        "SELECT 1 FROM email_log WHERE user_id = ? AND template_id = ?",
        (user_id, template_id)
    ).fetchone()
    if already_sent:
        return

    tmpl = TEMPLATES[template_id]
    html = open(tmpl["body_file"]).read().format(
        first_name=user[1].split()[0],
        library_url=f"{SITE_URL}/library",
        ask_url=f"{SITE_URL}/ask",
        unsub_url=f"{SITE_URL}/unsubscribe?token={prefs[1] if prefs else ''}",
    )

    resend.Emails.send({
        "from": f"{os.environ['EMAIL_FROM_NAME']} <{os.environ['EMAIL_FROM']}>",
        "to": [user[0]],
        "subject": tmpl["subject"],
        "html": html,
    })

    con.execute(
        "INSERT OR IGNORE INTO email_log (user_id, template_id) VALUES (?, ?)",
        (user_id, template_id)
    )
    con.commit()
```

### Phase 4 — Scheduler (`website/email_jobs.py`)

Runs from a daily cron job (`deploy/prepwithtee.cron`):

```python
"""
python -m website.email_jobs
Scans the DB and fires any due emails.
Run daily via cron, ideally at 09:00 local time.
"""

from datetime import datetime, timedelta
import sqlite3, os
from website.email_sender import send_email

DB = os.environ.get("DB_PATH", "data/index.db")

def run_all():
    con = sqlite3.connect(DB)

    # --- Onboarding sequence ---
    for days, template_id in [(0, "W1"), (1, "W2"), (3, "W3")]:
        cutoff = datetime.utcnow() - timedelta(days=days)
        users = con.execute(
            "SELECT id FROM users WHERE date(created_at) = date(?)", (cutoff,)
        ).fetchall()
        for (uid,) in users:
            send_email(uid, template_id, DB)

    # --- Re-engagement sequence ---
    for days, template_id in [(3, "R1"), (7, "R2"), (14, "R3")]:
        cutoff = datetime.utcnow() - timedelta(days=days)
        users = con.execute(
            """
            SELECT id FROM users
            WHERE date(last_active_at) = date(?)
              AND id NOT IN (
                SELECT user_id FROM email_log
                WHERE template_id = ?
                AND sent_at > datetime('now', '-30 days')
              )
            """,
            (cutoff, template_id)
        ).fetchall()
        for (uid,) in users:
            send_email(uid, template_id, DB)

    # --- Weekly tip (Sundays) ---
    if datetime.utcnow().weekday() == 6:
        users = con.execute("SELECT id FROM users").fetchall()
        for (uid,) in users:
            send_email(uid, "F1", DB)   # email_log UNIQUE on (user_id, template_id, week)

    # --- Seasonal emails (configure cutoff dates per exam window) ---
    # Add logic here when exam dates are known

if __name__ == "__main__":
    run_all()
```

Cron entry (daily at 09:00 PKT = 04:00 UTC):

```
0 4 * * * /root/prepwithtee/.venv/bin/python -m website.email_jobs >> /var/log/prepwithtee-email.log 2>&1
```

### Phase 5 — HTML Email Templates (`website/email_templates/`)

Each template is an HTML file. Keep them clean — single-column, max 600px,
inline CSS, muted PrepWithTee branding (owl logo, navy `#1a2e4a`, gold
`#c9a84c`).

Shared footer for every email:

```html
<table width="100%" cellpadding="0" cellspacing="0" style="margin-top:32px;
       border-top:1px solid #e5e7eb; padding-top:16px;">
  <tr>
    <td style="font-family:Georgia,serif;font-size:12px;color:#9ca3af;
               text-align:center;line-height:1.6;">
      PrepWithTee · Lahore, Pakistan<br>
      You're receiving this because you signed up at prepwithtee.com.<br>
      <a href="{unsub_url}" style="color:#9ca3af;">Unsubscribe</a>
    </td>
  </tr>
</table>
```

### Phase 6 — Unsubscribe endpoint (`website/app.py` addition)

```python
@app.route("/unsubscribe")
def unsubscribe():
    token = request.args.get("token", "")
    if not token:
        return "Invalid link.", 400
    db.execute(
        "UPDATE email_preferences SET unsubscribed = TRUE WHERE unsub_token = ?",
        (token,)
    )
    db.commit()
    return render_template("unsubscribed.html")   # simple "You've been unsubscribed" page
```

---

## Milestone Trigger Hooks

These fire inside existing route handlers:

```python
# After first successful library download
from website.email_sender import send_email
send_email(current_user.id, "M1", DB)     # email_log UNIQUE prevents duplicates

# After first test generated
send_email(current_user.id, "M2", DB)

# Streak tracked in users table; checked on each login
if user.streak_days == 7:
    send_email(user.id, "M3", DB)
```

---

## Metrics to Watch

| Metric | Target | Action if below |
|---|---|---|
| Open rate | > 40% | Rewrite subject lines |
| 3-day re-engagement click rate | > 15% | Soften R1 copy |
| Unsubscribe rate | < 2% / month | Reduce frequency |
| Day-7 retention (signup → active 7 days later) | > 30% | Improve W2/W3 |

Use Resend's built-in analytics dashboard for opens/clicks. Track
re-engagement by querying `last_active_at` before and after email send dates.

---

## Future Additions (not in scope now)

- **Progress digest** — weekly personalised "you've done X questions, your
  strongest topic is Y" (needs more activity tracking in DB)
- **Parent CC** — optional, for younger students; parent receives a summary
  once a week
- **Exam countdown** — dynamic subject line ("14 days to your O-Level Physics")
  using a per-user exam_date field
- **A/B testing subject lines** — Resend supports this natively
