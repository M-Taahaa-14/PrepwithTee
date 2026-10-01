"""Admin console v2: the Students table, a student's activity, the Overview.

Everything the new console lists is built here from bulk reads (one paged
read per table, never one query per student), then filtered, sorted and paged
in Python against a WHITELIST of columns - no client string ever reaches SQL.

The enriched student table is cached for CACHE_S seconds; every admin
mutation clears it, so a change shows at once in the admin's own view.
"""

from __future__ import annotations

import csv
import io
import json
import threading
import time
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel

import access as _access
import streaks as _streaks
import users_db as _udb
from admin_auth import Admin, record

router = APIRouter(prefix="/api/admin")

CACHE_S = 60
_cache: dict = {"at": 0.0, "rows": None}
_lock = threading.Lock()

BOARDS = {"o-level": "O Level", "igcse": "IGCSE", "a-level": "A Level"}
TZ = _streaks.zone("Asia/Karachi")

# Sortable columns -> how to read them from a row. Anything else is refused.
SORTS = {
    "name":            lambda r: (r["name"] or "").lower(),
    "email":           lambda r: (r["email"] or "").lower(),
    "created_at":      lambda r: r["created_at"] or "",
    "last_active":     lambda r: r["last_active"] or "",
    "plan":            lambda r: _access.PLAN_RANK.get(r["plan_effective"], -1),
    "plan_expires_at": lambda r: r["plan_expires_at"] or "",
    "streak":          lambda r: r["streak"],
    "minutes_7":       lambda r: r["minutes_7"],
    "booklets":        lambda r: r["booklets"],
    "mcq_avg":         lambda r: -1 if r["mcq_avg"] is None else r["mcq_avg"],
    "quiz_avg":        lambda r: -1 if r["quiz_avg"] is None else r["quiz_avg"],
    "confident_pct":   lambda r: r["confident_pct"],
    "papers_done":     lambda r: r["papers_done"],
    "open_homework":   lambda r: r["open_homework"],
    "subjects":        lambda r: len(r["subjects"]),
}
PLAN_FILTERS = {"free", "trial", "solo", "three", "all", "expired"}
ACTIVE_FILTERS = {"today", "7", "30", "inactive7", "inactive30", "never"}


# ── building the table ───────────────────────────────────────────────────────

def _day(ts) -> str | None:
    return _streaks.local_day(ts, TZ) if ts else None


def _pct(num, den) -> float | None:
    return round(100 * num / den, 1) if den else None


def _missing(p: dict, boards: list[str]) -> list[str]:
    out = []
    if not (p.get("name") or "").strip():
        out.append("name")
    if not p.get("phone"):
        out.append("WhatsApp number")
    if not boards:
        out.append("board")
    return out


def _plan_state(p: dict, now: datetime) -> tuple[str, bool]:
    """(effective plan label for filters, expired?)."""
    plan = p.get("plan") or "free"
    exp = p.get("plan_expires_at")
    if plan != "free" and exp:
        try:
            if datetime.fromisoformat(exp.replace("Z", "+00:00")) < now:
                return "expired", True
        except ValueError:
            pass
    if plan != "free" and p.get("plan_trial"):
        return "trial", False
    return plan, False


