"""Stage: AI worked solutions + Guide-me hints, generated once per question (free tier).

    python -m pipeline.explain --pilot 5 --syllabus 0625      # a few, printed + stored
    python -m pipeline.explain --drip --per-day 600           # background: newest papers first,
                                                              # stays inside the free daily quota
    python -m pipeline.explain --stats                        # how many are done

Tutor's decisions: every question gets ONE explanation, generated once and
served to every student (2026-09-25); and no paid models - free tiers only
(2026-09-25). So generation runs on free OpenAI-compatible providers (Groq by
default; Gemini drops in with GEMINI_API_KEY) and is spread over time:

  * --drip works through the backlog newest-first, pacing itself on the
    provider's rate-limit headers and leaving `--reserve` daily requests free
    for the live site, which shares the same key;
  * the website generates on demand when a student opens a question that is
    not done yet (website/ai_help.py calls generate_one), then stores it.

One call per question produces everything the viewer's AI panel shows:

    parts[]          worked solution per sub-part (steps, answer, how marks are given)
    hints[3]         Guide me: what is asked -> first step -> next step
    mcq_options[]    MCQ only: why each option is right or wrong
    common_mistakes  misconceptions examiners report

The model sees the question crop and the OFFICIAL mark scheme (crop or MCQ
letter), so the explanation must arrive at Cambridge's answer; when it can't,
`confidence` says so.
"""

import argparse
import base64
import json
import os
import re
import time

import fitz

from . import config, db, setup_logging

log = setup_logging("explain")

PROMPT_VERSION = 1
RENDER_DPI = 100
MAX_IMAGES = 3                     # per side (question / mark scheme)
MAX_TOKENS = 3500

# Free OpenAI-compatible vision providers, in order of preference.
PROVIDERS = {
    "groq": {"env": "GROQ_API_KEY",
             "url": "https://api.groq.com/openai/v1/chat/completions",
             "model": os.environ.get("EXPLAIN_GROQ_MODEL", "qwen/qwen3.8-27b"),
             # Reasoning burns the 8k tokens/minute budget and truncates the JSON;
             # the step-by-step prompt gives the working instead.
             "extra": {"reasoning_effort": "none"}},
    "gemini": {"env": "GEMINI_API_KEY",
               "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
               "model": os.environ.get("EXPLAIN_GEMINI_MODEL", "gemini-2.0-flash"),
               "extra": {}},
}

SYSTEM = """You are Tee, an expert Cambridge O Level / IGCSE / A Level tutor in Lahore. \
You write the worked solution a strong student would want after attempting a past-paper \
question, for the PrepWithTee study site.

You are given the question as image(s), its syllabus chapter, and the OFFICIAL Cambridge \
mark scheme (as image(s), or the correct option letter for multiple choice).

Rules:
- Arrive at the mark scheme's answer. The mark scheme is authoritative. If you genuinely \
think it is wrong or unreadable, still explain its answer and set confidence to "low".
- Explain every sub-part in order ((a), (b)(i), ...). Each step is short: what to do and \
why, then the working. Use the method and wording Cambridge credits (command words, units, \
significant figures, key phrases from the mark scheme).
- Maths notation: LaTeX inside $...$ (inline) or $$...$$ (display). Units in \\mathrm{}. \
No LaTeX in step titles. Because the reply is JSON, write every LaTeX backslash \
DOUBLED, e.g. "$\\\\frac{F}{A}$".
- "marking": how the marks are earned for that part, in plain words.
- "hints": exactly three, increasingly specific, WITHOUT the final answer: 1) what the \
question is really asking, 2) the first step, 3) the next step plus a self-check.
- "mcq_options": multiple choice only - one entry per option A-D, why it is right or the \
misconception that makes it tempting. Empty list for structured questions.
- "common_mistakes": up to 3 specific mistakes students make on this question.
- Write clearly for a 15-17 year old. No greetings, no mention of being an AI.

Reply with ONLY a JSON object of exactly this shape:
{"summary": "one or two sentences: what the question tests",
 "parts": [{"label": "(a)", "steps": [{"title": "...", "body": "..."}],
            "answer": "...", "marking": "..."}],
 "hints": ["...", "...", "..."],
 "mcq_options": [{"letter": "A", "correct": false, "why": "..."}],
 "common_mistakes": ["..."],
 "confidence": "high" | "medium" | "low"}"""


# ── Inputs ────────────────────────────────────────────────────────────────────

