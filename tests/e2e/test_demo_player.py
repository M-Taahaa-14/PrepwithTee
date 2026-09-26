"""P3 landing demo: the screenshot player on the home page."""

import json
from pathlib import Path

from playwright.sync_api import expect

DEMO = Path(__file__).resolve().parents[2] / "website" / "static" / "demos" / "how-it-works"


def test_timeline_points_at_real_shots():
    tl = json.loads((DEMO / "timeline.json").read_text(encoding="utf-8"))
    assert tl["steps"] and tl["w"] and tl["h"]
    for s in tl["steps"]:
        assert (DEMO / s["shot"]).exists(), s["shot"]
        assert s["caption"] and s["chapter"] and s["dur"] > 0
        if s["cursor"]:
            assert all(0 <= v <= 1 for v in s["cursor"])


def test_player_loads_lazily_and_plays(browser, base_url, shots):
    ctx = browser.new_context(base_url=base_url, viewport={"width": 1280, "height": 860})
    page = ctx.new_page()
    # without JS the section is a single poster frame
    ctx.route("**/demo-player.js*", lambda r: r.abort())
    page.goto("/")
    dp = page.locator(".dp[data-demo]")
    expect(dp.locator("img[src$='04-booklet.jpg']")).to_have_count(1)
    ctx.unroute("**/demo-player.js*")
    page.goto("/")

    dp.scroll_into_view_if_needed()
    expect(dp.locator(".dp-ch")).to_have_count(5)
    expect(dp.locator(".dp-n")).to_have_text("1/9")
    expect(dp.locator(".dp-n")).to_have_text("2/9", timeout=8_000)   # autoplay advances

    # chapter button jumps; hovering the screen pauses
    dp.locator(".dp-ch", has_text="Understand").click()
    expect(dp.locator(".dp-caption p")).to_contain_text("step-by-step")
    dp.locator(".dp-device").hover()
    expect(dp).to_have_class("dp is-paused")
    held = dp.locator(".dp-n").inner_text()
    page.wait_for_timeout(4_500)
    assert dp.locator(".dp-n").inner_text() == held
    page.wait_for_timeout(1_200)                              # let the crossfade settle
    dp.screenshot(path=str(shots / "demo-player.png"))

    # the pause button holds even after the mouse leaves
    dp.locator(".dp-play").click()
    page.mouse.move(5, 5)
    page.wait_for_timeout(300)
    expect(dp).to_have_class("dp is-paused")
    expect(dp.locator(".dp-play")).to_have_attribute("aria-label", "Play")
    dp.locator('[data-act="next"]').click()
    expect(dp.locator(".dp-n")).not_to_have_text(held)
    ctx.close()


def test_player_fits_a_phone(browser, base_url):
    ctx = browser.new_context(base_url=base_url, viewport={"width": 375, "height": 812}, is_mobile=True)
    page = ctx.new_page()
    page.goto("/")
    dp = page.locator(".dp[data-demo]")
    dp.scroll_into_view_if_needed()
    expect(dp.locator(".dp-ch")).to_have_count(5)
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    ctx.close()


def test_reduced_motion_shows_frames_without_autoplay(browser, base_url):
    ctx = browser.new_context(base_url=base_url, reduced_motion="reduce")
    page = ctx.new_page()
    page.goto("/")
    dp = page.locator(".dp[data-demo]")
    dp.scroll_into_view_if_needed()
    expect(dp.locator(".dp-n")).to_have_text("1/9")
    expect(dp.locator(".dp-play")).to_be_hidden()
    page.wait_for_timeout(5_000)
    expect(dp.locator(".dp-n")).to_have_text("1/9")
    dp.locator('[data-act="next"]').click()
    expect(dp.locator(".dp-n")).to_have_text("2/9")
    ctx.close()
