"""Topical builder -> viewer, in a real browser."""

import re

from playwright.sync_api import expect


def test_enrol_build_and_view(student, shots):
    page = student.new_page()

    # Locked subject -> enrol free -> builder appears
    page.goto("/papers/igcse")
    card = page.locator(".cat-subj", has_text="Physics")
    card.get_by_role("button", name="Enrol free").click()
    page.wait_for_load_state()
    expect(page.locator(".cat-subj.is-enrolled", has_text="Physics")).to_be_visible()

    page.goto("/papers/igcse/physics-0625?pick=Motion")
    expect(page.locator(".bld-slot").first).to_contain_text("Motion")
    page.get_by_role("checkbox", name="Pressure", exact=True).check()
    expect(page.locator(".bld-pool")).to_contain_text("available")
    page.screenshot(path=str(shots / "builder.png"))

    # 5th chapter is refused
    for name in ("Density", "Momentum"):
        page.get_by_role("checkbox", name=name, exact=True).check()
    fifth = page.locator(".bld-ch.is-disabled").first
    expect(fifth).to_be_visible()
    for name in ("Density", "Momentum"):
        page.locator(".bld-slot", has_text=name).get_by_role("button").click()

    page.locator("#bld-n").fill("8")
    with student.expect_page() as newtab:
        page.get_by_role("button", name="Build paper").click()
    viewer = newtab.value
    viewer.wait_for_url(re.compile(r"/papers/view/[\w-]+$"))
    expect(viewer.locator(".vw-tools")).to_be_visible(timeout=90_000)
    expect(viewer.locator(".vw-pg canvas").first).to_be_visible(timeout=30_000)
    viewer.wait_for_timeout(800)
    viewer.screenshot(path=str(shots / "viewer_cover.png"))

    # Contents drawer jumps to a question; the mark scheme opens in the panel
    viewer.get_by_role("button", name=re.compile("Contents")).click()
    viewer.locator(".vw-toc button").nth(2).click()
    viewer.wait_for_timeout(900)
    viewer.locator(".vw-chips").nth(2).get_by_role("button", name=re.compile("Mark scheme")).click()
    expect(viewer.locator(".vw-panel")).to_be_visible()
    expect(viewer.locator(".ai-body .ai-ms, .ai-body .ai-mcq-key, .ai-body .ai-muted").first).to_be_visible()
    viewer.wait_for_timeout(800)
    viewer.screenshot(path=str(shots / "viewer_question.png"))
