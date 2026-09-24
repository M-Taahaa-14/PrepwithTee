"""Stage: AI worked solutions + Guide-me hints, generated once per question.

    python -m pipeline.explain --estimate                       # projected cost, no API spend on output
    python -m pipeline.explain --pilot 5 --syllabus 0625        # a few live calls, printed + stored
    python -m pipeline.explain --submit [--syllabus 5054] [--limit N]   # Batch API (50% price)
    python -m pipeline.explain --status                         # batch progress
    python -m pipeline.explain --collect                        # store finished batch results

Tutor's decision (2026-09-25): generate for EVERY question in advance, once,
and serve the stored result to every student instantly. One call per
question produces everything the viewer's AI panel shows:

    parts[]          worked solution per sub-part (steps, answer, how marks are given)
    hints[3]         Guide me: what is asked -> first step -> next step
    mcq_options[]    MCQ only: why each option is right or wrong
    common_mistakes  misconceptions examiners report

The model sees the question crop and the OFFICIAL mark-scheme crop (or the MCQ
answer letter), so the explanation must arrive at Cambridge's answer; when it
can't, it says so in `confidence` rather than overriding the mark scheme.

Model: EXPLAIN_MODEL env or --model (default claude-opus-5). The key comes
from ANTHROPIC_API_KEY. Results go to question_explanations in the pipeline DB
(index.db); scripts/sync_explanations_to_supabase.py pushes them live.
"""

import argparse
import base64
import json
import os
import random
import time
from pathlib import Path

import fitz

from . import config, db, setup_logging

log = setup_logging("explain")

PROMPT_VERSION = 1
DEFAULT_MODEL = os.environ.get("EXPLAIN_MODEL", "claude-opus-5")
DEFAULT_EFFORT = os.environ.get("EXPLAIN_EFFORT", "medium")
MAX_TOKENS = 8000
RENDER_DPI = 110
MAX_IMAGES = 4                     # per side (question / mark scheme)
BATCH_CHUNK = 800                  # requests per batch (images make them large)
MANIFEST = config.DATA_DIR / "batches" / "explain_batches.json"

# $ per 1M tokens (input, output) - claude-api skill table, cached 2026-06-24.
# The Batch API is half of these.
PRICES = {"claude-opus-5": (5.00, 25.00), "claude-sonnet-5": (2.00, 10.00),
          "claude-haiku-4-5": (1.00, 5.00), "claude-opus-5-5": (4.00, 20.00)}

SYSTEM = """You are Tee, an expert Cambridge O Level / IGCSE / A Level tutor in Lahore. \
You write the worked solution a strong student would want after attempting a past-paper \
question, for the PrepWithTee study site.

You are given the question as image(s), its syllabus chapter, and the OFFICIAL Cambridge \
mark scheme (as image(s), or the correct option letter for multiple choice).

Rules:
- Arrive at the mark scheme's answer. The mark scheme is authoritative. If you genuinely \
think it is wrong or ambiguous, still explain its answer and set confidence to "low".
- Explain every sub-part in order ((a), (b)(i), ...). Each step is short: what to do and why, \
then the working. Use the method and wording Cambridge credits (command words, units, \
significant figures, key phrases the mark scheme lists).
- Maths and physics notation: LaTeX inside $...$ for inline and $$...$$ for display. Keep \
units in \\mathrm{}. Never put LaTeX in titles.
- "marking" says how the marks are earned for that part (e.g. "M1 for substituting into \
v = u + at, A1 for 14 m/s"), in plain words a student understands.
- hints: exactly three, increasingly specific, WITHOUT giving the final answer: \
1) what the question is really asking / which idea it tests, 2) the first step to take, \
3) the next step with a check the student can do themselves.
- mcq_options: for multiple choice only, one entry per option A-D saying why it is right \
or the misconception that makes it tempting-but-wrong. Empty for structured questions.
- common_mistakes: up to 3 real, specific mistakes students make on this question.
- Write clearly for a 15-17 year old. No filler, no greetings, no mention of being an AI.
- If an image is unreadable or the question needs a figure you cannot see, do your best \
and set confidence to "low"."""

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["summary", "parts", "hints", "mcq_options", "common_mistakes", "confidence"],
    "properties": {
        "summary": {"type": "string",
                    "description": "One or two sentences: what the question tests."},
        "parts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["label", "steps", "answer", "marking"],
            "properties": {
                "label": {"type": "string", "description": "e.g. (a)(i); empty if one part"},
                "steps": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["title", "body"],
                    "properties": {"title": {"type": "string"},
                                   "body": {"type": "string"}}}},
                "answer": {"type": "string"},
                "marking": {"type": "string"}}}},
        "hints": {"type": "array", "items": {"type": "string"}},
        "mcq_options": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["letter", "correct", "why"],
            "properties": {"letter": {"type": "string"},
                           "correct": {"type": "boolean"},
                           "why": {"type": "string"}}}},
        "common_mistakes": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
}


# ── Inputs ────────────────────────────────────────────────────────────────────

