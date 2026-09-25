"""Routing and official-answer checks for AI explanations.

    route(q)            'text' when the question and its mark scheme read cleanly
                        as text, else 'vision' (figures, drawn options, maths layout)
    question_text(q)    the crop's text, with superscripts kept as ^ (m/s^2, 10^8)
    ms_text(q)          the official mark-scheme crop's text
    check(data, q, ms)  does the explanation agree with Cambridge's key?
                        MCQ: exactly one option marked correct, and it is the key.
                        Structured: the mark scheme's significant numbers appear in
                        the explanation, and it isn't marked low-confidence.

An explanation that fails the check is never stored: the drip retries it on
another provider (or with the images), the site answers "try again".
"""

import re

import fitz

from . import config

# Maths papers put fractions, powers and roots in 2-D layout that text extraction
# flattens ("x2", stacked numerators), so they always go to a vision model.
VISION_SUBJECTS = {"4024", "0580", "9709"}
FIGURE_WORDS = re.compile(
    r"\b(fig\.?|figure|diagram|graph|grid|sketch|shaded|drawn|shown (?:below|above|in)|"
    r"the (?:circuit|apparatus|table below)|photograph|map|scale drawing|ray diagram)\b", re.I)


def _path(p):
    return config.ROOT / str(p).replace("\\", "/") if p else None


def pdf_text(pdf_path) -> str:
    """Text of a crop PDF, reading order kept, superscripts as ^n, subscripts as _n."""
    path = _path(pdf_path)
    if not path or not path.exists():
        return ""
    lines = []
    with fitz.open(path) as doc:
        for page in doc:
            d = page.get_text("dict", sort=True)
            for block in d.get("blocks", []):
                for line in block.get("lines", []):
                    out, base = "", None
                    spans = line.get("spans", [])
                    sizes = [s["size"] for s in spans if s.get("text", "").strip()]
                    main = max(sizes) if sizes else 0
                    for s in spans:
                        t = s.get("text", "")
                        if not t.strip():
                            out += t
                            continue
                        small = main and s["size"] < main * 0.8
                        if s.get("flags", 0) & 1 or (small and base is not None and s["origin"][1] < base - 1):
                            out += "^" + (t.strip() if len(t.strip()) == 1 else "(" + t.strip() + ")")
                        elif small and base is not None and s["origin"][1] > base + 1:
                            out += "_" + t.strip()
                        else:
                            out += t
                            base = s["origin"][1]
                    if out.strip():
                        lines.append(out.rstrip())
    return "\n".join(lines).strip()


def question_text(q) -> str:
    return pdf_text(q.get("crop_path") if hasattr(q, "get") else q["crop_path"])


def ms_text(q) -> str:
    get = q.get if hasattr(q, "get") else (lambda k: q[k])
    return pdf_text(get("ms_crop"))


def _figure_count(pdf_path) -> int:
    """Images + drawn shapes that are not plain lines (answer lines, table rules)."""
    path = _path(pdf_path)
    if not path or not path.exists():
        return 99
    n = 0
    with fitz.open(path) as doc:
        for page in doc:
            n += len(page.get_images())
            for d in page.get_drawings():
                r = d.get("rect")
                if r is None:
                    continue
                thin = r.width < 2.5 or r.height < 2.5
                curve = any(item[0] == "c" for item in d.get("items", []))
                if curve or not thin:
                    # a filled/stroked box around a table cell is still "thin" per edge;
                    # count shapes whose own bbox is 2-D, or any curve
                    n += 1
    return n


def _is_mcq(q) -> bool:
    return config.is_mcq(q["syllabus"], q["paper"])


def route(q) -> str:
    """'text' or 'vision' for this question."""
    if q["syllabus"] in VISION_SUBJECTS:
        return "vision"
    text = question_text(q)
    if len(text) < 40 or FIGURE_WORDS.search(text):
        return "vision"
    if _figure_count(q["crop_path"]) > 2:           # a box or two (e.g. a table frame) is fine
        return "vision"
    if _is_mcq(q):
        # All four options must be readable as text (not drawings / graphs).
        found = {m.group(1) for m in re.finditer(r"(?m)^\s*([ABCD])\b", text)}
        if len(found) < 4:
            return "vision"
    else:
        if not ms_text(q):                            # mark scheme only as an image
            return "vision"
    return "text"


# ── The official-answer check ────────────────────────────────────────────────

_MARK_CODES = re.compile(r"\b(?:[ABCM]\d|B\d+|owtte|ecf|cao|ora|oe|isw|ignore)\b", re.I)
_QREF = re.compile(r"(?m)^\s*\d{1,2}\s*(?:\(\s*[a-z]{1,4}\s*\)\s*)+")
_NUM = re.compile(r"(?<![A-Za-z_^])-?\d+(?:\.\d+)?")
_SCI = re.compile(r"(\d+(?:\.\d+)?)\s*(?:×|\\times|x|\*)\s*10\s*\^\s*\{?\s*\(?(-?\d+)\)?\s*\}?")


_PARTIAL = re.compile(r"(?i)\b(?:[ABMC]\d+|SC\d+)\s*(?:FT|ft)?\s+for\b[^\n]*")
_RANGE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:to|–|—)\s*(-?\d+(?:\.\d+)?)")


def _minus(s: str) -> str:
    """Cambridge typesets minus as − or an en dash: '–2.8 to –2.6' -> '-2.8 to -2.6'."""
    return re.sub(r"(^|[\s(=,:\[])[–—−](?=\s?\d)", r"\1-", s.replace("−", "-"), flags=re.M)


