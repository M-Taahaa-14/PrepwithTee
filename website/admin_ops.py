"""Admin console v2, phase 3: Inbox, Payments, renewals, newsletter broadcasts.

Inbox     - demo requests, contact messages, feedback and subject requests as ONE
            list, each with a status (new / replied / handled / archived) kept
            in inbox_status, and a reply-by-email that is logged on the item.
Payments  - proofs with automatic checks (billing.checks), approve = plan +
            expiry computed by billing.new_expiry + email; reject needs a reason.
            The screenshot is only served to admins (and its owner).
Newsletter- broadcasts are a background job: queued, sent in small batches with
            a pause, one newsletter_sends row per recipient, resumable.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

import access as _access
import billing as _billing
import users_db as _udb
from admin_auth import Admin, record

router = APIRouter(prefix="/api/admin")

INBOX_SOURCES = ("lead", "contact", "feedback", "request")
INBOX_STATUSES = ("new", "replied", "handled", "archived")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(raw, default):
    try:
        v = json.loads(raw) if isinstance(raw, str) else raw
        return v if v is not None else default
    except (TypeError, ValueError):
        return default


# ── Inbox ────────────────────────────────────────────────────────────────────

def _email_in(text: str | None) -> str | None:
    import re
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text or "")
    return m.group(0) if m else None


def _phone_in(text: str | None) -> str | None:
    import re
    digits = re.sub(r"[^\d+]", "", text or "")
    return text.strip() if text and len(re.sub(r"\D", "", digits)) >= 10 and "@" not in text else None


def inbox_items() -> list[dict]:
    got = _udb.gather(
        leads=lambda: _udb.get_leads(),
        contacts=lambda: _udb.get_contacts(),
        feedback=lambda: _udb.get_feedback(),
        requests=lambda: _udb.get_subject_requests(),
        status=lambda: _safe(_udb.list_inbox_status, {}),
    )
    st = got["status"]
    out = []

    def add(source, row_id, at, **item):
        s = st.get((source, str(row_id)), {})
        out.append({"key": f"{source}:{row_id}", "source": source, "id": str(row_id), "at": at,
                    "status": s.get("status") or "new", "handled_by": s.get("handled_by"),
                    "note": s.get("note"), "replies": _json(s.get("replies_json"), []),
                    "updated_at": s.get("updated_at"), **item})

    for r in got["leads"]:
        contact = r.get("contact") or ""
        add("lead", r["id"], r.get("timestamp"),
            name=r.get("parent_name") or r.get("student_name") or "Demo request",
            email=_email_in(contact), phone=_phone_in(contact),
            title=f"Demo request: {r.get('student_name') or '?'} ({r.get('grade') or 'grade?'}) - {r.get('subjects') or ''}".strip(" -"),
            body=r.get("message") or "", meta={"parent": r.get("parent_name"), "student": r.get("student_name"),
                                               "grade": r.get("grade"), "subjects": r.get("subjects"),
                                               "contact": contact})
    for r in got["contacts"]:
        add("contact", r["id"], r.get("created_at"), name=r.get("name") or r.get("email"),
            email=r.get("email"), phone=None, title=r.get("subject") or "Contact message",
            body=r.get("message") or "", meta={})
    for r in got["feedback"]:
        stars = f"{r['rating']}/5 - " if r.get("rating") else ""
        add("feedback", r["id"], r.get("ts"), name=r.get("name") or "Anonymous",
            email=r.get("email"), phone=None,
            title=f"{(r.get('type') or 'feedback').capitalize()}: {stars}{(r.get('page') or '').strip()}".strip(": "),
            body=r.get("message") or "", meta={"rating": r.get("rating"), "page": r.get("page"),
                                               "type": r.get("type"),
                                               "snips": _snips(r.get("attachments"))})
    for r in got["requests"]:
        add("request", r["id"], r.get("ts"), name="Subject request", email=None, phone=None,
            title=f"Add {r.get('subject') or '?'}" + (f" ({r['board']})" if r.get("board") else ""),
            body=r.get("message") or "", meta={"subject": r.get("subject"), "board": r.get("board")})
    out.sort(key=lambda x: x["at"] or "", reverse=True)
    return out


def _safe(fn, default):
    try:
        return fn()
    except Exception as exc:
        print(f"[admin_ops] read skipped: {exc}", flush=True)
        return default


@router.get("/inbox")
def inbox(_=Admin):
    items = inbox_items()
    counts: dict[str, dict[str, int]] = {}
    for i in items:
        c = counts.setdefault(i["source"], {})
        c[i["status"]] = c.get(i["status"], 0) + 1
    return {"items": items, "counts": counts,
            "open": sum(1 for i in items if i["status"] == "new")}


def _inbox_item(source: str, item_id: str) -> dict:
    if source not in INBOX_SOURCES:
        raise HTTPException(404, "Unknown inbox source")
    for i in inbox_items():
        if i["source"] == source and i["id"] == str(item_id):
            return i
    raise HTTPException(404, "Inbox item not found")


class InboxPatch(BaseModel):
    status: str | None = None
    note: str | None = None


@router.patch("/inbox/{source}/{item_id}")
def inbox_patch(source: str, item_id: str, req: InboxPatch, admin=Admin):
    _inbox_item(source, item_id)
    fields: dict = {}
    if req.status is not None:
        if req.status not in INBOX_STATUSES:
            raise HTTPException(400, f"status must be one of {list(INBOX_STATUSES)}")
        fields["status"] = req.status
    if req.note is not None:
        fields["note"] = req.note.strip()[:2000]
    if not fields:
        raise HTTPException(400, "Nothing to change")
    fields["handled_by"] = admin.get("email") or admin.get("name")
    return {"status": _udb.upsert_inbox_status(source, item_id, fields)}


class BulkInbox(BaseModel):
    keys: list[str]
    status: str


@router.post("/inbox/bulk")
def inbox_bulk(req: BulkInbox, admin=Admin):
    if req.status not in INBOX_STATUSES:
        raise HTTPException(400, f"status must be one of {list(INBOX_STATUSES)}")
    n = 0
    for key in req.keys[:500]:
        source, _, item_id = key.partition(":")
        if source in INBOX_SOURCES and item_id:
            _udb.upsert_inbox_status(source, item_id, {"status": req.status,
                                                       "handled_by": admin.get("email")})
            n += 1
    return {"ok": True, "done": n}


class InboxReply(BaseModel):
    subject: str
    body: str


@router.post("/inbox/{source}/{item_id}/reply")
def inbox_reply(source: str, item_id: str, req: InboxReply, admin=Admin):
    item = _inbox_item(source, item_id)
    if not item.get("email"):
        raise HTTPException(400, "This message has no email address to reply to")
    subject, body = req.subject.strip(), req.body.strip()
    if not subject or not body:
        raise HTTPException(400, "Write a subject and a message")
    from admin import _mail_html
    import html as _h
    html_body = _mail_html("".join(f'<p style="margin:0 0 14px">{_h.escape(par).replace(chr(10), "<br>")}</p>'
                                   for par in body.split("\n\n")))
    from app import _notify
    if not _notify(subject, body, to=item["email"], html_override=html_body):
        raise HTTPException(502, "The email could not be sent (check the mail settings on the server)")
    replies = item["replies"] + [{"at": _now(), "by": admin.get("email") or admin.get("name"),
                                  "subject": subject, "body": body}]
    st = _udb.upsert_inbox_status(source, item_id, {
        "status": "replied", "handled_by": admin.get("email"), "replies_json": json.dumps(replies)})
    return {"ok": True, "status": st}


# ── Payments ─────────────────────────────────────────────────────────────────

def _proof_view(p: dict, others: list[dict], users: dict[str, dict]) -> dict:
    p = dict(p)
    p["subjects"] = _json(p.get("subjects_json"), [])
    p["expected_pkr"] = p.get("expected_pkr") or _billing.expected_amount(p.get("plan"), p.get("period"))
    p["checks"] = _billing.checks(p, others)
    u = users.get(p["user_id"]) or {}
    p["student"] = {"id": p["user_id"], "name": u.get("name") or p.get("name"), "email": u.get("email") or p.get("email"),
                    "phone": u.get("phone"), "picture_url": u.get("picture_url"),
                    "plan": u.get("plan") or "free", "plan_expires_at": u.get("plan_expires_at"),
                    "plan_subjects": _json(u.get("plan_subjects_json"), [])}
    p["has_screenshot"] = bool(_billing.screenshot_path(p.get("screenshot_url")))
    p.pop("screenshot_url", None)          # served through the admin-only route
    p["period_label"] = (_billing.PERIODS.get(p.get("period") or "monthly") or {}).get("label")
    return p


@router.get("/payments")
def payments(_=Admin):
    proofs = _udb.get_payment_proofs(limit=2000)
    users = {u["id"]: u for u in _udb.fetch_all(
        "profiles", "id,name,email,phone,picture_url,plan,plan_expires_at,plan_subjects_json")}
    out = [_proof_view(p, [o for o in proofs if o["id"] != p["id"]], users) for p in proofs]
    return {"proofs": out, "periods": {k: {"label": v["label"], "amount": v["amount"]}
                                       for k, v in _billing.PERIODS.items()}}


@router.get("/payments/{proof_id}/screenshot")
def payment_screenshot(proof_id: int, _=Admin):
    p = _udb.get_payment_proof(proof_id)
    path = _billing.screenshot_path(p.get("screenshot_url")) if p else None
    if not path:
        raise HTTPException(404, "No screenshot for this proof")
    return FileResponse(path, headers={"Cache-Control": "private, no-store"})


@router.get("/feedback/snips/{name}")
def feedback_snip(name: str, _=Admin):
    """A screenshot a student snipped into feedback (stored privately by app._save_snips)."""
    import app as _app
    path = _app.snip_path(name)
    if not path:
        raise HTTPException(404, "Not found")
    return FileResponse(path, headers={"Cache-Control": "private, no-store"})


def _snips(raw) -> list[str]:
    try:
        names = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [f"/api/admin/feedback/snips/{n}" for n in names if isinstance(n, str)]


class ApproveProof(BaseModel):
    received: bool = False               # "I've seen the money in the account"
    note: str | None = None              # emailed to the student
    period: str | None = None            # override what the student picked
    subjects: list[str] | None = None    # for Solo / 3 Subjects, if missing or to correct


def _pending(proof_id: int) -> dict:
    p = _udb.get_payment_proof(proof_id)
    if not p:
        raise HTTPException(404, "Proof not found")
    if p.get("status") != "pending":
        raise HTTPException(409, "This proof has already been reviewed")
    return p


def approve_proof(proof_id: int, admin: dict, period: str | None = None,
                  subjects: list[str] | None = None, note: str | None = None) -> dict:
    """Shared by the console and the classic page's review button."""
    p = _pending(proof_id)
    period = period or p.get("period") or "monthly"
    if period not in _billing.PERIODS:
        raise HTTPException(400, f"period must be one of {list(_billing.PERIODS)}")
    plan = p["plan"]
    subs = subjects if subjects is not None else (_json(p.get("subjects_json"), []) or None)
    if plan in _access.PLAN_SUBJECT_LIMITS:
        if subs:
            subs = _access.clean_plan_subjects(plan, subs)
        else:
            student = _udb.get_user(p["user_id"]) or {}
            if len(_json(student.get("plan_subjects_json"), [])) != _access.PLAN_SUBJECT_LIMITS[plan]:
                raise HTTPException(400, f"Choose the {_access.PLAN_SUBJECT_LIMITS[plan]} subject(s) this plan covers")
            subs = None                       # keep the ones on the account
    student = _udb.get_user(p["user_id"]) or {}
    now = datetime.now(timezone.utc)
    expires = _billing.new_expiry(period, student.get("plan_expires_at"),
                                  student.get("plan") if student.get("plan") == plan else "free", now)
    _udb.update_user_plan(p["user_id"], plan, expires.isoformat(), started_at=now.isoformat(),
                          trial=False, subjects=subs)
    _udb.update_payment_proof(proof_id, {
        "status": "approved", "reviewed_at": now.isoformat(), "period": period,
        "reviewed_by": admin.get("email") or admin.get("name") or "admin",
        **({"reviewer_note": note.strip()} if note and note.strip() else {}),
        **({"subjects_json": json.dumps(subs)} if subs else {}),
    })
    emailed = False
    if student.get("email"):
        subj, text, html_body = _billing.approved_email(
            student.get("name"), plan, period, expires,
            subs or _json(student.get("plan_subjects_json"), []) or None, note)
        from app import _notify
        emailed = _notify(subj, text, to=student["email"], html_override=html_body)
        if emailed:
            _log_email(p["user_id"], "PAY_OK")
    try:
        import admin_students
        admin_students.invalidate()
    except Exception:
        pass
    return {"expires_at": expires.isoformat(), "emailed": emailed}


