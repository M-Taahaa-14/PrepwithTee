"""Keyword scorer for the heuristic classification backend.

Scores a question's full text (all sub-parts) against per-topic keyword lists
from taxonomy/{syllabus}.json. Longer phrases score higher than short ones.
Confidence is derived from the winner's margin over the runner-up and is
deliberately conservative: ambiguous questions should land in the review
queue, not be silently mislabelled.

Two rules keep the long tail from leaking (both learned the hard way on 9709,
2026-07-21):

* **Keywords match on word boundaries, never as bare substrings.** A raw
  `str.count` made "AB" match prob*ab*ility, "OA" match c*oa*ch, "sec" match
  *sec*onds and "power" match *power*s of x, which put Vectors and Mechanics
  topics on Probability & Statistics papers.
* **A topic is only scored for the paper components it is examined in**, via
  the taxonomy's optional per-topic `papers` array. Without it Pure 3
  integration questions were won by "Integration (P1)" and Pure 1 trigonometry
  by "Trigonometry (P3)". A topic with no `papers` key is scored everywhere,
  so single-component syllabi are unaffected.
"""

import json
import re
from functools import lru_cache

from . import config


def load_taxonomy(syllabus: str) -> dict:
    path = config.TAXONOMY_DIR / f"{syllabus}.json"
    tax = json.loads(path.read_text(encoding="utf-8"))
    if "alias_of" in tax:  # e.g. 0625 shares 5054's topic list
        base = load_taxonomy(tax["alias_of"])
        tax = {**base, "syllabus": syllabus, "subject": tax.get("subject", base["subject"])}
    return tax


def _normalize(s: str) -> str:
    """Strip apostrophes, quotes, hyphens and dashes so matching is accent/punct-insensitive."""
    return re.sub("[‘’‘’“”—–‒`’-]", "", s)


@lru_cache(maxsize=4096)
def _kw_pattern(keyword: str) -> re.Pattern:
    """Compile a keyword so it only matches whole words.

    \\b is only asserted at ends that are actually word characters, so keywords
    that start or end with punctuation or a symbol ("f(x)", "|ax + b|", the
    integral sign) still match. Runs of whitespace in the keyword match any
    whitespace, since Cambridge PDFs break stacked notation across lines
    (dy/dx extracts as "dy\\ndx").

    An optional trailing 's' is allowed so "hadith" matches "hadiths",
    "caliph" matches "caliphs", "pillar" matches "pillars", etc.
    """
    k = _normalize(keyword.lower().strip())
    body = r"\s+".join(re.escape(part) for part in k.split())
    left = r"\b" if k[:1].isalnum() else ""
    right = r"s?\b" if k[-1:].isalnum() else ""
    return re.compile(left + body + right)


def _keyword_weight(keyword: str) -> float:
    """Longer phrases are far stronger evidence than single generic words."""
    words = len(keyword.split())
    return 1.0 if words == 1 else 2.0 if words == 2 else 3.0


def score_subtopics(text: str, topic_entry: dict) -> list[tuple[str, float]]:
    """Score subtopics within a single topic entry.

    Returns [(subtopic_name, score), ...] sorted best-first.
    If the topic has no subtopics key, returns an empty list.
    """
    subtopics = topic_entry.get("subtopics", [])
    if not subtopics:
        return []
    t = " " + re.sub(r"\s+", " ", _normalize(text.lower())) + " "
    scores = []
    for sub in subtopics:
        s = 0.0
        for kw in sub.get("keywords", []):
            hits = len(_kw_pattern(kw).findall(t))
            if hits:
                s += _keyword_weight(kw) * min(hits, 4)
        scores.append((sub["name"], s))
    scores.sort(key=lambda x: -x[1])
    return scores


def classify_subtopic(text: str, taxonomy: dict, topic_name: str) -> str | None:
    """Return the best-matching subtopic name within a topic, or None if no signal."""
    topic_entry = next((t for t in taxonomy.get("topics", [])
                        if t["name"] == topic_name), None)
    if topic_entry is None:
        return None
    ranked = score_subtopics(text, topic_entry)
    if not ranked:
        return None
    best_name, best_score = ranked[0]
    return best_name if best_score > 0 else None


def score_topics(text: str, taxonomy: dict,
                 paper: int | None = None) -> list[tuple[str, float]]:
    """Return [(topic, score), ...] sorted best-first.

    When `paper` is given, topics whose `papers` array excludes it are skipped.
    """
    t = " " + re.sub(r"\s+", " ", _normalize(text.lower())) + " "
    scores = []
    for topic in taxonomy["topics"]:
        allowed = topic.get("papers")
        if paper is not None and allowed is not None and paper not in allowed:
            continue
        s = 0.0
        for kw in topic["keywords"]:
            hits = len(_kw_pattern(kw).findall(t))
            if hits:
                # cap so one repeated word can't dominate
                s += _keyword_weight(kw) * min(hits, 4)
        scores.append((topic["name"], s))
    scores.sort(key=lambda x: -x[1])
    return scores


def classify_text(text: str, taxonomy: dict,
                  paper: int | None = None) -> dict | None:
    """Return a classification record, or None when there is no signal at all."""
    ranked = score_topics(text, taxonomy, paper=paper)
    if not ranked:
        return None
    best_topic, best = ranked[0]
    if best <= 0:
        return None
    second_topic, second = ranked[1] if len(ranked) > 1 else (None, 0.0)

    secondary = second_topic if second >= 0.5 * best and second > 0 else None
    # margin-based confidence, conservative by design (max 0.85)
    margin = (best - second) / best
    confidence = round(min(0.45 + 0.4 * margin, 0.85), 2)
    rationale = f"keywords: {best_topic} scored {best:.0f}" + (
        f", runner-up {second_topic} {second:.0f}" if second > 0 else ", no runner-up"
    )
    return {
        "topic": best_topic,
        "secondary_topic": secondary,
        "difficulty": None,   # heuristics cannot judge difficulty
        "confidence": confidence,
        "rationale": rationale,
    }
