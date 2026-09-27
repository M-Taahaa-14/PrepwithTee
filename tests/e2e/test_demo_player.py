"""Home-page hero demo: the laptop walkthrough player (demo-player.js)."""

import json
import re
from pathlib import Path

from playwright.sync_api import expect

DEMO = Path(__file__).resolve().parents[2] / "website" / "static" / "demos" / "hero"


def test_timeline_points_at_real_shots():
    tl = json.loads((DEMO / "timeline.json").read_text(encoding="utf-8"))
    assert tl["steps"] and tl["w"] and tl["h"]
    assert tl["steps"][0].get("card") and tl["steps"][-1].get("card")      # opener + "Ask Tee" closer
    for s in tl["steps"]:
        assert s.get("card") or (DEMO / s["shot"]).exists(), s
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
    expect(dp.locator("img[src$='05-booklet.jpg']")).to_have_count(1)
    ctx.unroute("**/demo-player.js*")
    page.goto("/")

    dp.scroll_into_view_if_needed()
    expect(dp.locator(".dp-ch")).to_have_count(7)
    expect(dp).to_have_class(re.compile(r"is-open"))                 # the laptop lid opened
    expect(dp.locator(".dp-card")).to_contain_text("Not sure where to start?")
    expect(dp.locator(".dp-n")).to_have_text("1/12")
    expect(dp.locator(".dp-n")).to_have_text("2/12", timeout=10_000)  # autoplay advances

    # chapter button jumps; hovering the screen pauses
    dp.locator(".dp-ch", has_text="Learn").click()
    expect(dp.locator(".dp-caption p")).to_contain_text("step-by-step")
    dp.locator(".dp-device").hover()
    expect(dp).to_have_class(re.compile(r"is-paused"))
    held = dp.locator(".dp-n").inner_text()
    page.wait_for_timeout(4_500)
    assert dp.locator(".dp-n").inner_text() == held
    page.wait_for_timeout(1_200)                              # let the crossfade settle
    dp.screenshot(path=str(shots / "demo-player.png"))

    # the pause button holds even after the mouse leaves
    dp.locator(".dp-play").click()
    page.mouse.move(5, 5)
    page.wait_for_timeout(300)
    expect(dp).to_have_class(re.compile(r"is-paused"))
    expect(dp.locator(".dp-play")).to_have_attribute("aria-label", "Play")
    dp.locator('[data-act="next"]').click()
    expect(dp.locator(".dp-n")).not_to_have_text(held)

    # the closing card offers real ways to reach Tee
    dp.locator(".dp-ch", has_text="Ask Tee").click()
    expect(dp.locator(".dp-card-btn", has_text="WhatsApp Tee")).to_have_attribute("href", re.compile(r"^https://wa\.me/"))
    expect(dp.locator(".dp-card-btn", has_text="Book a free demo")).to_have_attribute("href", "#contact")
    ctx.close()


def test_player_fits_a_phone(browser, base_url):
    ctx = browser.new_context(base_url=base_url, viewport={"width": 375, "height": 812}, is_mobile=True)
    page = ctx.new_page()
    page.goto("/")
    dp = page.locator(".dp[data-demo]")
    dp.scroll_into_view_if_needed()
    expect(dp.locator(".dp-ch")).to_have_count(7)
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    ctx.close()


def test_reduced_motion_shows_frames_without_autoplay(browser, base_url):
    ctx = browser.new_context(base_url=base_url, reduced_motion="reduce")
    page = ctx.new_page()
    page.goto("/")
    dp = page.locator(".dp[data-demo]")
    dp.scroll_into_view_if_needed()
    expect(dp.locator(".dp-n")).to_have_text("1/12")
    expect(dp).to_have_class(re.compile(r"is-open"))                 # no lid animation, just open
    expect(dp.locator(".dp-play")).to_be_hidden()
    page.wait_for_timeout(5_000)
    expect(dp.locator(".dp-n")).to_have_text("1/12")
    dp.locator('[data-act="next"]').click()
    expect(dp.locator(".dp-n")).to_have_text("2/12")
    ctx.close()