@router.post("/payments/{proof_id}/approve")
def payment_approve(proof_id: int, req: ApproveProof, request: Request, admin=Admin):
    if not req.received:
        raise HTTPException(400, "Confirm you've seen the money in the account before approving")
    out = approve_proof(proof_id, admin, req.period, req.subjects, req.note)
    request.state.audited = True
    record(admin, "approve payment", f"proof={proof_id}", {"expires_at": out["expires_at"],
                                                           "emailed": out["emailed"]})
    return {"ok": True, **out, "proof": _udb.get_payment_proof(proof_id)}


class RejectProof(BaseModel):
    reason: str


@router.post("/payments/{proof_id}/reject")
def payment_reject(proof_id: int, req: RejectProof, request: Request, admin=Admin):
    emailed = reject_proof(proof_id, admin, req.reason)
    request.state.audited = True
    record(admin, "reject payment", f"proof={proof_id}", {"reason": req.reason, "emailed": emailed})
    return {"ok": True, "emailed": emailed, "proof": _udb.get_payment_proof(proof_id)}


def reject_proof(proof_id: int, admin: dict, reason: str | None) -> bool:
    """Shared by the console and the classic page. Returns whether the student was emailed."""
    reason = (reason or "").strip()
    if not reason:
        raise HTTPException(400, "Give the student a reason")
    p = _pending(proof_id)
    _udb.update_payment_proof(proof_id, {"status": "rejected", "reviewed_at": _now(),
                                         "reviewed_by": admin.get("email") or "admin",
                                         "reviewer_note": reason})
    student = _udb.get_user(p["user_id"]) or {}
    emailed = False
    if student.get("email"):
        subj, text, html_body = _billing.rejected_email(student.get("name"), p["plan"], reason)
        from app import _notify
        emailed = _notify(subj, text, to=student["email"], html_override=html_body)
        if emailed:
            _log_email(p["user_id"], "PAY_NO")
    return emailed


