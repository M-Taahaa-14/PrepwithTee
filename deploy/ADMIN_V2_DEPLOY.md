# Deploying admin console v2 (and everything else not yet live)

The working tree holds **everything since the last deploy (commit 5ccef91 on the server)**:
admin console v2 (phases 1-4), the strict Solo / 3 Subjects plans, the payment
checks, plus the earlier undeployed work in CLAUDE.md items 27-34 (calculator,
notes, section pages, UI rounds, viewer speed fixes). It all goes out together.

Server: `ubuntu@161.118.190.49`, key `C:\Users\user\ssh\ssh-key-2026-07-22.key`,
code in `/srv/prepwithtee`, env in `/etc/prepwithtee.env`, service `prepwithtee`
(gunicorn, Python **3.10**, 2 workers).

---

## 0. Commit (so there is something to roll back to)

```bash
git add -A
git commit -m "Admin console v2, strict plan subjects, payment checks, AI writing"
```

## 1. Database first - Supabase SQL editor

Run these files **in order**, each pasted whole. Every statement is
`IF NOT EXISTS`, so re-running one that was already applied is harmless.

1. `website/migrations/023_calc_state.sql`  (calculator memory - if not run yet)
2. `website/migrations/024_feedback_email.sql`  (feedback email column - if not run yet)
3. `website/migrations/025_admin_v2.sql`  (admin audit/views/notes, plan subjects,
   payment period/hash, inbox status, newsletter jobs, blog scheduling/revisions,
   course FAQ, usage per subject, last_seen_at)

Check: `select count(*) from admin_audit;` returns 0 (the table exists).

## 2. Give your account the admin role

The new console only lets in accounts whose role is `admin`. From the repo
root (this writes to Supabase through `.env`):

```bash
.venv\Scripts\python scripts\set_admin.py nexgentutors6@gmail.com
.venv\Scripts\python scripts\set_admin.py nexgentutors6@gmail.com --apply
```

The first line is a dry run that shows what it will change.

## 3. Ship the code

Code only (`website/`, `pipeline/`, `deploy/`), staged in /tmp because
`/srv/prepwithtee` is root-owned. PowerShell:

```powershell
$key = "C:\Users\user\ssh\ssh-key-2026-07-22.key"; $srv = "ubuntu@161.118.190.49"
tar --exclude=__pycache__ --exclude=*.pyc -czf $env:TEMP\pwt-code.tgz website pipeline deploy taxonomy
scp -i $key $env:TEMP\pwt-code.tgz "${srv}:/tmp/"
ssh -i $key $srv @'
set -e
sudo tar -czf /srv/backup-code-$(date +%Y%m%d-%H%M).tgz -C /srv/prepwithtee website pipeline deploy taxonomy
rm -rf /tmp/stage && mkdir /tmp/stage && tar -xzf /tmp/pwt-code.tgz -C /tmp/stage
/srv/prepwithtee/.venv/bin/python -m compileall -q /tmp/stage/website /tmp/stage/pipeline
sudo rsync -a /tmp/stage/ /srv/prepwithtee/
sudo systemctl restart prepwithtee
sleep 4; curl -s localhost:8017/api/health
'@
```

`compileall` runs with the server's own Python 3.10, so any syntax that only
works on newer Python stops the deploy **before** anything is replaced.

## 4. AI writing keys (optional but needed for the AI buttons)

The blog / course / newsletter writers use the free providers already in
`/etc/prepwithtee.env`, in this order: Mistral, NVIDIA, Gemini, then Groq text
last (Groq's allowance is shared with the live follow-up chat; the Photo
Solver's Groq vision budget is never used). Without any key the editors still
work - the AI buttons just say no provider is set up.

## 5. Check it live (5 minutes)

1. Open `https://prepwithtee.com/admin` and sign in with Google. You should land
   on Overview.
2. Students: sort a column, filter by plan, open a student.
3. Payments: any old pending Solo / 3 Subjects proof asks you to pick subjects
   when approving (they were submitted before subjects were recorded).
4. Blog studio: New post, then "Plan the outline". You should get an outline
   in under a minute.
5. Audit log: your actions show up.

The old page stays reachable at `/admin.html` (sidebar: "Classic admin") as a
fallback for a week or two; it uses the admin key as before.

## Roll back

```bash
ssh -i <key> ubuntu@161.118.190.49 "sudo tar -xzf /srv/backup-code-<stamp>.tgz -C /srv/prepwithtee && sudo systemctl restart prepwithtee"
```

The migrations only add tables and columns, so the old code keeps working on
the new schema - no database rollback is needed.
