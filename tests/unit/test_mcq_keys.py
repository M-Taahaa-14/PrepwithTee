"""pipeline.mcq: reading answer keys in both mark-scheme layouts."""

from pipeline import mcq

# 2010-2016: two columns, "Question Number | Key", no marks column.
OLD = ("Question \nNumber \nKey \n \nQuestion \nNumber \nKey \n1 \nD \n \n21 \nC \n2 \nA \n \n22 \nB \n"
       "10 \nA \n \n30 \nD \n11 \nA \n \n31 \nQuestion \nRemoved \n5054 \n11 \nPage 2")


def test_old_two_column_key_pairs_numbers_with_letters():
    got = mcq._key_pairs(OLD)
    assert got == {1: "D", 21: "C", 2: "A", 22: "B", 10: "A", 30: "D", 11: "A"}


def test_conflicting_letters_reject_the_page():
    assert mcq._key_pairs("1 A 2 B 1 C") is None


def test_page_furniture_is_not_a_key():
    # "5054 11" and "Page 2" never pair with a single A-D letter
    assert mcq._key_pairs("5054 11 Page 2 of 3 Mark Scheme") == {}


def test_new_layout_still_needs_the_mark():
    assert [m.groups() for m in mcq.ANSWER_ROW.finditer("12 B 1 13 C 1 9702/11")] == [("12", "B"), ("13", "C")]


def test_removed_questions_are_recognised():
    assert {int(m.group(1)) for m in mcq.REMOVED.finditer(OLD)} == {31}
    assert {int(m.group(1)) for m in mcq.REMOVED.finditer("25 \nQuestion discounted \n1")} == {25}