def _log_email(user_id: str, template: str) -> None:
    try:
        _udb._insert("email_log", {"user_id": user_id, "template_id": template, "sent_at": _now()},
                     ["user_id", "template_id", "sent_at"])
    except Exception as exc:
        print(f"[admin_ops] email_log insert failed: {exc}", flush=True)


@router.get("/payments/expiring")
def payments_expiring(days: int = Query(14, ge=1, le=120), _=Admin):
    import admin_students
    rows = admin_students.apply_filters(admin_students.student_rows(), {"expiring": days})
    rows.sort(key=lambda r: r["plan_expires_at"] or "")
    return {"rows": rows}


@router.post("/students/{user_id}/renewal-reminder")
def renewal_reminder(user_id: str, _=Admin):
    u = _udb.get_user(user_id)
    if not u:
        raise HTTPException(404, "No such student")
    if not u.get("email"):
        raise HTTPException(400, "This student has no email address")
    if (u.get("plan") or "free") == "free" or not u.get("plan_expires_at"):
        raise HTTPException(400, "This student has no paid plan to renew")
    exp = _billing._parse(u["plan_expires_at"])
    days_left = (exp - datetime.now(timezone.utc)).days if exp else 0
    subj, text, html_body = _billing.reminder_email(u.get("name"), u["plan"], u["plan_expires_at"], days_left)
    from app import _notify
    if not _notify(subj, text, to=u["email"], html_override=html_body):
        raise HTTPException(502, "The email could not be sent")
    _log_email(user_id, "RENEW_MANUAL")
    return {"ok": True}


