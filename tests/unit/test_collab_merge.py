"""static/collab.js merge3: the three-way merge that lets a teacher and a
student draw on the same page at once without losing each other's work."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIB = (ROOT / "website" / "static" / "collab.js").as_uri()
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")


def merge(base, mine, theirs):
    js = f"""
    const {{ merge3, baseOf }} = await import({json.dumps(LIB)});
    const out = merge3(baseOf({json.dumps(base)}), {json.dumps(mine)}, {json.dumps(theirs)});
    console.log(JSON.stringify(out));"""
    r = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


A, B, C = {"id": "a", "t": "pen", "x": 1}, {"id": "b", "t": "pen", "x": 2}, {"id": "c", "t": "pen", "x": 3}


def ids(objs):
    return [o["id"] for o in objs]


def test_both_add_keeps_both():
    assert ids(merge([A], [A, B], [A, C])) == ["a", "c", "b"]


def test_my_delete_sticks_when_they_did_not_touch_it():
    assert ids(merge([A, B], [A], [A, B, C])) == ["a", "c"]


def test_their_delete_sticks_when_i_did_not_touch_it():
    assert ids(merge([A, B], [A, B, C], [A])) == ["a", "c"]


def test_their_edit_wins_over_my_untouched_copy():
    moved = {**B, "x": 9}
    out = merge([A, B], [A, B, C], [A, moved])
    assert {o["id"]: o["x"] for o in out} == {"a": 1, "b": 9, "c": 3}


def test_my_edit_wins_over_theirs():
    mine, theirs = {**B, "x": 5}, {**B, "x": 9}
    out = merge([A, B], [A, mine], [A, theirs])
    assert {o["id"]: o["x"] for o in out} == {"a": 1, "b": 5}


def test_deleted_by_me_but_changed_by_them_comes_back():
    theirs = {**B, "x": 7}
    assert ids(merge([A, B], [A], [A, theirs])) == ["a", "b"]


def test_author_tag_alone_is_not_an_edit():
    tagged = {**B, "by": "teacher"}
    out = merge([A, B], [A, B, C], [A, tagged])
    assert ids(out) == ["a", "b", "c"]
