"""The free-plan limit card (static/limit-card.js) with its self-serve trial, and
snipping part of the page into a feedback report (static/snip.js)."""

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import expect

USERS_DB = Path(__file__).resolve().parents[2] / "data" / "users.db"


def _use_up(student, event: str, n: int):
    """Spend the student's free allowance directly in the local users DB."""
    uid = student.request.get("/auth/me").json()["id"]
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(USERS_DB) as c:
        c.executemany("INSERT INTO usage_events (user_id, event_type, created_at, syllabus) VALUES (?,?,?,?)",
                      [(uid, event, now, "0625")] * n)


def test_limit_card_then_trial(student, shots):
    student.request.post("/api/enrollments", data={"syllabus": "0625"})
    _use_up(student, "topical_paper", 3)
    page = student.new_page()
    page.goto("/papers/igcse/physics-0625?pick=Motion")
    expect(page.locator(".bld-slot").first).to_contain_text("Motion")
    page.locator("#bld-n").fill("6")
    page.get_by_role("button", name="Build booklet").click()

    expect(page.get_by_role("dialog", name=re.compile("free topical papers"))).to_be_visible()
    card = page.locator(".lc-card")
    expect(card).to_contain_text("3 / 3")
    expect(card.locator(".lc-trial")).to_contain_text("Try All Subjects")
    expect(card.locator(".lc-plan")).to_have_count(3)
    expect(page.locator("#bld-limit .lc-inline")).to_be_visible()      # small copy stays in the panel
    page.wait_for_timeout(400)
    page.screenshot(path=str(shots / "limit_card.png"))

    card.get_by_role("button", name=re.compile("Start my free 7-day trial")).click()
    expect(card).to_contain_text("Trial started")
    page.screenshot(path=str(shots / "limit_card_trial.png"))
    plan = student.request.get("/api/me/offer?event=topical_paper").json()
    assert plan["trial"] is True and plan["plan"] == "all" and plan["trial_eligible"] is False

    card.get_by_role("button", name=re.compile("Carry on")).click()
    page.wait_for_load_state()
    with student.expect_page() as newtab:                   # the build now goes through
        page.get_by_role("button", name="Build booklet").click()
    newtab.value.wait_for_url(re.compile(r"/papers/view/[\w-]+$"))


def test_card_closes_and_dark_mode(student, shots):
    _use_up(student, "topical_paper", 3)
    page = student.new_page()
    page.emulate_media(color_scheme="dark")
    page.add_init_script("localStorage.setItem('theme', 'dark')")
    page.goto("/papers")
    page.wait_for_function("() => !!window.PWTLimit")
    page.evaluate("""() => window.PWTLimit.show({code: 'quota_exceeded', event_type: 'topical_paper', used: 3, limit: 3,
                    message: "You've used 3/3 topical papers this billing period."})""")
    card = page.locator(".lc-card")
    expect(card.locator(".lc-plan").first).to_be_visible()
    page.wait_for_timeout(400)
    page.screenshot(path=str(shots / "limit_card_dark.png"))
    page.keyboard.press("Escape")
    expect(card).to_have_count(0)


def test_snip_into_feedback(student, shots):
    page = student.new_page()
    page.goto("/papers")
    page.locator("#fbTabBtn").click()
    page.get_by_role("button", name="Report an issue").click()
    field = page.locator("#fbSnips")
    expect(field.get_by_role("button", name=re.compile("Snip part of the page"))).to_be_visible()
    field.get_by_role("button", name=re.compile("Snip part of the page")).click()

    overlay = page.get_by_role("dialog", name="Snip part of the page")
    expect(overlay).to_be_visible(timeout=20_000)
    expect(page.locator("#fbPanel")).to_be_hidden()           # the panel is taken out of the picture
    page.mouse.move(120, 120)
    page.mouse.down()
    page.mouse.move(520, 380, steps=6)
    page.mouse.up()
    expect(overlay.get_by_role("button", name=re.compile("Attach"))).to_be_visible()
    overlay.get_by_role("button", name=re.compile("Mark it")).click()
    page.mouse.move(200, 200)
    page.mouse.down()
    page.mouse.move(300, 260, steps=5)
    page.mouse.up()
    page.screenshot(path=str(shots / "snip_overlay.png"))
    overlay.get_by_role("button", name=re.compile("Attach")).click()
    expect(overlay).to_have_count(0)
    expect(field.locator(".fb-snip-thumb")).to_have_count(1)
    src = field.locator(".fb-snip-thumb img").get_attribute("src")
    assert src.startswith("data:image/jpeg;base64,") and len(src) > 2000

    page.locator("#fbMessage").fill("The chapter list cuts off on my laptop")
    page.screenshot(path=str(shots / "snip_feedback.png"))
    with page.expect_response("**/api/feedback") as resp:
        page.locator("#fbSubmitBtn").click()
    assert resp.value.ok, resp.value.text()
    sent = resp.value.request.post_data_json
    assert len(sent["snips"]) == 1
