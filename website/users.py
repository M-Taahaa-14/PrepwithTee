"""User-facing API routes: profile, enrollment, progress, quiz, dashboard, teachers."""

import json
import re
import threading
from pathlib import Path
from typing import Annotated

import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel

from auth import get_current_user, maybe_user
import users_db as _udb
from access import check_quota, require_plan, _plan_active, MONTHLY_QUOTAS

router = APIRouter()

_CurrentUser = Annotated[dict, Depends(get_current_user)]
_MaybeUser = Annotated[dict | None, Depends(maybe_user)]

SUBJECT_NAMES = {
    "4024": "O Level Mathematics D",
    "0580": "IGCSE Mathematics",
    "5054": "O Level Physics",
    "0625": "IGCSE Physics",
    "2210": "O Level Computer Science",
    "0478": "IGCSE Computer Science",
    "5070": "O Level Chemistry",
    "0620": "IGCSE Chemistry",
    "9709": "A Level Mathematics",
    "9702": "A Level Physics",
    "9618": "A Level Computer Science",
}


# ── Profile ────────────────────────────────────────────────────────────────────

class ProfileUpdate(BaseModel):
    grade: str | None = None
    birthday: str | None = None
    gender: str | None = None
    phone: str | None = None
    name: str | None = None


# ── Onboarding flags ───────────────────────────────────────────────────────────

class FlagUpdate(BaseModel):
    key: str
    value: bool = True

class PersonaUpdate(BaseModel):
    persona: str  # student | teacher | parent


@router.post("/api/profile/persona")
def save_persona(req: PersonaUpdate, user: _CurrentUser):
    allowed = {"student", "teacher", "parent"}
    if req.persona not in allowed:
        raise HTTPException(400, f"persona must be one of: {', '.join(allowed)}")
    _udb.update_profile(user["id"], {"persona": req.persona})
    return {"ok": True, "persona": req.persona}


@router.patch("/api/flags")
def patch_flag(req: FlagUpdate, user: _CurrentUser):
    if not re.match(r'^[a-z][a-z0-9_]{1,63}$', req.key):
        raise HTTPException(400, "Invalid flag key")
    try:
        _udb.merge_flags(user["id"], req.key, req.value)
    except Exception:
        # Gracefully ignore DB errors (e.g. column not yet migrated in Supabase).
        # The client localStorage cache still holds the flag optimistically.
        return {"ok": False, "reason": "db_unavailable"}
    return {"ok": True}

def _normalize_grade(g: str | None) -> str:
    if not g:
        return ""
    gl = g.lower().strip()
    if "a level" in gl:
        return "A Level"
    if "igcse" in gl:
        return "IGCSE"
    if "o level" in gl:
        return "O Level"
    return g.strip()


@router.post("/api/profile")
@router.patch("/api/profile")
def save_profile(req: ProfileUpdate, user: _CurrentUser,
                 response: __import__("fastapi").Response):
    updates: dict = {}
    old_grade = _normalize_grade(user.get("grade"))
    for field in ("grade", "birthday", "gender", "phone", "name"):
        v = getattr(req, field)
        if v is not None:
            val = v.strip() if isinstance(v, str) else v
            if field == "grade":
                val = _normalize_grade(val)
            updates[field] = val

    # If grade changes, archive current active enrollments
    new_grade = updates.get("grade")
    if new_grade and old_grade and new_grade != old_grade:
        # Students may study on several boards (student_boards, picked on the
        # profile / papers pages); `grade` is only their MAIN board. So keep every
        # subject whose board is still one of theirs, archive the rest, and bring
        # back archived subjects of those boards. Without saved boards: the old
        # single-board rule (archive everything, restore the new board's).
        try:
            saved, _primary = _udb.get_boards(user["id"])
        except Exception:
            saved = []
        slug_names = {"o-level": "o level", "igcse": "igcse", "a-level": "a level"}
        keep = {slug_names[b] for b in saved if b in slug_names} | {new_grade.lower()}

        def on_kept_board(syl: str) -> bool:
            board_name = _udb.BOARDS_MAP.get(syl, ("", ""))[0].lower()
            return any(k in board_name for k in keep)

        if saved:
            for s in _udb.get_enrollments(user["id"]):
                if not on_kept_board(s):
                    _udb.unenroll(user["id"], s)
        else:
            _udb.archive_all_enrollments(user["id"])
        # bring back what they had on the NEW main board (only that one - an
        # archived subject on another kept board may have been removed on purpose)
        for s in _udb.get_archived_enrollments(user["id"]):
            if new_grade.lower() in _udb.BOARDS_MAP.get(s, ("", ""))[0].lower():
                _udb.restore_enrollment(user["id"], s)

    # Mark profile complete only when the student has BOTH a grade AND at least one subject enrolled.
    # Never demote an already-complete profile.
    has_grade = bool(updates.get("grade") or user.get("grade"))
    if has_grade and not user.get("profile_complete"):
        if _udb.get_enrollments(user["id"]):
            updates["profile_complete"] = 1

    if not updates:
        return {k: v for k, v in user.items() if k != "password_hash"}

    updated = _udb.update_profile(user["id"], updates)
    import auth as _auth_mod
    _auth_mod._set_cookie(response, updated["id"], updated)
    return {k: v for k, v in updated.items() if k != "password_hash"}


# ── Account deletion ──────────────────────────────────────────────────────────

class DeleteAccountReq(BaseModel):
    confirm: str  # must equal "DELETE"

@router.delete("/api/account")
def delete_account(
    req: DeleteAccountReq,
    response: Response,
    user: _CurrentUser,
):
    if req.confirm != "DELETE":
        raise HTTPException(400, "Send confirm='DELETE' to delete your account")
    _udb.delete_user(user["id"])
    # Clear the session cookie
    import auth as _auth_mod
    response.delete_cookie("session", httponly=True, samesite="lax")
    return {"ok": True}


# ── Change password ───────────────────────────────────────────────────────────

class ChangePasswordReq(BaseModel):
    current_password: str
    new_password: str

@router.post("/api/auth/change-password")
def change_password(req: ChangePasswordReq, user: _CurrentUser):
    import auth as _auth_mod

    # Google-only accounts have no password hash
    full = _udb.get_user(user["id"])
    if not full or not full.get("password_hash"):
        raise HTTPException(400, "Your account uses Google sign-in — no password to change")

    if not _auth_mod.verify_password(req.current_password, full["password_hash"]):
        raise HTTPException(401, "Current password is incorrect")

    _auth_mod._validate_password(req.new_password)
    new_hash = _auth_mod.hash_password(req.new_password)
    _udb.update_profile(user["id"], {"password_hash": new_hash})
    return {"ok": True}


# ── Enrollment ─────────────────────────────────────────────────────────────────

@router.get("/api/enrollments")
def list_enrollments(user: _CurrentUser):
    syllabuses = _udb.get_enrollments(user["id"])
    archived = _udb.get_archived_enrollments(user["id"])
    return {
        "enrollments": [
            {"syllabus": s, "name": SUBJECT_NAMES.get(s, s)}
            for s in syllabuses
        ],
        "archived": [
            {"syllabus": s, "name": SUBJECT_NAMES.get(s, s)}
            for s in archived
        ]
    }


@router.get("/api/enrollments/archived")
def list_archived_enrollments(user: _CurrentUser):
    archived = _udb.get_archived_enrollments(user["id"])
    return {
        "archived": [
            {"syllabus": s, "name": SUBJECT_NAMES.get(s, s)}
            for s in archived
        ]
    }


class EnrollReq(BaseModel):
    syllabus: str

@router.post("/api/enrollments")
def enroll(req: EnrollReq, user: _CurrentUser, response: Response):
    if not re.match(r"^[0-9A-Za-z]{4,6}$", req.syllabus):
        raise HTTPException(400, "Invalid syllabus code")
    _udb.enroll(user["id"], req.syllabus)
    # If this is the first enrollment and the user already has a grade, complete their profile now.
    if user.get("grade") and not user.get("profile_complete"):
        updated = _udb.update_profile(user["id"], {"profile_complete": 1})
        import auth as _auth_mod
        _auth_mod._set_cookie(response, user["id"], updated)
    return {"status": "enrolled", "syllabus": req.syllabus}


@router.post("/api/enrollments/restore")
@router.post("/api/enrollments/{syllabus}/restore")
def restore_enrollment_route(user: _CurrentUser, req: EnrollReq | None = None, syllabus: str | None = None):
    code = (syllabus or (req.syllabus if req else "")).strip()
    if not code:
        raise HTTPException(400, "Syllabus code required")
    _udb.restore_enrollment(user["id"], code)
    return {"status": "restored", "syllabus": code}


@router.delete("/api/enrollments/{syllabus}")
def unenroll(syllabus: str, user: _CurrentUser):
    _udb.unenroll(user["id"], syllabus)
    return {"status": "unenrolled", "syllabus": syllabus}


# ── Topic progress ─────────────────────────────────────────────────────────────

@router.get("/api/progress")
def get_progress(syllabus: str, user: _CurrentUser):
    rows = _udb.get_progress(user["id"], syllabus)
    return {"progress": rows}