def _load() -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=45)).strftime("%Y-%m-%d")
    got = _udb.gather(
        profiles=lambda: _udb.fetch_all("profiles", eq={"role": "student"}),
        boards=lambda: _udb.fetch_all("student_boards", "user_id,board,is_primary"),
        enrolls=lambda: _udb.fetch_all("enrollments", "user_id,syllabus,status,enrolled_at"),
        progress=lambda: _udb.fetch_all("topic_progress", "user_id,status"),
        quizzes=lambda: _udb.fetch_all("quiz_sessions", "user_id,score,max_marks,created_at"),
        booklets=lambda: _udb.fetch_all("booklets", "user_id,created_at"),
        mcq=lambda: _udb.fetch_all("mcq_sessions", "user_id,status,score,total,created_at,submitted_at"),
        papers=lambda: _udb.fetch_all("paper_progress", "user_id,status,updated_at"),
        time=lambda: _udb.fetch_all("daily_time_spent", "user_id,date,seconds", gte=("date", since)),
        assignments=lambda: _udb.fetch_all("assignments", "user_id,status"),
        teachers=lambda: _udb.fetch_all("teacher_students", "teacher_id,student_id,syllabus",
                                        eq={"status": "active"}),
        teacher_names=lambda: _udb.fetch_all("profiles", "id,name,email", eq={"role": "teacher"}),
    )
    now = datetime.now(timezone.utc)
    today = _streaks.local_today(TZ)
    week_ago = (today - timedelta(days=6)).isoformat()
    rows: dict[str, dict] = {}
    for p in got["profiles"]:
        p.pop("password_hash", None)
        try:
            plan_subjects = json.loads(p.get("plan_subjects_json") or "[]")
        except (TypeError, ValueError):
            plan_subjects = []
        eff, expired = _plan_state(p, now)
        rows[p["id"]] = {
            "id": p["id"], "name": p.get("name"), "email": p.get("email"),
            "phone": p.get("phone"), "picture_url": p.get("picture_url"),
            "grade": p.get("grade"), "created_at": p.get("created_at"),
            "plan": p.get("plan") or "free", "plan_effective": eff, "plan_expired": expired,
            "plan_trial": bool(p.get("plan_trial")), "plan_expires_at": p.get("plan_expires_at"),
            "plan_subjects": plan_subjects, "boards": [], "subjects": [], "teachers": [],
            "_days": set(), "_seen": [p.get("last_seen_at"), p.get("updated_at")],
            "topics_tracked": 0, "topics_confident": 0, "quiz_count": 0, "_quiz": [],
            "booklets": 0, "mcq_sessions": 0, "_mcq": [0, 0], "papers_done": 0,
            "minutes_7": 0, "open_homework": 0, "_profile": p,
        }

    def each(key, fn):
        for r in got[key]:
            row = rows.get(r.get("user_id") or r.get("student_id"))
            if row is not None:
                fn(row, r)

    each("boards", lambda row, r: (row["boards"].insert(0, r["board"]) if r.get("is_primary")
                                   else row["boards"].append(r["board"])))
    each("enrolls", lambda row, r: row["subjects"].append(r["syllabus"])
         if r.get("status") == "active" else None)

    def prog(row, r):
        row["topics_tracked"] += 1
        row["topics_confident"] += r.get("status") == "confident"
    each("progress", prog)

    def quiz(row, r):
        row["quiz_count"] += 1
        if r.get("score") is not None and r.get("max_marks"):
            row["_quiz"].append(r["score"] / r["max_marks"])
        row["_days"].add(_day(r.get("created_at"))); row["_seen"].append(r.get("created_at"))
    each("quizzes", quiz)

    def booklet(row, r):
        row["booklets"] += 1
        row["_days"].add(_day(r.get("created_at"))); row["_seen"].append(r.get("created_at"))
    each("booklets", booklet)

    def mcq(row, r):
        row["mcq_sessions"] += 1
        if r.get("status") == "submitted" and r.get("total"):
            row["_mcq"][0] += r.get("score") or 0
            row["_mcq"][1] += r["total"]
        ts = r.get("submitted_at") or r.get("created_at")
        row["_days"].add(_day(ts)); row["_seen"].append(ts)
    each("mcq", mcq)

    def paper(row, r):
        if r.get("status") == "confident":          # "Mark done" / a submitted MCQ paper
            row["papers_done"] += 1
        row["_days"].add(_day(r.get("updated_at"))); row["_seen"].append(r.get("updated_at"))
    each("papers", paper)

    def spent(row, r):
        if (r.get("seconds") or 0) > 0:
            row["_days"].add(r["date"])
            row["_seen"].append(r["date"])
            if r["date"] >= week_ago:
                row["minutes_7"] += round((r.get("seconds") or 0) / 60)
    each("time", spent)
    each("assignments", lambda row, r: row.__setitem__(
        "open_homework", row["open_homework"] + (r.get("status") != "done")))

    tnames = {t["id"]: t.get("name") or t.get("email") for t in got["teacher_names"]}
    for t in got["teachers"]:
        row = rows.get(t["student_id"])
        if row is not None:
            name = tnames.get(t["teacher_id"], "Teacher")
            if name not in row["teachers"]:
                row["teachers"].append(name)

    out = []
    for row in rows.values():
        days = {d for d in row.pop("_days") if d}
        row["streak"], row["streak_best"] = _streaks.streaks(days, today)
        row["active_days_7"] = sum(1 for d in days if d >= week_ago)
        seen = [s for s in row.pop("_seen") if s]
        row["last_active"] = max(seen) if seen else None
        q = row.pop("_quiz")
        row["quiz_avg"] = round(100 * sum(q) / len(q), 1) if q else None
        m = row.pop("_mcq")
        row["mcq_avg"] = _pct(m[0], m[1])
        row["confident_pct"] = _pct(row["topics_confident"], row["topics_tracked"]) or 0
        row["missing_fields"] = _missing(row.pop("_profile"), row["boards"])
        out.append(row)
    return out


