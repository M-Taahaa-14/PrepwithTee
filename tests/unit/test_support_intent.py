"""Help centre: intent routing (English + Roman Urdu) and page navigation.

support.intent() decides whether a question gets an account-aware answer with
one-tap fixes or goes to the AI. A problem ("my booklet failed") must never be
answered with a marketing blurb - that was the old widget's main fault.
"""

import pytest

support = pytest.importorskip("website.support")


@pytest.mark.parametrize("text, want", [
    ("I paid but my plan is still free", "payment_status"),
    ("I sent the jazzcash screenshot yesterday, when will it be approved?", "payment_status"),
    ("paise bhej diye abhi tak plan nahi aya", "payment_status"),
    ("my booklet failed to build", "booklet_problem"),
    ("mera booklet nahi ban raha", "booklet_problem"),
    ("the mock test pdf is stuck loading", "booklet_problem"),
    ("how many papers do I have left this month", "quota"),
    ("free limit khatam ho gayi", "quota"),
    ("I can't log in", "login"),
    ("forgot password", "password"),
    ("password bhool gaya", "password"),
    ("is there a free trial?", "trial"),
    ("which plan should I get?", "plan_advice"),
    ("how much are the plans", "pricing"),
    ("fees kitni hai?", "pricing"),
    ("tell me about the classes", "classes"),
    ("my son is in O level", "parent"),
    ("can I talk to a real person", "contact"),
    ("what subjects do you cover", "subjects"),
    ("the page is broken, error everywhere", "problem"),
])
def test_intent(text, want):
    assert support.intent(text) == want


def test_problems_never_get_the_pricing_blurb():
    # the old keyword matcher sent "I can't log in" to the sign-up FAQ and "payment" to pricing
    assert support.intent("I can't log in") != "pricing"
    assert support.intent("payment not showing") == "payment_status"


def test_word_boundaries():
    # "ms" used to match inside "problems"; "help" anywhere meant the contact card
    assert support.intent("what are vectors and momentum") is None
    assert support.intent("help me find 0625 notes") is None


@pytest.mark.parametrize("text, lang", [
    ("fees kitni hai?", "ur-Latn"), ("mera booklet nahi ban raha", "ur-Latn"),
    ("فیس کتنی ہے", "ur"), ("how much are the plans", "en")])
def test_language(text, lang):
    assert support.language(text) == lang


def test_sitting_parse():
    s = support._sitting(" 2019 may june paper 22 ")
    assert s == {"year": 2019, "session": "s", "paper": 2, "variant": "2"}
    assert support._sitting(" oct/nov 2021 p4 ")["session"] == "w"


def test_subject_codes_from_names():
    assert support._subject_codes(" igcse physics ") == ["0625"]
    assert support._subject_codes(" o level maths ") == ["4024"]
    assert support._subject_codes(" 9709 ") == ["9709"]
    assert set(support._subject_codes(" physics ")) >= {"5054", "0625"}


def test_navigate_to_a_sitting():
    out = support.navigate("2019 May/June paper 2 5054")
    assert out["links"][0]["u"] == "/yearly/open?syllabus=5054&year=2019&session=s&paper=2&variant=1"
    assert "/yearly/" in out["links"][1]["u"]          # every variant that year


def test_clean_links_drops_made_up_urls():
    txt = "See [plans](/pricing.html), [secret](/totally-made-up-page.html) and [evil](https://evil.example)."
    out = support.clean_links(txt)
    assert "[plans](/pricing.html)" in out
    assert "/totally-made-up-page" not in out and "evil.example" not in out
    assert "secret" in out and "evil" in out          # the words stay, the links go


def test_scrub_removes_contact_details():
    from website import support_store
    t = support_store.scrub("mail me at ali@gmail.com or call 0300 1234567, card 4111 1111 1111 1111")
    assert "gmail" not in t and "1234567" not in t and "4111" not in t
