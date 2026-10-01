"""A failed topical build explains itself, offers Try again, and can be reported."""

import json
import re
import sqlite3
import time

from playwright.sync_api import expect

from tests.e2e.conftest import USERS_DB

BUSY = {"code": "internal", "detail": "test: injected failure"}


def _build(ctx):
    ctx.request.post("/api/enrollments", data={"syllabus": "0625"})
    r = ctx.request.post("/api/booklets", data={
        "syllabus": "0625", "picks": [{"chapter": "Motion"}], "max_questions": 3})
    assert r.ok, r.text()
    bid = r.json()["id"]
    for _ in range(240):                       # let the real build finish first
        if ctx.request.get(f"/api/booklets/{bid}/status").json()["status"] in ("ready", "failed"):
            break
        time.sleep(0.5)
    return bid


def _fail(bid, err=BUSY):
    with sqlite3.connect(USERS_DB) as c:
        c.execute("UPDATE booklets SET status='failed', stage='Failed', error=? WHERE id=?",
                  (json.dumps(err), bid))


def test_failed_build_explains_retries_and_reports(student, shots):
    bid = _build(student)
    _fail(bid)
    page = student.new_page()
    page.goto(f"/papers/view/{bid}")

    card = page.locator(".vw-fail")
    expect(card).to_contain_text("Something broke on our side")
    expect(card.get_by_role("button", name="Try again")).to_be_visible()
    expect(card.get_by_role("link", name="Change my selection")).to_have_attribute(
        "href", re.compile(r"pick=Motion"))
    # internal problems need the tutor: the report form is already open, prefilled
    form = page.locator("#vw-report")
    expect(form).to_be_visible()
    expect(form.locator('input[name="name"]')).to_have_value("E2E Student")
    expect(form).to_contain_text(f"{bid} · internal")
    page.screenshot(path=str(shots / "booklet_failed.png"))

    form.locator("textarea").fill("Picked Motion, 3 questions")
    form.get_by_role("button", name="Send to Tee").click()
    expect(page.locator(".vw-report-done")).to_be_visible()

    # Try again rebuilds the same paper and opens it
    card.get_by_role("button", name="Try again").click()
    expect(page.locator(".vw-tools")).to_be_visible(timeout=120_000)


def test_busy_failure_keeps_the_form_folded(student, shots):
    bid = _build(student)
    _fail(bid, {"code": "busy", "detail": "EMAXCONNSESSION"})
    page = student.new_page()
    page.goto(f"/papers/view/{bid}")
    expect(page.locator(".vw-fail h1")).to_have_text("Our server was too busy")
    expect(page.locator("#vw-report")).to_be_hidden()
    expect(page.locator(".vw-fail")).not_to_contain_text("EMAXCONN")
    page.get_by_role("button", name="Report this problem").click()
    expect(page.locator("#vw-report")).to_be_visible()
    page.screenshot(path=str(shots / "booklet_busy.png"))
