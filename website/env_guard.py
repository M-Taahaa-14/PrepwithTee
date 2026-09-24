"""Refuse to run a local or test process against the production database.

`APP_ENV` says where a process is running:
  production (default)  the server; no check
  staging               a separate Supabase project; must NOT be production
  local                 a developer's machine; must NOT be production
  test                  pytest; must NOT be production

The local `.env` holds the live Supabase credentials, and `app.py` loads it
for any key the environment has not already set. Without this guard, starting
the site on a laptop quietly read and wrote real student data.

Set ALLOW_PROD_DB=1 to deliberately bypass (e.g. a read-only audit script).
"""

import os

# Supabase project refs that are production. The ref appears both in the
# pooler username (postgres.<ref>) and in SUPABASE_URL (<ref>.supabase.co).
_PROD_REFS = {r.strip() for r in os.environ.get(
    "PROD_SUPABASE_REFS", "qodznpcwoppzugoxqord").split(",") if r.strip()}

_GUARDED_ENVS = {"local", "test", "staging"}
_DB_KEYS = ("DATABASE_URL", "SUPABASE_URL")


def app_env() -> str:
    return (os.environ.get("APP_ENV") or "production").strip().lower()


class ProductionDatabaseError(RuntimeError):
    pass


def check() -> None:
    """Raise if a guarded environment is pointed at a production project."""
    env = app_env()
    if env not in _GUARDED_ENVS or os.environ.get("ALLOW_PROD_DB") == "1":
        return
    for key in _DB_KEYS:
        value = os.environ.get(key) or ""
        for ref in _PROD_REFS:
            if ref in value:
                raise ProductionDatabaseError(
                    f"APP_ENV={env} but {key} points at the production Supabase "
                    f"project ({ref}). Start with --env-file .env.local (SQLite) "
                    f"or .env.staging, or set ALLOW_PROD_DB=1 if you really mean it.")
