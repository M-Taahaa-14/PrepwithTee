"""pipeline.explain: parsing model output and pacing on rate-limit headers (no API calls)."""

import pytest

from pipeline import explain

GOOD = ('{"summary":"s","parts":[{"label":"","steps":[{"title":"t","body":"b"}],'
        '"answer":"A","marking":"m"}],"hints":["1","2","3","4"],"mcq_options":[],'
        '"common_mistakes":[],"confidence":"high"}')


def test_parse_keeps_three_hints():
    assert explain.parse_text(GOOD)["hints"] == ["1", "2", "3"]


def test_parse_accepts_code_fences_and_prose_around_json():
    assert explain.parse_text("Here you go:\n```json\n" + GOOD + "\n```")["summary"] == "s"


def test_single_backslash_latex_survives():
    # \frac and \times would otherwise decode as a form feed / tab + text
    raw = GOOD.replace('"body":"b"', '"body":"$\\frac{F}{A} \\times 2$ then\\nnext"')
    raw = raw.replace("\\\\", "\\")          # the model's single backslashes
    body = explain.parse_text(raw)["parts"][0]["steps"][0]["body"]
    assert "\\frac{F}{A}" in body and "\\times" in body and "\n" in body


@pytest.mark.parametrize("bad", ["not json", '{"parts":[]}',
                                 GOOD.replace('"hints":["1","2","3","4"]', '"hints":["1"]')])
def test_parse_rejects_unusable(bad):
    assert explain.parse_text(bad) is None


def test_bad_confidence_defaults_to_medium():
    assert explain.parse_text(GOOD.replace('"high"', '"sure"'))["confidence"] == "medium"


@pytest.mark.parametrize("header,seconds", [("7.66s", 7.66), ("2m59.5s", 179.5),
                                            ("1h2m3s", 3723), ("", 0), (None, 0)])
def test_reset_header_parsing(header, seconds):
    assert explain._seconds(header) == pytest.approx(seconds)
