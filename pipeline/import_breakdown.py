"""Convert the tutor's chapter-breakdown workbook into taxonomy JSON files.

    python -m pipeline.import_breakdown --xlsx "OL JAN-MAR 2025.xlsx" --syllabus 4024 0580

Expected sheet layout (header row 1): chapter number | TOPIC NAME | SUB TOPIC
| STATUS | DATE | YOUTUBE LINK... Chapter rows carry TOPIC NAME; subtopic rows
leave it blank. Chapter and subtopic names are preserved verbatim (title-cased
for chapters) - they are the tutor's own labels and become filter values.

Keywords for the heuristic pre-pass are derived from the subtopic and chapter
names; the session backend remains the authoritative classifier. YouTube
revision links are preserved per subtopic for the future website.

Rows whose TOPIC NAME is 'Study Plan' (or any non-chapter row without a
number) are skipped.
"""

import argparse
import json
import re
from pathlib import Path

import openpyxl

from . import config, setup_logging

log = setup_logging("import_breakdown")

# Tutor's decisions (2026-07-16): trig is split into separately studyable
# topics, and 0580 Extended needs chapters the O Level breakdown lacks.
RENAMES = {"Trigonometry": "2D Trigonometry"}

_TRIG_3D = {
    "name": "3D Trigonometry",
    "keywords": ["angle between", "diagonal of the cuboid", "cuboid",
                 "pyramid", "and the base", "prism diagonal"],
    "subtopics": [{"name": "Cuboid And Cube Diagonals", "links": []},
                  {"name": "Pyramids", "links": []},
                  {"name": "Prisms", "links": []}],
}
# Syllabus 1.17 (4024) / E1.17 (0580), added when Loci and Matrices were
# removed. The tutor's xlsx predates the change, so it is supplied here.
_EXP_GROWTH = {
    "name": "Exponential Growth And Decay",
    "keywords": ["exponentially", "exponential growth", "exponential decay",
                 "decreases exponentially", "increases exponentially",
                 "per year compound", "number of complete years",
                 "population of a town", "half of its original"],
    "subtopics": [{"name": "Growth", "links": []},
                  {"name": "Decay", "links": []},
                  {"name": "Finding The Number Of Years", "links": []}],
}
# Syllabus 4.2 Geometrical constructions + 4.3 Scale drawings. These were NOT
# removed with Loci - only questions genuinely about a locus are out of scope.
_CONSTRUCTIONS = {
    "name": "Constructions And Scale Drawings",
    "keywords": ["ruler and compasses", "compasses only", "straight edge and compasses",
                 "construct triangle", "construction arcs", "scale drawing",
                 "using a ruler and compasses", "complete the scale drawing"],
    "subtopics": [{"name": "Constructing Triangles", "links": []},
                  {"name": "Bisectors", "links": []},
                  {"name": "Scale Drawings", "links": []}],
}
EXTRA_CHAPTERS = {
    "4024": [_TRIG_3D, _EXP_GROWTH, _CONSTRUCTIONS],
    "0580": [
        _TRIG_3D, _EXP_GROWTH, _CONSTRUCTIONS,
        {"name": "Trigonometric Graphs",
         "keywords": ["sketch the graph of y = sin", "sketch the graph of y = cos",
                      "solve the equation sin", "solve the equation cos",
                      "solve the equation tan", "reflex angle"],
         "subtopics": [{"name": "Sketching Sin Cos Tan", "links": []},
                       {"name": "Solving Trig Equations", "links": []}]},
        {"name": "Differentiation",
         "keywords": ["differentiate", "derivative", "dy/dx", "turning point",
                      "stationary point", "gradient of the curve",
                      "tangent to the curve", "maximum point", "minimum point"],
         "subtopics": [{"name": "Derivatives", "links": []},
                       {"name": "Turning Points Max Min", "links": []},
                       {"name": "Tangents And Gradients", "links": []}]},
    ],
}


def extract(xlsx_path: Path) -> list[dict]:
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.worksheets[0]
    chapters: list[dict] = []
    for row in ws.iter_rows(min_row=2):
        num = row[0].value
        topic = str(row[1].value).strip() if row[1].value else ""
        sub = str(row[2].value).strip() if row[2].value else ""
        links = " ".join(str(c.value) for c in row[5:] if c.value)
        links = re.findall(r"https?://\S+", links)
        if topic:
            if topic.lower() == "study plan" or (num is None and not sub):
                chapters.append(None)  # sentinel: ignore following subtopics
                continue
            chapters.append({"name": topic.title(), "keywords": set(),
                             "subtopics": []})
        if not chapters or chapters[-1] is None:
            continue
        if sub:
            chapters[-1]["subtopics"].append(
                {"name": sub.title(), "links": links})
            chapters[-1]["keywords"].add(sub.lower())
    result = []
    for ch in chapters:
        if ch is None:
            continue
        ch["keywords"].add(ch["name"].lower())
        # drop generic tracker words that would misfire as keywords
        ch["keywords"] -= {"practice", "questions", "arranging", "rules"}
        ch["keywords"] = sorted(ch["keywords"])
        result.append(ch)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--xlsx", required=True, type=Path)
    p.add_argument("--syllabus", nargs="+", required=True,
                   choices=sorted(config.SUBJECT_FOLDERS))
    args = p.parse_args()

    chapters = extract(args.xlsx if args.xlsx.is_absolute()
                       else config.ROOT / args.xlsx)
    for ch in chapters:
        ch["name"] = RENAMES.get(ch["name"], ch["name"])
    for syl in args.syllabus:
        chapters_syl = chapters + EXTRA_CHAPTERS.get(syl, [])
        n_subs = sum(len(c["subtopics"]) for c in chapters_syl)
        out = {
            "syllabus": syl,
            "subject": "Mathematics (O Level)" if syl == "4024"
                       else "Mathematics (IGCSE)",
            "note": f"Derived from the tutor's chapter breakdown "
                    f"({args.xlsx.name}); chapter/subtopic names are the "
                    "tutor's own labels, preserved verbatim. Subtopic links "
                    "are revision videos for the future website. Trig is "
                    "split into 2D/3D/graphs per the tutor (2026-07-16); "
                    "extra chapters beyond the xlsx come from EXTRA_CHAPTERS.",
            "topics": chapters_syl,
        }
        path = config.ROOT / "taxonomy" / f"{syl}.json"
        path.write_text(json.dumps(out, indent=1), encoding="utf-8")
        log.info("%s: %d chapters, %d subtopics -> %s",
                 syl, len(chapters_syl), n_subs, path)


if __name__ == "__main__":
    main()