def student_rows(fresh: bool = False) -> list[dict]:
    with _lock:
        if not fresh and _cache["rows"] is not None and time.time() - _cache["at"] < CACHE_S:
            return _cache["rows"]
    rows = _load()
    with _lock:
        _cache.update(at=time.time(), rows=rows)
    return rows


def invalidate() -> None:
    with _lock:
        _cache.update(at=0.0, rows=None)


# ── filtering / sorting / paging ─────────────────────────────────────────────

def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


def apply_filters(rows: list[dict], f: dict) -> list[dict]:
    q = (f.get("q") or "").strip().lower()
    board, plan, subject = f.get("board"), f.get("plan"), f.get("subject")
    active, profile, teacher = f.get("active"), f.get("profile"), f.get("teacher")
    expiring = f.get("expiring")
    if plan and plan not in PLAN_FILTERS:
        raise HTTPException(400, f"plan filter must be one of {sorted(PLAN_FILTERS)}")
    if active and active not in ACTIVE_FILTERS:
        raise HTTPException(400, f"active filter must be one of {sorted(ACTIVE_FILTERS)}")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = []
    for r in rows:
        if q and q not in " ".join(str(r.get(k) or "") for k in ("name", "email", "phone")).lower():
            continue
        if board and board not in r["boards"]:
            continue
        if plan and r["plan_effective"] != plan:
            continue
        if subject and subject not in r["subjects"]:
            continue
        la = r["last_active"] or ""
        if active == "today" and not la.startswith(today):
            continue
        if active in ("7", "30") and la < _days_ago(int(active)):
            continue
        if active in ("inactive7", "inactive30") and la and la >= _days_ago(int(active[8:])):
            continue
        if active == "never" and (r["booklets"] or r["mcq_sessions"] or r["quiz_count"]
                                  or r["minutes_7"] or r["papers_done"]):
            continue
        if profile == "incomplete" and not r["missing_fields"]:
            continue
        if profile == "complete" and r["missing_fields"]:
            continue
        if teacher == "yes" and not r["teachers"]:
            continue
        if teacher == "no" and r["teachers"]:
            continue
        if expiring:
            exp = r["plan_expires_at"] or ""
            if r["plan"] == "free" or r["plan_expired"] or not exp or exp > _days_ago(-int(expiring)):
                continue
        out.append(r)
    return out


def facets(rows: list[dict]) -> dict:
    out = {"board": {}, "plan": {}, "subject": {}}
    for r in rows:
        for b in r["boards"]:
            out["board"][b] = out["board"].get(b, 0) + 1
        out["plan"][r["plan_effective"]] = out["plan"].get(r["plan_effective"], 0) + 1
        for s in r["subjects"]:
            out["subject"][s] = out["subject"].get(s, 0) + 1
    return out


def _filters(q, board, plan, subject, active, profile, teacher, expiring) -> dict:
    return {"q": q, "board": board, "plan": plan, "subject": subject, "active": active,
            "profile": profile, "teacher": teacher, "expiring": expiring}


def _sorted(rows: list[dict], sort: str, direction: str) -> list[dict]:
    if sort not in SORTS:
        raise HTTPException(400, f"sort must be one of {sorted(SORTS)}")
    return sorted(rows, key=SORTS[sort], reverse=direction != "asc")


