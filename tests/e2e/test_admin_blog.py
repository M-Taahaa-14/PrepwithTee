"""Blog studio in a real browser (no AI calls): create a post, write, save,
check the SEO panel and Google preview, schedule it, see the revision, delete."""

import uuid
from datetime import datetime, timedelta


def test_blog_studio_flow(admin_page, shots):
    page = admin_page
    page.goto("/admin#/blog")
    page.get_by_role("button", name="New post").click()
    page.wait_for_function("location.hash.startsWith('#/post/')")
    title = f"E2E post {uuid.uuid4().hex[:6]}"
    page.locator("[name=title]").fill(title)
    page.locator("[name=slug]").fill(title.lower().replace(" ", "-"))
    page.locator("[name=body]").fill("## One\n\nSee [booklets](/papers/topical) and [notes](/notes).\n\n## Two\n\nMore text.")
    page.locator("[name=meta_desc]").fill("A" * 140)
    assert page.locator("[data-serp-title]").inner_text() == title
    assert page.locator("[data-seo] .check-row.ok", has_text="links to your own pages").count() == 1
    page.get_by_role("button", name="Save").click()
    page.locator("[data-saved]", has_text="saved just now").wait_for()

    # bold button wraps the selection
    page.locator("[name=body]").evaluate("t => { t.focus(); t.setSelectionRange(3, 6); }")
    page.locator('[data-md="**"]').click()
    assert page.locator("[name=body]").input_value().startswith("## **One**")

    page.locator('[data-preview]').click()
    page.locator(".md-preview h2", has_text="One").wait_for()
    page.screenshot(path=str(shots / "admin-blog-editor.png"))
    page.locator('[data-preview]').click()

    when = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%dT10:00")
    page.locator("[name=when]").fill(when)
    page.get_by_role("button", name="Schedule").click()
    page.locator(".page-head .pill", has_text="Scheduled").wait_for()
    assert page.locator("[data-rev]").count() >= 2

    page.goto("/admin#/blog")
    row = page.locator(".dt tbody tr", has_text=title)
    row.locator(".pill", has_text="Scheduled").wait_for()
    row.click()
    page.locator("[data-del]").click()
    page.locator(".modal button[type=submit]").click()
    page.wait_for_function("location.hash === '#/blog'")
    page.wait_for_timeout(600)
    assert page.locator(".dt tbody tr", has_text=title).count() == 0
