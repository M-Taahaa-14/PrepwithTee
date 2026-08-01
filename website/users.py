"""User-facing API routes: profile, enrollment, progress, quiz, dashboard, teachers."""

import json
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import get_current_user, maybe_user
from . import users_db as _udb

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

@router.post("/api/profile")
def save_profile(req: ProfileUpdate, user: _CurrentUser):
    updates: dict = {}
    for field in ("grade", "birthday", "gender", "phone", "name"):
        v = getattr(req, field)
        if v is not None:
            updates[field] = v.strip()

    # Mark profile complete once we have at least grade
    if updates.get("grade") or user.get("grade"):
        updates["profile_complete"] = 1

    if not updates:
        return {k: v for k, v in user.items() if k != "password_hash"}

    updated = _udb.update_profile(user["id"], updates)
    return {k: v for k, v in updated.items() if k != "password_hash"}


# ── Enrollment ─────────────────────────────────────────────────────────────────

@router.get("/api/enrollments")
def list_enrollments(user: _CurrentUser):
    syllabuses = _udb.get_enrollments(user["id"])
    return {
        "enrollments": [
            {"syllabus": s, "name": SUBJECT_NAMES.get(s, s)}
            for s in syllabuses
        ]
    }


class EnrollReq(BaseModel):
    syllabus: str

@router.post("/api/enrollments")
def enroll(req: EnrollReq, user: _CurrentUser):
    if not re.match(r"^[0-9A-Za-z]{4,6}$", req.syllabus):
        raise HTTPException(400, "Invalid syllabus code")
    _udb.enroll(user["id"], req.syllabus)
    return {"status": "enrolled", "syllabus": req.syllabus}


@router.delete("/api/enrollments/{syllabus}")
def unenroll(syllabus: str, user: _CurrentUser):
    _udb.unenroll(user["id"], syllabus)
    return {"status": "unenrolled", "syllabus": syllabus}


# ── Topic progress ─────────────────────────────────────────────────────────────

@router.get("/api/progress")
def get_progress(syllabus: str, user: _CurrentUser):
    rows = _udb.get_progress(user["id"], syllabus)
    return {"progress": rows}


class ProgressUpdate(BaseModel):
    syllabus: str
    topic: str
    subtopic: str | None = None
    status: str  # not_started | learning | confident

@router.post("/api/progress")
def update_progress(req: ProgressUpdate, user: _CurrentUser):
    allowed = {"not_started", "learning", "confident"}
    if req.status not in allowed:
        raise HTTPException(400, f"status must be one of: {', '.join(allowed)}")
    result = _udb.upsert_progress(
        user["id"], req.syllabus, req.topic, req.subtopic, req.status
    )
    return result


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
    from .app import _chat_complete
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
    from .app import _con, _SESSION_ABBR, _USE_PG
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
def quiz_generate(req: QuizGenReq, user: _CurrentUser):
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
        from .app import _topic_samples
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
    from .app import _plain_math as impl
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
def quiz_evaluate(req: QuizEvalReq, user: _CurrentUser):
    if not (req.answer or "").strip():
        raise HTTPException(400, "Write your answer before submitting")

    question_text = req.question
    # Past-paper mode sends only an id: the student read the question from the
    # original crop, so pull its text layer for the examiner prompt.
    if req.question_id and not question_text.strip():
        try:
            from .app import _con
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


# ── Dashboard ──────────────────────────────────────────────────────────────────

@router.get("/api/dashboard")
def dashboard(user: _CurrentUser):
    enrollments = _udb.get_enrollments(user["id"])
    progress_summary = _udb.get_progress_summary(user["id"])
    recent_quizzes = _udb.get_quiz_history(user["id"], syllabus=None, limit=5)

    # Streak: consecutive days with at least one quiz
    streak = 0
    if recent_quizzes:
        from datetime import date
        days = set()
        for q in _udb.get_quiz_history(user["id"], syllabus=None, limit=50):
            created = (q.get("created_at") or "")[:10]
            if created:
                days.add(created)
        today = date.today().isoformat()
        day = today
        while day in days:
            streak += 1
            from datetime import timedelta
            day = (date.fromisoformat(day) - timedelta(days=1)).isoformat()

    return {
        "user": {k: v for k, v in user.items()
                 if k in ("id","email","name","picture_url","grade","profile_complete")},
        "enrollments": [
            {"syllabus": s, "name": SUBJECT_NAMES.get(s, s)}
            for s in enrollments
        ],
        "progress_summary": progress_summary,
        "recent_quizzes": recent_quizzes,
        "streak": streak,
    }


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
        "qualifications": (req.qualifications or "").strip() or None,
        "experience": (req.experience or "").strip() or None,
        "message": (req.message or "").strip() or None,
    }
    _udb.save_teacher_application(payload)

    # Notify admin (reuse existing helper from app.py)
    try:
        from .app import _notify
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
