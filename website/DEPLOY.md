# Deploying PrepWithTee to an Oracle Cloud Always Free VM

The site is a stateful FastAPI app: it reads a 21 MB SQLite index, streams PDFs
off local disk, and shells out to `pipeline.compose` to build booklets. That
rules out Vercel, Netlify and any serverless host — they give you a read-only
filesystem and kill long-running subprocesses. It needs a plain Linux VM.

Everything below assumes Ubuntu 22.04 on an Ampere A1 (ARM) shape.

---

## 0. What actually ships

`data/` on the dev machine is about **4.4 GB**, but most of it is build
artifacts the running site never opens:

| Directory      | Size    | Ship it? | Why |
|----------------|---------|----------|-----|
| `data/raw`     | 761 MB  | **yes**  | the library streams these; compose crops from them |
| `data/index.db`| 21 MB   | **yes**  | topics, classifications, paper metadata |
| `website/`     | 5 MB    | **yes**  | the site |
| `pipeline/`    | small   | **yes**  | compose / testgen / mcq |
| `taxonomy/*.json` | 100 KB | **yes** | topic lists |
| `taxonomy/*.pdf`  | 9 MB   | no       | official syllabus documents, reference only |
| `data/crops`   | 1.6 GB  | no       | compose uses `rel_path` + stored rects, never these |
| `data/debug`   | 991 MB  | no       | segmentation check images |
| `data/output`  | 897 MB  | no       | CLI output; the web app writes to a temp dir |
| `data/batches` | 3 MB    | no       | classification workflow only |

**Upload is therefore ~790 MB, not 4.4 GB.** `deploy/sync.sh` already excludes
the right things.

---

## 1. Provision the instance

1. Create the Oracle Cloud account (a card is needed for identity checks; Always
   Free resources are not billed). Pick your **home region carefully — it cannot
   be changed later.** Choose one close to your students.
2. Compute → Instances → Create instance.
   - Image: **Canonical Ubuntu 22.04**
   - Shape: **Ampere A1 Flex** — give it whatever the free allocation currently
     permits (historically 4 OCPU / 24 GB, since reduced). 1 OCPU / 6 GB is
     already plenty for this app.
   - Add your SSH **public** key.
   - Boot volume: 100 GB or more (free tier includes 200 GB total block storage).
3. **If you get "Out of host capacity"** — that is the well-known ARM shortage,
   not a mistake on your part. Retry later, try another availability domain, or
   fall back to the always-available `VM.Standard.E2.1.Micro` x86 shape.

> **ARM note:** the app's one heavy dependency is PyMuPDF. Verify early —
> after step 3, `python -c "import fitz; print(fitz.__doc__)"` must work. If a
> wheel is unavailable for aarch64 you would be facing a source build, which is
> the one genuinely painful scenario; the x86 micro shape avoids it entirely.

---

## 2. Open the ports — both layers

**This is the step that catches nearly everyone on Oracle Cloud.** There are
*two* firewalls and opening only the first leaves you with a site that times out
for no visible reason.

**Layer 1 — the VCN security list** (in the web console):
Networking → Virtual Cloud Networks → your VCN → Security Lists → Default →
Add Ingress Rules:

| Source    | Protocol | Destination port |
|-----------|----------|------------------|
| 0.0.0.0/0 | TCP      | 80               |
| 0.0.0.0/0 | TCP      | 443              |

**Layer 2 — iptables on the instance itself.** Oracle's Ubuntu images ship with
netfilter rules that drop everything except SSH, and they persist across
reboots:

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80  -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

Check it took: `sudo iptables -L INPUT -n --line-numbers | head`

---

## 3. Base setup

```bash
ssh ubuntu@<your-ip>

sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-venv python3-pip rsync

# A 6 GB box builds wheels fine, but swap is cheap insurance on the 1 OCPU shape
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Service account that owns the app but cannot log in
sudo useradd --system --create-home --home-dir /srv/prepwithtee --shell /usr/sbin/nologin prepwithtee
sudo mkdir -p /srv/prepwithtee/data
sudo chown -R prepwithtee:prepwithtee /srv/prepwithtee

# Let your login user write there so rsync works without root
sudo usermod -aG prepwithtee ubuntu
sudo chmod -R g+w /srv/prepwithtee
```

Log out and back in for the group change to apply.

---

## 4. Upload

From the repo root on your Windows machine, in **Git Bash**:

```bash
bash deploy/sync.sh ubuntu@<your-ip>
```

First run pushes ~790 MB. Re-runs only send what changed and take seconds.
If your connection drops, just run it again — rsync resumes.

---

## 5. Python environment

