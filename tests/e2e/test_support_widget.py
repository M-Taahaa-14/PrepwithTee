"""Help centre (static/support.js): open from the launcher, an account-aware
answer with link cards and buttons, the chat surviving a page change, the
handoff form reaching the admin Inbox, and the admin Support section."""

import re

from playwright.sync_api import expect


def test_help_centre_chat_and_handoff(student, admin_page, shots):
    page = student.new_page()
    page.goto("/papers")
    launcher = page.get_by_role("button", name=re.compile("Help and support"))
    expect(launcher).to_be_visible()
    launcher.click()
    panel = page.get_by_role("dialog", name="PrepWithTee help")
    expect(panel).to_be_visible()
    expect(panel.locator(".hc-q").first).to_be_visible()                  # questions for this page
    expect(panel.locator(".hc-plan")).to_have_count(0)                     # no plan card (tutor, 2026-10-09)
    page.wait_for_timeout(500)
    page.screenshot(path=str(shots / "help_home.png"))

    panel.get_by_role("tab", name="Chat").click()
    box = panel.get_by_role("textbox", name="Your question")
    box.fill("2019 may june paper 2 5054")
    box.press("Enter")
    card = panel.locator(".hc-linkcard").first
    expect(card).to_contain_text("2019 May/June Paper 21")
    expect(card).to_have_attribute("href", re.compile(r"^/yearly/open\?syllabus=5054"))

    # the conversation follows them to the next page
    page.goto("/yearly")
    page.get_by_role("button", name=re.compile("Help and support")).click()
    panel = page.get_by_role("dialog", name="PrepWithTee help")
    panel.get_by_role("tab", name="Chat").click()
    expect(panel.locator(".hc-msg.user")).to_contain_text("2019 may june paper 2 5054")
    page.wait_for_timeout(500)
    page.screenshot(path=str(shots / "help_chat.png"))

    panel.get_by_role("button", name="Send this to Tee").first.click()
    form = panel.locator("form.hc-form")
    expect(form.locator("[name=email]")).not_to_have_value("")              # prefilled from the account
    form.locator("[name=message]").fill("E2E: the 2019 paper link test")
    form.get_by_role("button", name="Send to Tee").click()
    expect(panel.locator(".hc-done")).to_contain_text("Sent to Tee")

    panel.get_by_role("tab", name="My requests").click()
    expect(panel.locator(".hc-thread").first).to_contain_text("E2E: the 2019 paper link test")

    # Tee sees it in the Inbox with the chat attached
    admin_page.goto("/admin#/inbox?source=support&status=new")
    row = admin_page.get_by_text("E2E: the 2019 paper link test").first
    expect(row).to_be_visible()
    row.click()
    expect(admin_page.locator(".chat-log")).to_contain_text("2019 may june paper 2 5054")
    expect(admin_page.locator(".acct-card")).to_contain_text("Free")
    admin_page.wait_for_timeout(600)
    admin_page.screenshot(path=str(shots / "help_inbox.png"))


def test_launcher_hidden_on_paper_viewer_but_menu_opens_it(student):
    page = student.new_page()
    page.goto("/yearly/open?syllabus=5054&year=2019&session=s&paper=2&variant=1")
    expect(page).to_have_url(re.compile(r"/yearly/view/\d+"))
    expect(page.locator("#pwt-chatbot-wrap")).to_be_hidden()
    page.evaluate("window.pwtSupport.open('home')")
    expect(page.get_by_role("dialog", name="PrepWithTee help")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog", name="PrepWithTee help")).to_be_hidden()


def test_admin_support_section(admin_page):
    admin_page.goto("/admin#/support")
    expect(admin_page.get_by_role("heading", name="Support", exact=True)).to_be_visible()
    expect(admin_page.locator(".kpi").first).to_contain_text("Questions asked")
    expect(admin_page.locator("#sp-status")).to_contain_text("Office hours")