@router.get("/api/student-progress/{student_id}")
def get_student_progress(student_id: str, user: _CurrentUser):
    """Parent-accessible: return all topic progress for a linked child."""
    role = user.get("role", "student")
    # Admins and teachers can view any student; parents only their linked children
    if role not in ("admin", "teacher"):
        if role != "parent":
            raise HTTPException(403, "Access denied")
        if not _udb.parent_link_exists(user["id"], student_id):
            raise HTTPException(403, "Not linked to this student")
    rows = _udb.get_all_progress_for_user(student_id)
    return {"progress": rows}


class ProgressUpdate(BaseModel):
    syllabus: str
    topic: str
    subtopic: str | None = None
    status: str | None = None          # how well they know it
    papers_status: str | None = None   # whether they've drilled its past papers

@router.post("/api/progress")
def update_progress(req: ProgressUpdate, user: _CurrentUser):
    allowed = {"not_started", "learning", "confident"}
    for field, value in (("status", req.status), ("papers_status", req.papers_status)):
        if value is not None and value not in allowed:
            raise HTTPException(400, f"{field} must be one of: {', '.join(sorted(allowed))}")
    if req.status is None and req.papers_status is None:
        raise HTTPException(400, "Send status, papers_status, or both")

    # Free plan: allow tracking for exactly 1 subject (the first enrolled one).
    # Pro+ can track all subjects.
    if _plan_active(user) == "free":
        enrolled = _udb.get_enrollments(user["id"])
        first = enrolled[0] if enrolled else req.syllabus
        if req.syllabus != first:
            raise HTTPException(
                403,
                detail={
                    "code": "upgrade_required",
                    "current_plan": "free",
                    "min_plan": "pro",
                    "message": (
                        "Free plan includes chapter tracking for 1 subject. "
                        "Upgrade to Pro to track all your subjects."
                    ),
                },
            )

    return _udb.upsert_progress(
        user["id"], req.syllabus, req.topic, req.subtopic,
        req.status, req.papers_status,
    )


# ── Quiz ───────────────────────────────────────────────────────────────────────

_SUBJECT_FULL = {
    "4024": "O Level Mathematics D (4024)",
    "0580": "IGCSE Mathematics (0580)",
    "5054": "O Level Physics (5054)",
    "0625": "IGCSE Physics (0625)",
    "2210": "O Level Computer Science (2210)",
    "0478": "IGCSE Computer Science (0478)",
    "9709": "A Level Mathematics (9709)",
    "9702": "A Level Physics (9702)",
    "9618": "A Level Computer Science (9618)",
}


def _chat(messages, max_tokens=800):
    """Reuse the provider chain from app.py.

    On failure _chat_complete returns (None, diagnostic); the diagnostic names
    env vars and provider errors, so it goes to the log, never to the student.
    """
    from app import _chat_complete
    text, info = _chat_complete(messages, max_tokens=max_tokens)
    if text is None:
        print(f"[quiz] no AI response: {info}", flush=True)
        raise HTTPException(
            503, "Practice questions are unavailable right now — try again shortly.")
    return text, info


# Topics whose questions are meaningless without a figure - a scale drawing, a
# circuit, a velocity-time graph. A text model cannot draw one, so for these we
# serve a real past-paper crop instead of inventing a question that references
# a diagram the student cannot see.
_NEEDS_FIGURE = re.compile(
    r"trigonometr|vector|mensuration|geometr|transformation|bearing|loci|"
    r"construction|graph|circuit|electric|magnet|motor|transformer|wave|"
    r"ray|lens|optic|force|moment|kinematic|momentum|energy|thermal|"
    r"logic|flowchart|pseudocode|network|topolog",
    re.I)


def _wants_figure(topic: str, subtopic: str | None) -> bool:
    return bool(_NEEDS_FIGURE.search(f"{topic} {subtopic or ''}"))


def _past_paper_question(syllabus: str, topic: str, subtopic: str | None) -> dict | None:
    """Pick one real classified question for this topic, newest sessions first.

    Returns the metadata the panel needs to render the original vector crop;
    the crop itself is served by /api/question/{id}/preview.
    """
    from app import _con, _SESSION_ABBR, _USE_PG
    con = _con()
    con.row_factory = __import__("sqlite3").Row
    rnd = "random()" if _USE_PG else "RANDOM()"
    sub_clause = "AND c.subtopic = ?" if subtopic else ""
    params = [syllabus, topic, topic] + ([subtopic] if subtopic else [])
    try:
        row = con.execute(
            f"""SELECT q.id, q.number, q.sub_part, q.marks,
                       p.syllabus, p.year, p.session, p.paper, p.variant
                FROM classifications c
                JOIN questions q ON q.id = c.question_id
                JOIN papers p ON p.id = q.paper_id
                WHERE p.syllabus = ? AND (c.topic = ? OR c.secondary_topic = ?)
                  {sub_clause}
                  AND q.crop_path IS NOT NULL
                  AND q.status IS NOT 'excluded'
                ORDER BY {rnd} LIMIT 1""", params).fetchone()
    except Exception as exc:
        print(f"[quiz] past-paper lookup failed: {exc}", flush=True)
        return None
    finally:
        con.close()
    if row is None:
        return None

    sa = _SESSION_ABBR.get(row["session"], row["session"].upper())
    part = f"({row['sub_part']})" if row["sub_part"] else ""
    return {
        "question_id": row["id"],
        "ref": (f"{row['syllabus']}/P{row['paper']}{row['variant']} "
                f"{sa} {row['year']} Q{row['number']}{part}"),
        "marks": row["marks"],
        "image_url": f"/api/question/{row['id']}/preview",
        "ms_url": f"/api/question/{row['id']}/ms-preview",
    }


class QuizGenReq(BaseModel):
    syllabus: str
    topic: str
    subtopic: str | None = None
    # auto: past paper when the topic needs a figure, otherwise AI-written
    mode: str = "auto"


@router.post("/api/quiz/generate")
def quiz_generate(req: QuizGenReq, user: _CurrentUser,
                  _plan: dict = Depends(require_plan("pro"))):
    check_quota(user, "ai_quiz")
    subject = _SUBJECT_FULL.get(req.syllabus, req.syllabus)
    topic_label = req.topic + (f" — {req.subtopic}" if req.subtopic else "")

    wants_pp = req.mode == "past_paper" or (
        req.mode == "auto" and _wants_figure(req.topic, req.subtopic))
    if wants_pp:
        pp = _past_paper_question(req.syllabus, req.topic, req.subtopic)
        if pp:
            return {"mode": "past_paper", "syllabus": req.syllabus,
                    "topic": req.topic, "subtopic": req.subtopic, **pp}
        if req.mode == "past_paper":
            raise HTTPException(
                404, "No past-paper question is available for this chapter yet.")
        # auto mode: fall through to an AI question rather than dead-ending

    # Ground the model in genuine Cambridge phrasing for this exact topic.
    samples = ""
    try:
        from app import _topic_samples
        samples = _topic_samples(req.syllabus, req.topic, k=3)
    except Exception:
        pass
    sample_block = (
        "\nReal Cambridge questions on this topic, for style and difficulty "
        "(do not copy them):\n" + samples + "\n" if samples else "")

    system = (
        f"You are a Cambridge examiner writing a question for {subject}.\n"
        f"Write ONE structured question on: \"{topic_label}\".\n"
        f"{sample_block}\n"
        "Follow the real paper's conventions:\n"
        "- Split it into parts (a), (b), (c); use (i)/(ii) only where a part "
        "genuinely subdivides.\n"
        "- Each part carries its own mark allocation, 1-4 marks, 5-9 in total.\n"
        "- Open every part with a Cambridge command word: State, Describe, "
        "Explain, Calculate, Determine, Show that, Suggest, Complete.\n"
        "- Marks must rise with demand: recall parts first, then application.\n"
        "- Use SI units and the notation the syllabus uses.\n"
        "- NEVER refer to a figure, diagram, graph, circuit or table - the "
        "student sees only your text. Give any data in words instead.\n"
        "- Write maths as plain Unicode exactly as it appears in the printed "
        "paper: x², x³, √, π, ±, ≤, ≥, ×, ÷, °, ½. NEVER use LaTeX ($...$, "
        "\\frac, \\sqrt), markdown, or caret notation like x^2. Write "
        "fractions inline, e.g. (-b ± √(b² - 4ac)) / 2a.\n\n"
        "Output ONLY valid JSON, no prose, no code fence:\n"
        '{"stem": "optional scene-setting sentence, may be empty", '
        '"parts": [{"label": "(a)", "text": "...", "marks": 2, '
        '"scheme": "the marking points for this part"}], "total_marks": N}'
    )

    text, _ = _chat([
        {"role": "system", "content": system},
        {"role": "user", "content": f"Write the question on {topic_label}."},
    ], max_tokens=900)

    try:
        clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        data = json.loads(clean)
        parts = data.get("parts") or []
        if not parts:
            raise ValueError("no parts")
        total = data.get("total_marks") or sum(p.get("marks") or 0 for p in parts)
        for p in parts:
            p["text"] = _plain_math(p.get("text"))
            p["scheme"] = _plain_math(p.get("scheme"))
        stem = _plain_math(data.get("stem"))
        scheme = "\n".join(
            f"{p.get('label','')} {p.get('scheme','')}".strip() for p in parts)
        return {
            "mode": "ai",
            "stem": stem,
            "parts": [{"label": p.get("label", ""), "text": p.get("text", ""),
                       "marks": p.get("marks")} for p in parts],
            "marks": total,
            "mark_scheme": scheme,
            "question": _flatten(stem, parts),
            "syllabus": req.syllabus, "topic": req.topic, "subtopic": req.subtopic,
        }
    except Exception:
        # Model ignored the schema; show its text rather than an error.
        return {"mode": "ai", "stem": "", "parts": [],
                "question": text.strip(), "marks": None, "mark_scheme": None,
                "syllabus": req.syllabus, "topic": req.topic,
                "subtopic": req.subtopic}


