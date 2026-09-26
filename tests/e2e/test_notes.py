"""Revision notes in a real browser: maths renders, the note is ticked as read
after scrolling to the end, and "Practise this chapter" opens the builder with
the chapter picked."""

import re

from playwright.sync_api import expect


def test_note_page_maths_read_tick_and_practise(student, shots):
    page = student.new_page()
    page.goto("/notes/igcse/physics-0625")
    page.get_by_role("link", name="Hooke's Law and springs").first.click()
    expect(page).to_have_url(re.compile(r"/notes/igcse/physics-0625/forces/hookes-law$"))
    expect(page.locator(".nt-body .katex").first).to_be_visible(timeout=10_000)   # F = ke typeset
    page.screenshot(path=str(shots / "note_page.png"))

    # read to the end -> ticked in the sidebar (this device)
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    expect(page.locator('.nt-side a[data-note="0625/forces/hookes-law"]')).to_have_class(re.compile("is-read"))

    # next / previous stay inside the subject, in syllabus order
    expect(page.locator(".nt-pn .nt-next")).to_contain_text("Turning effects")

    student.request.post("/api/enrollments", data={"syllabus": "0625"})
    page.locator(".nt-cta a").click()
    expect(page).to_have_url(re.compile(r"/papers/igcse/physics-0625\?pick=Forces#builder$"))
    expect(page.locator(".bld-slot").first).to_contain_text("Forces")
