"""Daily homework reminder emails.

Sends one digest per student covering work that is overdue or due within the
next `--days` days. Idempotent enough to run daily; it does not track what was
already sent, because a nudge about still-outstanding homework is exactly the
point of a daily reminder.

Run from the project root:

    .venv/bin/python -m website.scripts.homework_digest            # send
    .venv/bin/python -m website.scripts.homework_digest --dry-run  # preview

Cron (07:30 Pakistan time = 02:30 UTC):

    30 2 * * *  cd /srv/prepwithtee && \
      /srv/prepwithtee/.venv/bin/python -m website.scripts.homework_digest \
      >> /var/log/prepwithtee-digest.log 2>&1

The systemd unit's EnvironmentFile is not visible to cron, so the crontab entry
must source /etc/prepwithtee.env or the script will find no SMTP credentials and
silently send nothing.
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv                                    # noqa: E402
load_dotenv(ROOT / ".env")

from website import users_db as _udb                              # noqa: E402
from website import reminders                                     # noqa: E402
from website.app import _notify                                   # noqa: E402
from website.users import SUBJECT_NAMES                           # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3,
                    help="how far ahead counts as 'due soon' (default 3)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not (os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASS")):
        print("SMTP_USER/SMTP_PASS not set — nothing can be sent.", flush=True)
        return 1

    students = _udb.list_students()
    sent = skipped = 0

    for s in students:
        items = reminders.open_homework(s["id"])
        due = []
        for it in items:
            d = reminders.days_left(it.get("due_date"))
            if d is not None and d <= a.days:
                it["subject_name"] = SUBJECT_NAMES.get(it.get("syllabus"),
                                                       it.get("syllabus"))
                due.append(it)
        if not due:
            skipped += 1
            continue

        due.sort(key=lambda x: x.get("due_date") or "")
        label = ", ".join(
            f"{x['title']} ({reminders.due_phrase(reminders.days_left(x.get('due_date')))})"
            for x in due)
        if a.dry_run:
            print(f"[dry-run] {s.get('email')}: {label}", flush=True)
            sent += 1
            continue

        if reminders.send_digest_email(s, due, _notify):
            print(f"sent -> {s.get('email')}: {len(due)} item(s)", flush=True)
            sent += 1
        else:
            print(f"FAILED -> {s.get('email')}", flush=True)

    print(f"done: {sent} reminded, {skipped} had nothing due", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