def _plain_math(s: str | None) -> str:
    """Printed-paper notation. One shared implementation lives in app.py so the
    tutor, the solver and the quiz can never drift apart on formatting."""
    from app import _plain_math as impl
    return impl(s)


def _flatten(stem: str | None, parts: list) -> str:
    """Plain-text form of the question, for marking and the history record."""
    out = [stem.strip()] if stem else []
    for p in parts:
        marks = f" [{p.get('marks')}]" if p.get("marks") else ""
        out.append(f"{p.get('label','')} {p.get('text','')}{marks}".strip())
    return "\n".join(out)


class QuizEvalReq(BaseModel):
    syllabus: str
    topic: str
    subtopic: str | None = None
    question: str = ""
    mark_scheme: str | None = None
    answer: str
    marks: int | None = None
    # past-paper mode: the official scheme is an image, so it is revealed
    # rather than fed to the model
    question_id: int | None = None


@router.post("/api/quiz/evaluate")
def quiz_evaluate(req: QuizEvalReq, user: _CurrentUser,
                  _plan: dict = Depends(require_plan("pro"))):
    if not (req.answer or "").strip():
        raise HTTPException(400, "Write your answer before submitting")

    question_text = req.question
    # Past-paper mode sends only an id: the student read the question from the
    # original crop, so pull its text layer for the examiner prompt.
    if req.question_id and not question_text.strip():
        try:
            from app import _con
            con = _con()
            con.row_factory = __import__("sqlite3").Row
            row = con.execute("SELECT text FROM questions WHERE id = ?",
                              (req.question_id,)).fetchone()
            con.close()
            question_text = (row["text"] or "") if row else ""
        except Exception as exc:
            print(f"[quiz] could not load question {req.question_id}: {exc}", flush=True)
    if not question_text.strip():
        raise HTTPException(400, "The question could not be read for marking.")

    marks_label = f"{req.marks} marks" if req.marks else "several marks"
    scheme_note = (f"Mark scheme:\n{req.mark_scheme}\n\n" if req.mark_scheme
                   else "Use your knowledge of Cambridge marking to award marks.\n\n")

    system = (
        "You are a Cambridge examiner marking a student's answer.\n"
        f"Question ({marks_label}):\n{question_text}\n\n"
        f"{scheme_note}"
        f"Student's answer:\n{req.answer}\n\n"
        "Award marks generously but fairly. Output ONLY valid JSON:\n"
        '{"score": N, "feedback": "2-3 sentences on strengths and gaps", '
        '"ideal_answer": "key points that a full-mark answer would include"}'
    )

    text, _ = _chat([
        {"role": "system", "content": system},
        {"role": "user", "content": "Mark this answer and give feedback."},
    ], max_tokens=500)

    try:
        clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        data = json.loads(clean)
    except Exception:
        data = {"score": None, "feedback": text.strip(), "ideal_answer": None}

    # Persist the quiz session
    _udb.save_quiz(
        user_id=user["id"],
        syllabus=req.syllabus,
        topic=req.topic,
        subtopic=req.subtopic,
        question_text=question_text,
        student_answer=req.answer,
        score=data.get("score"),
        max_marks=req.marks,
        ideal_answer=data.get("ideal_answer"),
        feedback=data.get("feedback"),
    )

    return {
        "score": data.get("score"),
        "max_marks": req.marks,
        "feedback": data.get("feedback"),
        "ideal_answer": data.get("ideal_answer"),
        # Cambridge's own scheme beats a generated one, so show it when we have it.
        "ms_url": (f"/api/question/{req.question_id}/ms-preview"
                   if req.question_id else None),
    }


@router.get("/api/quiz/history")
def quiz_history(user: _CurrentUser, syllabus: str | None = None, limit: int = 10):
    rows = _udb.get_quiz_history(user["id"], syllabus, min(limit, 50))
    return {"history": rows}


# ── Past-paper practice tracker ────────────────────────────────────────────────

_STATUSES = {"not_started", "learning", "confident"}


@router.get("/api/papers-progress")
def list_paper_progress(user: _CurrentUser, syllabus: str | None = None):
    return {"papers": _udb.get_paper_progress(user["id"], syllabus)}


class PaperProgressUpdate(BaseModel):
    syllabus: str
    year: int
    session: str
    paper: int
    variant: str | None = ""
    status: str
    score: int | None = None
    max_score: int | None = None
    grade: str | None = None
    confidence: str | None = None
    attempts_json: str | None = None
    synced: int | None = None
    note: str | None = None


@router.post("/api/papers-progress")
def update_paper_progress(req: PaperProgressUpdate, user: _CurrentUser):
    if req.status not in _STATUSES:
        raise HTTPException(400, f"status must be one of: {', '.join(sorted(_STATUSES))}")
    if not re.match(r"^[0-9A-Za-z]{4,6}$", req.syllabus):
        raise HTTPException(400, "Invalid syllabus code")
    if req.session not in {"s", "w", "m"}:
        raise HTTPException(400, "session must be s, w or m")
    if not 2000 <= req.year <= 2100:
        raise HTTPException(400, "Implausible year")
    return _udb.upsert_paper_progress(
        user["id"], req.syllabus, req.year, req.session, req.paper,
        req.variant or "", req.status, req.score, req.max_score,
        req.grade, req.confidence, req.attempts_json or "[]", req.synced or 0,
        req.note, set_by="student")


@router.get("/api/grade-thresholds")
def get_grade_thresholds(syllabus: str, year: int | None = None, session: str | None = None, user: _CurrentUser = None):
    return {"thresholds": _udb.get_grade_thresholds(syllabus, year, session)}


@router.get("/api/grade-options")
def get_grade_options(syllabus: str, year: int | None = None, session: str | None = None):
    return {"options": _udb.get_grade_options(syllabus, year, session)}


@router.get("/api/grade-thresholds/history")
def get_grade_thresholds_history(syllabus: str, paper: int):
    return {"thresholds": _udb.get_grade_thresholds_history(syllabus, paper)}


@router.get("/api/grade-options/history")
def get_grade_options_history(syllabus: str, option_code: str | None = None):
    return {"options": _udb.get_grade_options_history(syllabus, option_code)}


@router.get("/api/student-scores")
def get_student_scores(syllabus: str, user: _CurrentUser):
    return {"scores": _udb.get_student_scores(user["id"], syllabus)}


class StudentScoreReq(BaseModel):
    syllabus: str
    year: int
    session: str
    paper: int
    variant: str = ""
    raw_mark: int
    max_mark: int
    component_grade: str | None = None
    option_code: str | None = None
    notes: str | None = None
    set_by: str = "student"


@router.post("/api/student-scores")
def save_student_score(req: StudentScoreReq, user: _CurrentUser):
    session = (req.session or "").strip().lower()
    if session not in {"s", "w", "m"}:
        raise HTTPException(400, "session must be s, w or m")
    if not 2000 <= req.year <= 2100:
        raise HTTPException(400, "Implausible year")
    if req.raw_mark < 0 or req.raw_mark > req.max_mark:
        raise HTTPException(400, "raw_mark out of range")

    # Auto-compute component grade from thresholds if not provided
    grade = req.component_grade
    if not grade:
        thresholds = _udb.get_grade_thresholds(req.syllabus, req.year, session)
        t = next((t for t in thresholds
                  if t["paper"] == req.paper
                  and str(t.get("variant", "")) == str(req.variant)), None)
        if t:
            mark = req.raw_mark
            if t.get("grade_astar") is not None and mark >= t["grade_astar"]:
                grade = "A*"
            elif mark >= t["grade_a"]:
                grade = "A"
            elif mark >= t["grade_b"]:
                grade = "B"
            elif mark >= t["grade_c"]:
                grade = "C"
            elif mark >= t["grade_d"]:
                grade = "D"
            elif mark >= t["grade_e"]:
                grade = "E"
            elif t.get("grade_f") is not None and mark >= t["grade_f"]:
                grade = "F"
            elif t.get("grade_g") is not None and mark >= t["grade_g"]:
                grade = "G"
            else:
                grade = "U"

    role = user.get("role", "student")
    set_by = "tutor" if role in {"teacher", "admin"} else "student"

    row = _udb.upsert_student_score(
        user["id"], req.syllabus, req.year, session,
        req.paper, req.variant or "", req.raw_mark, req.max_mark,
        grade, req.option_code, req.notes, set_by=set_by)
    row["component_grade"] = grade
    return row




