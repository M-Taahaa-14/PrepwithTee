"""Importer for structured study-recall content.

Reads every *.md and *.txt file in  data/flashcards markdowns/  and upserts
CARD / DEF / FORMULA / LIST / TIMELINE blocks into the fc_* tables in the
site database (data/index.db).

Run:
    python -m pipeline.import_flashcards               # all files
    python -m pipeline.import_flashcards 9702_*.md    # specific files

Fully idempotent: re-running after editing a source file updates existing
blocks and adds new ones without duplicating rows (keyed on source_hash).

Supported block types:

    CARD
    Topic: chapter name
    Q: question text  (supports $LaTeX$ inline, $$LaTeX$$ display)
    A: answer text
    END

    DEF
    Term: term
    Meaning: definition text   (stored as 'definition' in payload)
    Unit: optional unit
    Context: chapter/topic  (used when Topic: is absent)
    END

    FORMULA
    Topic: chapter name
    Name: label                (stored as 'label' in payload)
    Equation: $v = u + at$    (stored as 'formula' in payload)
    Variables: description     (stored as 'where' in payload)
    Notes: IS/NOT in formula booklet ...
    END

    LIST
    Topic: chapter name
    Title: list title
    Type: ordered | unordered
    - item text
    END

    TIMELINE
    Subject: optional
    Topic: chapter name
    EVENT | YEAR | DETAIL
    event name | YYYY CE | detail text
    ...
    END
    (Converted to LIST with items "event name (YYYY) — detail" )

Header formats supported (no explicit SUBJECT HEADER: marker needed):
    Subject: X
    Board: X
    Code: XXXX | Papers: P1 (label), P2 (label)
    O-Level: Code XXXX | Papers: ...
    IGCSE: Code XXXX | Papers: ...
    O-Level Code: XXXX | Papers: ...
    Level: A-Level / O-Level / IGCSE
    Syllabus Code: XXXX
    Paper: Paper 1 — Name (for single-paper syllabi like 2059)
    # Cambridge International A-Level Mathematics 9709   (heading detection)
    Box-drawing: ISLAMIYAT — O-LEVEL (2058) & IGCSE (0493)
"""

import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FC_DIR = DATA / "flashcards markdowns"
DB_PATH = DATA / "index.db"

# ── SQLite DDL (creates tables if absent; safe to re-run) ──────────────────

_DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS fc_boards (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    code TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS fc_subjects (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    board_id       INTEGER NOT NULL REFERENCES fc_boards(id) ON DELETE CASCADE,
    name           TEXT NOT NULL,
    code           TEXT NOT NULL UNIQUE,
    level          TEXT,
    alt_codes_json TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS fc_papers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL REFERENCES fc_subjects(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    code       TEXT NOT NULL,
    UNIQUE(subject_id, code)
);

CREATE TABLE IF NOT EXISTS fc_chapters (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id    INTEGER NOT NULL REFERENCES fc_papers(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    order_index INTEGER NOT NULL DEFAULT 0,
    UNIQUE(paper_id, name)
);

CREATE TABLE IF NOT EXISTS fc_blocks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id   INTEGER NOT NULL REFERENCES fc_chapters(id) ON DELETE CASCADE,
    type         TEXT    NOT NULL,
    topic_label  TEXT,
    payload_json TEXT    NOT NULL DEFAULT '{}',
    source_hash  TEXT,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS fc_blocks_uq
    ON fc_blocks (chapter_id, type, source_hash)
    WHERE source_hash IS NOT NULL;

CREATE TABLE IF NOT EXISTS fc_card_progress (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id       TEXT    NOT NULL,
    block_id         INTEGER NOT NULL REFERENCES fc_blocks(id) ON DELETE CASCADE,
    status           TEXT    NOT NULL DEFAULT 'new',
    times_reviewed   INTEGER NOT NULL DEFAULT 0,
    times_correct    INTEGER NOT NULL DEFAULT 0,
    ease_factor      REAL    NOT NULL DEFAULT 2.5,
    interval_days    REAL    NOT NULL DEFAULT 0.0,
    next_review_at   TEXT,
    saved_for_review INTEGER NOT NULL DEFAULT 0,
    last_result      TEXT,
    updated_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(student_id, block_id)
);

CREATE TABLE IF NOT EXISTS fc_review_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  TEXT    NOT NULL,
    block_id    INTEGER NOT NULL REFERENCES fc_blocks(id) ON DELETE CASCADE,
    rating      TEXT    NOT NULL,
    reviewed_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS fc_study_sessions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id     TEXT    NOT NULL,
    scope_json     TEXT,
    started_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    ended_at       TEXT,
    cards_reviewed INTEGER NOT NULL DEFAULT 0,
    cards_aced     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS fc_streaks (
    student_id       TEXT    PRIMARY KEY,
    current_streak   INTEGER NOT NULL DEFAULT 0,
    longest_streak   INTEGER NOT NULL DEFAULT 0,
    last_active_date TEXT
);
"""

# ── Parsing helpers ────────────────────────────────────────────────────────

_PAPER_PREFIX_RE = re.compile(
    r"^(P\d+|M\d+|S\d+)\s*[—–\-·]\s*(.+)$", re.IGNORECASE
)

_IN_BOOKLET_RE = re.compile(
    r"\b(IS|NOT|is|not)\s+in\s+(?:the\s+)?(?:cambridge\s+)?formula\s+booklet",
    re.IGNORECASE,
)

# Heading patterns that mark a chapter boundary in files (used to strip them).
# They are NOT the source of chapter names — those come from Topic:/Context: fields.
_CHAPTER_HEADING_RE = re.compile(
    r"^[═=━\-#*]{3,}.*(?:CHAPTER|TOPIC|UNIT)\b.*$",
    re.IGNORECASE | re.MULTILINE,
)


def _block_hash(type_: str, payload: dict) -> str:
    key = json.dumps({"t": type_, "p": payload}, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(key.encode()).hexdigest()[:16]


def _in_formula_booklet(notes: str) -> bool | None:
    m = _IN_BOOKLET_RE.search(notes or "")
    if not m:
        return None
    return m.group(1).upper() == "IS"


# ── Header parsing ─────────────────────────────────────────────────────────

def _parse_header(text: str) -> dict:
    """
    Extract syllabus metadata from the preamble of a file.
    Works without any explicit SUBJECT HEADER: marker.
    """
    result = {
        "subject": "",
        "board": "",
        "level": "",
        "primary_code": "",
        "alt_codes": [],
        "papers": [],
    }
    pending_single_code = None

    # Special: detect 9709 from heading line
    m9709 = re.search(r"(?:Cambridge\s+)?(?:International\s+)?A-Level\s+Mathematics\s+9709",
                      text, re.IGNORECASE)
    if m9709:
        result["subject"] = "Mathematics"
        result["level"] = "A-Level"
        result["primary_code"] = "9709"
        # Paper code from "## Paper: M1 ..." or "Paper: P1 ..."
        pm = re.search(r"Paper:\s*(P\d+|M\d+|S\d+)\b", text, re.IGNORECASE)
        if pm:
            pcode = pm.group(1).upper()
            pname_m = re.search(
                r"Paper:\s*(?:P\d+|M\d+|S\d+)[^()\n]*\(([^)]+)\)", text, re.IGNORECASE
            )
            pname = pname_m.group(1) if pname_m else pcode
            result["papers"] = [{"code": pcode, "name": pname}]
        return result

    # Special: box-drawing / decorative headers (Islamiat Notes.txt)
    box_m = re.search(
        r"ISLAMIYAT.*?O-LEVEL.*?\((\d{4})\).*?(?:IGCSE.*?\((\d{4})\))?",
        text, re.IGNORECASE | re.DOTALL
    )
    if box_m:
        result["subject"] = "Islamiyat"
        result["level"] = "O-Level / IGCSE"
        result["primary_code"] = box_m.group(1)
        if box_m.group(2):
            result["alt_codes"] = [box_m.group(2)]
        result["papers"] = [{"code": "P1", "name": "Paper 1"}, {"code": "P2", "name": "Paper 2"}]
        return result

    # Bare bold code header: **O-Level 4024 | IGCSE 0580 | ...** (no colon)
    bare_m = re.search(
        r"\*\*O-Level\s+(\d{4,5})\s*\|\s*IGCSE\s+(\d{4,5})",
        text[:800], re.IGNORECASE,
    )
    if bare_m:
        result["primary_code"] = bare_m.group(1)
        result["alt_codes"] = [bare_m.group(2)]
        result["level"] = "O-Level / IGCSE"
        result["papers"] = [
            {"code": "P1", "name": "Paper 1 (Non-calculator)"},
            {"code": "P2", "name": "Paper 2 (Calculator)"},
        ]
        # subject from line above the bold header
        subj_m = re.search(r"(?:^|\n)#[^\n]+Maths", text[:400], re.I)
        result["subject"] = "Mathematics" if subj_m else "Mathematics"
        return result

    # Standard key:value lines (first ~30 lines of preamble)
    preamble_lines = text.split("\n")[:40]
    for raw in preamble_lines:
        # Strip markdown bold, borders, special chars
        line = re.sub(r"\*\*|__", "", raw).strip().lstrip("-#>│║╔╚╝╗═━ ").strip()
        if not line:
            continue

        key, _, val = line.partition(":")
        key = key.strip().rstrip("*_ ")
        val = val.strip()

        k = key.lower()

        if k == "subject":
            result["subject"] = val.split("|")[0].strip().split("—")[0].strip()
        elif k == "board":
            result["board"] = val
        elif k == "level":
            result["level"] = val

        elif any(x in k for x in ("o-level", "igcse", "o level")):
            # "O-Level: Code 5054 | Papers: P1 (MCQ), P2 (Structured Theory)"
            # "O-Level: Code 2210 | Papers: P1, P2"
            # "O-Level 4024 | IGCSE 0580" → may appear as bold header line
            codes_found = re.findall(r"\b(\d{4,5})\b", val)
            papers_part = ""
            pipe_parts = val.split("|")
            code_str = pipe_parts[0]
            if len(pipe_parts) > 1:
                papers_m = re.search(r"Papers?\s*:\s*(.+)", pipe_parts[1], re.I)
                if papers_m:
                    papers_part = papers_m.group(1)

            for code in codes_found:
                if not result["primary_code"]:
                    result["primary_code"] = code
                elif code not in result["alt_codes"]:
                    result["alt_codes"].append(code)

            if papers_part:
                result["papers"].extend(_parse_papers_str(papers_part))

        elif "code" in k and val:
            # "Code: 9702 | Papers: ..." or "O-Level Code: 2210 | Papers: ..."
            # "Syllabus Code: 2059"
            pipe_parts = val.split("|")
            code_part = pipe_parts[0].strip()
            code_m = re.search(r"\b(\d{4,5})\b", code_part)
            if not code_m:
                continue
            code = code_m.group(1)

            if not result["primary_code"]:
                result["primary_code"] = code
            elif code not in result["alt_codes"]:
                result["alt_codes"].append(code)

            if len(pipe_parts) > 1:
                papers_m = re.search(r"Papers?\s*:\s*(.+)", pipe_parts[1], re.I)
                if papers_m:
                    result["papers"].extend(_parse_papers_str(papers_m.group(1)))
            else:
                pending_single_code = code

        elif k == "paper" and pending_single_code:
            p = _paper_from_phrase(val)
            if p:
                result["papers"].append(p)
            pending_single_code = None

    # Deduplicate papers
    seen, unique = set(), []
    for p in result["papers"]:
        if p["code"] not in seen:
            unique.append(p)
            seen.add(p["code"])
    result["papers"] = unique

    if not result["papers"]:
        result["papers"] = [{"code": "ALL", "name": "General"}]

    return result


def _parse_papers_str(s: str) -> list[dict]:
    """Parse "P1 (MCQ), P2 (AS Structured)" → list of dicts."""
    papers = []
    for tok in re.split(r",\s*(?![^(]*\))", s):
        tok = tok.strip()
        if tok:
            p = _paper_from_phrase(tok)
            if p:
                papers.append(p)
    return papers


def _paper_from_phrase(phrase: str) -> dict:
    m = re.match(
        r"^(P\d+|Paper\s*\d+|M\d+|S\d+)(?:/P\d+)*"
        r"(?:\s*[—–·\-]\s*|\s+)"
        r"(?:\(([^)]+)\)|(.+))?",
        phrase.strip(),
        re.IGNORECASE,
    )
    if not m:
        return {}
    raw_code = m.group(1).strip()
    code = re.sub(r"(?i)paper\s*", "P", raw_code)
    name = (m.group(2) or m.group(3) or "").strip() or code
    return {"code": code, "name": name}


_LEVEL_TO_BOARD = {
    "a-level": ("Cambridge A-Level", "cambridge-al"),
    "as level": ("Cambridge A-Level", "cambridge-al"),
    "a level": ("Cambridge A-Level", "cambridge-al"),
    "o-level": ("Cambridge O-Level / IGCSE", "cambridge-ol"),
    "igcse": ("Cambridge O-Level / IGCSE", "cambridge-ol"),
    "o level": ("Cambridge O-Level / IGCSE", "cambridge-ol"),
}


def _board_for_level(level: str, board_str: str) -> tuple[str, str]:
    combined = (level + " " + board_str).lower()
    for key, pair in _LEVEL_TO_BOARD.items():
        if key in combined:
            return pair
    return ("Cambridge O-Level / IGCSE", "cambridge-ol")


# ── Block parsers ──────────────────────────────────────────────────────────

def _parse_timeline_block(lines: list[str]) -> dict | None:
    """Convert a TIMELINE block into a LIST block."""
    kv: dict[str, list[str]] = {}
    rows = []

    past_header_row = False
    for line in lines:
        m = re.match(r"^([A-Za-z][A-Za-z _()]*?)\s*:\s*(.*)", line)
        if m:
            k = m.group(1).strip().upper()
            v = m.group(2).strip()
            kv.setdefault(k, []).append(v)
            continue
        # Pipe-separated row: "EVENT | YEAR | DETAIL"
        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 2:
                # Skip header row (first pipe row that looks like a column header)
                if not past_header_row and parts[0].upper() in ("EVENT", ""):
                    past_header_row = True
                    continue
                past_header_row = True
                event = parts[0]
                year = parts[1] if len(parts) > 1 else ""
                detail = parts[2] if len(parts) > 2 else ""
                if event and year:
                    item = f"{event} ({year})"
                    if detail:
                        item += f" — {detail}"
                    rows.append(item)

    def _get(k):
        return " ".join(kv.get(k, [])).strip()

    topic = _get("TOPIC") or _get("SUBJECT") or "Timeline"
    title = _get("TITLE") or topic

    if not rows:
        return None

    return {
        "type": "list",
        "topic": topic,
        "payload": {
            "title": title,
            "list_type": "ordered",
            "items": rows,
        },
    }


def _parse_block_text(raw: str) -> dict | None:
    """
    Parse one raw block (type marker line + fields, without the END line).
    Returns None if unrecognised or malformed.
    """
    lines = [l.rstrip() for l in raw.strip().split("\n")]
    if not lines:
        return None

    marker = lines[0].strip().upper()
    if marker not in ("CARD", "DEF", "FORMULA", "LIST", "TIMELINE"):
        return None

    body_lines = lines[1:]

    if marker == "TIMELINE":
        return _parse_timeline_block(body_lines)

    kv: dict[str, list[str]] = {}
    list_items: list[str] = []
    current_key: str | None = None

    for line in body_lines:
        # List item
        if line.startswith("- "):
            list_items.append(line[2:].strip())
            current_key = None
            continue
        # Key: value  (key can be a single letter, e.g. "Q:" or "A:")
        m = re.match(r"^([A-Za-z][A-Za-z _()]*?)\s*:\s*(.*)", line)
        if m:
            current_key = m.group(1).strip().upper()
            val = m.group(2).strip()
            if current_key == "TYPE" and val.lower() in ("ordered", "unordered"):
                kv[current_key] = [val]
                current_key = "_LIST_ITEMS"
            else:
                kv.setdefault(current_key, []).append(val)
        elif current_key and (line.startswith("  ") or line.startswith("\t")):
            # Continuation (indented)
            if kv.get(current_key):
                kv[current_key][-1] += " " + line.strip()
        elif current_key == "_LIST_ITEMS" and line:
            list_items.append(line.strip().lstrip("- "))

    def _get(key: str) -> str:
        return " ".join(kv.get(key, [])).strip()

    topic = _get("TOPIC") or _get("CONTEXT")

    if marker == "CARD":
        q = _get("Q") or _get("QUESTION")
        a = _get("A") or _get("ANSWER")
        if not q:
            return None
        return {"type": "card", "topic": topic,
                "payload": {"question": q, "answer": a}}

    if marker == "DEF":
        term = _get("TERM")
        # Store as 'definition' (frontend reads p.definition)
        definition = _get("MEANING") or _get("DEFINITION")
        if not term:
            return None
        payload: dict = {"term": term, "definition": definition}
        unit = _get("UNIT")
        if unit:
            payload["unit"] = unit
        ctx = _get("CONTEXT")
        if ctx:
            payload["context"] = ctx
        return {"type": "def", "topic": topic, "payload": payload}

    if marker == "FORMULA":
        # Store as 'label'/'formula'/'where' (frontend reads these keys)
        label = _get("NAME") or _get("LABEL")
        formula_expr = _get("EQUATION") or _get("FORMULA")
        if not label:
            return None
        notes = _get("NOTES")
        payload = {
            "label": label,
            "formula": formula_expr,
            "where": _get("VARIABLES") or _get("WHERE"),
            "notes": notes,
            "in_formula_booklet": _in_formula_booklet(notes),
        }
        return {"type": "formula", "topic": topic, "payload": payload}

    if marker == "LIST":
        title = _get("TITLE")
        list_type = _get("TYPE") or "unordered"
        if not list_items:
            return None
        return {
            "type": "list",
            "topic": topic,
            "payload": {
                "title": title or topic,
                "list_type": list_type.lower(),
                "items": list_items,
            },
        }

    return None


# ── File-level parser ──────────────────────────────────────────────────────

def _strip_code_fences(text: str) -> str:
    """Remove ``` ... ``` fences while keeping block content inside."""
    return re.sub(r"```[a-z]*\n?", "", text)


def _parse_file(path: Path) -> tuple[dict, list[dict]]:
    """Return (header_dict, [blocks]) for a content file."""
    raw_text = path.read_text(encoding="utf-8")

    # Strip markdown code fences (Maths OL file wraps blocks in them)
    text = _strip_code_fences(raw_text)

    header = _parse_header(text)

    # Code fallback from filename
    if not header.get("primary_code"):
        m = re.search(r"\b(\d{4,5})\b", path.stem)
        if m:
            header["primary_code"] = m.group(1)

    # Split into blocks on lines that are exactly a block marker
    blocks = []
    block_types = "CARD|DEF|FORMULA|LIST|TIMELINE"
    # Split at lines that are purely a block marker (whole line = marker word)
    segments = re.split(
        r"\n(?=(?:" + block_types + r")\s*\n)",
        text,
        flags=re.IGNORECASE,
    )

    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        # Find END marker (case-insensitive, whole line)
        end_m = re.search(r"\nEND\s*$", seg, re.MULTILINE | re.IGNORECASE)
        if not end_m:
            continue
        body = seg[: end_m.start()]
        # Only parse if first line is a known block type
        first_line = body.split("\n")[0].strip().upper()
        if first_line not in ("CARD", "DEF", "FORMULA", "LIST", "TIMELINE"):
            continue
        parsed = _parse_block_text(body)
        if parsed:
            blocks.append(parsed)

    return header, blocks


# ── DB helpers ────────────────────────────────────────────────────────────

def _upsert_board(con, name: str, code: str) -> int:
    con.execute(
        "INSERT OR IGNORE INTO fc_boards (name, code) VALUES (?, ?)", (name, code)
    )
    return con.execute("SELECT id FROM fc_boards WHERE code = ?", (code,)).fetchone()[0]


def _upsert_subject(con, board_id: int, name: str, code: str,
                    level: str, alt_codes: list) -> int:
    con.execute(
        """INSERT INTO fc_subjects (board_id, name, code, level, alt_codes_json)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(code) DO UPDATE SET
               name=excluded.name, level=excluded.level,
               alt_codes_json=excluded.alt_codes_json""",
        (board_id, name, code, level, json.dumps(alt_codes)),
    )
    return con.execute("SELECT id FROM fc_subjects WHERE code = ?", (code,)).fetchone()[0]


def _upsert_paper(con, subject_id: int, code: str, name: str) -> int:
    con.execute(
        "INSERT OR IGNORE INTO fc_papers (subject_id, code, name) VALUES (?, ?, ?)",
        (subject_id, code, name),
    )
    return con.execute(
        "SELECT id FROM fc_papers WHERE subject_id = ? AND code = ?",
        (subject_id, code),
    ).fetchone()[0]


def _upsert_chapter(con, paper_id: int, name: str, order_idx: int) -> int:
    con.execute(
        "INSERT OR IGNORE INTO fc_chapters (paper_id, name, order_index) VALUES (?, ?, ?)",
        (paper_id, name, order_idx),
    )
    con.execute(
        "UPDATE fc_chapters SET order_index = ? WHERE paper_id = ? AND name = ?",
        (order_idx, paper_id, name),
    )
    return con.execute(
        "SELECT id FROM fc_chapters WHERE paper_id = ? AND name = ?",
        (paper_id, name),
    ).fetchone()[0]


def _upsert_block(con, chapter_id: int, type_: str, topic_label: str,
                  payload: dict, source_hash: str) -> tuple[int, bool]:
    """Return (block_id, is_new)."""
    existing = con.execute(
        "SELECT id FROM fc_blocks WHERE source_hash = ?", (source_hash,)
    ).fetchone()
    if existing:
        con.execute(
            """UPDATE fc_blocks
               SET chapter_id=?, type=?, topic_label=?, payload_json=?
               WHERE id=?""",
            (chapter_id, type_, topic_label, json.dumps(payload), existing[0]),
        )
        return existing[0], False
    con.execute(
        """INSERT INTO fc_blocks (chapter_id, type, topic_label, payload_json, source_hash)
           VALUES (?, ?, ?, ?, ?)""",
        (chapter_id, type_, topic_label, json.dumps(payload), source_hash),
    )
    return con.execute("SELECT last_insert_rowid()").fetchone()[0], True


# ── Main import routine ───────────────────────────────────────────────────

def _import_file(con, path: Path, verbose: bool = True) -> tuple[int, int]:
    header, blocks = _parse_file(path)

    if not header.get("primary_code"):
        print(f"  SKIP {path.name}: no syllabus code detected")
        return 0, 0

    board_name, board_code = _board_for_level(
        header.get("level", ""), header.get("board", "")
    )
    board_id = _upsert_board(con, board_name, board_code)

    subject_name = header.get("subject") or path.stem
    subject_id = _upsert_subject(
        con, board_id,
        name=subject_name,
        code=header["primary_code"],
        level=header.get("level", ""),
        alt_codes=header.get("alt_codes", []),
    )

    papers = header.get("papers") or [{"code": "ALL", "name": "General"}]
    paper_id_of: dict[str, int] = {}
    for p in papers:
        paper_id_of[p["code"]] = _upsert_paper(con, subject_id, p["code"], p["name"])

    if "ALL" not in paper_id_of:
        paper_id_of["ALL"] = _upsert_paper(con, subject_id, "ALL", "General")

    known_codes = [c for c in paper_id_of if c != "ALL"]

    chapter_order: dict[tuple, int] = {}
    new_count = updated_count = 0

    for blk in blocks:
        topic_raw = (blk.get("topic") or "").strip()

        paper_code = "ALL"
        chapter_name = topic_raw or "General"

        pm = _PAPER_PREFIX_RE.match(topic_raw)
        if pm:
            candidate = pm.group(1).upper()
            if candidate in known_codes:
                paper_code = candidate
                chapter_name = pm.group(2).strip()

        paper_id = paper_id_of.get(paper_code, paper_id_of["ALL"])
        key = (paper_id, chapter_name)
        order_idx = chapter_order.setdefault(key, len(chapter_order))
        chapter_id = _upsert_chapter(con, paper_id, chapter_name, order_idx)

        h = _block_hash(blk["type"], blk["payload"])
        _, is_new = _upsert_block(con, chapter_id, blk["type"], topic_raw, blk["payload"], h)

        if is_new:
            new_count += 1
        else:
            updated_count += 1

    if verbose:
        subj_str = f"{subject_name} [{header['primary_code']}]"
        alt = header.get("alt_codes")
        if alt:
            subj_str += f" + {', '.join(alt)}"
        print(
            f"  {path.name}: {len(blocks)} blocks "
            f"({new_count} new, {updated_count} updated) → {subj_str}"
        )
    return new_count, updated_count


def import_all(files: list[Path] | None = None, verbose: bool = True) -> None:
    if not DB_PATH.exists():
        print(f"ERROR: database not found at {DB_PATH}")
        sys.exit(1)

    if files is None:
        # Include both .md and .txt
        files = sorted(
            list(FC_DIR.glob("*.md")) + list(FC_DIR.glob("*.txt"))
        )

    if not files:
        print(f"No .md / .txt files found in {FC_DIR}")
        return

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(_DDL)
    con.commit()

    total_new = total_updated = 0
    for path in files:
        if not path.exists():
            print(f"  SKIP {path}: not found")
            continue
        n, u = _import_file(con, path, verbose=verbose)
        total_new += n
        total_updated += u

    con.commit()
    con.close()
    print(f"\nDone: {total_new} new blocks, {total_updated} updated across {len(files)} file(s).")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args:
        paths = [Path(a) if Path(a).is_absolute() else FC_DIR / a for a in args]
    else:
        paths = None
    import_all(paths)
