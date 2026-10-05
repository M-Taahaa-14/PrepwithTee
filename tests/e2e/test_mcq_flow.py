"""MCQ solver (P1-e) in a real browser: set up from the subject page, paper
view + answer sheet, one-by-one with the keyboard, live check, submit, results,
review with "why", annotations saved, phone layout."""

import re
from urllib.parse import quote

from playwright.sync_api import expect


def _enrol(student):
    student.request.post("/api/enrollments", data={"syllabus": "5054"})


def test_full_paper_from_setup_to_results(student, shots):
    _enrol(student)
    page = student.new_page()
    page.goto("/mcq/o-level/physics-5054")
    setup = page.locator("#mq-setup")
    expect(setup.get_by_role("tab", name=re.compile("Full past paper"))).to_have_attribute("aria-selected", "true")
    setup.get_by_role("button", name="2016", exact=True).click()
    setup.get_by_role("button", name="May/June").click()
    expect(setup.locator(".mqs-summary")).to_contain_text("May/June 2016")
    setup.get_by_role("button", name=re.compile("Paper$")).click()
    page.screenshot(path=str(shots / "mcq_setup.png"), full_page=True)
    setup.get_by_role("button", name=re.compile("Start practice")).click()
    expect(page).to_have_url(re.compile(r"/mcq/session/[\w-]+$"))

    # intro -> start: the real paper with a marker beside every question
    expect(page.locator(".mq-intro")).to_contain_text("60 min")
    page.get_by_role("button", name=re.compile(r"^Start")).click()
    expect(page.locator(".vw-pg canvas").first).to_be_visible(timeout=30_000)
    expect(page.locator(".mq-mark")).to_have_count(40)
    expect(page.locator("#mq-time")).to_have_text(re.compile(r"^(59|60):\d\d$"))

    sheet = page.locator("#mq-sheet")
    sheet.locator('[data-pick="1|B"]').click()
    sheet.locator('[data-pick="2|C"]').click()
    sheet.locator('[data-flag="2"]').click()
    expect(sheet.locator(".mq-sheet-head")).to_contain_text("2/40 answered")
    expect(page.locator('.vw-chips[data-seq="1"] .mq-mark-a')).to_have_text("B")
    page.wait_for_timeout(600)
    page.screenshot(path=str(shots / "mcq_paper_view.png"))

    # one by one + keyboard
    page.get_by_role("tab", name=re.compile("One by one")).click()
    expect(page.locator(".mq-qcount")).to_contain_text("Question")
    expect(page.locator(".mq-single canvas.mq-crop-canvas")).to_be_visible(timeout=20_000)
    sheet.locator('[data-go="4"]').click()                      # an unanswered one
    page.keyboard.press("ArrowRight")
    n = int(page.locator(".mq-qcount b").inner_text())
    assert n == 5
    page.keyboard.press("a")
    expect(page.locator(".mq-opt.is-picked")).to_have_text("A")
    expect(sheet.locator(f'.mq-row[data-n="{n}"] .mq-bub.is-on')).to_have_text("A")
    page.screenshot(path=str(shots / "mcq_single.png"))

    # a reload resumes where we were (answers + flags from the server)
    expect(page.locator("#mq-save")).to_have_text("All answers saved")
    page.reload()
    expect(sheet.locator(".mq-sheet-head")).to_contain_text("3/40 answered")
    expect(sheet.locator('[data-flag="2"]')).to_have_attribute("aria-pressed", "true")

    # submit -> results
    page.get_by_role("button", name="Submit", exact=True).click()
    expect(page.locator(".mq-modal")).to_contain_text("37 unanswered")
    page.locator(".mq-modal").get_by_role("button", name="Submit anyway").click()
    expect(page.locator(".mq-hero")).to_be_visible()
    expect(page.locator(".mq-tile")).to_have_count(40)
    expect(page.locator("#mq-scorechip")).to_contain_text("/")
    page.screenshot(path=str(shots / "mcq_results.png"), full_page=True)

    # review a question: right and wrong letters shown, answer locked
    page.locator('.mq-tile[data-review="1"]').click()
    expect(page.locator(".mq-opt.is-key")).to_have_count(1)
    expect(page.locator(".mq-opt").first).to_be_disabled()
    expect(page.locator("#mq-feedback")).not_to_be_empty()


