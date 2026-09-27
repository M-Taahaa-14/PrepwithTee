"""Cambridge renumbered papers when syllabuses changed: 0620/0625 Paper 2 was
written Core theory until 2015, 0625 Paper 3 Extended theory until 2015, and
9709 Paper 5 was Mechanics 2 until 2019 (Statistics 1 was Paper 6)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "website"))

from pipeline import config


def test_old_igcse_paper_2_is_not_multiple_choice():
    assert config.is_mcq("0625", 2, 2016) and config.is_mcq("0620", 2, 2024)
    assert not config.is_mcq("0625", 2, 2015) and not config.is_mcq("0620", 2, 2010)
    assert config.is_mcq("0625", 2)                 # no year: the current meaning
    assert config.is_mcq("0625", 1, 2010)           # Paper 1 was always MCQ


def test_components_in_scope_only_for_their_years():
    assert config.paper_in_scope("0625", 3, 2015) and not config.paper_in_scope("0625", 3, 2016)
    assert config.paper_in_scope("9709", 6, 2019) and not config.paper_in_scope("9709", 6, 2020)
    assert config.paper_in_scope("9709", 5, 2012)   # unlimited components pass


def test_labels_follow_the_year():
    import catalog
    assert catalog.component("9709", 5, 2014)["short"] == "Mechanics 2"
    assert catalog.component("9709", 5, 2021)["short"] == "Statistics"
    assert catalog.component("9709", 5)["short"] == "Statistics"
    assert catalog.component("0625", 2, 2012)["short"] == "Theory Core"
    assert catalog.component("0625", 2, 2018)["short"] == "MCQ Extended"