def _pngs(pdf_path: str | None) -> list[bytes]:
    if not pdf_path:
        return []
    path = config.ROOT / str(pdf_path).replace("\\", "/")
    if not path.exists():
        return []
    with fitz.open(path) as doc:
        return [p.get_pixmap(dpi=RENDER_DPI).tobytes("png") for p in list(doc)[:MAX_IMAGES]]


def _png_blocks(pdf_path: str | None) -> list[dict]:
    """Anthropic-style image blocks (kept for any caller that wants them)."""
    return [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": base64.standard_b64encode(b).decode()}}
            for b in _pngs(pdf_path)]


def _image_parts(pdf_path: str | None) -> list[dict]:
    """OpenAI-compatible image parts."""
    return [{"type": "image_url", "image_url": {
        "url": "data:image/png;base64," + base64.standard_b64encode(b).decode()}}
        for b in _pngs(pdf_path)]


QUESTION_SQL = """
    SELECT q.id, q.number, q.sub_part, q.marks, q.crop_path, q.text,
           c.topic, c.subtopic, p.syllabus, p.year, p.session, p.paper, p.variant,
           m.crop_path AS ms_crop, m.answer AS mcq_answer
    FROM questions q
    JOIN papers p ON p.id = q.paper_id
    JOIN classifications c ON c.question_id = q.id
    LEFT JOIN question_explanations e ON e.question_id = q.id
    LEFT JOIN papers mp ON mp.syllabus = p.syllabus AND mp.year = p.year
         AND mp.session = p.session AND mp.paper = p.paper
         AND mp.variant = p.variant AND mp.kind = 'ms'
    LEFT JOIN ms_entries m ON m.paper_id = mp.id AND m.question_number = q.number
         AND m.sub_part = q.sub_part"""


def pending(con, syllabus=None, limit=None, force=False):
    """Questions still needing an explanation, newest papers first."""
    where = ["p.kind = 'qp'", "q.status IS NOT 'excluded'", "q.crop_path IS NOT NULL"]
    params: list = []
    if syllabus:
        where.append("p.syllabus = ?")
        params.append(syllabus)
    if not force:
        where.append("(e.question_id IS NULL OR e.prompt_version < ?)")
        params.append(PROMPT_VERSION)
    sql = QUESTION_SQL + f" WHERE {' AND '.join(where)} ORDER BY p.year DESC, p.session DESC, q.id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return con.execute(sql, params).fetchall()


def build_messages(q) -> list[dict]:
    """OpenAI-compatible chat messages for one question."""
    syl, paper = q["syllabus"], q["paper"]
    mcq = config.is_mcq(syl, paper)
    ref = config.source_ref(syl, f"{paper}{q['variant']}", q["session"], q["year"],
                            q["number"], q["sub_part"] or "")
    header = (f"Subject: {_subject(syl)} ({syl})\nSource: {ref}\nChapter: {q['topic']}"
              + (f"\nSubtopic: {q['subtopic']}" if q["subtopic"] else "")
              + (f"\nMarks: {q['marks']}" if q["marks"] else "")
              + f"\nType: {'multiple choice' if mcq else 'structured'}")
    content: list[dict] = [{"type": "text", "text": header + "\n\nQUESTION:"}]
    content += _image_parts(q["crop_path"])
    if mcq and q["mcq_answer"]:
        content.append({"type": "text",
                        "text": f"OFFICIAL MARK SCHEME: the correct option is {q['mcq_answer']}."})
    else:
        ms = _image_parts(q["ms_crop"])
        if ms:
            content.append({"type": "text", "text": "OFFICIAL MARK SCHEME:"})
            content += ms
        else:
            content.append({"type": "text", "text": "OFFICIAL MARK SCHEME: not available - "
                            "solve it carefully and set confidence accordingly."})
    content.append({"type": "text", "text": "Reply with the JSON object now."})
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}]


_SUBJECTS: dict[str, str] = {}


def _subject(syl: str) -> str:
    if syl not in _SUBJECTS:
        from . import heuristics
        try:
            _SUBJECTS[syl] = heuristics.load_taxonomy(syl).get("subject", syl)
        except Exception:
            _SUBJECTS[syl] = syl
    return _SUBJECTS[syl]


# ── Output ────────────────────────────────────────────────────────────────────