def test_topical_live_check_and_annotations(student, shots):
    _enrol(student)
    topics = student.request.get("/api/mcq/topics?syllabus=5054").json()["topics"]
    s = student.request.post("/api/mcq/sessions", data={
        "syllabus": "5054", "topics": [topics[0]["name"]], "count": 5, "mode": "paper",
        "live_check": True, "timer": "none", "seed": 11}).json()
    page = student.new_page()
    page.goto(s["url"])
    # every question is fetched before Start is allowed - the clock never runs on "Loading…"
    expect(page.locator("#mq-prep")).to_contain_text("Paper ready", timeout=30_000)
    start = page.get_by_role("button", name=re.compile(r"^Start"))
    expect(start).to_be_enabled()
    start.click()
    expect(page.locator(".mq-q")).to_have_count(5)
    expect(page.locator(".mq-q").first.locator("canvas.mq-crop-canvas")).to_be_visible(timeout=3_000)

    # live check: marked at once, then locked, "Why" appears
    page.locator('#mq-sheet [data-pick="1|A"]').click()
    row = page.locator('#mq-sheet .mq-row[data-n="1"]')
    expect(row).to_have_class(re.compile(r"is-(right|wrong)"))
    expect(row.locator(".mq-bub").first).to_be_disabled()
    expect(page.locator('.mq-q[data-n="1"] [data-open="explain"]')).to_be_visible()

    # draw a highlighter stroke on question 1: saved per question, survives reload
    page.locator('.an-bar [data-tool="marker"]').click()
    box = page.locator('.mq-q[data-n="1"] .mq-crop').bounding_box()
    page.mouse.move(box["x"] + 30, box["y"] + 30)
    page.mouse.down()
    for i in range(1, 12):
        page.mouse.move(box["x"] + 30 + i * 18, box["y"] + 32)
    page.mouse.up()
    expect(page.locator(".an-saved")).to_have_text("Saved", timeout=5000)
    qid = page.locator('.mq-q[data-n="1"] .mq-crop').get_attribute("data-qid")
    saved = student.request.get(f"/api/annotations?doc=mcq:{s['id']}:q{qid}").json()["pages"]["0"]
    assert saved[0]["t"] == "marker" and len(saved[0]["pts"]) > 5
    page.screenshot(path=str(shots / "mcq_topical_live.png"))
    page.keyboard.press("Control+z")
    for _ in range(20):                                          # saved after a short debounce
        page.wait_for_timeout(250)
        if student.request.get(f"/api/annotations?doc=mcq:{s['id']}:q{qid}").json()["pages"] == {}:
            break
    else:
        raise AssertionError("undo was not saved")


def test_phone_layout_uses_the_drawer(browser, base_url, shots):
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, base_url=base_url,
                              is_mobile=True, has_touch=True)
    import uuid
    ctx.request.post("/auth/register", data={"email": f"e2e_{uuid.uuid4().hex[:8]}@test.local",
                                             "password": "Passw0rd!23", "name": "Phone"})
    ctx.request.post("/api/me/setup", data={"name": "Phone", "phone": "+92 3001234567",
                                            "boards": ["o-level"]})      # the enrolment gate
    _enrol(ctx)
    topics = ctx.request.get("/api/mcq/topics?syllabus=5054").json()["topics"]
    s = ctx.request.post("/api/mcq/sessions", data={"syllabus": "5054", "topics": [topics[1]["name"]],
                                                    "count": 5, "mode": "single"}).json()
    page = ctx.new_page()
    page.goto(s["url"])
    page.get_by_role("button", name=re.compile(r"^Start")).click()
    expect(page.locator(".mq-single canvas.mq-crop-canvas")).to_be_visible(timeout=20_000)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.locator(".mq-opt").nth(2).click()
    dock = page.locator("#mq-dock")
    expect(dock).to_contain_text("1/5")
    page.screenshot(path=str(shots / "mcq_phone_single.png"))
    dock.click()
    expect(page.locator("#mq-sheet")).to_be_in_viewport()
    page.screenshot(path=str(shots / "mcq_phone_sheet.png"))
    ctx.close()


def test_topical_picker_subtopics(student, shots):
    """Chapters show their subtopics; tapping chips makes a partial chapter, the
    tray sums the pool, search finds subtopics, and the session keeps to them."""
    _enrol(student)
    topics = student.request.get("/api/mcq/topics?syllabus=5054").json()["topics"]
    ch = next(t for t in topics if sum(1 for s in t["subtopics"] if s["count"] >= 3) >= 2)
    subs = [s for s in ch["subtopics"] if s["count"] >= 3][:2]
    page = student.new_page()
    page.goto("/mcq/o-level/physics-5054")
    setup = page.locator("#mq-setup")
    setup.get_by_role("tab", name=re.compile("Topical practice")).click()
    card = setup.locator(".mqs-ch", has=page.locator(".mqs-ch-name", has_text=ch["display"])).first
    expect(card.locator(".mqs-sub")).to_have_count(len(ch["subtopics"]))

    # search narrows to the chapter holding that subtopic and highlights the chip
    setup.locator("[data-q]").fill(subs[0]["name"][:12])
    expect(card).to_be_visible()
    expect(card.locator(".mqs-sub.is-hit").first).to_be_visible()
    setup.locator("[data-q]").fill("")

    for s in subs:
        card.locator(f'.mqs-sub[data-sub="{s["name"]}"]').click()
    card = setup.locator(".mqs-ch", has=page.locator(".mqs-ch-name", has_text=ch["display"])).first
    expect(card).to_have_class(re.compile("is-some"))
    expect(card.locator(".mqs-ch-tick")).to_have_attribute("aria-checked", "mixed")
    tray = setup.locator(".mqs-tray")
    expect(tray).to_contain_text(f"2 of ")
    expect(tray.locator(".mqs-tray-sum b")).to_have_text(str(subs[0]["count"] + subs[1]["count"]))
    setup.get_by_role("button", name="10", exact=True).click()
    card.scroll_into_view_if_needed()
    page.screenshot(path=str(shots / "mcq_topical_picker.png"), full_page=True)

    setup.get_by_role("button", name=re.compile("Start practice")).click()
    expect(page).to_have_url(re.compile(r"/mcq/session/[\w-]+$"))
    sid = page.url.rsplit("/", 1)[1]
    d = student.request.get(f"/api/mcq/sessions/{sid}").json()
    assert {q["topic"] for q in d["questions"]} == {ch["name"]}
    assert {q["subtopic"] for q in d["questions"]} == {s["name"] for s in subs}

    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("/mcq/o-level/physics-5054?topics=" + quote(ch["name"]))
    expect(page.locator(".mqs-ch.is-all")).to_have_count(1)
    page.screenshot(path=str(shots / "mcq_topical_picker_phone.png"), full_page=False)