@router.get("/students/table")
def students_table(q: str = "", board: str | None = None, plan: str | None = None,
                   subject: str | None = None, active: str | None = None,
                   profile: str | None = None, teacher: str | None = None,
                   expiring: int | None = Query(None, ge=1, le=365),
                   sort: str = "last_active", dir: str = "desc",
                   page: int = Query(1, ge=1), per: int = Query(50, ge=1, le=500),
                   fresh: bool = False, _=Admin):
    all_rows = student_rows(fresh)
    rows = _sorted(apply_filters(all_rows, _filters(q, board, plan, subject, active,
                                                    profile, teacher, expiring)), sort, dir)
    start = (page - 1) * per
    return {"rows": rows[start:start + per], "total": len(rows), "all": len(all_rows),
            "page": page, "per": per, "facets": facets(all_rows),
            "sorts": sorted(SORTS)}


CSV_COLS = ["name", "email", "phone", "boards", "subjects", "plan_effective",
            "plan_expires_at", "plan_subjects", "teachers", "streak", "minutes_7",
            "booklets", "mcq_sessions", "mcq_avg", "quiz_count", "quiz_avg",
            "confident_pct", "papers_done", "open_homework", "last_active", "created_at"]


@router.get("/students/export.csv")
def students_csv(q: str = "", board: str | None = None, plan: str | None = None,
                 subject: str | None = None, active: str | None = None,
                 profile: str | None = None, teacher: str | None = None,
                 expiring: int | None = Query(None, ge=1, le=365),
                 sort: str = "last_active", dir: str = "desc", _=Admin):
    rows = _sorted(apply_filters(student_rows(), _filters(q, board, plan, subject, active,
                                                          profile, teacher, expiring)), sort, dir)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLS)
    for r in rows:
        w.writerow(["; ".join(v) if isinstance(v, list) else ("" if v is None else v)
                    for v in (r.get(c) for c in CSV_COLS)])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="students.csv"'})


# ── bulk actions ─────────────────────────────────────────────────────────────

class BulkReq(BaseModel):
    ids: list[str]
    action: str                        # plan | assign_teacher | unassign_teacher | email
    plan: str | None = None
    subjects: list[str] | None = None
    trial: bool = False
    teacher_id: str | None = None      # teacher's profiles.id
    syllabus: str | None = None
    subject: str | None = None         # email subject line
    body: str | None = None


@router.post("/students/bulk")
def students_bulk(req: BulkReq, request: Request, admin=Admin):
    ids = list(dict.fromkeys(i for i in req.ids if i))
    if not ids:
        raise HTTPException(400, "Select at least one student")
    if len(ids) > 500:
        raise HTTPException(400, "At most 500 students per bulk action")
    known = {r["id"]: r for r in student_rows()}
    missing = [i for i in ids if i not in known]
    if missing:
        known = {r["id"]: r for r in student_rows(fresh=True)}
        missing = [i for i in ids if i not in known]
    if missing:
        raise HTTPException(404, f"{len(missing)} selected student(s) no longer exist")

    done: list[str] = []
    failed: list[dict] = []
    if req.action == "plan":
        from admin import VALID_PLANS
        if req.plan not in VALID_PLANS:
            raise HTTPException(400, f"plan must be one of {sorted(VALID_PLANS)}")
        subjects = _access.clean_plan_subjects(req.plan, req.subjects) \
            if req.plan in _access.PLAN_SUBJECT_LIMITS else None
        now = datetime.now(timezone.utc)
        if req.plan == "free":
            exp = None
        else:
            days = _access.TRIAL_DAYS if req.trial else _access.BILLING_CYCLE_DAYS
            exp = (now + timedelta(days=days)).isoformat()
        for i in ids:
            _udb.update_user_plan(i, req.plan, exp, started_at=now.isoformat(),
                                  trial=req.trial and req.plan != "free", subjects=subjects)
            done.append(i)
    elif req.action in ("assign_teacher", "unassign_teacher"):
        t = _udb.get_user(req.teacher_id or "")
        if not t or t.get("role") not in ("teacher", "admin"):
            raise HTTPException(404, "Pick a teacher account")
        if not req.syllabus and req.action == "assign_teacher":
            raise HTTPException(400, "Pick the subject this teacher takes")
        for i in ids:
            if req.action == "assign_teacher":
                _udb.assign_teacher_student(t["id"], i, req.syllabus)
                done.append(i)
            elif _udb.remove_teacher_student(t["id"], i, req.syllabus):
                done.append(i)
    elif req.action == "email":
        subject, body = (req.subject or "").strip(), (req.body or "").strip()
        if not subject or not body:
            raise HTTPException(400, "Write a subject and a message")
        from app import _notify
        for i in ids:
            r = known[i]
            if not r.get("email"):
                failed.append({"id": i, "reason": "no email"})
                continue
            first = (r.get("name") or "there").split()[0]
            text = body.replace("{first_name}", first).replace("{name}", r.get("name") or first)
            if _notify(subject, text, to=r["email"]):
                done.append(i)
                _log_email(i)
            else:
                failed.append({"id": i, "reason": "send failed"})
    else:
        raise HTTPException(400, "Unknown bulk action")
    invalidate()
    request.state.audited = True
    record(admin, f"bulk {req.action}", f"{len(done)} students",
           {"ids": ids[:50], "plan": req.plan, "teacher": req.teacher_id,
            "syllabus": req.syllabus, "subject": req.subject, "failed": len(failed)})
    return {"ok": True, "done": len(done), "failed": failed}


