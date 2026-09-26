"""P2-e in a real browser. The AI itself is stubbed at the network layer
(page.route), so these check the page: the Solver's crop + both modes +
follow-up, and the Tutor's search, server ids, edit-and-resend and regenerate."""

import json
import re

from playwright.sync_api import expect

def _png_file(tmp_path):
    import fitz
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 240, 160), 0)
    pix.set_rect(pix.irect, (240, 236, 220))
    f = tmp_path / "q.png"
    f.write_bytes(pix.tobytes("png"))
    return str(f)


def test_solver_solve_crop_and_follow_up(student, shots, tmp_path):
    page = student.new_page()
    sent = []

    def solve(route):
        sent.append(json.loads(route.request.post_data))
        route.fulfill(json={"html": "<h3>Working</h3><div class='step'>\\(v = s/t = 120/8\\)</div>"
                                    "<h3>Answer</h3><p>15 m/s</p>", "provider": "stub", "mode": "solve"})
    page.route("**/api/solve", solve)
    page.route("**/api/solve/followup", lambda r: r.fulfill(json={"html": "<p>Because speed is distance over time.</p>"}))
    page.goto("/solver")
    expect(page.locator("#sv-go")).to_be_disabled()
    page.locator('#sv-q input[type=file]').last.set_input_files(_png_file(tmp_path))
    expect(page.locator("#sv-q .sv-crop-rect")).to_be_visible()
    # drag the crop's bottom-right corner in
    h = page.locator("#sv-q .sv-h-se").bounding_box()
    page.mouse.move(h["x"] + 8, h["y"] + 8); page.mouse.down()
    page.mouse.move(h["x"] - 60, h["y"] - 40, steps=5); page.mouse.up()
    page.locator("#sv-note").fill("part (b)")
    page.locator("#sv-go").click()
    expect(page.locator(".sv-answer")).to_contain_text("15 m/s")
    expect(page.locator(".sv-answer .katex").first).to_be_visible(timeout=10_000)
    body = sent[-1]
    assert body["mode"] == "solve" and body["note"] == "part (b)"
    assert body["image"].startswith("data:image/jpeg;base64,")
    page.locator("#sv-fq").fill("why divide?")
    page.locator("#sv-follow button[type=submit]").click()
    expect(page.locator(".sv-thread .sv-a")).to_contain_text("distance over time")
    page.screenshot(path=str(shots / "solver.png"))


def test_solver_check_my_working_typed(student, tmp_path):
    page = student.new_page()
    sent = []

    def solve(route):
        sent.append(json.loads(route.request.post_data))
        route.fulfill(json={"html": "<h3>Verdict</h3><p><b>Estimated mark: 2 / 3</b></p>"
                                    "<div class='mark ok'>Correct formula</div><div class='mark bad'>Unit missing</div>",
                            "provider": "stub", "mode": "check"})
    page.route("**/api/solve", solve)
    page.goto("/solver?mode=check")
    expect(page.locator('[data-mode="check"]')).to_have_attribute("aria-checked", "true")
    page.locator('#sv-q input[type=file]').last.set_input_files(_png_file(tmp_path))
    expect(page.locator("#sv-go")).to_be_disabled()                    # working still missing
    page.locator('[data-wtab="type"]').click()
    page.locator("#sv-wtext").fill("v = 120 / 8 = 15")
    page.locator("#sv-go").click()
    expect(page.locator(".sv-answer .mark.bad")).to_contain_text("Unit missing")
    assert sent[-1]["mode"] == "check" and sent[-1]["working_text"] == "v = 120 / 8 = 15"
    assert "working" not in sent[-1]


def _sse(text, uid, bid, sid="s-1"):
    done = {"done": True, "html": f"<p>{text}</p>", "provider": "stub", "session_id": sid,
            "user_message_id": uid, "bot_message_id": bid, "summary": None}
    return f"data: {json.dumps({'token': text})}\n\ndata: {json.dumps(done)}\n\n"


def test_tutor_search_edit_and_regenerate(student, shots):
    page = student.new_page()
    page.route("**/api/tutor/sessions", lambda r: r.fulfill(json={"sessions": [
        {"id": "a", "title": "Hooke's law springs", "subject": "0625", "updated_at": "2026-09-26T10:00:00Z", "pinned": False},
        {"id": "b", "title": "Quadratic inequalities", "subject": "0580", "updated_at": "2026-09-20T10:00:00Z", "pinned": False}]}))
    streams, deletes = [], []
    replies = iter([("First answer", "u1", "b1"), ("Edited answer", "u2", "b2"), ("Another try", "u3", "b3")])

    def stream(route):
        streams.append(json.loads(route.request.post_data))
        text, uid, bid = next(replies)
        route.fulfill(status=200, headers={"Content-Type": "text/event-stream"}, body=_sse(text, uid, bid))
    page.route("**/api/tutor/stream", stream)
    page.route(re.compile(r".*/api/tutor/sessions/s-1/messages/.*"),
               lambda r: (deletes.append(r.request.url.rsplit("/", 1)[-1]), r.fulfill(json={"ok": True, "deleted": 2})))
    page.goto("/tutor.html")

    # search the chat list
    expect(page.locator(".tc-session-item")).to_have_count(2)
    page.locator("#tc-search").fill("hooke")
    expect(page.locator(".tc-session-item:not([hidden])")).to_have_count(1)
    page.locator("#tc-search").fill("zzz")
    expect(page.locator("#tc-search-none")).to_be_visible()
    page.locator("#tc-search").fill("")

    # a reply takes the server's ids
    page.locator("#tc-msg").fill("What is Hooke's law?")
    page.locator("#tc-send").click()
    expect(page.locator(".tc-msg.bot .tc-bubble").last).to_contain_text("First answer")
    expect(page.locator('.tc-msg.bot[data-msg="b1"]')).to_have_count(1)
    expect(page.locator('.tc-msg.user[data-msg="u1"]')).to_have_count(1)

    # edit and resend: the conversation restarts from the edited message
    page.locator('.tc-msg.user[data-msg="u1"]').hover()
    page.locator('.tc-msg.user[data-msg="u1"] .tc-edit-btn').click()
    page.locator(".tc-edit-box textarea").fill("State Hooke's law")
    page.locator(".tc-edit-box [data-send]").click()
    expect(page.locator(".tc-msg.bot .tc-bubble").last).to_contain_text("Edited answer")
    expect(page.locator(".tc-msg.user")).to_have_count(1)
    expect(page.locator(".tc-msg.bot")).to_have_count(1)
    assert deletes == ["u1"] and streams[-1]["message"] == "State Hooke's law"

    # regenerate replaces the answer (and cuts from its question on the server)
    page.locator('.tc-msg.bot[data-msg="b2"] .regen-btn').click()
    expect(page.locator(".tc-msg.bot .tc-bubble").last).to_contain_text("Another try")
    expect(page.locator(".tc-msg.bot")).to_have_count(1)
    assert deletes[-1] == "u2" and streams[-1]["message"] == "State Hooke's law"
    page.wait_for_timeout(900)                       # let the bubbles' fade-in finish
    page.screenshot(path=str(shots / "tutor.png"))


def test_old_solver_links_land_on_the_solver(student):
    page = student.new_page()
    page.goto("/ask.html")
    expect(page).to_have_url(re.compile(r"/solver$"))
    page.goto("/tutor.html?tab=solver")
    expect(page).to_have_url(re.compile(r"/solver$"))