# ── Topical paper built for a student (homework) ─────────────────────────────

@router.post("/students/{user_id}/booklets")
def booklet_for_student(user_id: str, req: dict, admin=Admin):
    """Build a topical paper owned by the student, for a homework attachment.

    Same selection rules as the student's own builder, but no quota is used and
    no enrolment is needed - the tutor decides. Returns the booklet id.
    """
    import secrets
    import booklets as _b
    import catalog as _catalog
    from selection import order_recent_first, select_mixed
    student = _udb.get_user(user_id)
    if not student:
        raise HTTPException(404, "No such student")
    try:
        sel = _b.BookletReq(**req)
    except Exception as exc:                       # pydantic ValidationError
        raise HTTPException(422, str(exc).splitlines()[0][:300])
    known = _b._validate_chapters(sel)
    pool = _b.question_pool(sel)
    if not pool:
        raise HTTPException(400, "No questions match - widen the years or pick other chapters")
    seed = sel.seed if sel.seed is not None else secrets.randbits(31)
    chosen = order_recent_first(select_mixed(pool, sel.max_questions, seed))
    subj = _catalog.SUBJECTS[sel.syllabus]
    title = (("Mock test: " if sel.kind == "test" else "")
             + " · ".join(known[p.chapter]["display"] for p in sel.picks)
             + f" — {subj['plain']} {sel.syllabus}")
    bid = secrets.token_urlsafe(6)
    _udb.create_booklet({
        "id": bid, "user_id": user_id, "syllabus": sel.syllabus, "title": title, "seed": seed,
        "params_json": {**sel.model_dump(), "total_marks": sum(q["marks"] or 0 for q in chosen),
                        "set_by": admin.get("email") or "admin"},
        "question_ids": [q["id"] for q in chosen], "status": "queued", "progress": 0,
        "stage": "Picking questions"})
    if os.environ.get("APP_ENV") != "test":
        _b._EXEC.submit(_b._build_safely, bid, student, False)       # record=False: no quota used
    return {"id": bid, "title": title, "questions": len(chosen), "url": f"/papers/view/{bid}"}


