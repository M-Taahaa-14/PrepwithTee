"""One-off (2026-09-26, P2-d): move revision notes onto the syllabus taxonomy.

Before: website/static/notes-content/manifest.json described each subject's own
chapter list, and notes lived at notes-content/{syllabus}/{manifest-chapter}/{slug}.html.
After:  notes live under the TAXONOMY chapter they belong to (the same chapters
as the topical builder and /papers pages):

    notes-content/{syllabus}/{taxonomy-chapter-slug}/{note-slug}.html
    notes-content/{syllabus}/{taxonomy-chapter-slug}/_chapter.json   (learning outcomes...)
    notes-content/{syllabus}/_subject.json                          (description, study guide)
    notes-content/_redirects.json                                   (old slugs -> new, for 301s)

Each note starts with a metadata comment that website/notes.py reads:

    <!--note {"title": "Hooke's Law and springs", "order": 3, "subtopic": "Hooke's Law and spring constant"} -->

Run once:  .venv\\Scripts\\python scripts\\migrate_notes_to_taxonomy.py [--apply]
(dry run by default).
"""

import argparse
import difflib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTES = ROOT / "website" / "static" / "notes-content"
sys.path.insert(0, str(ROOT / "website"))


def slugify(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")


# Manifest chapters whose names are not taxonomy names. note slug -> taxonomy chapter
# where one manifest chapter's notes belong to different syllabus chapters.
CHAPTER_MAP = {
    ("4024", "graphs-of-functions"): "Graphs Of Functions",
    ("2058", "battles-of-islam"): "The Life of the Prophet Muhammad (pbuh)",
}
NOTE_MAP = {
    ("2058", "quranic-references", "important-verses"): "The Qur'an — Themes and Teachings",
    ("2058", "quranic-references", "key-hadith"): "Teachings of the Hadiths",
}
SUBTOPIC_MAP = {
    ("2058", "battle-of-badr"): "Battles and military campaigns",
    ("2058", "battle-of-uhud"): "Battles and military campaigns",
    ("2058", "battle-of-khandaq"): "Battles and military campaigns",
    ("2058", "conquest-of-makkah"): "Battles and military campaigns",
    ("2058", "key-hadith"): "Hadith on individual conduct, character and worship",
    ("2058", "important-verses"): "Qur'anic themes on worship, guidance and Muslim life",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    manifest = json.loads((NOTES / "manifest.json").read_text(encoding="utf-8"))
    redirects: dict[str, dict] = {}
    moves = []
    for code, subj in manifest.items():
        tax = json.loads((ROOT / "taxonomy" / f"{code}.json").read_text(encoding="utf-8"))
        topics = {t["name"]: t for t in tax["topics"]}
        by_slug = {slugify(n): n for n in topics}
        red = redirects.setdefault(code, {"chapters": {}, "notes": {}})
        meta_subject = {k: subj[k] for k in ("description", "study_guide", "papers", "color", "emoji")
                        if k in subj}
        moves.append(("subject-meta", code, meta_subject))
        for ch in subj["chapters"]:
            default = (CHAPTER_MAP.get((code, ch["slug"])) or by_slug.get(ch["slug"])
                       or by_slug.get(slugify(ch["name"])))
            chapter_meta = {k: ch[k] for k in ("syllabus_ref", "section", "weighting", "tier_split",
                                               "learning_outcomes") if ch.get(k)}
            if default:
                red["chapters"][ch["slug"]] = slugify(default)
                moves.append(("chapter-meta", code, slugify(default), chapter_meta))
            for order, st in enumerate(ch["subtopics"], 1):
                src = NOTES / code / ch["slug"] / f"{st['slug']}.html"
                if not src.exists():
                    continue
                target = NOTE_MAP.get((code, ch["slug"], st["slug"])) or default
                if not target:
                    print(f"!! no taxonomy chapter for {code}/{ch['slug']}/{st['slug']}")
                    continue
                subs = [s["name"] for s in topics[target].get("subtopics", [])]
                sub = SUBTOPIC_MAP.get((code, st["slug"]))
                if not sub and subs:
                    best = difflib.get_close_matches(st["name"], subs, n=1, cutoff=0.45)
                    sub = best[0] if best else None
                meta = {"title": st["name"], "order": order}
                if sub:
                    meta["subtopic"] = sub
                if st.get("tier"):
                    meta["tier"] = st["tier"]
                dest = NOTES / code / slugify(target) / f"{st['slug']}.html"
                red["notes"][f"{ch['slug']}/{st['slug']}"] = f"{slugify(target)}/{st['slug']}"
                moves.append(("note", src, dest, meta))
                print(f"{code}: {ch['slug']}/{st['slug']} -> {slugify(target)}/{st['slug']}"
                      f"  [{sub or '-'}]")
    if not args.apply:
        print("\n(dry run - pass --apply to move the files)")
        return
    for m in moves:
        if m[0] == "subject-meta":
            _, code, meta = m
            (NOTES / code).mkdir(parents=True, exist_ok=True)
            (NOTES / code / "_subject.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), "utf-8")
        elif m[0] == "chapter-meta":
            _, code, slug, meta = m
            if meta:
                (NOTES / code / slug).mkdir(parents=True, exist_ok=True)
                (NOTES / code / slug / "_chapter.json").write_text(
                    json.dumps(meta, indent=2, ensure_ascii=False), "utf-8")
        else:
            _, src, dest, meta = m
            body = src.read_text(encoding="utf-8")
            body = re.sub(r"^\s*<!--note .*?-->\s*", "", body, flags=re.S)
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".tmp")
            tmp.write_text(f"<!--note {json.dumps(meta, ensure_ascii=False)} -->\n{body}", "utf-8")
            if src != dest:
                src.unlink()
            tmp.replace(dest)
    # empty old chapter folders
    for d in sorted(NOTES.glob("*/*"), reverse=True):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    (NOTES / "_redirects.json").write_text(json.dumps(redirects, indent=2), "utf-8")
    shutil.move(str(NOTES / "manifest.json"), str(NOTES.parent.parent.parent / "data" / "notes-manifest.old.json"))
    print("done; manifest.json archived to data/notes-manifest.old.json")


if __name__ == "__main__":
    main()
