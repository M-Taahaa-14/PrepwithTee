"""Topical builder -> viewer, in a real browser."""

import re

from playwright.sync_api import expect


def test_enrol_build_and_view(student, shots):
    page = student.new_page()

    # Locked subject -> enrol free -> builder appears
    page.goto("/papers/igcse")
    card = page.locator(".pk-tile", has_text="Physics")
    card.get_by_role("button", name="Enrol free").click()
    page.wait_for_load_state()
    expect(page.locator(".pk-tile.is-mine", has_text="Physics")).to_be_visible()

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
        page.get_by_role("button", name="Build booklet").click()
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


def test_subtopic_chips_pick_part_of_a_chapter(student, shots):
    student.request.post("/api/enrollments", data={"syllabus": "0625"})
    page = student.new_page()
    page.goto("/papers/igcse/physics-0625#builder")
    ch = page.locator(".bld-ch").first
    chip = ch.locator(".bld-subchip").first
    name = chip.locator("span").inner_text()
    chip.click()
    expect(ch.locator(".bld-subchip.is-on")).to_have_count(1)
    expect(page.locator(".bld-slot").first).to_contain_text(name)
    expect(ch.locator(".bld-partial")).to_contain_text("1/")
    # ticking the chapter itself takes the whole chapter
    ch.locator("input[type=checkbox]").check()
    expect(page.locator(".bld-slot").first).to_contain_text("Whole chapter")
    # search narrows the list to matching chapters / subtopics
    page.locator("#bld-filter").fill(name[:6])
    page.wait_for_timeout(300)
    expect(page.locator(".bld-subchip.is-hit").first).to_be_visible()


def test_a_level_builder_groups_by_paper_and_builds_a_mock_test(student, shots):
    student.request.put("/api/me/boards", data={"boards": ["a-level"]})
    student.request.post("/api/enrollments", data={"syllabus": "9709"})
    page = student.new_page()
    page.goto("/papers/a-level/mathematics-9709?mode=test#builder")
    secs = page.locator(".bld-sec")
    expect(secs).to_have_count(4)
    expect(secs.nth(1)).to_contain_text("Pure Mathematics 3")
    expect(secs.nth(1).locator(".bld-level-A2")).to_be_visible()
    expect(page.locator('[data-kind="test"]')).to_have_attribute("aria-checked", "true")
    # mix papers: one P1 chapter and one P3 chapter
    secs.nth(0).locator(".bld-ch input[type=checkbox]").first.check()
    secs.nth(1).locator(".bld-ch input[type=checkbox]").first.check()
    expect(page.locator(".bld-pool")).to_contain_text("available")
    page.screenshot(path=str(shots / "builder_alevel_test.png"))
    page.locator("#bld-n").fill("3")
    with student.expect_page() as newtab:
        page.get_by_role("button", name="Build mock test").click()
    viewer = newtab.value
    viewer.wait_for_url(re.compile(r"/papers/view/[\w-]+$"))
    expect(viewer.locator(".vw-seg")).to_be_visible(timeout=90_000)
    expect(viewer.locator("#vw-stage .vw-pg canvas").first).to_be_visible(timeout=30_000)
    ms_tab = viewer.get_by_role("tab", name=re.compile("Mark scheme"))
    expect(ms_tab).to_be_disabled()
    viewer.get_by_role("button", name=re.compile("Start")).click()
    expect(viewer.locator("#vw-timer")).to_have_attribute("aria-pressed", "true")
    viewer.once("dialog", lambda d: d.accept())
    viewer.get_by_role("button", name="Finish test").click()
    expect(ms_tab).to_be_enabled()
    expect(viewer.locator("#vw-stage-ms .vw-pg canvas").first).to_be_visible(timeout=30_000)
    viewer.wait_for_timeout(600)
    viewer.screenshot(path=str(shots / "mock_test_ms.png"))