def _log_email(user_id: str, template: str = "MANUAL") -> None:
    try:
        _udb._insert("email_log", {"user_id": user_id, "template_id": template,
                                   "sent_at": datetime.now(timezone.utc).isoformat()},
                     ["user_id", "template_id", "sent_at"])
    except Exception as exc:
        print(f"[admin] email_log insert failed for {user_id}: {exc}", flush=True)


# ── one student: summary + activity timeline + admin notes ───────────────────

EVENT_TYPES = ("booklet", "mcq", "yearly", "quiz", "ai_help", "homework", "payment",
               "email", "note", "enrol", "tutor")


def _events(uid: str) -> tuple[list[dict], dict]:
    got = _udb.gather(
        booklets=lambda: _udb.fetch_all("booklets", "id,syllabus,title,status,params_json,created_at",
                                        eq={"user_id": uid}),
        mcq=lambda: _udb.fetch_all("mcq_sessions", "id,syllabus,kind,title,status,score,total,"
                                   "elapsed_s,created_at,submitted_at", eq={"user_id": uid}),
        papers=lambda: _udb.fetch_all("paper_progress", "syllabus,year,session,paper,variant,"
                                      "status,score,max_score,grade,set_by,updated_at",
                                      eq={"user_id": uid}),
        quizzes=lambda: _udb.fetch_all("quiz_sessions", "syllabus,topic,subtopic,score,max_marks,"
                                       "created_at", eq={"user_id": uid}),
        unlocks=lambda: _safe(lambda: _udb.fetch_all("explanation_unlocks", "question_id,unlocked_at",
                                                     eq={"user_id": uid})),
        homework=lambda: _udb.fetch_all("assignments", "id,syllabus,title,due_date,status,"
                                        "completed_at,created_at", eq={"user_id": uid}),
        payments=lambda: _udb.fetch_all("payment_proofs", "*", eq={"user_id": uid}),
        emails=lambda: _safe(lambda: _udb.fetch_all("email_log", "template_id,sent_at",
                                                    eq={"user_id": uid})),
        notes=lambda: _safe(lambda: _udb.list_admin_notes(uid)),
        enrolls=lambda: _udb.fetch_all("enrollments", "syllabus,status,enrolled_at",
                                       eq={"user_id": uid}),
        tutor=lambda: _safe(lambda: _udb.fetch_all("tutor_sessions", "id,title,subject,topic,"
                                                   "created_at,updated_at", eq={"user_id": uid})),
        time=lambda: _udb.fetch_all("daily_time_spent", "date,seconds", eq={"user_id": uid}),
    )
    ev: list[dict] = []

    def add(kind, at, text, **extra):
        if at:
            ev.append({"type": kind, "at": at, "text": text, **extra})

    for b in got["booklets"]:
        kind = "Mock test" if '"test"' in (b.get("params_json") or "") else "Booklet"
        add("booklet", b.get("created_at"), f"{kind}: {b.get('title') or b['syllabus']}",
            syllabus=b["syllabus"], status=b.get("status"), id=b["id"])
    for m in got["mcq"]:
        done = m.get("status") == "submitted"
        score = f" - {m.get('score')}/{m.get('total')}" if done and m.get("total") else ""
        add("mcq", m.get("submitted_at") or m.get("created_at"),
            f"MCQ {m.get('kind') or ''} {m.get('title') or m['syllabus']}{score}"
            f"{'' if done else ' (not finished)'}", syllabus=m["syllabus"],
            pct=_pct(m.get("score") or 0, m.get("total")) if done else None)
    for p in got["papers"]:
        ref = f"{p['syllabus']} {p['session']}{str(p['year'])[-2:]} P{p['paper']}{p.get('variant') or ''}"
        score = f" - {p['score']}/{p['max_score']}" if p.get("score") is not None and p.get("max_score") else ""
        grade = f", grade {p['grade']}" if p.get("grade") else ""
        who = " (set by tutor)" if p.get("set_by") == "tutor" else ""
        add("yearly", p.get("updated_at"), f"Yearly paper {ref}: {p.get('status')}{score}{grade}{who}",
            syllabus=p["syllabus"])
    for q in got["quizzes"]:
        score = f" - {q['score']}/{q['max_marks']}" if q.get("score") is not None and q.get("max_marks") else ""
        add("quiz", q.get("created_at"), f"AI quiz {q['syllabus']} {q['topic']}{score}",
            syllabus=q["syllabus"])
    for u in got["unlocks"]:
        add("ai_help", u.get("unlocked_at"), f"Opened a worked solution (question {u['question_id']})")
    for h in got["homework"]:
        add("homework", h.get("created_at"), f"Homework set: {h['title']}"
            + (f" (due {h['due_date']})" if h.get("due_date") else ""), status=h.get("status"))
        if h.get("completed_at"):
            add("homework", h["completed_at"], f"Homework handed in: {h['title']}")
    for pr in got["payments"]:
        add("payment", pr.get("created_at"), f"Payment proof: {pr.get('plan')}"
            + (f", PKR {pr['amount_pkr']:,}" if pr.get("amount_pkr") else "")
            + f" via {pr.get('method') or '?'} - {pr.get('status')}", status=pr.get("status"))
    for e in got["emails"]:
        add("email", e.get("sent_at"), f"Email sent: {e['template_id']}")
    for n in got["notes"]:
        add("note", n.get("created_at"), n["body"], id=n["id"], by=n.get("admin_name"))
    for e in got["enrolls"]:
        add("enrol", e.get("enrolled_at"), f"Enrolled in {e['syllabus']}"
            + ("" if e.get("status") == "active" else " (archived)"))
    for t in got["tutor"]:
        add("tutor", t.get("updated_at") or t.get("created_at"),
            f"AI tutor chat: {t.get('title') or t.get('topic') or t.get('subject') or 'untitled'}")
    ev.sort(key=lambda e: e["at"], reverse=True)
    return ev, got


