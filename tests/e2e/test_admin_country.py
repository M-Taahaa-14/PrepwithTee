"""Students table shows each student's country (from the WhatsApp number) and
filters/sorts by it (2026-10-04)."""

import sqlite3
import uuid

import pytest

from tests.e2e.conftest import USERS_DB

pytestmark = pytest.mark.e2e


def test_country_column_and_filter(admin_page, base_url):
    tag = uuid.uuid4().hex[:6]
    ctx = admin_page.context.browser.new_context(base_url=base_url)   # separate session
    for i, phone in enumerate(["+966 533450595", "03204884375", "+880 1911607915"]):
        r = ctx.request.post("/auth/register", data={
            "email": f"e2e_c{tag}{i}@test.local", "password": f"{uuid.uuid4().hex}Aa1!",
            "name": f"Country {tag} {i}"})
        assert r.ok, r.text()
        con = sqlite3.connect(USERS_DB)
        con.execute("UPDATE profiles SET phone=? WHERE email=?", (phone, f"e2e_c{tag}{i}@test.local"))
        con.commit(); con.close()
    ctx.close()

    page = admin_page
    page.goto(f"/admin#/students?q={tag}")
    page.wait_for_selector(".dt .country")
    text = page.locator(".dt tbody").inner_text()
    assert "Saudi Arabia" in text and "Pakistan" in text and "Bangladesh" in text

    sel = page.locator('[data-filter="country"]')
    assert "Saudi Arabia" in sel.inner_text()
    sel.select_option("SA")
    page.wait_for_function("document.querySelectorAll('.dt tbody tr').length === 1")
    assert "Saudi Arabia" in page.locator(".dt tbody").inner_text()
    page.screenshot(path="e2e-shots/admin_country.png", full_page=False)