def _json_list(raw) -> list:
    if isinstance(raw, list):
        return raw
    try:
        val = json.loads(raw or "[]")
        return val if isinstance(val, list) else []
    except (TypeError, ValueError):
        return []


def _decorate_assignment(a: dict) -> dict:
    """Add the derived fields every homework view needs, so due-date arithmetic
    happens once on the server rather than in three places on the client."""
    from datetime import date
    due = (a.get("due_date") or "").strip() or None
    days_left = None
    if due:
        try:
            days_left = (date.fromisoformat(due) - date.today()).days
        except ValueError:
            due = None
    done = a.get("status") == "done"
    return {
        **a,
        "topics": _json_list(a.get("topics_json")),
        # Attachments are exposed by index; `rel` for an upload is a server
        # path and never leaves the backend.
        "attachments": [
            {"idx": i, "type": t.get("type"), "name": t.get("name"),
             "rel": t.get("rel") if t.get("type") == "resource" else None,
             "params": t.get("params"), "size": t.get("size")}
            for i, t in enumerate(_json_list(a.get("attachments_json")))
        ],
        "subject_name": SUBJECT_NAMES.get(a.get("syllabus"), a.get("syllabus")),
        "due_date": due,
        "days_left": days_left,
        "overdue": bool(not done and days_left is not None and days_left < 0),
        # Student's own submitted files — rel path is stripped (server-side only)
        "submissions": [
            {"idx": i, "name": s.get("name"), "size": s.get("size"),
             "submitted_at": s.get("submitted_at")}
            for i, s in enumerate(_json_list(a.get("student_submissions_json")))
        ],
    }


def _own_assignment(assignment_id: int, user: dict) -> dict:
    row = _udb.get_assignment(assignment_id)
    # Same 404 whether it does not exist or belongs to someone else — a
    # different message would let anyone probe for other students' homework.
    if row is None or row.get("user_id") != user["id"]:
        raise HTTPException(404, "No such assignment")
    return row


@router.get("/api/assignments")
def list_assignments(user: _CurrentUser):
    items = [_decorate_assignment(a) for a in _udb.get_assignments(user["id"])]
    return {
        "assignments": items,
        "open": sum(1 for a in items if a["status"] != "done"),
        "overdue": sum(1 for a in items if a["overdue"]),
    }


@router.get("/api/notifications")
def list_notifications(user: _CurrentUser):
    """The student's alert feed, derived from their assignments.

    Deliberately computed rather than stored: every event a student cares
    about — a test scheduled, homework set, something due tomorrow, something
    already late — is a fact about an assignment row that already exists.
    A notifications table would be a second copy of that truth, and would drift
    the moment a due date moved.

    Read state lives in the browser (a timestamp of the last time the bell was
    opened), so this returns `at` on every item and lets the client decide what
    is new. Nothing here is per-device sensitive, so that trade is worth
    avoiding another write path for.
    """
    from datetime import date
    today = date.today()
    items = [_decorate_assignment(a) for a in _udb.get_assignments(user["id"])]

    notes = []
    for a in items:
        is_test = (a.get("kind") or "") == "test"
        title = a.get("title") or ("Test" if is_test else "Homework")
        subject = a.get("subject_name") or ""
        days = a.get("days_left")
        done = a.get("status") == "done"

        # 1. It was set. `created_at` is what makes this "new" to the student.
        notes.append({
            "id": f"set-{a['id']}",
            "assignment_id": a["id"],
            "kind": "test" if is_test else "assigned",
            "icon": "📝" if is_test else "📚",
            "title": (f"Test scheduled: {title}" if is_test
                      else f"New homework: {title}"),
            "body": " · ".join(x for x in (
                subject, _due_phrase(a.get("due_date"), days, is_test)) if x),
            "at": a.get("created_at"),
            "href": "/homework.html",
            "done": done,
        })

        # 2. Deadline pressure, but only while it is still actionable.
        if done or days is None:
            continue
        if days < 0:
            notes.append({
                "id": f"late-{a['id']}", "assignment_id": a["id"],
                "kind": "overdue", "icon": "⏰",
                "title": f"Overdue: {title}",
                "body": f"Was due {a['due_date']}"
                        + (f" · {subject}" if subject else ""),
                # Sorted by when it became late, so it rises as it ages.
                "at": _at_days_after(a.get("due_date"), 1),
                "href": "/homework.html", "done": False,
            })
        elif days <= 2:
            notes.append({
                "id": f"soon-{a['id']}", "assignment_id": a["id"],
                "kind": "test_soon" if is_test else "due_soon",
                "icon": "📌",
                "title": (f"{title} is {'today' if days == 0 else 'tomorrow' if days == 1 else 'in 2 days'}"),
                "body": ("Your test" if is_test else "Due") + f" {a['due_date']}"
                        + (f" · {subject}" if subject else ""),
                "at": _at_days_after(a.get("due_date"), -days),
                "href": "/homework.html", "done": False,
            })

    # Newest first; anything without a timestamp sinks rather than jumping.
    notes.sort(key=lambda n: str(n.get("at") or ""), reverse=True)
    notes = notes[:40]

    upcoming_tests = [a for a in items
                      if (a.get("kind") == "test") and a.get("status") != "done"
                      and (a.get("days_left") is None or a["days_left"] >= 0)]
    upcoming_tests.sort(key=lambda a: str(a.get("due_date") or "9999"))

    return {
        "notifications": notes,
        "latest_at": notes[0]["at"] if notes else None,
        "upcoming_tests": upcoming_tests,
        "counts": {
            "open": sum(1 for a in items if a["status"] != "done"),
            "overdue": sum(1 for a in items if a["overdue"]),
            "tests": len(upcoming_tests),
        },
    }


def _due_phrase(due: str | None, days: int | None, is_test: bool) -> str:
    if not due:
        return "No date set"
    if days is None:
        return f"{'On' if is_test else 'Due'} {due}"
    if days < 0:
        return f"Was due {due}"
    if days == 0:
        return "Today"
    if days == 1:
        return "Tomorrow"
    return f"{'On' if is_test else 'Due'} {due} · in {days} days"


def _at_days_after(due: str | None, offset: int) -> str | None:
    """Timestamp for a derived event, so it sorts against real created_at."""
    from datetime import date, datetime, time, timezone, timedelta
    if not due:
        return None
    try:
        d = date.fromisoformat(str(due)) + timedelta(days=offset)
    except ValueError:
        return None
    return datetime.combine(d, time(6, 0), tzinfo=timezone.utc).isoformat()


class AssignmentStatusReq(BaseModel):
    status: str | None = None          # assigned | done
    student_note: str | None = None
    seen: bool | None = None


@router.post("/api/assignments/{assignment_id}/status")
def set_assignment_status(assignment_id: int, req: AssignmentStatusReq,
                          user: _CurrentUser):
    row = _own_assignment(assignment_id, user)
    fields: dict = {}
    if req.status is not None:
        if req.status not in {"assigned", "done"}:
            raise HTTPException(400, "status must be 'assigned' or 'done'")
        fields["status"] = req.status
        fields["completed_at"] = _udb._now() if req.status == "done" else None
    if req.student_note is not None:
        fields["student_note"] = req.student_note.strip() or None
    # First open stamps seen_at; later opens leave the original timestamp alone
    # so the tutor can tell how long it sat unread.
    if req.seen and not row.get("seen_at"):
        fields["seen_at"] = _udb._now()
    if not fields:
        # The homework page pings {seen:true} on every open, so a repeat call
        # with nothing left to change is the normal path, not an error.
        if req.seen:
            return {"assignment": _decorate_assignment(row)}
        raise HTTPException(400, "Nothing to update")
    return {"assignment": _decorate_assignment(
        _udb.update_assignment(assignment_id, fields))}


@router.get("/api/assignments/{assignment_id}/file/{idx}")
def download_assignment_file(assignment_id: int, idx: int, user: _CurrentUser):
    """Serve an uploaded worksheet. Ownership is checked first, and the stored
    name is resolve-and-checked against the upload directory before serving."""
    from fastapi.responses import FileResponse
    from admin import UPLOADS_DIR

    row = _own_assignment(assignment_id, user)
    attachments = _json_list(row.get("attachments_json"))
    if not 0 <= idx < len(attachments):
        raise HTTPException(404, "No such attachment")
    att = attachments[idx]
    if att.get("type") != "upload":
        raise HTTPException(400, "That attachment is not a file")

    base = UPLOADS_DIR.resolve()
    path = (UPLOADS_DIR / (att.get("rel") or "")).resolve()
    if not str(path).startswith(str(base)) or not path.is_file():
        raise HTTPException(404, "That file is no longer on the server")

    # The admin's label (e.g. "Week 3 Worksheet") may have no extension, so
    # the OS can't tell the file type. Always append the stored extension.
    import mimetypes as _mt
    name = att.get("name") or path.name
    ext = path.suffix.lower()
    if ext and not name.lower().endswith(ext):
        name = name + ext
    media_type = _mt.guess_type(str(path))[0] or "application/octet-stream"
    return FileResponse(path, filename=name, media_type=media_type)


