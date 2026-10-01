"""Admin console phase 3 in a real browser: every section opens without a
console error, a payment proof is approved through the gate, an inbox item is
handled, homework is set and marked, and the student page's Manage card works.
Screenshots: e2e-shots/admin-<section>.png."""

import sqlite3
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
USERS_DB = ROOT / "data" / "users.db"
SECTIONS = ["inbox", "payments", "teachers", "homework", "groups", "courses", "newsletter", "emails",
            "calendly", "audit"]


def _student(base_url):
    """A fresh student, registered over a separate HTTP session - registering in
    the admin's browser context would swap its session cookie for the student's."""
    import requests
    email = f"e2e_p3_{uuid.uuid4().hex[:8]}@test.local"
    r = requests.post(f"{base_url}/auth/register", json={"email": email, "password": "Passw0rd!23x",
                                                         "name": "P3 Student"}, timeout=10)
    assert r.ok, r.text
    con = sqlite3.connect(USERS_DB)
    sid = con.execute("SELECT id FROM profiles WHERE email=?", (email,)).fetchone()[0]
    con.close()
    return sid, email


def test_every_section_opens_cleanly(admin_page, shots):
    page = admin_page
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    for s in SECTIONS:
        page.goto(f"/admin#/{s}")
        page.locator("#view h1").wait_for()
        page.wait_for_timeout(700)
        assert not page.locator("#view .empty", has_text="Couldn't").count(), s
        page.screenshot(path=str(shots / f"admin-{s}.png"))
    assert errors == []


def test_payment_approval(admin_page, shots, base_url):
    page = admin_page
    sid, _ = _student(base_url)
    shot_dir = ROOT / "data" / "uploads" / "payments"
    shot_dir.mkdir(parents=True, exist_ok=True)
    name = f"e2e-{uuid.uuid4().hex}.webp"
    (shot_dir / name).write_bytes((ROOT / "website" / "static" / "logo-nav.webp").read_bytes())
    tid = f"E2E-{uuid.uuid4().hex[:6]}"
    con = sqlite3.connect(USERS_DB)
    con.execute("INSERT INTO payment_proofs (user_id, plan, amount_pkr, method, transaction_id, screenshot_url,"
                " status, created_at, period, expected_pkr) VALUES (?,?,?,?,?,?,?,datetime('now'),?,?)",
                (sid, "all", 3000, "jazzcash", tid, f"/uploads/payments/{name}", "pending", "monthly", 3000))
    con.commit()
    con.close()
    try:
        page.goto("/admin#/payments")
        card = page.locator(".proof", has_text=tid)
        card.wait_for()
        assert card.locator(".check-row.ok", has_text="Amount matches").count() == 1
        assert card.locator("img.shot").evaluate("i => i.complete && i.naturalWidth > 0")
        card.get_by_role("button", name="Approve").click()
        page.locator(".modal button[type=submit]").click()
        assert page.locator(".modal .err").inner_text().startswith("Tick the box")
        page.locator(".modal [name=received]").check()
        page.locator(".modal button[type=submit]").click()
        page.locator(".toast", has_text="Approved").wait_for()
        card.wait_for(state="detached")
        plan = sqlite3.connect(USERS_DB).execute("SELECT plan FROM profiles WHERE id=?", (sid,)).fetchone()[0]
        assert plan == "all"
    finally:
        (shot_dir / name).unlink(missing_ok=True)
        con = sqlite3.connect(USERS_DB)
        con.execute("UPDATE profiles SET plan='free', plan_expires_at=NULL WHERE id=?", (sid,))
        con.commit()
        con.close()


def test_inbox_handle(admin_page):
    page = admin_page
    subject = f"E2E question {uuid.uuid4().hex[:6]}"
    con = sqlite3.connect(USERS_DB)
    con.execute("INSERT INTO contacts (name, email, subject, message) VALUES (?,?,?,?)",
                ("E2E Parent", "parent@test.local", subject, "When are classes?"))
    con.commit()
    con.close()
    page.goto("/admin#/inbox")
    row = page.locator(".dt tbody tr", has_text=subject)
    row.click()
    page.locator(".drawer").get_by_role("button", name="Mark handled").click()
    page.locator(".toast", has_text="Updated").wait_for()
    page.wait_for_timeout(500)
    assert page.locator(".dt tbody tr", has_text=subject).count() == 0   # "new" filter hides it


def test_homework_and_manage_card(admin_page, base_url):
    page = admin_page
    sid, email = _student(base_url)
    page.goto(f"/admin#/student/{sid}")
    page.locator("#manage .tab").first.wait_for()
    page.locator('#manage .tab[data-tab="homework"]').click()
    page.locator("#manage [data-add]").click()
    title = f"E2E worksheet {uuid.uuid4().hex[:5]}"
    page.locator(".modal [name=title]").fill(title)
    page.locator(".modal [name=notify]").uncheck()
    page.locator(".modal button[type=submit]").click()
    page.locator("#manage .list-row", has_text=title).wait_for()
    page.goto("/admin#/homework?state=open")
    page.locator(".dt tbody tr", has_text=title).click()
    page.locator(".drawer").get_by_role("button", name="Mark done").click()
    page.locator(".toast", has_text="Updated").wait_for()
    st = sqlite3.connect(USERS_DB).execute("SELECT status FROM assignments WHERE title=?", (title,)).fetchone()[0]
    assert st == "done"