def _safe(fn):
    """A table that may not exist yet (migration not run) reads as empty."""
    try:
        return fn()
    except Exception as exc:
        print(f"[admin] activity read skipped: {exc}", flush=True)
        return []


@router.get("/students/{user_id}/activity")
def student_activity(user_id: str, type: str | None = None,
                     limit: int = Query(200, ge=1, le=2000), _=Admin):
    user = _udb.get_user(user_id)
    if not user:
        raise HTTPException(404, "No such student")
    if type and type not in EVENT_TYPES:
        raise HTTPException(400, f"type must be one of {list(EVENT_TYPES)}")
    ev, got = _events(user_id)
    counts: dict[str, int] = {}
    for e in ev:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    today = _streaks.local_today(TZ)
    days = {_day(e["at"]) for e in ev if e["type"] not in ("email", "note", "payment", "enrol")}
    days |= {t["date"] for t in got["time"] if (t.get("seconds") or 0) > 0}
    days.discard(None)
    streak, best = _streaks.streaks(days, today)
    week_ago = (today - timedelta(days=6)).isoformat()
    mcq_done = [m for m in got["mcq"] if m.get("status") == "submitted" and m.get("total")]
    summary = {
        "streak": streak, "streak_best": best,
        "minutes_7": round(sum((t.get("seconds") or 0) for t in got["time"]
                               if t["date"] >= week_ago) / 60),
        "active_days_7": sum(1 for d in days if d >= week_ago),
        "booklets": len(got["booklets"]),
        "mcq_sessions": len(got["mcq"]),
        "mcq_avg": _pct(sum(m.get("score") or 0 for m in mcq_done), sum(m["total"] for m in mcq_done)),
        "papers": len(got["papers"]),
        "quizzes": len(got["quizzes"]),
        "explanations": len(got["unlocks"]),
        "open_homework": sum(1 for h in got["homework"] if h.get("status") != "done"),
        "last_active": ev[0]["at"] if ev else user.get("last_seen_at"),
        "time_by_day": sorted(({"date": t["date"], "minutes": round((t.get("seconds") or 0) / 60)}
                               for t in got["time"] if t["date"] >= (today - timedelta(days=27)).isoformat()),
                              key=lambda x: x["date"]),
    }
    events = [e for e in ev if not type or e["type"] == type][:limit]
    try:
        plan = _access.plan_info(user)
    except Exception:
        plan = {"plan": user.get("plan") or "free"}
    return {"summary": summary, "counts": counts, "events": events, "plan": plan,
            "teachers": _udb.get_student_teachers(user_id),
            "boards": [b["board"] for b in _safe(lambda: _udb.fetch_all(
                "student_boards", "board,is_primary", eq={"user_id": user_id}))]}


