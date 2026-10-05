"""Keyboard shortcuts (static/shortcuts.js): the header button + "?" panel on
static and server-rendered pages, G-then-letter navigation, Alt+C calculator,
Alt+P pen, and switching single-key shortcuts off."""

import re

from playwright.sync_api import expect


def _ready(page):
    page.wait_for_function("() => !!window.pwtShortcuts")


def test_panel_from_button_and_question_mark(page, base_url, shots):
    page.goto(f"{base_url}/papers")                      # server-rendered page
    _ready(page)
    btn = page.locator(".site-header [data-shortcuts]")
    expect(btn).to_be_visible()
    btn.click()
    dlg = page.get_by_role("dialog", name="Keyboard shortcuts")
    expect(dlg).to_be_visible()
    expect(dlg.locator(".ks-group h3")).to_contain_text(["Anywhere", "Tools on this page", "Go to a page"])
    page.wait_for_timeout(400)                           # let the fade-in finish
    page.screenshot(path=str(shots / "shortcuts_panel.png"))
    dlg.locator("[data-ks-filter]").fill("calc")
    expect(dlg.locator(".ks-row:visible")).to_have_count(1)
    page.keyboard.press("Escape")
    expect(dlg).to_be_hidden()

    page.goto(f"{base_url}/pricing.html")                # stamped static page
    _ready(page)
    page.keyboard.press("?")
    expect(page.get_by_role("dialog", name="Keyboard shortcuts")).to_be_visible()


def test_go_to_chord(page, base_url):
    page.goto(f"{base_url}/papers")
    _ready(page)
    page.keyboard.press("g")
    expect(page.locator(".ks-hint.is-on")).to_contain_text("MCQ practice")
    page.keyboard.press("m")
    expect(page).to_have_url(re.compile(r"/mcq$"))


def test_alt_c_opens_calculator_where_no_dock_was(page, base_url, shots):
    page.goto(f"{base_url}/papers")
    _ready(page)
    assert page.locator(".pwt-dock").count() == 0
    page.keyboard.press("Alt+c")
    expect(page.locator(".pwt-dock.open #pwt-dock-panel")).to_be_visible(timeout=15_000)
    expect(page.locator(".pwt-tab.on")).to_have_attribute("data-tool", "calculator")
    page.wait_for_timeout(600)
    page.screenshot(path=str(shots / "shortcuts_calculator.png"))
    page.locator("body").click(position={"x": 30, "y": 400})
    page.keyboard.press("Alt+c")                         # same tool again closes it
    expect(page.locator(".pwt-dock.open")).to_have_count(0)


def test_alt_p_pen_toggles(page, base_url):
    page.goto(f"{base_url}/papers")
    _ready(page)
    page.wait_for_function("() => !!window.pwtInk", timeout=15_000)
    page.keyboard.press("Alt+p")
    assert page.evaluate("window.pwtInk.tool") == "pen"
    expect(page.locator(".ks-toast.is-on")).to_contain_text("Pen")
    page.keyboard.press("Alt+p")
    assert page.evaluate("window.pwtInk.tool") == "pointer"


def test_single_keys_can_be_switched_off(page, base_url):
    page.goto(f"{base_url}/papers")
    _ready(page)
    page.keyboard.press("?")
    dlg = page.get_by_role("dialog", name="Keyboard shortcuts")
    dlg.locator(".ks-switch").click()
    page.keyboard.press("Escape")
    page.keyboard.press("?")
    expect(dlg).to_be_hidden()
    page.keyboard.press("g")
    expect(page.locator(".ks-hint.is-on")).to_have_count(0)
    page.keyboard.press("Alt+c")                         # Alt shortcuts still work
    expect(page.locator(".pwt-dock.open #pwt-dock-panel")).to_be_visible(timeout=15_000)
