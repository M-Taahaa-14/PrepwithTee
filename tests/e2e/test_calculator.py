"""Calculator memory + history kept per account (P2-c): compute, store in a
variable and memory, reload, open on a second device, and a guest's history
merged into the account when they sign in."""

import uuid

from playwright.sync_api import expect


def keys(page, *ks):
    for k in ks:
        page.locator(f'.calc-keys button[data-k="{k}"]').first.click()


def test_history_memory_and_variables_follow_the_account(browser, base_url, shots):
    email = f"e2e_{uuid.uuid4().hex[:8]}@test.local"
    ctx = browser.new_context(viewport={"width": 1280, "height": 860}, base_url=base_url)
    page = ctx.new_page()
    # as a guest first: one calculation
    page.goto("/calculator.html")
    expect(page.locator(".calc-keys")).to_be_visible()
    keys(page, "7", "×", "6", "=")
    expect(page.locator(".calc-hist-a").first).to_have_text("= 42")
    expect(page.locator("[data-sync]")).to_contain_text("this device")

    # sign up in the same browser: the guest history is merged into the account
    assert ctx.request.post("/auth/register", data={"email": email, "password": "Passw0rd!23",
                                                    "name": "Calc Student"}).ok
    page.reload()
    expect(page.locator("[data-sync]")).to_contain_text("your account")
    expect(page.locator(".calc-hist-a").first).to_have_text("= 42")

    # 12 × 3 = 36, store in A, add to memory
    keys(page, "AC", "1", "2", "×", "3", "=")
    page.locator("[data-sto]").click()
    page.locator('[data-var="A"]').click()
    expect(page.locator('[data-var="A"] span')).to_have_text("36")
    keys(page, "M+")
    expect(page.locator("[data-mem]")).to_be_visible()
    # use A in a new sum: A + 4 = 40
    keys(page, "AC")
    page.locator('[data-var="A"]').click()
    keys(page, "+", "4", "=")
    expect(page.locator(".calc-hist-a").first).to_have_text("= 40")
    page.wait_for_timeout(800)                            # state save is debounced
    page.screenshot(path=str(shots / "calculator.png"))

    # reload: everything still there
    page.reload()
    expect(page.locator(".calc-hist-a")).to_have_count(3)
    expect(page.locator('[data-var="A"] span')).to_have_text("36")
    expect(page.locator("[data-mem]")).to_be_visible()

    # a second device (new browser, same account) sees the same
    other = browser.new_context(viewport={"width": 1280, "height": 860}, base_url=base_url)
    assert other.request.post("/auth/login", data={"email": email, "password": "Passw0rd!23"}).ok
    p2 = other.new_page()
    p2.goto("/calculator.html")
    expect(p2.locator(".calc-hist-a").first).to_have_text("= 40")
    expect(p2.locator('[data-var="A"] span')).to_have_text("36")
    keys(p2, "AC", "MR", "=")
    expect(p2.locator(".calc-hist-a").first).to_have_text("= 36")

    # tap ↺ to bring a calculation back for editing; clear history
    page.reload()
    page.locator("[data-hist-q]").last.click()
    expect(page.locator("[data-expr]")).to_have_text("7×6")
    page.once("dialog", lambda d: d.accept())
    page.locator("[data-clear]").click()
    expect(page.locator(".calc-hist-a")).to_have_count(0)
    other.close()
    ctx.close()