class NoteIn(BaseModel):
    body: str


@router.post("/students/{user_id}/notes")
def add_note(user_id: str, req: NoteIn, admin=Admin):
    if not _udb.get_user(user_id):
        raise HTTPException(404, "No such student")
    body = req.body.strip()
    if not body:
        raise HTTPException(400, "Write the note first")
    return {"note": _udb.add_admin_note(user_id, admin, body[:4000])}


@router.delete("/students/{user_id}/notes/{note_id}")
def delete_note(user_id: str, note_id: int, _=Admin):
    if not _udb.delete_admin_note(note_id, user_id):
        raise HTTPException(404, "Note not found")
    return {"ok": True}


# ── saved views ──────────────────────────────────────────────────────────────

class ViewIn(BaseModel):
    section: str
    name: str
    params: dict


@router.get("/views")
def list_views(section: str, _=Admin):
    return {"views": [{**v, "params": json.loads(v.get("params_json") or "{}")}
                      for v in _udb.list_admin_views(section)]}


@router.post("/views")
def save_view(req: ViewIn, admin=Admin):
    name = req.name.strip()[:60]
    if not name:
        raise HTTPException(400, "Name the view")
    params = {k: v for k, v in req.params.items() if isinstance(v, (str, int, float, bool))}
    v = _udb.create_admin_view(admin.get("id"), req.section[:40], name, json.dumps(params))
    return {"view": {**v, "params": params}}


@router.delete("/views/{view_id}")
def delete_view(view_id: int, _=Admin):
    if not _udb.delete_admin_view(view_id):
        raise HTTPException(404, "View not found")
    return {"ok": True}


# ── who am I / audit log ─────────────────────────────────────────────────────

@router.get("/me")
def whoami(admin=Admin):
    return {"admin": admin}


@router.get("/audit")
def audit(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), _=Admin):
    rows = _udb.list_admin_audit(limit, offset)
    for r in rows:
        try:
            r["details"] = json.loads(r.pop("details_json") or "{}")
        except (TypeError, ValueError):
            r["details"] = {}
    return {"rows": rows}


# ── Overview ─────────────────────────────────────────────────────────────────

def _inbox_new() -> int:
    try:
        import admin_ops
        return sum(1 for i in admin_ops.inbox_items() if i["status"] == "new")
    except Exception as exc:                # the overview never fails over a badge
        print(f"[admin] inbox count skipped: {exc}", flush=True)
        return 0