def _png_blocks(pdf_path: str | None) -> list[dict]:
    """Render a crop PDF to base64 PNG image blocks (one per page, capped)."""
    if not pdf_path:
        return []
    path = config.ROOT / str(pdf_path).replace("\\", "/")
    if not path.exists():
        return []
    out = []
    with fitz.open(path) as doc:
        for page in list(doc)[:MAX_IMAGES]:
            png = page.get_pixmap(dpi=RENDER_DPI).tobytes("png")
            out.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/png",
                "data": base64.standard_b64encode(png).decode()}})
    return out


def pending(con, syllabus=None, limit=None, force=False):
    """Questions still needing an explanation at the current prompt version."""
    where = ["p.kind = 'qp'", "q.status IS NOT 'excluded'", "q.crop_path IS NOT NULL"]
    params: list = []
    if syllabus:
        where.append("p.syllabus = ?")
        params.append(syllabus)
    if not force:
        where.append("(e.question_id IS NULL OR e.prompt_version < ?)")
        params.append(PROMPT_VERSION)
    sql = f"""
        SELECT q.id, q.number, q.sub_part, q.marks, q.crop_path,
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
             AND m.sub_part = q.sub_part
        WHERE {' AND '.join(where)}
        ORDER BY p.year DESC, p.syllabus, q.id"""
    if limit:
        sql += f" LIMIT {int(limit)}"
    return con.execute(sql, params).fetchall()