# ── Newsletter ───────────────────────────────────────────────────────────────

BATCH = int(os.environ.get("NEWSLETTER_BATCH", "20"))
STALE_S = 300                      # a 'sending' broadcast with no heartbeat for 5 min is resumed
WORKER = f"{os.getpid()}-{os.urandom(3).hex()}"
PAUSE_S = float(os.environ.get("NEWSLETTER_PAUSE_S", "2"))
_worker_lock = threading.Lock()


@router.get("/newsletter/subscribers")
def nl_subscribers(_=Admin):
    return {"subscribers": _udb.get_newsletter_subscribers(limit=100000)}


class SubStatus(BaseModel):
    status: str


@router.patch("/newsletter/subscribers/{sub_id}")
def nl_subscriber_status(sub_id: int, req: SubStatus, _=Admin):
    if req.status not in ("subscribed", "unsubscribed"):
        raise HTTPException(400, "status must be subscribed or unsubscribed")
    _udb.update_newsletter_subscriber(sub_id, {
        "status": req.status, "unsubscribed_at": _now() if req.status == "unsubscribed" else None})
    return {"ok": True}


def render_newsletter(b: dict, token: str | None) -> tuple[str, str]:
    """(plain text, html) for one recipient."""
    from admin import _mail_html
    from blog import _md
    unsub = f"https://prepwithtee.com/unsubscribe?token={token}" if token else "https://prepwithtee.com/"
    body = _md(b["body_markdown"])
    footer = (f'<p style="margin:26px 0 0;font-size:.75rem;color:#999;text-align:center">'
              f'You get this because you joined the PrepWithTee list. '
              f'<a href="{unsub}" style="color:#999">Unsubscribe</a></p>')
    html_body = _mail_html(body + footer, b.get("cta_label") or "", b.get("cta_url") or "")
    text = f"{b['body_markdown']}\n\n---\nUnsubscribe: {unsub}\n"
    return text, html_body


class BroadcastIn(BaseModel):
    subject: str
    body_markdown: str
    cta_label: str | None = None
    cta_url: str | None = None
    scheduled_at: str | None = None      # ISO; empty = now
    test_email: str | None = None        # send ONE copy here instead of queueing


@router.post("/newsletter/broadcasts")
def nl_create(req: BroadcastIn, admin=Admin):
    subject, body = req.subject.strip(), req.body_markdown.strip()
    if not subject or not body:
        raise HTTPException(400, "Write a subject and a message")
    if req.cta_url and not req.cta_url.startswith(("https://", "http://", "/")):
        raise HTTPException(400, "The button link must start with https://")
    b = {"subject": subject, "body_markdown": body, "cta_label": (req.cta_label or "").strip() or None,
         "cta_url": (req.cta_url or "").strip() or None}
    if req.test_email:
        text, html_body = render_newsletter(b, None)
        from app import _notify
        if not _notify(f"[TEST] {subject}", text, to=req.test_email.strip(), html_override=html_body):
            raise HTTPException(502, "The test email could not be sent")
        return {"ok": True, "test": True}
    if req.scheduled_at:
        when = _billing._parse(req.scheduled_at)
        if not when:
            raise HTTPException(400, "scheduled_at must be an ISO date-time")
        b["scheduled_at"] = when.isoformat()
    b.update(status="queued", created_by=admin.get("email") or admin.get("name"),
             total=len(_udb.get_newsletter_subscribers(limit=100000, active_only=True)))
    row = _udb.create_broadcast(b)
    if not b.get("scheduled_at"):
        kick()
    return {"ok": True, "broadcast": _udb.get_broadcast(row["id"])}