@router.post("/api/assignments/{assignment_id}/submit")
async def submit_assignment(assignment_id: int, user: _CurrentUser,
                            file: UploadFile = File(...)):
    """Upload a student's completed work for an assignment."""
    from admin import UPLOADS_DIR, MAX_UPLOAD_BYTES, ALLOWED_UPLOAD_EXTS

    row = _own_assignment(assignment_id, user)

    original = os.path.basename(file.filename or "file")
    ext = os.path.splitext(original)[1].lower()
    if ext not in ALLOWED_UPLOAD_EXTS:
        raise HTTPException(400, f"File type {ext or '(none)'} is not allowed. "
                            "Upload a PDF, image, Word or Office document.")

    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is larger than 25 MB")
    if not data:
        raise HTTPException(400, "That file appears to be empty")

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    rel = f"sub_{assignment_id}_{uuid.uuid4().hex[:12]}{ext}"
    (UPLOADS_DIR / rel).write_bytes(data)

    submissions = _json_list(row.get("student_submissions_json"))
    submissions.append({
        "rel": rel, "name": original,
        "size": len(data), "submitted_at": _udb._now(),
    })
    updated = _udb.update_assignment(
        assignment_id, {"student_submissions_json": json.dumps(submissions)})
    return {"assignment": _decorate_assignment(updated)}


@router.get("/api/assignments/{assignment_id}/submission/{idx}")
def download_own_submission(assignment_id: int, idx: int, user: _CurrentUser):
    """Let a student re-download a file they submitted."""
    from fastapi.responses import FileResponse
    from admin import UPLOADS_DIR

    row = _own_assignment(assignment_id, user)
    submissions = _json_list(row.get("student_submissions_json"))
    if not 0 <= idx < len(submissions):
        raise HTTPException(404, "No such submission")
    sub = submissions[idx]
    base = UPLOADS_DIR.resolve()
    path = (UPLOADS_DIR / (sub.get("rel") or "")).resolve()
    if not str(path).startswith(str(base)) or not path.is_file():
        raise HTTPException(404, "That file is no longer on the server")
    import mimetypes as _mt
    name = sub.get("name") or path.name
    ext = path.suffix.lower()
    if ext and not name.lower().endswith(ext):
        name = name + ext
    media_type = _mt.guess_type(str(path))[0] or "application/octet-stream"
    return FileResponse(path, filename=name, media_type=media_type)


# ── Calendar feed ──────────────────────────────────────────────────────────────

@router.get("/api/my-calendar")
def my_calendar(user: _CurrentUser):
    """The student's own subscribe-once homework feed URL."""
    import reminders
    return {"url": reminders.calendar_url(user["id"]),
            "webcal": reminders.calendar_url(user["id"]).replace("https://", "webcal://")
                                                        .replace("http://", "webcal://")}


@router.get("/api/calendar/{user_id}/{token}.ics")
def calendar_feed(user_id: str, token: str):
    """iCalendar feed of a student's homework.

    Deliberately NOT cookie-authenticated: a phone's calendar app fetches this
    on a schedule with no session. The token in the path is a keyed digest of
    the user id, so it is unguessable and revocable by rotating SECRET_KEY.
    Exposes only homework titles and dates — no marks, no contact details.
    """
    from fastapi.responses import Response
    import reminders

    if not reminders.verify_calendar_token(user_id, token):
        raise HTTPException(404, "No such calendar")
    user = _udb.get_user(user_id)
    if not user:
        raise HTTPException(404, "No such calendar")

    ics = reminders.build_ics(user, _udb.get_assignments(user_id))
    return Response(
        ics, media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="prepwithtee-homework.ics"',
                 "Cache-Control": "no-cache"})


# ── Class log (read-only for the student) ──────────────────────────────────────

@router.get("/api/classes")
def list_classes(user: _CurrentUser):
    rows = _udb.get_class_log(user["id"])
    for r in rows:
        r["subject_name"] = SUBJECT_NAMES.get(r.get("syllabus"), r.get("syllabus"))
    return {"classes": rows,
            "held": sum(1 for r in rows if (r.get("status") or "held") == "held")}


# ── Dashboard ──────────────────────────────────────────────────────────────────

def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default


def _flashcard_days(uid: str) -> list[str]:
    """Timestamps (one per distinct UTC day) of the student's flashcard reviews."""
    import flashcards as _fc
    con = _fc._con()
    try:
        rows = con.execute("SELECT DISTINCT substr(reviewed_at, 1, 19) AS t FROM fc_review_events "
                           "WHERE student_id = ? ORDER BY t DESC LIMIT 2000", [uid]).fetchall()
    finally:
        con.close()
    return [r["t"] for r in rows]


@router.get("/api/dashboard")
def dashboard(user: _CurrentUser, tz: str = ""):
    import streaks as _streaks
    uid = user["id"]
    zone = _streaks.zone(tz)
    today = _streaks.local_today(zone)
    got = _udb.gather(
        enrollments=lambda: _udb.get_enrollments(uid),
        archived_enrollments=lambda: _udb.get_archived_enrollments(uid),
        progress_summary=lambda: _udb.get_progress_summary(uid),
        quizzes=lambda: _udb.get_quiz_history(uid, syllabus=None, limit=50),
        assignments=lambda: _udb.get_assignments(uid, 60),
        papers=lambda: _udb.get_paper_progress(uid),
        classes=lambda: _udb.get_class_log(uid, 500),
        today_seconds=lambda: _udb.get_today_time_spent(uid, today.isoformat()),
        booklets=lambda: _safe(lambda: _udb.list_booklets(uid, 200), []),
        mcq=lambda: _safe(lambda: _udb.list_mcq_sessions(uid, None, 200), []),
        time_days=lambda: _safe(lambda: _udb.get_time_spent_range(
            uid, (today - __import__("datetime").timedelta(days=400)).isoformat(), today.isoformat()), []),
        fc_days=lambda: _safe(lambda: _flashcard_days(uid), []),
    )
    enrollments = got["enrollments"]
    archived_enrollments = got["archived_enrollments"]
    progress_summary = got["progress_summary"]
    quizzes = got["quizzes"]
    recent_quizzes = quizzes[:5]

    # Streak: consecutive LOCAL days with any activity at all (streaks.py).
    days: set = set()
    for row in got["time_days"]:
        if (row.get("seconds") or 0) > 0:
            days.add(row["date"])
    stamps = ([q.get("created_at") for q in quizzes]
              + [b.get("created_at") for b in got["booklets"]]
              + [m.get(k) for m in got["mcq"] for k in ("created_at", "submitted_at")]
              + [p.get("updated_at") for p in got["papers"]]
              + list(got["fc_days"]))
    for ts in stamps:
        d = _streaks.local_day(ts, zone)
        if d:
            days.add(d)
    streak, streak_best = _streaks.streaks(days, today)
    week = [(today - __import__("datetime").timedelta(days=i)).isoformat() for i in range(6, -1, -1)]

    assignments = [_decorate_assignment(a) for a in got["assignments"]]
    open_hw = [a for a in assignments if a["status"] != "done"]

    return {
        "user": {k: v for k, v in user.items()
                 if k in ("id","email","name","picture_url","grade","profile_complete")},
        "enrollments": [
            {"syllabus": s, "name": SUBJECT_NAMES.get(s, s)}
            for s in enrollments
        ],
        "archived_enrollments": [
            {"syllabus": s, "name": SUBJECT_NAMES.get(s, s)}
            for s in archived_enrollments
        ],
        "progress_summary": progress_summary,
        "paper_summary": _paper_summary(got["papers"]),
        "recent_quizzes": recent_quizzes,
        "streak": streak,
        "streak_best": streak_best,
        "active_today": today.isoformat() in days,
        "week_active": [d in days for d in week],        # last 7 local days, oldest first
        "today_seconds": got["today_seconds"],
        "homework": {
            "open": len(open_hw),
            "overdue": sum(1 for a in open_hw if a["overdue"]),
            "due_soon": sum(1 for a in open_hw
                            if a["days_left"] is not None and 0 <= a["days_left"] <= 2),
            # Soonest deadline first; undated homework sinks to the bottom.
            "items": sorted(open_hw,
                            key=lambda a: (a["due_date"] is None, a["due_date"] or ""))[:5],
        },
        "classes_held": sum(
            1 for c in got["classes"]
            if (c.get("status") or "held") == "held"),
    }


class _PaperProgressReq(BaseModel):
    syllabus: str
    year: int
    session: str          # "s" | "w" | "m"
    paper: int
    variant: str
    status: str           # "confident" | "learning" | "not_started"
    score: int | None = None
    max_score: int | None = None
    note: str | None = None


