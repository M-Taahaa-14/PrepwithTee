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
    # What's new nudges (whats-new.js) would sit over pages other tests click on;
    # tests that check them set "pwt-wn" to "{}" themselves.
    ctx.add_init_script("if (!localStorage.getItem('pwt-wn')) localStorage.setItem('pwt-wn', "
                        "JSON.stringify({'board-2026-10': 1, 'instagram-2026-10': 1, 'coach-rail': 1}))")
    yield ctx
    ctx.close()


USERS_DB = Path(__file__).resolve().parents[2] / "data" / "users.db"


@pytest.fixture()
def admin_page(browser, base_url):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, base_url=base_url)
    email = f"e2e_admin_{uuid.uuid4().hex[:8]}@test.local"
    r = ctx.request.post("/auth/register", data={
        "email": email, "password": f"{uuid.uuid4().hex}Aa1!", "name": "E2E Admin"})
    assert r.ok, r.text()
    import sqlite3
    con = sqlite3.connect(USERS_DB)
    con.execute("UPDATE profiles SET role='admin' WHERE email=?", (email,))
    con.commit()
    con.close()
    page = ctx.new_page()
    yield page
    ctx.close()