# LaTeX commands a model may leave with a single backslash inside JSON. Several
# start with a letter JSON treats as an escape (f t n b r), so a lone "\frac"
# would silently decode as a form feed + "rac". Double them before parsing.
_LATEX_CMDS = (
    "frac|dfrac|tfrac|sqrt|times|div|cdot|pm|mp|approx|neq|leq|geq|le|ge|ne|"
    "theta|alpha|beta|gamma|delta|Delta|lambda|mu|nu|rho|sigma|Sigma|omega|Omega|"
    "pi|phi|epsilon|eta|tau|infty|degree|circ|angle|triangle|parallel|perp|"
    "mathrm|text|textbf|mathbf|left|right|begin|end|underline|overline|"
    "vec|hat|bar|dot|sin|cos|tan|log|ln|lim|sum|int|partial|nabla|"
    "rightarrow|leftarrow|Rightarrow|to|in|notin|subset|cup|cap|quad|qquad|"
    "displaystyle|operatorname|propto|therefore|because|ldots|cdots")
_LATEX_RE = re.compile(r"(?<!\\)\\(?=(?:" + _LATEX_CMDS + r")(?![A-Za-z]))")


def _repair_latex(text: str) -> str:
    return _LATEX_RE.sub(lambda m: "\\\\", text)


def parse_text(text: str) -> dict | None:
    """The explanation JSON from model text, or None if unusable."""
    text = _repair_latex((text or "").strip())
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict) or not data.get("parts") or len(data.get("hints") or []) < 3:
        return None
    data["hints"] = [str(h) for h in data["hints"][:3]]
    data.setdefault("mcq_options", [])
    data.setdefault("common_mistakes", [])
    if data.get("confidence") not in ("high", "medium", "low"):
        data["confidence"] = "medium"
    return data


def store(con, qid: int, data: dict, model: str, usage: dict | None) -> None:
    usage = usage or {}
    con.execute(
        """INSERT INTO question_explanations
               (question_id, content_json, model, prompt_version, input_tokens, output_tokens)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(question_id) DO UPDATE SET
               content_json = excluded.content_json, model = excluded.model,
               prompt_version = excluded.prompt_version,
               input_tokens = excluded.input_tokens, output_tokens = excluded.output_tokens,
               flagged = 0""",
        (qid, json.dumps(data, ensure_ascii=False), model, PROMPT_VERSION,
         usage.get("prompt_tokens"), usage.get("completion_tokens")))
    con.commit()


# ── Provider calls ────────────────────────────────────────────────────────────

class RateLimited(Exception):
    def __init__(self, wait: float, daily: bool):
        super().__init__(f"rate limited ({'daily' if daily else 'per-minute'}), wait {wait:.0f}s")
        self.wait, self.daily = wait, daily


def _seconds(v: str | None) -> float:
    """Groq reset headers look like '7.66s', '2m59.56s' or '1h2m3s'."""
    if not v:
        return 0.0
    total, num = 0.0, ""
    for ch in v:
        if ch.isdigit() or ch == ".":
            num += ch
        else:
            total += float(num or 0) * {"h": 3600, "m": 60, "s": 1}.get(ch, 0)
            num = ""
    return total + (float(num) if num else 0.0)


def available_providers() -> list[str]:
    return [n for n, p in PROVIDERS.items() if os.environ.get(p["env"])]


def call(messages: list[dict], provider: str | None = None, timeout: int = 90):
    """(text, usage, model, headers) from the first configured provider."""
    import requests
    names = [provider] if provider else available_providers()
    if not names:
        raise RuntimeError("No free AI provider key set (GROQ_API_KEY or GEMINI_API_KEY).")
    last = None
    for name in names:
        p = PROVIDERS[name]
        r = requests.post(p["url"], timeout=timeout,
                          headers={"Authorization": f"Bearer {os.environ[p['env']]}"},
                          json={"model": p["model"], "messages": messages,
                                # No response_format: strict JSON mode rejects the
                                # whole answer over one LaTeX backslash; parse_text
                                # repairs and validates instead.
                                "max_tokens": MAX_TOKENS, "temperature": 0.2, **p["extra"]})
        if r.status_code == 429:
            daily = r.headers.get("x-ratelimit-remaining-requests") == "0"
            wait = float(r.headers.get("retry-after") or 0) or _seconds(
                r.headers.get("x-ratelimit-reset-requests" if daily else "x-ratelimit-reset-tokens"))
            last = RateLimited(max(wait, 2.0), daily)
            continue
        if r.status_code in (500, 502, 503, 504):
            # Free tiers go "over capacity" regularly; back off and retry.
            last = RateLimited(30.0, False)
            continue
        if r.status_code >= 400:
            last = RuntimeError(f"{name} {r.status_code}: {r.text[:300]}")
            continue
        j = r.json()
        return (j["choices"][0]["message"].get("content") or "", j.get("usage") or {},
                f"{name}:{p['model']}", r.headers)
    raise last