@router.post("/api/paper-progress")
def save_paper_progress(req: _PaperProgressReq, user: _CurrentUser):
    """Student saves their MCQ paper result from the end-of-session dialog."""
    valid_statuses = {"confident", "learning", "not_started"}
    if req.status not in valid_statuses:
        raise HTTPException(400, "Invalid status.")
    row = _udb.upsert_paper_progress(
        user_id=user["id"],
        syllabus=req.syllabus,
        year=req.year,
        session=req.session,
        paper=req.paper,
        variant=str(req.variant),
        status=req.status,
        score=req.score,
        max_score=req.max_score,
        note=req.note,
        set_by="student",
    )
    return {"ok": True, "row": row}


def _paper_summary(rows: list[dict]) -> dict:
    """{syllabus: {confident, learning, not_started, avg_score, best_score}} for the dashboard rings."""
    out: dict[str, dict] = {}
    for row in rows:
        entry = out.setdefault(row["syllabus"],
                               {"total": 0, "confident": 0, "learning": 0,
                                "not_started": 0, "scores": []})
        entry["total"] += 1
        status = row.get("status") or "not_started"
        if status in entry:
            entry[status] += 1
        score = row.get("score")
        max_score = row.get("max_score")
        if score is not None and max_score and max_score > 0:
            pct = round((score / max_score) * 100, 1)
            entry["scores"].append(pct)

    for syl, entry in out.items():
        scores = entry.pop("scores", [])
        if scores:
            entry["avg_score"] = round(sum(scores) / len(scores), 1)
            entry["best_score"] = round(max(scores), 1)
        else:
            entry["avg_score"] = None
            entry["best_score"] = None

    return out


# ── Teachers ───────────────────────────────────────────────────────────────────

@router.get("/api/teachers")
def list_teachers(_: _MaybeUser):
    teachers = _udb.get_teachers()
    # Decode subjects_json → list
    for t in teachers:
        if isinstance(t.get("subjects_json"), str):
            try:
                t["subjects"] = json.loads(t["subjects_json"])
            except Exception:
                t["subjects"] = []
        else:
            t["subjects"] = t.get("subjects_json") or []
        t["subject_names"] = [SUBJECT_NAMES.get(s, s) for s in t["subjects"]]
    return {"teachers": teachers}


class TeacherAppReq(BaseModel):
    name: str
    email: str
    phone: str | None = None
    subjects: str | None = None
    subject_codes: list[str] | None = None   # syllabus codes behind the labels
    qualifications: str | None = None
    experience: str | None = None
    message: str | None = None


@router.post("/api/teacher-applications")
def submit_teacher_application(req: TeacherAppReq):
    name = (req.name or "").strip()
    email = (req.email or "").strip()
    if not name:
        raise HTTPException(400, "Name is required")
    if not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
        raise HTTPException(400, "Valid email is required")

    payload = {
        "name": name,
        "email": email,
        "phone": (req.phone or "").strip() or None,
        "subjects": (req.subjects or "").strip() or None,
        "subject_codes": ",".join(
            c for c in (req.subject_codes or []) if re.match(r"^[0-9A-Za-z]{4,6}$", c)
        ) or None,
        "qualifications": (req.qualifications or "").strip() or None,
        "experience": (req.experience or "").strip() or None,
        "message": (req.message or "").strip() or None,
    }
    _udb.save_teacher_application(payload)

    # Notify admin (reuse existing helper from app.py)
    try:
        from app import _notify
        _notify(
            f"[PrepWithTee] Teacher Application — {name}",
            f"Name: {name}\nEmail: {email}\nSubjects: {req.subjects}\n\n{req.message or ''}",
            rows=[
                ("Name", name), ("Email", email),
                ("Phone", req.phone or "—"),
                ("Subjects", req.subjects or "—"),
                ("Qualifications", req.qualifications or "—"),
                ("Experience", req.experience or "—"),
                ("Message", req.message or "—"),
            ],
        )
    except Exception:
        pass

    return {"status": "success", "message": "Application received — we'll be in touch soon!"}


# ── Usage / quota ──────────────────────────────────────────────────────────────

@router.get("/api/usage")
def get_usage(user: _CurrentUser):
    """Return billing-cycle usage counts, limits, and plan info for the dashboard meter."""
    from access import MONTHLY_QUOTAS, TRIAL_QUOTAS, plan_info

    info = plan_info(user)
    plan = info["plan"]
    trial = info["trial"]
    period_start = info["period_start"]

    counts = _udb.get_monthly_usage(user["id"], period_start)
    result = {}
    for event_type, counts_by_plan in MONTHLY_QUOTAS.items():
        if trial:
            limit = TRIAL_QUOTAS.get(event_type)
        else:
            limit = counts_by_plan.get(plan)
        result[event_type] = {
            "used": counts.get(event_type, 0),
            "limit": limit,
            "unlimited": limit is None,
        }
    return {
        "plan": plan,
        "trial": trial,
        "trial_days_left": info.get("trial_days_left"),
        "expires_at": info.get("expires_at"),
        "started_at": info.get("started_at"),
        "period_start": period_start,
        "usage": result,
    }


# ── Groups (student) ──────────────────────────────────────────────────────────

@router.get("/api/groups")
def list_groups(user: _CurrentUser):
    """Active groups students can browse and join."""
    groups = _udb.get_active_groups()
    for g in groups:
        g["member_count"] = _udb.get_group_member_count(g["id"])
    return {"groups": groups}


@router.get("/api/groups/mine")
def my_groups(user: _CurrentUser):
    return {"groups": _udb.get_student_groups(user["id"])}


@router.post("/api/groups/{group_id}/join")
def join_group(group_id: int, user: _CurrentUser):
    g = _udb.get_group(group_id)
    if not g:
        raise HTTPException(404, "Group not found")
    if g["status"] != "active":
        raise HTTPException(409, "This group is not open for enrolment")
    current = _udb.get_group_member_count(group_id)
    if current >= g["max_students"]:
        raise HTTPException(409, "This group is full")
    membership = _udb.join_group(group_id, user["id"])
    return {"ok": True, "membership": membership}


@router.post("/api/groups/{group_id}/leave")
def leave_group(group_id: int, user: _CurrentUser):
    _udb.leave_group(group_id, user["id"])
    return {"ok": True}


# ── Payment proofs (student uploads screenshot) ───────────────────────────────

class PaymentProofReq(BaseModel):
    plan: str
    amount_pkr: int | None = None
    method: str = "other"           # jazzcash|easypaisa|bank|other
    transaction_id: str | None = None
    screenshot_url: str | None = None
    note: str | None = None


VALID_PAYMENT_PLANS = {"solo", "three", "all"}


def _notify_admin_new_proof(user: dict, proof: dict):
    """Fire-and-forget email to admin when a payment proof is submitted."""
    import smtplib
    import logging
    from email.mime.text import MIMEText as _MT
    try:
        import requests as _req
    except ImportError:
        _req = None

    log = logging.getLogger(__name__)
    labels = {"solo": "Solo", "three": "3 Subjects", "all": "All Subjects"}
    plan_label = labels.get(proof.get("plan", ""), proof.get("plan", ""))
    student = user.get("name") or user.get("email", "unknown")
    amount = proof.get("amount_pkr")
    amount_str = f"PKR {amount:,}" if isinstance(amount, int) else "unspecified"
    base_url = os.environ.get("APP_BASE_URL", "https://prepwithtee.com")
    body = (
        f"New payment proof received.\n\n"
        f"Student:  {student}\n"
        f"Plan:     {plan_label}\n"
        f"Method:   {proof.get('method', '—')}\n"
        f"Amount:   {amount_str}\n"
        f"Tx ID:    {proof.get('transaction_id') or '—'}\n\n"
        f"Review at: {base_url}/admin.html\n\nPrepWithTee"
    )
    subject = f"[PrepWithTee] Payment proof: {plan_label} — {student}"
    admin_email = (os.environ.get("ADMIN_EMAIL")
                   or os.environ.get("SMTP_USER")
                   or "nexgentutors6@gmail.com")
    smtp_user = os.environ.get("SMTP_USER", "")
    resend_key = os.environ.get("RESEND_API_KEY", "")

    if resend_key and _req:
        from_addr = (f"PrepWithTee <{smtp_user}>" if smtp_user
                     else "PrepWithTee <onboarding@resend.dev>")
        try:
            r = _req.post(
                "https://api.resend.com/emails",
                json={"from": from_addr, "to": [admin_email],
                      "subject": subject, "text": body},
                headers={"Authorization": f"Bearer {resend_key}"},
                timeout=10,
            )
            if r.status_code < 300:
                return
            log.warning("proof notify Resend %s: %s", r.status_code, r.text[:200])
        except Exception as exc:
            log.warning("proof notify Resend: %s", exc)

    smtp_pass = os.environ.get("SMTP_PASS", "")
    if smtp_user and smtp_pass:
        try:
            msg = _MT(body)
            msg["Subject"] = subject
            msg["From"] = smtp_user
            msg["To"] = admin_email
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=8) as srv:
                srv.starttls()
                srv.login(smtp_user, smtp_pass)
                srv.sendmail(smtp_user, admin_email, msg.as_string())
        except Exception as exc:
            log.warning("proof notify SMTP: %s", exc)


