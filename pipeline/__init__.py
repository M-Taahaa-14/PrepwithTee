"""Topical past-paper engine pipeline.

Stages (each runnable as `python -m pipeline.<stage>`):
    fetch    - download QP/MS PDFs from papers.fastpapers.uk
    segment  - split QPs into per-question vector crops (PyMuPDF)
    classify - tag questions with syllabus topics (pluggable backends)
    link_ms  - segment mark schemes and join to questions
    compose  - build topical question + mark-scheme PDFs
    validate - compare classifications against the manual Excel tracker
"""

import logging


def setup_logging(name: str) -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger(name)
