"""Stage: AI worked solutions + Guide-me hints, generated once per question (free tiers).

    python -m pipeline.explain --probe                        # which free providers answer
    python -m pipeline.explain --pilot 5 --syllabus 0625      # a few, stored
    python -m pipeline.explain --drip --loop                  # background, every provider
    python -m pipeline.explain --stats                        # how many are done

Tutor's decisions: every question gets ONE explanation, generated once and
served to every student; free tiers only; and every explanation must agree with
the OFFICIAL Cambridge mark scheme (2026-09-26).

How a question is written up (pipeline/ai_providers.py has the providers):

  1. route   explain_check.route(): questions whose text and mark scheme read
             cleanly go the TEXT route (any free text model - Mistral, NVIDIA,
             OpenRouter, Groq gpt-oss ...); figures, drawn options and maths
             layout go the VISION route (Mistral, Gemini; Groq's vision model is
             the live Photo Solver's budget and stays out of the background job).
             A text model that finds it needs the diagram says so and the
             question moves to the vision route.
  2. write   one JSON per question: parts[] (steps, answer, how marks are given),
             hints[3], mcq_options[] (why each option), common_mistakes.
  3. check   explain_check.check(): MCQ - exactly one option marked correct and
             it is the official key; structured - the mark scheme's values are in
             the working. Then a second model reads the official mark scheme and
             the solution's final answers and must say they agree (the mark-scheme
             IMAGE for maths). Anything that fails is retried elsewhere, never stored.

The website generates on demand (website/ai_help.py -> generate_one) the first
time a student opens a question that is not done yet, with the same checks.
"""

import argparse
import base64
import json
import os
import re
import time

import fitz

from . import ai_providers as ap
from . import config, db, setup_logging
from . import explain_check as ck

log = setup_logging("explain")

PROMPT_VERSION = 1
RENDER_DPI = 100
MAX_IMAGES = 3                     # per side (question / mark scheme)
MAX_TOKENS = 3500
RateLimited = ap.RateLimited
_seconds = ap.seconds

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
- "parts" is never empty: a multiple-choice question has one part (label "") with the \
working that leads to the correct option, and "answer" is that option's letter.
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


_OVER = re.compile(r"\\{2,}(?=[A-Za-z])")


def _unescape_latex(v):
    """Some models escape twice: after JSON decoding a string still holds '\\\\times'
    (KaTeX reads '\\\\' as a line break). Collapse to one backslash before a command."""
    if isinstance(v, str):
        return _OVER.sub(lambda m: "\\", v)
    if isinstance(v, list):
        return [_unescape_latex(x) for x in v]
    if isinstance(v, dict):
        return {k: _unescape_latex(x) for k, x in v.items()}
    return v


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
    if not isinstance(data, dict):
        return None
    if not data.get("parts") and data.get("mcq_options"):
        # Some models put the whole MCQ working into the options: make it the part.
        right = [o for o in data["mcq_options"] if isinstance(o, dict) and o.get("correct") is True]
        if len(right) == 1:
            data["parts"] = [{"label": "", "steps": [{"title": f"Why {right[0].get('letter')} is correct",
                                                      "body": str(right[0].get("why", ""))}],
                              "answer": str(right[0].get("letter", "")),
                              "marking": "1 mark for the correct option."}]
    if not data.get("parts") or len(data.get("hints") or []) < 3:
        return None
    data = _unescape_latex(data)
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



# ── Text route ────────────────────────────────────────────────────────────────

TEXT_NOTE = """

The question and mark scheme below are TEXT extracted from the PDF: superscripts are
written with ^ (m/s^2, 3.0 x 10^8), subscripts with _ (CH_3), and answer lines/dots
are omitted. If the question cannot be answered correctly without seeing a diagram,
graph or picture that the text does not describe, reply with exactly
{"needs_diagram": true} and nothing else."""


def build_text_messages(q, qtext: str, mstext: str) -> list[dict]:
    syl, paper = q["syllabus"], q["paper"]
    mcq = config.is_mcq(syl, paper)
    ref = config.source_ref(syl, f"{paper}{q['variant']}", q["session"], q["year"],
                            q["number"], q["sub_part"] or "")
    header = (f"Subject: {_subject(syl)} ({syl})\nSource: {ref}\nChapter: {q['topic']}"
              + (f"\nSubtopic: {q['subtopic']}" if q["subtopic"] else "")
              + (f"\nMarks: {q['marks']}" if q["marks"] else "")
              + f"\nType: {'multiple choice' if mcq else 'structured'}")
    key = (f"OFFICIAL MARK SCHEME: the correct option is {q['mcq_answer']}."
           if mcq else f"OFFICIAL MARK SCHEME (text):\n{mstext[:6000]}")
    user = (f"{header}\n\nQUESTION (text):\n{qtext[:8000]}\n\n{key}\n\n"
            "Reply with the JSON object now.")
    return [{"role": "system", "content": SYSTEM + TEXT_NOTE}, {"role": "user", "content": user}]