def ms_ranges(ms: str) -> list[tuple[float, float]]:
    """'2.4 to 2.7' style accepted ranges in a mark scheme."""
    out = []
    for m in _RANGE.finditer(_PARTIAL.sub(" ", _minus(ms))):
        a, b = float(m.group(1)), float(m.group(2))
        out.append((min(a, b), max(a, b)))
    return out


def ms_numbers(ms: str, qnum: int | None = None) -> list[float]:
    """Significant numbers in a mark scheme: final answers, not question refs, mark
    codes, partial-credit working ("M1 for ..."), or accepted ranges (see ms_ranges)."""
    s = _PARTIAL.sub(" ", _minus(ms))
    s = _RANGE.sub(" ", s)
    s = _QREF.sub(" ", s)
    s = _MARK_CODES.sub(" ", s)
    s = re.sub(r"\[\s*\d+\s*\]", " ", s)                 # [2] mark tallies
    s = re.sub(r"(?i)page \d+ of \d+|\b\d{4}/\d{2}\b|\b(?:19|20)\d{2}\b", " ", s)
    vals = []
    for m in _NUM.finditer(s):
        t = m.group(0)
        if "." not in t and len(t.lstrip("-")) < 2:       # single digits: marks, counts
            continue
        try:
            v = float(t)
        except ValueError:
            continue
        if qnum is not None and v == qnum:                # the question's own number
            continue
        vals.append(v)
    return vals


def _all_text(data) -> str:
    out = []

    def walk(v):
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(data)
    return "\n".join(out)


def explanation_numbers(data) -> list[float]:
    t = _all_text(data).replace("\\,", "").replace("{,}", "").replace("\\!", "")
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)            # 1,500 -> 1500
    vals = []
    for m in _SCI.finditer(t):
        try:
            vals.append(float(m.group(1)) * 10 ** int(m.group(2)))
        except (ValueError, OverflowError):
            pass
    for m in _NUM.finditer(t):
        try:
            vals.append(float(m.group(0)))
        except ValueError:
            pass
    return vals


def _close(a: float, b: float) -> bool:
    return a == b or abs(a - b) <= max(1e-9, 1e-6 * max(abs(a), abs(b)))


def check(data: dict, q, ms: str | None = None) -> tuple[bool, str]:
    """(agrees, reason). Deterministic - no model calls."""
    if not data:
        return False, "no explanation"
    if _is_mcq(q):
        key = (q["mcq_answer"] or "").strip().upper()
        if key not in ("A", "B", "C", "D"):
            return False, "no official key to check against"
        opts = data.get("mcq_options") or []
        marked = [str(o.get("letter", "")).strip("() ").upper()
                  for o in opts if isinstance(o, dict) and o.get("correct") is True]
        if len(opts) < 4:
            return False, "not every option explained"
        if marked != [key]:
            return False, f"says {'/'.join(marked) or 'nothing'} is correct, the key is {key}"
        return True, "matches the official key"
    if data.get("confidence") == "low":
        return False, "model was unsure (low confidence)"
    if q["syllabus"] in VISION_SUBJECTS:
        # Maths mark schemes don't survive text extraction (stacked fractions),
        # so the numbers can't be compared - a model checks against the image.
        return True, "needs model verification (maths layout)"
    if ms is None:
        ms = ms_text(q)
    have = explanation_numbers(data)
    ranges = ms_ranges(ms or "")
    bad_ranges = [r for r in ranges if not any(r[0] - 1e-9 <= h <= r[1] + 1e-9 for h in have)]
    want = ms_numbers(ms or "", q["number"])
    missing = [w for w in want if not any(_close(w, h) for h in have)]
    total = len(want) + len(ranges)
    if not total:
        return True, "no numeric answers in the mark scheme to compare"
    found = 1 - (len(missing) + len(bad_ranges)) / total
    if found < 0.75:
        return False, f"mark-scheme values missing from the working: {(missing + bad_ranges)[:5]}"
    return True, f"{total - len(missing) - len(bad_ranges)}/{total} mark-scheme values present"


VERIFY_SYSTEM = """You check worked solutions against the OFFICIAL Cambridge mark scheme.
Reply with ONLY a JSON object: {"agrees": true or false, "problem": "one short sentence, empty if it agrees"}.
It agrees when every final answer matches the mark scheme's answer (equivalent forms, the
mark scheme's own alternatives, rounding it accepts, and correct units all count) and the
method does not contradict the mark scheme. Be strict about wrong values, wrong units,
wrong option letters and wrong reasoning for "explain" questions."""


def verify_messages(data: dict, q, ms: str) -> list[dict]:
    answers = "\n".join(f"{p.get('label') or 'Answer'}: {p.get('answer', '')}\n  marking: {p.get('marking', '')}"
                        for p in data.get("parts", []))
    return [{"role": "system", "content": VERIFY_SYSTEM},
            {"role": "user", "content": f"OFFICIAL MARK SCHEME:\n{ms[:6000]}\n\n"
                                        f"SOLUTION'S FINAL ANSWERS:\n{answers[:6000]}"}]


def parse_verdict(text: str) -> tuple[bool, str] | None:
    s = (text or "").strip()
    a, b = s.find("{"), s.rfind("}")
    if a < 0 or b <= a:
        low = s.lower()
        if '"agrees": true' in low or "agrees: true" in low:
            return True, ""
        return None
    import json
    try:
        d = json.loads(s[a:b + 1])
    except ValueError:
        return None
    if not isinstance(d.get("agrees"), bool):
        return None
    return d["agrees"], str(d.get("problem") or "")