@router.post("/api/upload/payment-screenshot")
async def upload_payment_screenshot(user: _CurrentUser, file: UploadFile = File(...)):
    ALLOWED = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
    MAX_BYTES = 10 * 1024 * 1024
    if file.content_type not in ALLOWED:
        raise HTTPException(400, "Only JPEG, PNG, WebP, or PDF accepted")
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(400, "File too large (max 10 MB)")
    raw_name = file.filename or ""
    ext = raw_name.rsplit(".", 1)[-1].lower() if "." in raw_name else "jpg"
    if ext not in {"jpg", "jpeg", "png", "webp", "pdf"}:
        ext = "jpg"
    filename = f"{uuid.uuid4().hex}.{ext}"
    dest_dir = Path(__file__).resolve().parent.parent / "data" / "uploads" / "payments"
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / filename).write_bytes(data)
    return {"url": f"/uploads/payments/{filename}"}


@router.post("/api/upload/avatar")
async def upload_avatar(user: _CurrentUser, file: UploadFile = File(...)):
    ALLOWED = {"image/jpeg", "image/png", "image/webp"}
    MAX_BYTES = 5 * 1024 * 1024
    if file.content_type not in ALLOWED:
        raise HTTPException(400, "Only JPEG, PNG, or WebP accepted")
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(400, "File too large (max 5 MB)")
    raw_name = file.filename or ""
    ext = raw_name.rsplit(".", 1)[-1].lower() if "." in raw_name else "jpg"
    if ext not in {"jpg", "jpeg", "png", "webp"}:
        ext = "jpg"
    filename = f"avatar_{user['id']}_{uuid.uuid4().hex[:8]}.{ext}"
    dest_dir = Path(__file__).resolve().parent.parent / "data" / "uploads" / "avatars"
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / filename).write_bytes(data)
    url = f"/uploads/avatars/{filename}"
    _udb.update_profile(user["id"], {"picture_url": url})
    return {"url": url}


@router.post("/api/payment-proof")
def submit_payment_proof(req: PaymentProofReq, user: _CurrentUser):
    if req.plan not in VALID_PAYMENT_PLANS:
        raise HTTPException(400, f"plan must be one of: {', '.join(sorted(VALID_PAYMENT_PLANS))}")
    proof = _udb.create_payment_proof({
        "user_id": user["id"],
        "plan": req.plan,
        "amount_pkr": req.amount_pkr,
        "method": req.method,
        "transaction_id": req.transaction_id,
        "screenshot_url": req.screenshot_url,
        "note": req.note,
    })
    threading.Thread(
        target=_notify_admin_new_proof, args=(user, proof), daemon=True
    ).start()
    return {"ok": True, "proof_id": proof["id"]}


# ── Student code ───────────────────────────────────────────────────────────────

@router.get("/api/student-code")
def get_student_code(user: _CurrentUser):
    if user.get("role") != "student":
        raise HTTPException(403, "Only students have a student code")
    code = _udb.ensure_student_code(user["id"])
    return {"code": code}


# ── Parent dashboard ──────────────────────────────────────────────────────────

class LinkChildReq(BaseModel):
    code: str


@router.post("/api/parent/link-child")
def link_child(req: LinkChildReq, user: _CurrentUser):
    if user.get("role") != "parent":
        raise HTTPException(403, "Only parents can link children")
    code = req.code.strip().upper()
    student = _udb.get_profile_by_student_code(code)
    if not student:
        raise HTTPException(404, "No student found with that code — please check and try again")
    if student["id"] == user["id"]:
        raise HTTPException(400, "You cannot link yourself")
    if _udb.parent_link_exists(user["id"], student["id"]):
        raise HTTPException(409, "This student is already linked to your account")
    _udb.create_parent_link(user["id"], student["id"])
    return {"ok": True, "student": student}


@router.get("/api/parent/children")
def get_children(user: _CurrentUser):
    if user.get("role") != "parent":
        raise HTTPException(403, "Only parents can access this")
    links = _udb.get_parent_links(user["id"])
    return {"children": links}


@router.get("/api/parent/child/{child_id}/classes")
def get_child_classes(child_id: str, user: _CurrentUser):
    """Return class log for a linked child — parent-facing."""
    if user.get("role") != "parent":
        raise HTTPException(403, "Only parents can access this")
    links = _udb.get_parent_links(user["id"])
    if not any(l.get("student_id") == child_id or l.get("profiles", {}).get("id") == child_id
               for l in links):
        raise HTTPException(403, "This child is not linked to your account")
    rows = _udb.get_class_log(child_id)
    for r in rows:
        r["subject_name"] = SUBJECT_NAMES.get(r.get("syllabus"), r.get("syllabus"))
    return {"classes": rows,
            "held": sum(1 for r in rows if (r.get("status") or "held") == "held")}


@router.get("/api/parent/child/{child_id}/assignments")
def get_child_assignments(child_id: str, user: _CurrentUser):
    """Homework list for a linked child — parent-facing."""
    if user.get("role") != "parent":
        raise HTTPException(403, "Only parents can access this")
    links = _udb.get_parent_links(user["id"])
    if not any(l.get("student_id") == child_id or l.get("profiles", {}).get("id") == child_id
               for l in links):
        raise HTTPException(403, "This child is not linked to your account")
    items = [_decorate_assignment(a) for a in _udb.get_assignments(child_id)]
    return {
        "assignments": items,
        "open": sum(1 for a in items if a["status"] != "done"),
        "overdue": sum(1 for a in items if a["overdue"]),
        "done": sum(1 for a in items if a["status"] == "done"),
    }


@router.get("/api/parent/child/{child_id}/stats")
def get_child_stats(child_id: str, user: _CurrentUser):
    """Summary stats for child card tiles and overview panel."""
    if user.get("role") != "parent":
        raise HTTPException(403, "Only parents can access this")
    links = _udb.get_parent_links(user["id"])
    if not any(l.get("student_id") == child_id or l.get("profiles", {}).get("id") == child_id
               for l in links):
        raise HTTPException(403, "This child is not linked to your account")

    from datetime import date
    today = date.today()
    month_start = today.replace(day=1).isoformat()

    classes = _udb.get_class_log(child_id)
    assignments = [_decorate_assignment(a) for a in _udb.get_assignments(child_id)]

    held = [c for c in classes if (c.get("status") or "held") == "held"]
    classes_this_month = sum(
        1 for c in held if (c.get("class_date") or "") >= month_start)
    total_mins = sum(c.get("duration_min") or 0 for c in held)
    sorted_held = sorted(held, key=lambda x: x.get("class_date") or "", reverse=True)
    last_class = sorted_held[0]["class_date"] if sorted_held else None

    open_hw = sum(1 for a in assignments if a["status"] != "done")
    overdue_hw = sum(1 for a in assignments if a["overdue"])
    done_hw = sum(1 for a in assignments if a["status"] == "done")
    total_hw = len(assignments)
    completion_rate = round(done_hw / total_hw * 100) if total_hw else None

    return {
        "classes_this_month": classes_this_month,
        "classes_held_total": len(held),
        "total_hours": round(total_mins / 60, 1),
        "last_class_date": last_class,
        "homework_open": open_hw,
        "homework_overdue": overdue_hw,
        "homework_done": done_hw,
        "homework_total": total_hw,
        "completion_rate": completion_rate,
    }


@router.get("/api/parent/child/{child_id}/paper-progress")
def get_child_paper_progress(child_id: str, user: _CurrentUser):
    """Yearly paper tracker for a linked child — parent-facing."""
    if user.get("role") != "parent":
        raise HTTPException(403, "Only parents can access this")
    links = _udb.get_parent_links(user["id"])
    if not any(l.get("student_id") == child_id or l.get("profiles", {}).get("id") == child_id
               for l in links):
        raise HTTPException(403, "This child is not linked to your account")
    papers = _udb.get_paper_progress(child_id)
    return {"papers": papers}


# ── Direct messaging ──────────────────────────────────────────────────────────

class SendMessageReq(BaseModel):
    recipient_id: str
    body: str


@router.get("/api/my-teachers")
def get_my_teachers(user: _CurrentUser):
    """Returns the teachers assigned to the current student."""
    return {"teachers": _udb.get_student_teachers(user["id"])}


@router.get("/api/messages")
def get_my_conversations(user: _CurrentUser):
    convs = _udb.get_conversations(user["id"])
    unread = _udb.count_unread_messages(user["id"])
    return {"conversations": convs, "unread": unread}


@router.get("/api/messages/{partner_id}")
def get_thread(partner_id: str, user: _CurrentUser):
    msgs = _udb.get_messages_between(user["id"], partner_id)
    _udb.mark_messages_read(user["id"], partner_id)
    return {"messages": msgs}


@router.post("/api/messages")
def send_message(req: SendMessageReq, user: _CurrentUser):
    body = req.body.strip()
    if not body:
        raise HTTPException(400, "Message body cannot be empty")
    if len(body) > 4000:
        raise HTTPException(400, "Message too long (max 4000 chars)")
    msg = _udb.create_message(user["id"], req.recipient_id, body)
    return {"ok": True, "message": msg}