def _vision_verify_messages(data: dict, q) -> list[dict]:
    answers = "\n".join(f"{p.get('label') or 'Answer'}: {p.get('answer', '')}"
                        for p in data.get("parts", []))
    content = [{"type": "text", "text": "OFFICIAL MARK SCHEME:"}] + _image_parts(q["ms_crop"])
    content.append({"type": "text", "text": f"SOLUTION'S FINAL ANSWERS:\n{answers[:6000]}"})
    return [{"role": "system", "content": ck.VERIFY_SYSTEM}, {"role": "user", "content": content}]


# ── Generating one explanation ───────────────────────────────────────────────

class NeedsVision(Exception):
    """A text model said it cannot answer without the diagram."""


class KeyMismatch(Exception):
    """The explanation disagrees with the official Cambridge answer."""


def available_providers(purpose: str = "site") -> list[str]:
    return ap.configured(purpose)


def route_of(q) -> str:
    try:
        return ck.route(q)
    except Exception as exc:                  # unreadable crop: let a vision model look
        log.debug("q%s route: %s", q["id"], exc)
        return "vision"


def providers_for(route: str, purpose: str = "site", exclude=()) -> list[str]:
    reg = ap.registry()
    return [n for n in ap.configured(purpose)
            if n not in exclude and (reg[n]["vision"] if route == "vision" else reg[n]["text"])]


def attempt(q, name: str, route: str, ms: str | None = None):
    """One provider, one try: (data, usage, model, headers). Raises RateLimited,
    NeedsVision, KeyMismatch (with the reason) or RuntimeError."""
    if route == "text":
        messages = build_text_messages(q, ck.question_text(q), ms if ms is not None else ck.ms_text(q))
    else:
        messages = build_messages(q)
    text, usage, model, headers = ap.call(name, messages)
    if route == "text" and '"needs_diagram"' in (text or "").replace(" ", "") and len(text) < 80:
        raise NeedsVision(model)
    data = parse_text(text)
    if data is None:
        raise KeyMismatch(f"{model}: unusable reply")
    ok, why = ck.check(data, q, ms)
    if not ok:
        raise KeyMismatch(f"{model}: {why}")
    data["check"] = {"route": route, "key": why, "writer": model}
    return data, usage, model, headers


def verify(data: dict, q, route: str, ms: str | None, purpose: str, prefer=()) -> tuple[bool | None, str]:
    """A second model compares the solution's final answers with the official mark
    scheme. MCQ needs no model (the key check is exact). None = nobody free to ask."""
    if config.is_mcq(q["syllabus"], q["paper"]):
        return True, "key letter"
    maths = q["syllabus"] in ck.VISION_SUBJECTS
    ms = ms if ms is not None else ck.ms_text(q)
    if maths or not ms:
        if not q["ms_crop"]:
            return None, "no mark scheme"
        need, messages = "vision", _vision_verify_messages(data, q)
    else:
        need, messages = "text", ck.verify_messages(data, q, ms)
    names = providers_for(need, purpose)
    names = [n for n in prefer if n in names] + [n for n in names if n not in prefer]
    for name in names:
        try:
            text, _u, model, _h = ap.call(name, messages, max_tokens=400, temperature=0)
        except (RateLimited, RuntimeError):
            continue
        verdict = ck.parse_verdict(text)
        if verdict is None:
            continue
        agrees, problem = verdict
        data.setdefault("check", {})["verified_by"] = model
        return agrees, problem or "agrees with the mark scheme"
    return None, "no verifier available"


def generate_one(q, provider: str | None = None, route: str | None = None,
                 purpose: str = "site", check_with_model: bool = True):
    """(data, usage, model, headers) for one question; data None if no provider
    produced an explanation that agrees with the official answer. Raises
    RateLimited when every provider that could do it is rate limited."""
    route = route or route_of(q)
    ms = ck.ms_text(q) if not config.is_mcq(q["syllabus"], q["paper"]) else None
    names = [provider] if provider else providers_for(route, purpose)
    limited = None
    for name in names:
        try:
            data, usage, model, headers = attempt(q, name, route, ms)
        except NeedsVision:
            if route == "text" and not provider:
                return generate_one(q, None, "vision", purpose, check_with_model)
            continue
        except RateLimited as e:
            limited = e
            continue
        except KeyMismatch as e:
            log.info("q%s rejected: %s", q["id"], e)
            continue
        except RuntimeError as e:
            log.warning("q%s %s: %s", q["id"], name, e)
            continue
        if check_with_model:
            agrees, why = verify(data, q, route, ms, purpose, prefer=[n for n in names if n != name])
            if agrees is False:
                log.info("q%s rejected by the verifier: %s", q["id"], why)
                continue
            data["check"]["verdict"] = why if agrees else "not model-verified"
        return data, usage, model, headers
    if limited is not None:
        raise limited
    return None, {}, "", {}