def build_params(q, model: str, effort: str) -> dict:
    """Messages API params for one question (shared by pilot and batch)."""
    syl, paper = q["syllabus"], q["paper"]
    mcq = config.is_mcq(syl, paper)
    ref = config.source_ref(syl, f"{paper}{q['variant']}", q["session"], q["year"],
                            q["number"], q["sub_part"] or "")
    subject = _subject(syl)
    header = (f"Subject: {subject} ({syl})\nSource: {ref}\nChapter: {q['topic']}"
              + (f"\nSubtopic: {q['subtopic']}" if q["subtopic"] else "")
              + (f"\nMarks: {q['marks']}" if q["marks"] else "")
              + f"\nType: {'multiple choice' if mcq else 'structured'}")
    content: list[dict] = [{"type": "text", "text": header + "\n\nQUESTION:"}]
    content += _png_blocks(q["crop_path"])
    if mcq and q["mcq_answer"]:
        content.append({"type": "text",
                        "text": f"OFFICIAL MARK SCHEME: the correct option is {q['mcq_answer']}."})
    else:
        ms = _png_blocks(q["ms_crop"])
        if ms:
            content.append({"type": "text", "text": "OFFICIAL MARK SCHEME:"})
            content += ms
        else:
            content.append({"type": "text", "text": "OFFICIAL MARK SCHEME: not available - "
                            "solve it carefully yourself and set confidence accordingly."})
    content.append({"type": "text", "text": "Write the explanation now."})
    return {
        "model": model, "max_tokens": MAX_TOKENS,
        "system": [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": content}],
        "output_config": {"effort": effort,
                          "format": {"type": "json_schema", "schema": SCHEMA}},
    }


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

def parse_message(msg) -> dict | None:
    """The JSON explanation from a response, or None if unusable."""
    if getattr(msg, "stop_reason", None) in ("refusal", "max_tokens"):
        return None
    text = next((b.text for b in msg.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not data.get("parts") or len(data.get("hints") or []) < 3:
        return None
    data["hints"] = data["hints"][:3]
    return data


def store(con, qid: int, data: dict, model: str, usage) -> None:
    con.execute(
        """INSERT INTO question_explanations
               (question_id, content_json, model, prompt_version, input_tokens, output_tokens)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(question_id) DO UPDATE SET
               content_json = excluded.content_json, model = excluded.model,
               prompt_version = excluded.prompt_version,
               input_tokens = excluded.input_tokens, output_tokens = excluded.output_tokens,
               flagged = 0, created_at = datetime('now')""",
        (qid, json.dumps(data, ensure_ascii=False), model, PROMPT_VERSION,
         _in_tokens(usage), getattr(usage, "output_tokens", None)))
    con.commit()


def _in_tokens(usage) -> int | None:
    if usage is None:
        return None
    return ((usage.input_tokens or 0) + (getattr(usage, "cache_read_input_tokens", 0) or 0)
            + (getattr(usage, "cache_creation_input_tokens", 0) or 0))


def cost(model: str, tokens_in: float, tokens_out: float, batch: bool) -> float:
    pin, pout = PRICES.get(model, PRICES["claude-opus-5"])
    usd = (tokens_in * pin + tokens_out * pout) / 1e6
    return usd / 2 if batch else usd


# ── Modes ─────────────────────────────────────────────────────────────────────

def _client():
    import anthropic                     # lazy: the rest of the pipeline is keyless
    return anthropic.Anthropic()


def run_pilot(con, args):
    client = _client()
    rows = pending(con, args.syllabus, None, args.force)
    random.Random(7).shuffle(rows)
    rows = rows[:args.pilot]
    tin = tout = 0
    for q in rows:
        params = build_params(q, args.model, args.effort)
        msg = client.messages.create(**params)
        data = parse_message(msg)
        tin += _in_tokens(msg.usage) or 0
        tout += msg.usage.output_tokens or 0
        if data is None:
            log.warning("q%s: unusable response (%s)", q["id"], msg.stop_reason)
            continue
        store(con, q["id"], data, args.model, msg.usage)
        log.info("q%s %s: %d parts, confidence %s, %d in / %d out tokens",
                 q["id"], q["syllabus"], len(data["parts"]), data["confidence"],
                 _in_tokens(msg.usage), msg.usage.output_tokens)
    if rows:
        n = len(rows)
        log.info("pilot: %d questions, avg %.0f in / %.0f out tokens, "
                 "%.4f USD each at full price", n, tin / n, tout / n,
                 cost(args.model, tin / n, tout / n, batch=False))


def run_estimate(con, args):
    client = _client()
    rows = pending(con, args.syllabus, None, args.force)
    total = len(rows)
    sample = random.Random(3).sample(rows, min(25, total))
    counted = []
    for q in sample:
        p = build_params(q, args.model, args.effort)
        r = client.messages.count_tokens(model=p["model"], system=p["system"],
                                         messages=p["messages"],
                                         output_config=p["output_config"])
        counted.append(r.input_tokens)
    avg_in = sum(counted) / max(1, len(counted))
    done = con.execute("SELECT AVG(output_tokens) FROM question_explanations "
                       "WHERE output_tokens IS NOT NULL").fetchone()[0]
    avg_out = done or 1800.0
    print(f"{total:,} questions to explain; sampled {len(counted)} -> avg {avg_in:,.0f} input "
          f"tokens, {avg_out:,.0f} output tokens"
          f"{' (measured from pilot)' if done else ' (assumed - run --pilot for a real number)'}")
    for m in PRICES:
        print(f"  {m:18} batch: ${cost(m, avg_in * total, avg_out * total, True):>9,.0f}"
              f"   (standard ${cost(m, avg_in * total, avg_out * total, False):,.0f})")


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text("utf-8")) if MANIFEST.exists() else {"batches": []}


def _save_manifest(m: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(m, indent=1), "utf-8")


def run_submit(con, args):
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    client = _client()
    rows = pending(con, args.syllabus, args.limit, args.force)
    queued = {cid for b in _manifest()["batches"] if not b.get("collected")
              for cid in b["ids"]}
    rows = [q for q in rows if f"q{q['id']}" not in queued]
    man = _manifest()
    for i in range(0, len(rows), BATCH_CHUNK):
        chunk = rows[i:i + BATCH_CHUNK]
        reqs = [Request(custom_id=f"q{q['id']}",
                        params=MessageCreateParamsNonStreaming(**build_params(q, args.model, args.effort)))
                for q in chunk]
        batch = client.messages.batches.create(requests=reqs)
        man["batches"].append({"id": batch.id, "model": args.model, "created": time.time(),
                               "ids": [f"q{q['id']}" for q in chunk], "collected": False})
        _save_manifest(man)
        log.info("submitted batch %s with %d questions", batch.id, len(chunk))


def run_status(_con, _args):
    client = _client()
    for b in _manifest()["batches"]:
        if b.get("collected"):
            continue
        s = client.messages.batches.retrieve(b["id"])
        c = s.request_counts
        print(f"{b['id']}  {s.processing_status:12} ok {c.succeeded}  err {c.errored}  "
              f"running {c.processing}  ({len(b['ids'])} questions)")


def run_collect(con, _args):
    client = _client()
    man = _manifest()
    for b in man["batches"]:
        if b.get("collected"):
            continue
        s = client.messages.batches.retrieve(b["id"])
        if s.processing_status != "ended":
            log.info("%s still %s", b["id"], s.processing_status)
            continue
        ok = bad = 0
        for res in client.messages.batches.results(b["id"]):
            qid = int(res.custom_id[1:])
            if res.result.type != "succeeded":
                bad += 1
                continue
            data = parse_message(res.result.message)
            if data is None:
                bad += 1
                continue
            store(con, qid, data, b["model"], res.result.message.usage)
            ok += 1
        b["collected"] = True
        b["ok"], b["failed"] = ok, bad
        _save_manifest(man)
        log.info("%s: stored %d, failed %d (failed ones stay pending for the next --submit)",
                 b["id"], ok, bad)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pilot", type=int, metavar="N")
    mode.add_argument("--estimate", action="store_true")
    mode.add_argument("--submit", action="store_true")
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--collect", action="store_true")
    ap.add_argument("--syllabus")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--effort", default=DEFAULT_EFFORT,
                    choices=("low", "medium", "high", "xhigh", "max"))
    ap.add_argument("--force", action="store_true", help="redo questions already explained")
    args = ap.parse_args(argv)
    con = db.connect()
    try:
        {"pilot": run_pilot, "estimate": run_estimate, "submit": run_submit,
         "status": run_status, "collect": run_collect}[
            next(k for k in ("pilot", "estimate", "submit", "status", "collect")
                 if getattr(args, k))](con, args)
    finally:
        con.close()


if __name__ == "__main__":
    main()
