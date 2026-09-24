"""The mark-scheme sync must insert missing rows, update changed ones, and
refuse anything that could clobber an unrelated row."""

import pytest

from scripts.sync_ms_to_supabase import plan

PAPER = ("5054", 2016, "s", 2, "1", "ms")


class FakeCursor:
    def __init__(self, papers, ms_rows):
        self._papers, self._ms, self._last = papers, ms_rows, None

    def execute(self, sql, *a):
        self._last = self._papers if "FROM papers" in sql else self._ms

    def fetchall(self):
        return self._last


def row(id, q, sub="", crop="data\\crops\\x\\q.pdf", ans=None, year=2016, paper_id=1):
    return {"id": id, "paper_id": paper_id, "question_number": q, "sub_part": sub,
            "crop_path": crop, "rects_json": "[]", "answer": ans,
            "year": year, "syllabus": "5054"}


def test_inserts_missing_and_normalises_path():
    cur = FakeCursor([(1, *PAPER)], [])
    rows, report = plan({1: PAPER}, [row(10, 1)], cur)
    assert rows == [(10, 1, 1, "", "data/crops/x/q.pdf", "[]", None)]
    assert report[("2010-19", "insert")] == 1


def test_unchanged_row_is_skipped():
    cur = FakeCursor([(1, *PAPER)], [(10, 1, 1, "", "data\\crops\\x\\q.pdf", "[]", None)])
    rows, report = plan({1: PAPER}, [row(10, 1)], cur)
    assert rows == [] and report[("2010-19", "unchanged")] == 1


def test_update_keeps_supabase_id():
    cur = FakeCursor([(1, *PAPER)], [(999, 1, 1, "", None, "[]", None)])
    rows, _ = plan({1: PAPER}, [row(10, 1, ans="B")], cur)
    assert rows[0][0] == 999 and rows[0][-1] == "B"


def test_id_clash_aborts():
    # Supabase already uses id 10 for question 7; local wants id 10 for question 1.
    cur = FakeCursor([(1, *PAPER)], [(10, 1, 7, "", None, "[]", None)])
    with pytest.raises(SystemExit, match="id clashes"):
        plan({1: PAPER}, [row(10, 1)], cur)


def test_paper_id_mismatch_aborts():
    cur = FakeCursor([(1, "5054", 2017, "s", 2, "1", "ms")], [])
    with pytest.raises(SystemExit, match="paper ids differ"):
        plan({1: PAPER}, [row(10, 1)], cur)