```bash
cd /srv/prepwithtee
sudo -u prepwithtee python3 -m venv .venv
sudo -u prepwithtee .venv/bin/pip install --upgrade pip
sudo -u prepwithtee .venv/bin/pip install -r requirements.txt

# prove PyMuPDF is fine on ARM before going further
sudo -u prepwithtee .venv/bin/python -c "import fitz; print('PyMuPDF', fitz.VersionBind)"
```

---

## 6. Secrets

```bash
sudo tee /etc/prepwithtee.env >/dev/null <<'EOF'
ANTHROPIC_API_KEY=sk-ant-...
GROQ_API_KEY=gsk_...
SMTP_USER=nexgentutors6@gmail.com
SMTP_PASS=your-gmail-app-password
EOF
sudo chmod 600 /etc/prepwithtee.env
```

Use a Gmail **App Password**, never the account password.

Each key enables one feature and every feature degrades gracefully without it:

| Variable | Powers | Without it |
|----------|--------|-----------|
| `ANTHROPIC_API_KEY` | Ask page (photo → worked solution) | "not switched on yet" message |
| `GROQ_API_KEY` | AI Tutor (question generator / concept chat) | "not switched on yet" message |
| `SMTP_USER`/`SMTP_PASS` | Demo-booking email notification | booking still saved to `data/leads.db`, email skipped |

Get the free Groq key at **console.groq.com → API Keys** (starts `gsk_`). The
tutor also supports `OPENROUTER_API_KEY` and `CEREBRAS_API_KEY` as automatic
fallbacks — set any you have and the first that answers is used.

---

## 7. Run it as a service

```bash
sudo cp /srv/prepwithtee/deploy/prepwithtee.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now prepwithtee
sudo systemctl status prepwithtee

curl -s localhost:8017/api/health
# {"status":"ok","papers":1378,"archive_present":true}
```

If it fails to start: `sudo journalctl -u prepwithtee -n 50 --no-pager`

---

## 8. Domain and HTTPS

Point an **A record** at the instance's public IP first and let it propagate —
Caddy needs the domain resolving to this box before it can get a certificate.

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy

sudo cp /srv/prepwithtee/deploy/Caddyfile /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile     # put your real domain in
sudo systemctl reload caddy
sudo journalctl -u caddy -n 30 --no-pager   # watch the certificate arrive
```

---

## 9. Keep-alive

Free-tier hosts may reclaim instances that look idle. A request a few times an
hour is enough, and it doubles as a health check:

```bash
sudo -u prepwithtee crontab -e
# */20 * * * * curl -fsS localhost:8017/api/health >/dev/null 2>&1
```

---

## 10. Back up the leads

`data/leads.db` holds every demo booking and is the one file you cannot
regenerate. Everything else can be rebuilt from the pipeline.

```bash
sudo -u prepwithtee crontab -e
# 0 3 * * * cp /srv/prepwithtee/data/leads.db /srv/prepwithtee/data/leads-$(date +\%u).db
```

That keeps a rolling week. Copy them off the box periodically —
`rsync ubuntu@<ip>:/srv/prepwithtee/data/leads*.db ./backups/`

---

## Updating later

```bash
bash deploy/sync.sh ubuntu@<your-ip>
ssh ubuntu@<your-ip> 'sudo systemctl restart prepwithtee'
```

> **Logo on generated PDFs:** the brand logo lives at
> `website/static/prepwithtee-logo.png` so it ships with every `sync.sh` run
> (it used to sit in the repo root, which sync never sent — that is why the
> covers on Oracle came out as plain text). If a live PDF is still missing the
> owl after an update, re-run sync and restart; `config.LOGO_PATH` must resolve
> on the server.

If you fetch and classify new papers locally, re-run the same command — it
pushes the new PDFs and the updated `index.db` together.

---

## Still to do before you announce it

- [ ] Real testimonials. Nine cards across `index.html` and `pricing.html` are
      visibly-marked placeholders. Do not launch with invented quotes.
- [ ] Sanity-check the comparison figures on `pricing.html` against real local
      rates. They are labelled as typical rates, not quotes, but they should
      still be defensible.
- [ ] Homepage student photos need parent permission before real ones go up.
- [ ] `resources.html` is entirely "coming soon" — fill it or drop it from the nav.
- [ ] Test the WhatsApp links (`wa.me/923204884375`) from a real phone.

## Known limits

`POST /api/generate` spawns a subprocess per request with a 300 s timeout. Two
gunicorn workers means roughly two concurrent booklet builds before requests
queue. That is fine at launch; if it becomes a problem, move generation to a
job queue rather than adding workers.

The `/api/solve` rate limit (15/hour per IP) is held **in each worker's memory**,
so with `-w 2` a determined caller gets 30. Acceptable for now — it exists to
stop runaway API spend, not to be airtight.