# ── Modes ─────────────────────────────────────────────────────────────────────

def run_probe(_con, _args):
    rows = ap.probe()
    if not rows:
        print("No free AI provider keys in .env yet.")
    for name, status in rows:
        print(f"  {name:11s} {status}")
    missing = [n for n in ap.registry() if n not in ap.configured()]
    if missing:
        print("\nNot configured:", ", ".join(missing))


def run_pilot(con, args):
    import random
    rows = pending(con, args.syllabus, None, args.force)
    random.Random(7).shuffle(rows)
    for q in rows[:args.pilot]:
        route = route_of(q)
        try:
            data, usage, model, _h = generate_one(q, args.provider, route, purpose="drip")
        except RateLimited as e:
            log.warning("q%s: every provider is rate limited (%s)", q["id"], e)
            continue
        if data is None:
            log.warning("q%s (%s): no explanation agreed with the official answer", q["id"], route)
            continue
        store(con, q["id"], data, model, usage)
        log.info("q%s %s %s via %s: %s", q["id"], q["syllabus"], route, model,
                 data.get("check", {}).get("verdict", ""))


DAY = 24 * 3600
MAX_TRIES = 4                       # different providers / routes before giving up this run


class Pacer:
    """One provider's pace: minimum gap, input-token budget per minute, a daily
    share, and a rest after a daily limit. Shared by generation and checking."""

    def __init__(self, name: str, per_day_default: int):
        p = ap.registry()[name]
        self.name, self.p = name, p
        self.per_day = p.get("per_day", per_day_default)
        self.done, self.day0, self.next_ok, self.strikes = 0, time.time(), 0.0, 0

    def ready(self) -> float:
        """Seconds until this provider may be used (0 = now)."""
        now = time.time()
        if now - self.day0 >= DAY:
            self.done, self.day0 = 0, now
        if self.done >= self.per_day:
            return self.day0 + DAY - now
        return max(0.0, self.next_ok - now)

    def used(self, usage: dict | None):
        self.done += 1
        self.strikes = 0
        gap = self.p.get("min_gap", 0)
        itpm = self.p.get("itpm")
        if itpm and usage:
            gap = max(gap, (usage.get("prompt_tokens") or 0) / itpm * 60)
        self.next_ok = time.time() + gap

    def limited(self, e: RateLimited):
        self.strikes += 1
        if e.daily:
            self.next_ok = time.time() + max(e.wait, 3600)
        else:
            self.next_ok = time.time() + (min(e.wait * 2 ** min(self.strikes - 1, 5), 900)
                                          if e.busy else min(e.wait, 300)) + 1