# ── Public contact form ───────────────────────────────────────────────────────

class ContactReq(BaseModel):
    name: str | None = None
    email: str
    subject: str | None = None
    message: str


@router.post("/api/contact")
def submit_contact(req: ContactReq):
    if not req.email or "@" not in req.email:
        raise HTTPException(400, "Valid email required")
    if not req.message.strip():
        raise HTTPException(400, "Message cannot be empty")
    _udb.create_contact(
        name=req.name or "",
        email=req.email.strip().lower(),
        subject=req.subject or "",
        message=req.message.strip(),
    )
    threading.Thread(target=_notify_contact, args=(req,), daemon=True).start()
    return {"ok": True}


def _notify_contact(req: ContactReq) -> None:
    try:
        import smtplib, os
        from email.mime.text import MIMEText
        smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER") or os.getenv("ADMIN_EMAIL", "nexgentutors6@gmail.com")
        smtp_pass = os.getenv("SMTP_PASS")
        admin_email = os.getenv("ADMIN_EMAIL", "nexgentutors6@gmail.com")
        if not smtp_pass:
            return
        msg = MIMEText(
            f"From: {req.name or 'Anonymous'} <{req.email}>\n"
            f"Subject: {req.subject or '(no subject)'}\n\n"
            f"{req.message}"
        )
        msg["Subject"] = f"[PrepWithTee Contact] {req.subject or req.name or req.email}"
        msg["From"] = smtp_user
        msg["To"] = admin_email
        with smtplib.SMTP(smtp_host, smtp_port) as s:
            s.starttls()
            s.login(smtp_user, smtp_pass)
            s.sendmail(smtp_user, [admin_email], msg.as_string())
    except Exception:
        pass


# ── Newsletter signup ─────────────────────────────────────────────────────────

class NewsletterReq(BaseModel):
    email: str


@router.post("/api/newsletter")
def newsletter_signup(req: NewsletterReq):
    email = req.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "Valid email required")
    is_new, token = _udb.create_newsletter_subscriber(email)
    
    if is_new and token:
        unsub_url = f"https://prepwithtee.com/unsubscribe?token={token}"
        body = (
            f"Hi there,\n\n"
            f"You're on the PrepWithTee list! We're excited to have you join us.\n\n"
            f"Here's what PrepWithTee can do for you:\n"
            f"- Access 5,000+ categorized Cambridge O Level & IGCSE past paper questions\n"
            f"- Practice with official mark schemes instantly attached to every question\n"
            f"- Use our AI Tutor to break down tricky physics & maths problems step-by-step\n\n"
            f"Visit PrepWithTee: https://prepwithtee.com/\n\n"
            f"To unsubscribe at any time, click here: {unsub_url}\n"
        )
        rows = [
            ("Email", email),
            ("Status", "Subscribed"),
            ("Unsubscribe", unsub_url),
        ]
        try:
            from app import _notify
            _notify("[PrepWithTee] You're on the list!", body, rows=rows, to=email,
                    cta=("Explore PrepWithTee", "https://prepwithtee.com/"))
        except Exception as exc:
            print(f"[newsletter] could not send confirmation email to {email}: {exc}", flush=True)

    return {"ok": True, "is_new": is_new}


@router.get("/unsubscribe")
@router.get("/api/newsletter/unsubscribe")
def newsletter_unsubscribe(token: str):
    if not token or not token.strip():
        raise HTTPException(400, "Unsubscribe token required")
    ok = _udb.unsubscribe_newsletter(token.strip())
    if not ok:
        return Response(content="<h1>Invalid or expired unsubscribe link</h1>", media_type="text/html", status_code=404)
    return Response(
        content="""<!DOCTYPE html>
<html>
<head><title>Unsubscribed — PrepWithTee</title></head>
<body style="font-family:sans-serif;text-align:center;padding:50px;background:#f4f0ea;color:#1a1a2e">
  <div style="max-width:450px;margin:0 auto;background:#fff;padding:40px;border-radius:12px;box-shadow:0 4px 12px rgba(0,0,0,0.1)">
    <h2 style="color:#2E1B4A">You have been unsubscribed</h2>
    <p style="color:#666">You will no longer receive newsletter emails from PrepWithTee.</p>
    <a href="https://prepwithtee.com/" style="display:inline-block;margin-top:20px;padding:10px 20px;background:#E8913A;color:#fff;text-decoration:none;border-radius:8px;font-weight:bold">Return to Homepage</a>
  </div>
</body>
</html>""",
        media_type="text/html"
    )


# ── Daily Time Spent Tracking ──────────────────────────────────────────────────

class TimeSpentReq(BaseModel):
    seconds: int
    day: str | None = None      # the browser's local YYYY-MM-DD


@router.post("/api/time-spent")
def record_time_spent(req: TimeSpentReq, user: _CurrentUser):
    if user.get("role") != "student":
        return {"ok": True}
    # Cap maximum increment to 5 minutes to prevent abuse
    sec = min(max(req.seconds, 1), 300)
    import streaks as _streaks
    _udb.add_time_spent(user["id"], sec, _streaks.valid_client_day(req.day))
    return {"ok": True}


@router.get("/api/analytics/time")
def get_weekly_time(user: _CurrentUser):
    if user.get("role") != "student":
        return {"weekly_time": []}
    return {"weekly_time": _udb.get_weekly_time_spent(user["id"])}


# ── Student personal notes ─────────────────────────────────────────────────────

class NoteCreate(BaseModel):
    type: str = "text"                  # 'text' | 'sticky'
    title: str | None = None
    content: str | None = None
    color: str | None = None            # sticky colour
    linked_type: str | None = None      # 'paper'|'flashcard_block'|'chapter'|'tutor_message'
    linked_id: str | None = None
    linked_label: str | None = None     # human label stored at write time
    syllabus: str | None = None
    tags_json: str = "[]"
    pinned_to_dashboard: bool = False
    location_json: dict | None = None   # structured navigation target for "jump to source"
    is_mistake: bool = False
    is_exam_revision: bool = False


class NoteUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    color: str | None = None
    tags_json: str | None = None
    pinned_to_dashboard: bool | None = None
    syllabus: str | None = None
    linked_type: str | None = None
    linked_id: str | None = None
    linked_label: str | None = None
    type: str | None = None
    location_json: dict | None = None
    is_mistake: bool | None = None
    is_exam_revision: bool | None = None


class PinRequest(BaseModel):
    pinned: bool = True


@router.get("/api/notes/pinned")
def get_pinned_notes(user: _CurrentUser):
    """Up to 3 pinned notes — for the dashboard widget."""
    notes = _udb.get_pinned_notes(user["id"], limit=3)
    return {"notes": notes}


@router.get("/api/notes")
def list_notes(user: _CurrentUser,
               syllabus: str | None = None,
               type: str | None = None,
               linked_type: str | None = None,
               linked_id: str | None = None,
               pinned: bool | None = None,
               is_mistake: bool | None = None,
               is_exam_revision: bool | None = None,
               q: str | None = None,
               limit: int = 50,
               offset: int = 0):
    notes = _udb.list_notes(
        user["id"],
        syllabus=syllabus,
        type_=type,
        linked_type=linked_type,
        linked_id=linked_id,
        pinned=pinned,
        is_mistake=is_mistake,
        is_exam_revision=is_exam_revision,
        q=q,
        limit=min(limit, 100),
        offset=offset,
    )
    return {"notes": notes, "count": len(notes)}


@router.post("/api/notes")
def create_note(req: NoteCreate, user: _CurrentUser):
    allowed_types = {"text", "sticky"}
    if req.type not in allowed_types:
        raise HTTPException(400, f"type must be one of: {', '.join(allowed_types)}")
    note = _udb.create_note(user["id"], req.model_dump())
    return note


@router.get("/api/notes/{note_id}")
def get_note(note_id: int, user: _CurrentUser):
    note = _udb.get_note(note_id, user["id"])
    if not note:
        raise HTTPException(404, "Note not found")
    return note


@router.patch("/api/notes/{note_id}")
def update_note(note_id: int, req: NoteUpdate, user: _CurrentUser):
    payload = {k: v for k, v in req.model_dump().items() if v is not None}
    note = _udb.update_note(note_id, user["id"], payload)
    if not note:
        raise HTTPException(404, "Note not found")
    return note


@router.delete("/api/notes/{note_id}")
def delete_note(note_id: int, user: _CurrentUser):
    ok = _udb.delete_note(note_id, user["id"])
    if not ok:
        raise HTTPException(404, "Note not found")
    return {"ok": True}


@router.post("/api/notes/{note_id}/pin")
def pin_note(note_id: int, req: PinRequest, user: _CurrentUser):
    note = _udb.pin_note(note_id, user["id"], req.pinned)
    if not note:
        raise HTTPException(404, "Note not found")
    return note


# ── Referrals & Points ────────────────────────────────────────────────────────

@router.get("/api/referrals/me")
def get_my_referrals(user: _CurrentUser):
    return _udb.get_user_points(user["id"])
