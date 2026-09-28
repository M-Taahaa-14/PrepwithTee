"""End-to-end tests: a real browser against a running local server.

Start the site first (it must be the SQLite/local config, never production):
    .venv\\Scripts\\python -m uvicorn website.app:app --port 8017 --env-file .env.local
then:
    .venv\\Scripts\\python -m pytest -m e2e tests/e2e --headed      (watch it)
    .venv\\Scripts\\python -m pytest -m e2e tests/e2e               (headless)

E2E_BASE_URL overrides the address. Screenshots land in e2e-shots/.
"""

import os
import uuid
from pathlib import Path

import pytest
import requests

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8017").rstrip("/")
SHOTS = Path(__file__).resolve().parents[2] / "e2e-shots"   # pytest-playwright wipes test-results/


def _up() -> bool:
    try:
        return requests.get(f"{BASE}/api/health", timeout=3).ok
    except requests.RequestException:
        return False


def pytest_collection_modifyitems(config, items):
    here = Path(__file__).parent
    for item in items:
        if here in Path(item.fspath).parents:
            item.add_marker(pytest.mark.e2e)


@pytest.fixture(scope="session")
def base_url():
    if not _up():
        pytest.skip(f"no local server at {BASE} (start prepwithtee-local first)")
    return BASE


@pytest.fixture(scope="session")
def shots():
    SHOTS.mkdir(exist_ok=True)
    return SHOTS


@pytest.fixture()
def student(browser, base_url):
    """A fresh signed-in student (browser context with the session cookie)."""
    ctx = browser.new_context(viewport={"width": 1280, "height": 860}, base_url=base_url)
    email = f"e2e_{uuid.uuid4().hex[:8]}@test.local"
    r = ctx.request.post("/auth/register", data={
        "email": email, "password": "Passw0rd!23", "name": "E2E Student"})
    assert r.ok, r.text()
    ctx.request.post("/api/me/setup", data={          # enrolment gate
        "name": "E2E Student", "phone": "+92 3001234567", "boards": ["igcse", "o-level", "a-level"]})
    ctx.request.put("/api/me/boards", data={"boards": ["igcse", "o-level"]})
    yield ctx
    ctx.close()
