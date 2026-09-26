"""Home page booking + feedback panels: hidden ones are inert (out of the tab
order), open ones must be usable again."""

from playwright.sync_api import expect


def test_booking_panel_is_inert_until_opened(browser, base_url):
    ctx = browser.new_context(base_url=base_url)
    page = ctx.new_page()
    page.goto("/")
    choice = page.locator("#bkChoice")
    assert choice.evaluate("el => el.inert") is True
    page.locator('a[href="#contact"]').first.click()
    expect(choice).to_have_class("bk-choice open")
    assert choice.evaluate("el => el.inert") is False
    # something inside the open dialog takes a real click (inert would swallow it)
    btn = choice.locator("button, a").filter(has_not_text="×").first
    btn.click(timeout=3_000)
    page.keyboard.press("Escape")
    assert page.locator("#fbPanel").evaluate("el => el.inert") is True
    ctx.close()
