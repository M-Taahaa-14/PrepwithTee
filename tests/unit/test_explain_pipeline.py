"""pipeline.explain: prompt building and response parsing (no API calls)."""

import json
from types import SimpleNamespace

import pytest

from pipeline import explain


def _msg(payload, stop="end_turn"):
    return SimpleNamespace(stop_reason=stop,
                           content=[SimpleNamespace(type="text", text=json.dumps(payload))])


GOOD = {"summary": "s", "parts": [{"label": "", "steps": [], "answer": "A", "marking": "m"}],
        "hints": ["1", "2", "3", "4"], "mcq_options": [], "common_mistakes": [],
        "confidence": "high"}


def test_parse_keeps_three_hints():
    assert explain.parse_message(_msg(GOOD))["hints"] == ["1", "2", "3"]


@pytest.mark.parametrize("bad", [
    _msg(GOOD, stop="max_tokens"), _msg(GOOD, stop="refusal"),
    _msg({**GOOD, "parts": []}), _msg({**GOOD, "hints": ["only one"]}),
    SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="not json")]),
])
def test_parse_rejects_unusable(bad):
    assert explain.parse_message(bad) is None


def test_batch_cost_is_half():
    full = explain.cost("claude-opus-5", 3000, 2000, batch=False)
    assert full == pytest.approx((3000 * 5 + 2000 * 25) / 1e6)
    assert explain.cost("claude-opus-5", 3000, 2000, batch=True) == pytest.approx(full / 2)


def test_schema_is_strict_objects():
    """Structured outputs need additionalProperties: false on every object."""
    def walk(node):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False
            assert set(node["required"]) == set(node["properties"])
            for v in node["properties"].values():
                walk(v)
        if node.get("type") == "array":
            walk(node["items"])
    walk(explain.SCHEMA)