def _drip_worker(name, queues, pacer, args, lock, totals, stop, tries):
    """One provider: takes vision work if it can see, else text work."""
    import queue
    con = db.connect()
    reg = ap.registry()[name]
    order = (["vision", "text"] if reg["vision"] else []) if reg["text"] else ["vision"]
    if reg["text"] and not reg["vision"]:
        order = ["text"]
    try:
        while not stop.is_set():
            wait = pacer.ready()
            if wait > 0:
                if not args.loop and pacer.done >= pacer.per_day:
                    return
                stop.wait(min(wait, 600))
                continue
            item = None
            for r in order:
                try:
                    item = queues[r].get_nowait()
                    break
                except queue.Empty:
                    continue
            if item is None:
                # Nothing routed for us yet: route a fresh one from the backlog.
                try:
                    q = queues["new"].get_nowait()
                except queue.Empty:
                    if all(queues[k].empty() for k in queues):
                        return
                    stop.wait(5)
                    continue
                route = route_of(q)
                if route not in order:
                    queues[route].put((q, route))
                    continue
                item = (q, route)
            q, route = item
            try:
                data, usage, model, _h = attempt(q, name, route)
            except NeedsVision:
                queues["vision"].put((q, "vision"))
                pacer.used(None)
                continue
            except RateLimited as e:
                queues[route].put(item)
                pacer.limited(e)
                log.info("%s: %s", name, e)
                continue
            except (KeyMismatch, RuntimeError) as e:
                pacer.used(None)
                with lock:
                    tries[q["id"]] = tries.get(q["id"], 0) + 1
                    n = tries[q["id"]]
                    totals["rejected"] += 1
                log.info("%s q%s rejected (%d): %s", name, q["id"], n, e)
                if n < MAX_TRIES:
                    # Another provider next time; after two text misses, show it the images.
                    queues["vision" if n >= 2 else route].put((q, "vision" if n >= 2 else route))
                continue
            pacer.used(usage)
            agrees, why = verify(data, q, route, None, "drip", prefer=[name])
            if agrees is False:
                with lock:
                    tries[q["id"]] = tries.get(q["id"], 0) + 1
                    totals["rejected"] += 1
                log.info("%s q%s rejected by the verifier: %s", name, q["id"], why)
                if tries[q["id"]] < MAX_TRIES:
                    queues["vision"].put((q, "vision"))
                continue
            if agrees is None and not config.is_mcq(q["syllabus"], q["paper"]):
                queues[route].put(item)                  # can't confirm yet: later
                stop.wait(30)
                continue
            data["check"]["verdict"] = why
            with lock:
                store(con, q["id"], data, model, usage)
                totals["stored"] += 1
                totals[name] = totals.get(name, 0) + 1
                totals[route] = totals.get(route, 0) + 1
                n = totals["stored"]
            if n % 25 == 0:
                log.info("drip: %d stored (%s)", n, ", ".join(
                    f"{p} {totals.get(p, 0)}" for p in args.providers))
    finally:
        con.close()


def run_drip(con, args):
    """Work through the backlog on every free provider at once, newest papers first."""
    import queue
    import threading
    args.providers = [args.provider] if args.provider else available_providers("drip")
    if not args.providers:
        raise SystemExit("No free AI provider keys in .env (see pipeline/ai_providers.py).")
    queues = {"new": queue.Queue(), "text": queue.Queue(), "vision": queue.Queue()}
    for q in pending(con, args.syllabus, None, args.force):
        # Only questions with an official answer to check against.
        if config.is_mcq(q["syllabus"], q["paper"]) and not q["mcq_answer"]:
            continue
        if not config.is_mcq(q["syllabus"], q["paper"]) and not q["ms_crop"]:
            continue
        queues["new"].put(q)
    log.info("drip: %d pending with an official answer; providers %s%s", queues["new"].qsize(),
             ", ".join(args.providers), " (looping)" if args.loop else "")
    lock, stop = threading.Lock(), threading.Event()
    totals = {"stored": 0, "rejected": 0}
    tries: dict[int, int] = {}
    threads = [threading.Thread(target=_drip_worker, name=p, daemon=True,
                                args=(p, queues, Pacer(p, args.per_day), args, lock, totals, stop, tries))
               for p in args.providers]
    for t in threads:
        t.start()
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("stopping after the current requests...")
        stop.set()
        for t in threads:
            t.join(150)
    log.info("drip: stored %d (%s; text %d, vision %d), rejected %d", totals["stored"],
             ", ".join(f"{p} {totals.get(p, 0)}" for p in args.providers),
             totals.get("text", 0), totals.get("vision", 0), totals["rejected"])


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
    for model, n in con.execute(
            "SELECT model, COUNT(*) FROM question_explanations GROUP BY model ORDER BY 2 DESC"):
        print(f"    {model}: {n:,}")


def main(argv=None):
    ap_ = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = ap_.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pilot", type=int, metavar="N")
    mode.add_argument("--drip", action="store_true")
    mode.add_argument("--stats", action="store_true")
    mode.add_argument("--probe", action="store_true", help="test every configured provider")
    ap_.add_argument("--syllabus")
    ap_.add_argument("--provider", choices=sorted(ap.registry()))
    ap_.add_argument("--per-day", type=int, default=2000,
                     help="max explanations per provider per day (providers may set their own)")
    ap_.add_argument("--loop", action="store_true",
                     help="drip: keep running, resting through each provider's limits")
    ap_.add_argument("--force", action="store_true", help="redo questions already explained")
    args = ap_.parse_args(argv)
    try:                                   # keys live in .env; never override the shell
        from dotenv import load_dotenv
        load_dotenv(config.ROOT / ".env", override=False)
    except ImportError:
        pass
    con = db.connect()
    try:
        if args.probe:
            run_probe(con, args)
        elif args.pilot:
            run_pilot(con, args)
        elif args.drip:
            run_drip(con, args)
        else:
            run_stats(con, args)
    finally:
        con.close()


if __name__ == "__main__":
    main()
