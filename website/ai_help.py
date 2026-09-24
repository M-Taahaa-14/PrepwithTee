"""AI help on a past-paper question: Explain, Guide me, and follow-up questions.

    GET  /api/questions/{qid}/explain          the stored worked solution (pre-generated)
    GET  /api/questions/{qid}/hints?level=1-3  Guide me, one hint at a time
    GET  /api/questions/{qid}/thread           this student's follow-up chat so far
    POST /api/questions/{qid}/ask              a follow-up question (streamed answer)
    POST /api/questions/{qid}/report           "this explanation looks wrong"

Explanations and hints are generated once per question by pipeline/explain.py
and served from the database - no model call when a student opens them.
Follow-ups are live calls (they depend on what the student asks).

Access (tutor, 2026-09-25):
  free     ONE explanation (and can reopen it); hints and follow-ups need a plan
  trial    5 explanations, 20 hints, 20 follow-ups
  paid     explanations + hints unlimited (pre-generated, free to serve);
           follow-ups capped at FOLLOWUP_MONTHLY_CAP per billing period
  staff    unlimited
"""

import json
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

import access as _access
import auth as _auth
import db as _db
import users_db as _udb

router = APIRouter()

FOLLOWUP_MODEL = os.environ.get("FOLLOWUP_MODEL", "claude-opus-5")
FOLLOWUP_MONTHLY_CAP = int(os.environ.get("FOLLOWUP_MONTHLY_CAP", "300"))
TRIAL_LIMITS = {"ai_explain": 5, "ai_hint": 20, "ai_followup": 20}
MAX_HISTORY = 12            # follow-up turns sent back to the model

UPGRADE_URL = "/pricing.html"


# ── Access ────────────────────────────────────────────────────────────────────

def _upgrade(message: str) -> HTTPException:
    return HTTPException(403, {"code": "upgrade_required", "min_plan": "solo",
                               "message": message, "url": UPGRADE_URL})


def _plan_state(user: dict) -> tuple[dict, str, bool]:
    fresh = _udb.get_user(user["id"]) or user
    plan = _access._plan_active(fresh)
    trial = bool(fresh.get("plan_trial")) and plan != "free"
    return fresh, plan, trial


def _used(user: dict, kind: str) -> int:
    start = _access.billing_period_start(user.get("plan_started_at"))
    return _udb.count_usage_this_month(user["id"], kind, start)


def gate_explain(user: dict, qid: int) -> None:
    """Free students get one explanation (reopenable); trial five; paid all."""
    if user.get("role") in ("teacher", "admin"):
        return
    unlocked = _udb.unlocked_explanations(user["id"])
    if qid in unlocked:
        return
    fresh, plan, trial = _plan_state(user)
    if plan == "free" and len(unlocked) >= 1:
        raise _upgrade("You've used your free worked solution. Take a plan to unlock "
                       "explanations for every question, step-by-step hints and follow-up help.")
    if trial and len(unlocked) >= TRIAL_LIMITS["ai_explain"]:
        raise _upgrade("You've used the worked solutions included in your trial. "
                       "Subscribe to keep going.")
    _udb.unlock_explanation(user["id"], qid)


def gate_usage(user: dict, kind: str) -> None:
    """Hints and follow-ups: a plan is required; trials and follow-ups are capped."""
    if user.get("role") in ("teacher", "admin"):
        return
    fresh, plan, trial = _plan_state(user)
    what = "step-by-step hints" if kind == "ai_hint" else "follow-up questions"
    if plan == "free":
        raise _upgrade(f"Take a plan to use {what} on every question.")
    limit = TRIAL_LIMITS[kind] if trial else (
        FOLLOWUP_MONTHLY_CAP if kind == "ai_followup" else None)
    if limit is not None and _used(fresh, kind) >= limit:
        raise HTTPException(429, {"code": "quota_exceeded", "event_type": kind,
                                  "limit": limit, "url": UPGRADE_URL,
                                  "message": f"You've reached this month's limit of {limit} "
                                             f"{what}. It resets with your next billing cycle."})


# ── Data ──────────────────────────────────────────────────────────────────────

def _ensure_table(con) -> None:
    """Local SQLite: the pipeline creates this table; tests may not have run it."""
    if not _db.USE_PG:
        con.execute("""CREATE TABLE IF NOT EXISTS question_explanations (
            question_id INTEGER PRIMARY KEY, content_json TEXT NOT NULL, model TEXT,
            prompt_version INTEGER NOT NULL DEFAULT 1, input_tokens INTEGER,
            output_tokens INTEGER, flagged INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')))""")


def _question(qid: int) -> dict:
    """The question with everything a follow-up needs (crops, MS, chapter)."""
    con = _db.plain_connect()
    try:
        _ensure_table(con)
        row = con.execute(
            """SELECT q.id, q.number, q.sub_part, q.marks, q.crop_path,
                      c.topic, c.subtopic, p.syllabus, p.year, p.session, p.paper, p.variant,
                      m.crop_path AS ms_crop, m.answer AS mcq_answer,
                      e.content_json, e.flagged
               FROM questions q
               JOIN papers p ON p.id = q.paper_id
               LEFT JOIN classifications c ON c.question_id = q.id
               LEFT JOIN question_explanations e ON e.question_id = q.id
               LEFT JOIN papers mp ON mp.syllabus = p.syllabus AND mp.year = p.year
                    AND mp.session = p.session AND mp.paper = p.paper
                    AND mp.variant = p.variant AND mp.kind = 'ms'
               LEFT JOIN ms_entries m ON m.paper_id = mp.id
                    AND m.question_number = q.number AND m.sub_part = q.sub_part
               WHERE q.id = ?""", (qid,)).fetchone()
    finally:
        con.close()
    if row is None:
        raise HTTPException(404, "Question not found")
    q = dict(row)
    raw = q.pop("content_json")
    q["explanation"] = json.loads(raw) if isinstance(raw, str) else raw
    return q


