"""Country from a student's WhatsApp number (admin Students table, 2026-10-04)."""

import pytest


@pytest.mark.parametrize("phone, iso", [
    ("+966 533450595", "SA"), ("+351 935388217", "PT"), ("+880 1911607915", "BD"),
    ("+971501234567", "AE"), ("+230 57095167", "MU"), ("+1 8765551234", "JM"),
    ("+1 4165551234", "US"), ("+77012345678", "KZ"),
    ("+92 300 1234567", "PK"), ("+‪92 300 1234567", "PK"),
    ("03204884375", "PK"), ("3222656414", "PK"), ("923168851986", "PK"),
    ("00965 67645386", "KW"),
])
def test_known(phone, iso):
    import countries
    assert countries.lookup(phone)[0] == iso


@pytest.mark.parametrize("phone", [None, "", "eet444", "51602071", "9826072011", "999"])
def test_unknown_is_never_guessed(phone):
    import countries
    assert countries.lookup(phone) is None