def generate_one(q, provider: str | None = None):
    """(data, usage, model, headers) for one question; data None if unusable."""
    text, usage, model, headers = call(build_messages(q), provider)
    return parse_text(text), usage, model, headers


# ── Modes ─────────────────────────────────────────────────────────────────────

def run_pilot(con, args):
    import random
    rows = pending(con, args.syllabus, None, args.force)
    random.Random(7).shuffle(rows)
    for q in rows[:args.pilot]:
        for _attempt in range(3):
            try:
                data, usage, model, _h = generate_one(q, args.provider)
                break
            except RateLimited as e:
                if e.daily:
                    log.warning("daily limit reached - stopping pilot")
                    return
                log.info("per-minute limit, waiting %.0fs", e.wait)
                time.sleep(min(e.wait + 1, 90))
        else:
            continue
        if data is None:
            log.warning("q%s: unusable response", q["id"])
            continue
        store(con, q["id"], data, model, usage)
        log.info("q%s %s: %d parts, confidence %s, %s tokens", q["id"], q["syllabus"],
                 len(data["parts"]), data["confidence"], usage.get("total_tokens"))


def run_drip(con, args):
    """Work through the backlog inside the free quota, newest papers first."""
    done = fails = 0
    for q in pending(con, args.syllabus, None, args.force):
        if done >= args.per_day:
            log.info("daily share reached (%d) - run again tomorrow", done)
            break
        for attempt in range(3):
            try:
                data, usage, model, headers = generate_one(q, args.provider)
                break
            except RateLimited as e:
                if e.daily:
                    log.info("provider daily limit reached after %d today - stopping", done)
                    return
                log.info("per-minute limit, sleeping %.0fs", e.wait)
                time.sleep(min(e.wait + 1, 120))
            except Exception as e:                     # network / 5xx: skip this one
                log.warning("q%s: %s", q["id"], e)
                data, headers = None, {}
                break
        else:
            continue
        if data is None:
            fails += 1
            continue
        store(con, q["id"], data, model, usage)
        done += 1
        # Leave room for the live site, which shares the key and its daily quota.
        remaining = int(headers.get("x-ratelimit-remaining-requests") or 10**6)
        if remaining <= args.reserve:
            log.info("only %d requests left today - leaving them for the live site", remaining)
            break
        # Pace on the per-minute token budget instead of hammering into 429s.
        left_tokens = int(headers.get("x-ratelimit-remaining-tokens") or 10**6)
        if left_tokens < 4000:
            time.sleep(min(_seconds(headers.get("x-ratelimit-reset-tokens")) + 0.5, 60))
    log.info("drip: stored %d, unusable %d", done, fails)


def run_stats(con, _args):
    total = con.execute("SELECT COUNT(*) FROM questions q JOIN papers p ON p.id=q.paper_id "
                        "WHERE p.kind='qp' AND q.status IS NOT 'excluded'").fetchone()[0]
    done = con.execute("SELECT COUNT(*) FROM question_explanations "
                       "WHERE prompt_version >= 1").fetchone()[0]
    print(f"{done:,} of {total:,} questions explained ({100 * done / max(1, total):.1f}%)")
    for syl, n in con.execute(
            "SELECT p.syllabus, COUNT(*) FROM question_explanations e "
            "JOIN questions q ON q.id=e.question_id JOIN papers p ON p.id=q.paper_id "
            "WHERE e.prompt_version >= 1 GROUP BY 1 ORDER BY 1"):
        print(f"  {syl}: {n:,}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pilot", type=int, metavar="N")
    mode.add_argument("--drip", action="store_true")
    mode.add_argument("--stats", action="store_true")
    ap.add_argument("--syllabus")
    ap.add_argument("--provider", choices=sorted(PROVIDERS))
    ap.add_argument("--per-day", type=int, default=600,
                    help="max explanations this run (free daily quota is shared with the site)")
    ap.add_argument("--reserve", type=int, default=300,
                    help="stop when the provider has this many requests left today")
    ap.add_argument("--force", action="store_true", help="redo questions already explained")
    args = ap.parse_args(argv)
    con = db.connect()
    try:
        if args.pilot:
            run_pilot(con, args)
        elif args.drip:
            run_drip(con, args)
        else:
            run_stats(con, args)
    finally:
        con.close()


if __name__ == "__main__":
    main()