class PreviewIn(BaseModel):
    body_markdown: str
    cta_label: str | None = None
    cta_url: str | None = None


@router.post("/newsletter/preview")
def nl_preview(req: PreviewIn, _=Admin):
    _, html_body = render_newsletter({"body_markdown": req.body_markdown, "cta_label": req.cta_label,
                                      "cta_url": req.cta_url}, "preview")
    return {"html": html_body}


@router.get("/newsletter/broadcasts")
def nl_list(_=Admin):
    return {"broadcasts": _udb.list_broadcasts()}


@router.post("/newsletter/broadcasts/{bid}/cancel")
def nl_cancel(bid: int, _=Admin):
    b = _udb.get_broadcast(bid)
    if not b:
        raise HTTPException(404, "Broadcast not found")
    if b["status"] not in ("queued", "sending"):
        raise HTTPException(409, f"This broadcast is already {b['status']}")
    _udb.update_broadcast(bid, {"status": "cancelled", "finished_at": _now()})
    return {"ok": True}


def run_broadcast(bid: int, notify=None, pause: float | None = None) -> dict:
    """Send one broadcast to every active subscriber not yet sent to. Resumable."""
    b = _udb.get_broadcast(bid)
    if not b or b["status"] not in ("queued", "sending"):
        return b or {}
    stale = datetime.fromtimestamp(time.time() - STALE_S, timezone.utc).isoformat()
    if not _udb.claim_broadcast(bid, WORKER, stale):
        return b                              # another worker is sending it
    if notify is None:
        from app import _notify as notify
    pause = PAUSE_S if pause is None else pause
    _udb.update_broadcast(bid, {"started_at": b.get("started_at") or _now()})
    done = _udb.broadcast_sent_emails(bid)
    subs = [s for s in _udb.get_newsletter_subscribers(limit=100000, active_only=True)
            if s["email"] not in done]
    sent, failed = b.get("sent") or 0, b.get("failed") or 0
    for i, s in enumerate(subs):
        if i and i % BATCH == 0:
            cur = _udb.get_broadcast(bid)
            if cur and cur["status"] == "cancelled":
                return cur
            _udb.update_broadcast(bid, {"sent": sent, "failed": failed, "heartbeat_at": _now()})
            time.sleep(pause)
        text, html_body = render_newsletter(b, s.get("unsubscribe_token"))
        try:
            ok = bool(notify(b["subject"], text, to=s["email"], html_override=html_body))
            err = None if ok else "not sent"
        except Exception as exc:              # one bad address never stops the run
            ok, err = False, str(exc)[:300]
        _udb.log_broadcast_send(bid, s["email"], ok, err)
        sent, failed = sent + ok, failed + (not ok)
    _udb.update_broadcast(bid, {"status": "sent" if sent or not failed else "failed",
                                "sent": sent, "failed": failed, "finished_at": _now(),
                                "total": sent + failed})
    return _udb.get_broadcast(bid)


def due_broadcasts() -> list[int]:
    now = _now()
    return [b["id"] for b in _udb.list_broadcasts()
            if b["status"] in ("queued", "sending") and (not b.get("scheduled_at") or b["scheduled_at"] <= now)]


def _work() -> None:
    if not _worker_lock.acquire(blocking=False):
        return                                # another run is already going
    try:
        for bid in due_broadcasts():
            try:
                run_broadcast(bid)
            except Exception as exc:
                print(f"[newsletter] broadcast {bid} failed: {exc}", flush=True)
                _udb.update_broadcast(bid, {"status": "failed", "error": str(exc)[:500]})
    finally:
        _worker_lock.release()


def kick() -> None:
    """Start sending now (in the background), unless running under tests."""
    if os.environ.get("APP_ENV") != "test":
        threading.Thread(target=_work, name="newsletter-send", daemon=True).start()


def _scheduler() -> None:
    while True:
        time.sleep(60)
        try:
            _work()
        except Exception as exc:
            print(f"[newsletter] scheduler: {exc}", flush=True)


if os.environ.get("APP_ENV") != "test":
    threading.Thread(target=_scheduler, name="newsletter-scheduler", daemon=True).start()
