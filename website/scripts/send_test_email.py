"""Send one test notification, and say which transport carried it.

Deliverability failures are silent by design — `_notify` returns False and the
site carries on — so there has to be a way to ask the question directly:

    .venv/Scripts/python -m website.scripts.send_test_email you@example.com

On the server:

    sudo -u prepwithtee /srv/prepwithtee/.venv/bin/python \
        -m website.scripts.send_test_email you@example.com

A "sent via resend" line means the domain is verified and DKIM is signing. A
fallback to SMTP almost always means the DNS records in website/DEPLOY.md are
missing or have not propagated yet — the rejection reason is printed above it.

Then open the message in Gmail -> "Show original" and check all three of
SPF / DKIM / DMARC say PASS. DKIM must show d=prepwithtee.com; if it says
d=gmail.com the mail went out on the fallback path.
"""

import os
import sys

from ..app import _notify, _mail_from, _reply_to


def main() -> int:
    to = sys.argv[1] if len(sys.argv) > 1 else _reply_to()
    key = os.environ.get("RESEND_API_KEY")
    smtp = os.environ.get("SMTP_USER")

    print(f"RESEND_API_KEY: {'set (' + key[:7] + '…)' if key else 'NOT SET'}")
    print(f"SMTP fallback : {smtp or 'NOT SET'}")
    print(f"From          : {_mail_from()}")
    print(f"Reply-To      : {_reply_to()}")
    print(f"To            : {to}\n")

    ok = _notify(
        "[PrepWithTee] Test notification",
        "This is a deliverability test. If it reached the inbox rather than "
        "spam, the domain is set up correctly.\n",
        rows=[("Transport", "Resend" if key else "Gmail SMTP"),
              ("From", _mail_from()),
              ("Purpose", "Deliverability check")],
        to=to,
        cta=("Open PrepWithTee", "https://prepwithtee.com/dashboard.html"),
    )
    # _notify falls back silently, so "True" alone does not prove Resend worked;
    # any rejection reason is printed by the helper itself, just above this.
    print(f"\nsent: {ok}"
          f"{' — check the log lines above for a Resend rejection' if ok and key else ''}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