def _need_explanation(q: dict) -> dict:
    if not q["explanation"]:
        raise HTTPException(404, {"code": "not_ready",
                                  "message": "The worked solution for this question is "
                                             "still being prepared. Check back soon."})
    return q["explanation"]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/api/questions/{qid}/explain")
def explain(qid: int, user: dict = Depends(_auth.get_current_user)):
    q = _question(qid)
    data = _need_explanation(q)                  # never spend the free one on nothing
    gate_explain(user, qid)
    out = {k: data.get(k) for k in ("summary", "parts", "mcq_options",
                                    "common_mistakes", "confidence")}
    out["mcq_answer"] = q["mcq_answer"]
    out["has_hints"] = len(data.get("hints") or []) >= 3
    return out


@router.get("/api/questions/{qid}/hints")
def hints(qid: int, level: int = 1, user: dict = Depends(_auth.get_current_user)):
    if not 1 <= level <= 3:
        raise HTTPException(422, "level must be 1, 2 or 3")
    q = _question(qid)
    data = _need_explanation(q)
    gate_usage(user, "ai_hint")
    _access.record_quota(user, "ai_hint")
    return {"level": level, "hints": (data.get("hints") or [])[:level]}


@router.get("/api/questions/{qid}/thread")
def thread(qid: int, user: dict = Depends(_auth.get_current_user)):
    return {"messages": _udb.thread_messages(user["id"], qid)}


class AskReq(BaseModel):
    message: str
    quoted_text: str | None = None

    @field_validator("message")
    @classmethod
    def _msg(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError("Type a question first")
        if len(v) > 2000:
            raise ValueError("Keep it under 2000 characters")
        return v


ASK_SYSTEM = """You are Tee, a friendly expert Cambridge tutor on PrepWithTee. A student \
is working on one past-paper question and asks a follow-up about it. You have the \
question, the official mark scheme and the worked solution they already read.

- Answer exactly what they asked, briefly (usually under 150 words), then stop.
- If they quote part of the solution, explain that part specifically.
- Use LaTeX in $...$ for maths. Use Cambridge wording and units.
- Stay on this question and its topic. If they ask for something unrelated, gently \
bring them back.
- Never contradict the official mark scheme; if something is ambiguous, say so."""


def _context_blocks(q: dict) -> list[dict]:
    from pipeline import config, explain as _ex
    ref = config.source_ref(q["syllabus"], f"{q['paper']}{q['variant']}", q["session"],
                            q["year"], q["number"], q["sub_part"] or "")
    blocks = [{"type": "text", "text": f"Question {ref} - chapter {q.get('topic') or ''}"}]
    blocks += _ex._png_blocks(q["crop_path"])
    if q.get("mcq_answer"):
        blocks.append({"type": "text", "text": f"Official answer: {q['mcq_answer']}"})
    else:
        ms = _ex._png_blocks(q["ms_crop"])
        if ms:
            blocks.append({"type": "text", "text": "Official mark scheme:"})
            blocks += ms
    if q["explanation"]:
        blocks.append({"type": "text", "text": "Worked solution the student read:\n"
                       + json.dumps({k: q["explanation"].get(k) for k in ("summary", "parts")},
                                    ensure_ascii=False)})
    blocks[-1]["cache_control"] = {"type": "ephemeral"}     # stable per question
    return blocks


def _client():
    import anthropic
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(503, "Follow-up help isn't switched on yet.")
    return anthropic.Anthropic()


@router.post("/api/questions/{qid}/ask")
def ask(qid: int, req: AskReq, user: dict = Depends(_auth.get_current_user)):
    q = _question(qid)
    gate_usage(user, "ai_followup")
    client = _client()
    history = _udb.thread_messages(user["id"], qid)[-MAX_HISTORY:]
    msgs = [{"role": "user", "content": _context_blocks(q)},
            {"role": "assistant", "content": "Got it - ask me anything about this question."}]
    for m in history:
        msgs.append({"role": m["role"], "content": m["content"]})
    text = req.message if not req.quoted_text else (
        f'About this part: "{req.quoted_text.strip()[:600]}"\n\n{req.message}')
    msgs.append({"role": "user", "content": text})
    _udb.add_thread_message(user["id"], qid, "user", req.message, req.quoted_text)

    def stream():
        parts = []
        try:
            with client.messages.stream(model=FOLLOWUP_MODEL, max_tokens=2000,
                                        system=ASK_SYSTEM, messages=msgs,
                                        output_config={"effort": "low"}) as s:
                for chunk in s.text_stream:
                    parts.append(chunk)
                    yield chunk
            answer = "".join(parts).strip()
            if answer:
                _udb.add_thread_message(user["id"], qid, "assistant", answer)
                _access.record_quota(user, "ai_followup")
        except Exception as exc:                  # show it, never hang the panel
            print(f"[ask q{qid}] {exc}", flush=True)
            yield "\n\n_Sorry - that didn't go through. Please try again._"

    return StreamingResponse(stream(), media_type="text/plain; charset=utf-8",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


class ReportReq(BaseModel):
    reason: str | None = None


@router.post("/api/questions/{qid}/report")
def report(qid: int, req: ReportReq, user: dict = Depends(_auth.get_current_user)):
    _question(qid)
    _udb.report_explanation(user["id"], qid, req.reason)
    con = _db.plain_connect()
    try:
        _ensure_table(con)
        con.execute("UPDATE question_explanations SET flagged = flagged + 1 WHERE question_id = ?",
                    (qid,))
        con.commit()
    finally:
        con.close()
    return {"ok": True}