@router.get("/overview/stats")
def overview_stats(days: int = Query(7, ge=1, le=90), _=Admin):
    rows = student_rows()
    now = datetime.now(timezone.utc)
    cur_from, prev_from = _days_ago(days), _days_ago(2 * days)

    def window(ts):
        if not ts:
            return None
        return "cur" if ts >= cur_from else ("prev" if ts >= prev_from else None)

    signups = {"cur": 0, "prev": 0}
    active = {"cur": 0, "prev": 0}
    for r in rows:
        w = window(r["created_at"])
        if w:
            signups[w] += 1
        w = window(r["last_active"])
        if w:
            active[w] += 1

    got = _udb.gather(
        booklets=lambda: _udb.fetch_all("booklets", "user_id,title,syllabus,created_at",
                                        gte=("created_at", prev_from)),
        mcq=lambda: _udb.fetch_all("mcq_sessions", "user_id,syllabus,title,score,total,status,"
                                   "created_at,submitted_at", gte=("created_at", prev_from)),
        proofs=lambda: _udb.fetch_all("payment_proofs", "id,user_id,plan,amount_pkr,status,"
                                      "created_at,reviewed_at"),
        apps=lambda: _udb.fetch_all("teacher_applications", "id,status,created_at"),
        assignments=lambda: _udb.fetch_all("assignments", "user_id,status,due_date"),
    )
    practice = {"cur": 0, "prev": 0}
    for b in got["booklets"] + got["mcq"]:
        w = window(b.get("created_at"))
        if w:
            practice[w] += 1
    revenue = {"cur": 0, "prev": 0}
    for p in got["proofs"]:
        if p.get("status") == "approved":
            w = window(p.get("reviewed_at") or p.get("created_at"))
            if w:
                revenue[w] += p.get("amount_pkr") or 0
    pending_proofs = [p for p in got["proofs"] if p.get("status") == "pending"]
    today = now.strftime("%Y-%m-%d")
    week = (now + timedelta(days=7)).isoformat()
    expiring = [r for r in rows if r["plan"] != "free" and not r["plan_expired"]
                and r["plan_expires_at"] and r["plan_expires_at"] <= week]
    overdue = sum(1 for a in got["assignments"]
                  if a.get("status") != "done" and a.get("due_date") and a["due_date"] < today)
    names = {r["id"]: r["name"] or r["email"] for r in rows}
    feed = []
    for b in got["booklets"]:
        feed.append({"at": b["created_at"], "user_id": b["user_id"], "type": "booklet",
                     "text": f"{names.get(b['user_id'], 'Someone')} built {b.get('title') or 'a booklet'}"})
    for m in got["mcq"]:
        if m.get("status") == "submitted":
            feed.append({"at": m.get("submitted_at") or m["created_at"], "user_id": m["user_id"],
                         "type": "mcq", "text": f"{names.get(m['user_id'], 'Someone')} scored "
                                                f"{m.get('score')}/{m.get('total')} on {m.get('title') or m['syllabus']} MCQ"})
    for r in rows:
        if r["created_at"] and r["created_at"] >= cur_from:
            feed.append({"at": r["created_at"], "user_id": r["id"], "type": "signup",
                         "text": f"New sign-up: {r['name'] or r['email']}"})
    for p in got["proofs"]:
        feed.append({"at": p["created_at"], "user_id": p["user_id"], "type": "payment",
                     "text": f"Payment proof from {names.get(p['user_id'], 'a student')}: "
                             f"{p.get('plan')}" + (f", PKR {p['amount_pkr']:,}" if p.get("amount_pkr") else "")})
    feed = sorted((f for f in feed if f["at"]), key=lambda f: f["at"], reverse=True)[:25]

    by_day: dict[str, int] = {}
    for b in got["booklets"] + got["mcq"]:
        d = (b.get("created_at") or "")[:10]
        if d and b["created_at"] >= cur_from:
            by_day[d] = by_day.get(d, 0) + 1

    return {
        "days": days,
        "kpis": {
            "active": active, "signups": signups, "practice": practice, "revenue": revenue,
            "students": len(rows),
        },
        "attention": {
            "pending_proofs": len(pending_proofs),
            "oldest_proof": min((p["created_at"] for p in pending_proofs), default=None),
            "applications": sum(1 for a in got["apps"] if (a.get("status") or "pending") == "pending"),
            "expiring_7": len(expiring),
            "incomplete_profiles": sum(1 for r in rows if r["missing_fields"]),
            "overdue_homework": overdue,
            "inbox_new": _inbox_new(),
        },
        "feed": feed,
        "practice_by_day": [{"date": d, "count": by_day[d]} for d in sorted(by_day)],
    }
