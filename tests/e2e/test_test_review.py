"""Test builder v2: pick chapters -> Review & customise -> swap / remove / reorder
-> build; the built paper holds exactly the reviewed questions, in that order."""

import time

from playwright.sync_api import expect

SUBJECT = "/papers/igcse/physics-0625?pick=Motion&pick=Momentum&mode=test#builder"


def _ids(page):
    return [int(x) for x in page.locator(".rv-card").evaluate_all("cs => cs.map(c => c.dataset.id)")]


def test_review_customise_and_build(student, shots):
    student.request.post("/api/enrollments", data={"syllabus": "0625"})
    page = student.new_page()
    page.goto(SUBJECT)
    page.select_option("#bld-y0", "2021")
    review = page.locator("#bld-review")
    expect(review).to_be_enabled(timeout=20_000)
    review.click()

    expect(page.locator(".rv-card").first).to_be_visible(timeout=20_000)
    expect(page.locator('[data-sec-kind="mcq"] h3')).to_contain_text("Section A")
    expect(page.locator('[data-sec-kind="theory"] h3')).to_contain_text("Section B")
    page.screenshot(path=str(shots / "review_step.png"))

    # mix: 2 MCQ + 1 theory from Motion, 2 theory from Momentum
    for key, n in (("Motion|mcq", 2), ("Motion|theory", 1), ("Momentum|mcq", 0), ("Momentum|theory", 2)):
        page.locator(f'[data-rv-count="{key}"]').fill(str(n))
        page.locator(f'[data-rv-count="{key}"]').dispatch_event("change")
    page.locator('[data-rv="apply"]').click()
    expect(page.locator(".rv-card")).to_have_count(5, timeout=20_000)
    expect(page.locator('[data-sec-kind="mcq"] .rv-card')).to_have_count(2)

    # reorder inside Section B, remove one, swap one, add one
    first_theory = page.locator('[data-sec-kind="theory"] .rv-card').first
    tid = int(first_theory.get_attribute("data-id"))
    first_theory.locator('[data-rv="down"]').click()
    assert _ids(page)[3] == tid
    gone = _ids(page)[0]
    page.locator(f'.rv-card[data-id="{gone}"] [data-rv="remove"]').click()
    assert gone not in _ids(page)

    page.locator(f'.rv-card[data-id="{tid}"] [data-rv="swap"]').click()
    alt = page.locator('.rv-alt [data-rv="use"]').first
    expect(alt).to_be_visible(timeout=20_000)
    new_id = int(alt.get_attribute("data-id"))
    alt.click()
    ids = _ids(page)
    assert new_id in ids and tid not in ids

    page.locator('[data-rv="add"]').click()
    add = page.locator('.rv-alt [data-rv="use"]').first
    expect(add).to_be_visible(timeout=20_000)
    add.click()
    page.locator(".rv-close").click()
    ids = _ids(page)
    assert len(ids) == 5

    # preview shows the whole question
    page.locator(".rv-card").first.locator('[data-rv="preview"]').first.click()
    expect(page.locator(".rv-full")).to_be_visible(timeout=20_000)
    page.screenshot(path=str(shots / "review_preview.png"))
    page.keyboard.press("Escape")

    # build: the paper holds exactly these questions, in this order
    with page.context.expect_page() as popup:
        page.locator('[data-rv="build"]').click()
    viewer = popup.value
    viewer.wait_for_url("**/papers/view/**", timeout=20_000)
    bid = viewer.url.rsplit("/", 1)[-1]
    for _ in range(240):
        st = student.request.get(f"/api/booklets/{bid}/status").json()
        if st["status"] in ("ready", "failed"):
            break
        time.sleep(0.5)
    assert st["status"] == "ready", st
    d = student.request.get(f"/api/booklets/{bid}").json()
    assert d["question_ids"] == ids
    assert d["params_json"]["reviewed"] is True
