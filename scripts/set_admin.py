"""Give (or take away) the admin role on an existing account.

The admin console (/admin) signs in with the normal site session and lets in
only accounts whose role is 'admin'. Sign in to the site once (Google or
email) so the account exists, then:

    .venv\\Scripts\\python scripts\\set_admin.py you@example.com            # dry run
    .venv\\Scripts\\python scripts\\set_admin.py you@example.com --apply    # make admin
    .venv\\Scripts\\python scripts\\set_admin.py you@example.com --revoke --apply

Which database it writes to follows the usual env: .env (Supabase) by default,
or --env-file .env.local for the local SQLite copy.
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "website")]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("email")
    ap.add_argument("--revoke", action="store_true", help="make the account a student again")
    ap.add_argument("--apply", action="store_true", help="write the change (default: dry run)")
    ap.add_argument("--env-file", default=".env")
    args = ap.parse_args()

    from dotenv import load_dotenv
    load_dotenv(ROOT / args.env_file)
    import users_db

    user = users_db.get_user_by_email(args.email)
    if not user:
        print(f"No account for {args.email}. Sign in to the site once first.")
        return 1
    target = "student" if args.revoke else "admin"
    where = "Supabase" if users_db._USE_SUPABASE else os.environ.get("USERS_DB_PATH", "local SQLite")
    print(f"{user['email']} ({user.get('name') or 'no name'}): role {user.get('role')} -> {target}  [{where}]")
    if user.get("role") == target:
        print("Nothing to do.")
        return 0
    if not args.apply:
        print("Dry run - add --apply to write it.")
        return 0
    users_db.update_profile(user["id"], {"role": target})
    print("Done. Sign out and back in on the site once, then open /admin.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
