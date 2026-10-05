"""The AI help panel in the viewer: Explain (KaTeX), free-plan gate, Guide me."""

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone

from playwright.sync_api import expect

from tests.conftest import INDEX_DB, ROOT

SAMPLE = {
    "summary": "Tests **pressure** = force ÷ area.",
    "parts": [{"label": "(a)", "steps": [
        {"title": "Recall the formula", "body": "Pressure is $p = \\frac{F}{A}$."},
        {"title": "Substitute", "body": "$$p = \\frac{400}{0.2} = 2000\\,\\mathrm{Pa}$$"}],
        "answer": "$2000\\,\\mathrm{Pa}$", "marking": "C1 for the formula, A1 for 2000 Pa"}],
    "hints": ["Which quantity links force and area?", "Write $p = F/A$.",
              "Is the area in $\\mathrm{m^2}$?"],
    "mcq_options": [], "common_mistakes": ["Leaving the area in cm²"], "confidence": "high"}


def _seed(qids):
    con = sqlite3.connect(INDEX_DB)
    con.execute("""CREATE TABLE IF NOT EXISTS question_explanations (
        question_id INTEGER PRIMARY KEY, content_json TEXT NOT NULL, model TEXT,
        prompt_version INTEGER NOT NULL DEFAULT 1, input_tokens INTEGER, output_tokens INTEGER,
        flagged INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT (datetime('now')))""")
    for q in qids:        # prompt_version 0 + model tag: real generation overwrites these
        con.execute("INSERT OR IGNORE INTO question_explanations "
                    "(question_id, content_json, model, prompt_version) VALUES (?, ?, 'e2e-sample', 0)",
                    (q, json.dumps(SAMPLE)))
    con.commit()
    con.close()


def _cleanup():
    con = sqlite3.connect(INDEX_DB)
    con.execute("DELETE FROM question_explanations WHERE model = 'e2e-sample'")
    con.commit()
    con.close()


def _make_paid(email):
    con = sqlite3.connect(ROOT / "data" / "users.db")
    now = datetime.now(timezone.utc)
    con.execute("UPDATE profiles SET plan='solo', plan_trial=0, plan_started_at=?, plan_expires_at=? "
                "WHERE email=?", (now.isoformat(), (now + timedelta(days=30)).isoformat(), email))
    con.commit()
    con.close()


def test_explain_panel_and_plan_gate(student, shots):
    req = student.request
    req.post("/api/enrollments", data={"syllabus": "5054"})
    b = req.post("/api/booklets", data={
        "syllabus": "5054", "papers": [2], "year_from": 2019, "year_to": 2025,
        "picks": [{"chapter": "Pressure"}], "max_questions": 3}).json()
    page = student.new_page()
    page.goto(b["url"])
    expect(page.locator(".vw-pg canvas").first).to_be_visible(timeout=90_000)
    qids = [q["qid"] for q in req.get(f"/api/booklets/{b['id']}").json()["page_map_json"]["questions"]]
    _seed(qids)
    try:
        chips = page.locator(".vw-chips")
        chips.first.get_by_role("button", name=re.compile("Explain")).click()
        panel = page.locator(".vw-panel")
        expect(panel.locator(".ai-summary")).to_contain_text("pressure")
        expect(panel.locator(".katex").first).to_be_visible()            # LaTeX typeset
        expect(panel.locator(".ai-answer")).to_contain_text("2000")
        page.wait_for_timeout(500)
        page.screenshot(path=str(shots / "ai_explain.png"))

        # free plan: Guide me needs a plan; a second Explain needs a plan
        panel.get_by_role("tab", name="Guide me").click()
        panel.get_by_role("button", name="Show hint 1").click()
        expect(panel.locator(".ai-plan")).to_be_visible()
        # the site-wide limit card (limit-card.js) opens over the page too
        expect(page.locator(".lc-card")).to_contain_text("hints")
        page.keyboard.press("Escape")
        expect(page.locator(".lc-card")).to_have_count(0)
        chips.nth(1).get_by_role("button", name=re.compile("Explain")).click()
        expect(panel.locator(".ai-plan")).to_contain_text("free worked solution")
        page.keyboard.press("Escape")
        page.screenshot(path=str(shots / "ai_gate.png"))

        # on a plan: hints one at a time
        _make_paid(page.evaluate("fetch('/auth/me?fresh=true').then(r => r.json()).then(u => u.email)"))
        chips.nth(1).get_by_role("button", name=re.compile("Guide me")).click()
        panel.get_by_role("button", name="Show hint 1").click()
        expect(panel.locator(".ai-hints li")).to_have_count(1)
        panel.get_by_role("button", name="Show hint 2").click()
        expect(panel.locator(".ai-hints li")).to_have_count(2)
        page.screenshot(path=str(shots / "ai_hints.png"))
    finally:
        _cleanup()
