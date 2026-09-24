"""Shared pytest setup.

The environment is pinned BEFORE the app is imported: app.py calls
load_dotenv(.env) at import time, which only fills keys that are missing, so
setting them (even to "") here keeps the live credentials out of every test.

Layout
  tests/unit  pure functions, no app, no DB
  tests/api   FastAPI TestClient against SQLite (index.db read-only, a fresh
              throwaway users DB per test session), LLMs + email disabled
  tests/pdf   builds real booklets from the local index.db and checks layout
  tests/e2e   Playwright against a running local server (see tests/e2e/conftest.py)
"""

import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_TMP = Path(tempfile.mkdtemp(prefix="pwt_tests_"))

os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": "",
    "SUPABASE_URL": "",
    "SUPABASE_SERVICE_ROLE_KEY": "",
    "SUPABASE_SERVICE_KEY": "",
    "USERS_DB_PATH": str(_TMP / "users.db"),
    "BOOKLET_DIR": str(_TMP / "booklets"),
    "RESEND_API_KEY": "",
    "SMTP_USER": "",
    "SMTP_PASS": "",
    "ANTHROPIC_API_KEY": "",
    "GROQ_API_KEY": "",
    "GEMINI_API_KEY": "",
    "OPENROUTER_API_KEY": "",
    "CEREBRAS_API_KEY": "",
    "SECRET_KEY": "test-secret-not-for-production",
    "APP_BASE_URL": "http://testserver",
    "ADMIN_ACCESS_KEY": "test-admin-key",
})

for p in (ROOT, ROOT / "website"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

INDEX_DB = ROOT / "data" / "index.db"
# The website reads a throwaway copy, so tests may write (explanations,
# flags) without touching the real archive. pipeline subprocesses (compose)
# still read the original - same data, read-only.
if INDEX_DB.exists():
    import shutil
    shutil.copyfile(INDEX_DB, _TMP / "index.db")
    os.environ["INDEX_DB_PATH"] = str(_TMP / "index.db")
needs_index_db = pytest.mark.skipif(
    not INDEX_DB.exists(), reason="data/index.db (pipeline archive) not present")


@pytest.fixture(scope="session")
def app():
    from website.app import app as _app
    return _app


@pytest.fixture()
def client(app):
    """A fresh client per test, so cookies never leak between tests."""
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def new_student(client):
    """Register a brand-new student and leave the client logged in as them."""
    def _make(role: str = "student", password: str = "Passw0rd!23"):
        email = f"t_{uuid.uuid4().hex[:10]}@test.local"
        r = client.post("/auth/register", json={
            "email": email, "password": password, "name": "Test Student", "role": role})
        assert r.status_code == 200, r.text
        return {**r.json(), "password": password}
    return _make
