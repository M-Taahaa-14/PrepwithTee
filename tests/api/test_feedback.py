"""Feedback forms need a name and a reachable email (tutor, 2026-09-30)."""
import pytest


@pytest.fixture()
def no_dns(monkeypatch):
    """Domain lookups are faked: "nowhere.invalid" does not exist, the rest do."""
    import website.app as appmod
    monkeypatch.setattr(appmod, "_email_domain_exists", lambda d: d != "nowhere.invalid")


def _send(client, **kw):
    body = {"message": "The ruler snaps to the wrong edge", "type": "issue", "page": "/papers"}
    return client.post("/api/feedback", json={**body, **kw})


def test_name_and_email_are_required(client, no_dns):
    assert _send(client, email="ali@gmail.com").status_code == 400                 # no name
    assert _send(client, name="Ali").status_code == 400                            # no email
    r = _send(client, name="Ali", email="ali@gmail.com")
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("email", ["ali", "ali@", "ali@gmail", "a li@gmail.com", "ali@@gmail.com",
                                   "ali..x@gmail.com", "ali@nowhere.invalid"])
def test_bad_emails_are_refused(client, no_dns, email):
    r = _send(client, name="Ali", email=email)
    assert r.status_code == 400
    assert "email" in r.json()["detail"].lower()


def test_email_is_stored(client, no_dns):
    import users_db
    _send(client, name="Sara Khan", email="sara.k@outlook.com")
    row = users_db.get_feedback(5)[0]
    assert row["name"] == "Sara Khan" and row["email"] == "sara.k@outlook.com"


def test_signed_in_account_email_skips_the_domain_lookup(client, new_student, monkeypatch):
    import website.app as appmod
    def boom(d):
        raise AssertionError("looked up the account's own domain")
    monkeypatch.setattr(appmod, "_email_domain_exists", boom)
    me = new_student()
    r = _send(client, name="Test Student", email=me["email"].upper())
    assert r.status_code == 200, r.text
