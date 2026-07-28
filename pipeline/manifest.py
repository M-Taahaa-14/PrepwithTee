"""Download, cache and query the fastpapers /api/bucket file tree.

The bucket listing is the single source of truth for what exists on the
server; /api/pdf will happily sign paths that do not exist, so paths must
always come from this tree, never be constructed.
"""

import json
import logging
import re

import requests

from . import config

log = logging.getLogger(__name__)

# 5054_s25_qp_22.pdf -> (5054, s, 25, qp, 22). Other kinds (gt/er/ci/ir) don't match.
FILENAME_RE = re.compile(r"^(\d{4})_([smw])(\d{2})_(qp|ms)_(\d{1,2})\.pdf$", re.I)
# 9702_s23_er.pdf -> session-level examiner report (one per session, no paper/variant).
ER_RE = re.compile(r"^(\d{4})_([smw])(\d{2})_er\.pdf$", re.I)


def load(refresh: bool = False) -> list:
    if refresh or not config.MANIFEST_PATH.exists():
        log.info("downloading bucket manifest from %s", config.BUCKET_API)
        r = requests.get(
            config.BUCKET_API, timeout=120, headers={"User-Agent": config.USER_AGENT}
        )
        r.raise_for_status()
        config.MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        config.MANIFEST_PATH.write_text(r.text, encoding="utf-8")
        log.info("manifest cached to %s (%d bytes)", config.MANIFEST_PATH, len(r.text))
    return json.loads(config.MANIFEST_PATH.read_text(encoding="utf-8"))


def _find_child(nodes: list, name: str) -> dict | None:
    # Folder names in the bucket sometimes carry stray leading spaces.
    for n in nodes:
        if n["name"].strip() == name.strip():
            return n
    return None


def subject_node(tree: list, syllabus: str) -> dict:
    node = {"children": tree}
    for part in config.SUBJECT_FOLDERS[syllabus].split("/"):
        node = _find_child(node.get("children", []), part)
        if node is None:
            raise LookupError(f"folder {part!r} not found in manifest for {syllabus}")
    return node


def iter_papers(
    tree: list,
    syllabus: str,
    papers: tuple | None = None,
    year_from: int = config.YEAR_MIN,
    year_to: int = config.YEAR_MAX,
    sessions: tuple = config.SESSION_CODES,
    kinds: tuple = ("qp", "ms"),
):
    """Yield a metadata dict for every in-scope PDF under the subject folder."""
    papers = tuple(papers) if papers else config.PAPER_MATRIX[syllabus]
    subj = subject_node(tree, syllabus)
    pp = _find_child(subj.get("children", []), "past papers")
    if pp is None:
        raise LookupError(f"'past papers' folder missing for {syllabus}")
    for year_node in pp.get("children", []):
        name = year_node["name"].strip()
        if year_node.get("type") != "folder" or not name.isdigit():
            continue
        year = int(name)
        if not (year_from <= year <= year_to):
            continue
        for sess_node in sorted(year_node.get("children", []), key=lambda n: n["name"]):
            session = config.folder_to_session(sess_node["name"])
            if session is None or session not in sessions:
                continue
            for f in sorted(sess_node.get("children", []), key=lambda n: n["name"]):
                if f.get("type") != "file":
                    continue
                m = FILENAME_RE.match(f["name"].strip())
                if not m:
                    continue
                syl, _s, _yy, kind, code = m.groups()
                kind = kind.lower()
                if syl != syllabus or kind not in kinds or int(code[0]) not in papers:
                    continue
                yield {
                    "syllabus": syllabus,
                    "year": year,
                    "session": session,
                    "paper": int(code[0]),
                    "variant": code[1:],
                    "code": code,
                    "kind": kind,
                    "filename": f["name"].strip(),
                    "bucket_path": f["path"],
                }


def iter_syllabus_docs(tree: list, syllabus: str):
    subj = subject_node(tree, syllabus)
    syl = _find_child(subj.get("children", []), "Syllabus")
    if syl is None:
        return
    for f in syl.get("children", []):
        if f.get("type") == "file":
            yield {"filename": f["name"].strip(), "bucket_path": f["path"]}


def iter_er_files(
    tree: list,
    syllabus: str,
    year_from: int = config.YEAR_MIN,
    year_to: int = config.YEAR_MAX,
    sessions: tuple = config.SESSION_CODES,
):
    """Yield metadata for examiner report PDFs (one per session, no variant)."""
    subj = subject_node(tree, syllabus)
    pp = _find_child(subj.get("children", []), "past papers")
    if pp is None:
        return
    for year_node in pp.get("children", []):
        name = year_node["name"].strip()
        if year_node.get("type") != "folder" or not name.isdigit():
            continue
        year = int(name)
        if not (year_from <= year <= year_to):
            continue
        for sess_node in year_node.get("children", []):
            session = config.folder_to_session(sess_node["name"])
            if session is None or session not in sessions:
                continue
            for f in sess_node.get("children", []):
                if f.get("type") != "file":
                    continue
                m = ER_RE.match(f["name"].strip())
                if not m:
                    continue
                syl, _s, _yy = m.group(1), m.group(2), m.group(3)
                if syl != syllabus:
                    continue
                yield {
                    "syllabus": syllabus,
                    "year": year,
                    "session": session,
                    "filename": f["name"].strip(),
                    "bucket_path": f["path"],
                }
