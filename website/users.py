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


class QuizGenReq(BaseModel):
    syllabus: str
    topic: str
    subtopic: str | None = None


@router.post("/api/quiz/generate")
def quiz_generate(req: QuizGenReq, user: _CurrentUser):
    subject = _SUBJECT_FULL.get(req.syllabus, req.syllabus)
    topic_label = f"{req.topic}" + (f" — {req.subtopic}" if req.subtopic else "")

    system = (
        f"You are a Cambridge examiner writing exam questions for {subject}.\n"
        f"Generate ONE structured question on the topic: \"{topic_label}\".\n"
        "Requirements:\n"
        "- 4-8 marks total\n"
        "- Use Cambridge command words: State, Explain, Calculate, Describe, Show that\n"
        "- Mark allocation shown in brackets, e.g. [3]\n"
        "- The question must be self-contained (no figure needed if possible)\n"
        "Output ONLY valid JSON with no extra text:\n"
        '{"question": "...", "marks": N, "mark_scheme": "..."}\n'
        "mark_scheme: bullet points of marking points (one per mark)."
    )

    text, _ = _chat([
        {"role": "system", "content": system},
        {"role": "user", "content": f"Generate a question on {topic_label}."},
    ], max_tokens=600)

    try:
        # Strip accidental markdown fences
        clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        data = json.loads(clean)
        if "question" not in data or "marks" not in data:
            raise ValueError("missing fields")
    except Exception:
        # Return raw text so the student still sees something
        data = {"question": text.strip(), "marks": None, "mark_scheme": None}

    return {
        "question": data.get("question", ""),
        "marks": data.get("marks"),
        "mark_scheme": data.get("mark_scheme"),
        "syllabus": req.syllabus,
        "topic": req.topic,
        "subtopic": req.subtopic,
    }


class QuizEvalReq(BaseModel):
    syllabus: str
    topic: str
    subtopic: str | None = None
    question: str
    mark_scheme: str | None = None
    answer: str
    marks: int | None = None


@router.post("/api/quiz/evaluate")
def quiz_evaluate(req: QuizEvalReq, user: _CurrentUser):
    if not (req.answer or "").strip():
        raise HTTPException(400, "Write your answer before submitting")

    marks_label = f"{req.marks} marks" if req.marks else "several marks"
    scheme_note = (f"Mark scheme:\n{req.mark_scheme}\n\n" if req.mark_scheme
                   else "Use your knowledge of Cambridge marking to award marks.\n\n")

    system = (
        "You are a Cambridge examiner marking a student's answer.\n"
        f"Question ({marks_label}):\n{req.question}\n\n"
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
        question_text=req.question,
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
