"""Free-plan limits -> upgrade card + self-serve trial.

    GET  /api/me/offer?event=topical_paper   what the limit card shows: the student's
                                             plan, whether a free trial is still open to
                                             them, what the trial and each plan include,
                                             and when the free allowance resets
    POST /api/me/trial                       start the 7-day All Subjects trial

The trial is once per account (tutor, 2026-10-05): it grants 'all' with
access.TRIAL_QUOTAS for TRIAL_DAYS, then access._plan_active falls back to free
when plan_expires_at passes. "Once" is remembered as a usage_events row
(event_type 'trial_started'), so no schema change is needed.
The card itself is static/limit-card.js.
"""

import threading
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

import access as _access
import billing as _billing
import users_db as _udb
from auth import get_current_user

router = APIRouter()

TRIAL_EVENT = "trial_started"
TRIAL_PLAN = "all"
_TRIAL_LOCK = threading.Lock()

# What each feature is called on the card (event_type -> words).
FEATURES: dict[str, dict] = {
    "topical_paper": {"name": "topical papers", "one": "topical paper", "icon": "📑"},
    "topic_test":    {"name": "mock tests", "one": "mock test", "icon": "🧪"},
    "ai_quiz":       {"name": "AI quizzes", "one": "AI quiz", "icon": "🧠"},
    "mcq_drill":     {"name": "MCQ drills", "one": "MCQ drill", "icon": "⚡"},
    "ai_tutor":      {"name": "AI Tutor questions", "one": "AI Tutor question", "icon": "🤖"},
    "ai_explain":    {"name": "worked solutions", "one": "worked solution", "icon": "💡"},
    "ai_hint":       {"name": "step-by-step hints", "one": "hint", "icon": "🧭"},
    "ai_followup":   {"name": "follow-up questions", "one": "follow-up", "icon": "💬"},
}

# Shown on the plan tiles; kept in step with pricing.html.
PLAN_PERKS: dict[str, list[str]] = {
    "solo": ["Unlimited topical papers & mock tests", "Every worked solution, hints & follow-ups",
             "Unlimited AI Tutor", "1 subject of your choice"],
    "three": ["Everything in Solo", "3 subjects of your choice", "Flashcards & notes for all 3"],
    "all": ["Everything, for every subject", "MCQ live solver", "Priority support"],
}

TRIAL_INCLUDES = [
    ("topical_paper", _access.TRIAL_QUOTAS.get("topical_paper")),
    ("topic_test", _access.TRIAL_QUOTAS.get("topic_test")),
    ("ai_explain", None),
    ("ai_hint", None),
    ("mcq_drill", _access.TRIAL_QUOTAS.get("mcq_drill")),
    ("ai_quiz", _access.TRIAL_QUOTAS.get("ai_quiz")),
]


def _trial_used(user_id: str) -> bool:
    return _udb.count_usage_this_month(user_id, TRIAL_EVENT, "2000-01-01T00:00:00+00:00") > 0


def trial_eligible(user: dict) -> bool:
    """A student on the free plan who has never had a trial."""
    if (user.get("role") or "student") != "student":
        return False
    fresh = _udb.get_user(user["id"]) or user
    if _access._plan_active(fresh) != "free":
        return False
    return not _trial_used(user["id"])


def _trial_items() -> list[dict]:
    import ai_help as _ai
    out = []
    for ev, n in TRIAL_INCLUDES:
        if ev in ("ai_explain", "ai_hint"):
            n = _ai.TRIAL_LIMITS.get(ev)
        f = FEATURES[ev]
        out.append({"event": ev, "icon": f["icon"], "count": n, "label": f["name"]})
    return out


@router.get("/api/me/offer")
def offer(event: str | None = Query(None, max_length=40), syllabus: str | None = Query(None, max_length=8),
          user: dict = Depends(get_current_user)):
    info = _access.plan_info(user)
    plan = info["plan"]
    feat = FEATURES.get(event or "", {"name": "this feature", "one": "use", "icon": "✨"})
    used = limit = None
    if event in _access.MONTHLY_QUOTAS:
        limit = (_access.TRIAL_QUOTAS.get(event) if info.get("trial")
                 else _access.MONTHLY_QUOTAS[event].get(plan))
        used = _udb.count_usage_this_month(user["id"], event, info.get("period_start"))
    resets = None
    try:
        start = datetime.fromisoformat(str(info["period_start"]).replace("Z", "+00:00"))
        resets = (start + timedelta(days=_access.BILLING_CYCLE_DAYS)).date().isoformat()
    except (KeyError, TypeError, ValueError):
        pass
    monthly = _billing.PERIODS["monthly"]["amount"]
    order = ["solo", "three", "all"]
    rank = _access.PLAN_RANK.get(plan, 0)
    plans = [{"id": p, "label": _access.PLAN_LABELS[p], "price": monthly[p],
              "perks": PLAN_PERKS[p], "best": p == "three",
              "url": f"/pricing.html?plan={p}#plans"}
             for p in order if _access.PLAN_RANK[p] > rank or info.get("trial")]
    return {
        "plan": plan, "plan_label": _access.PLAN_LABELS.get(plan, plan),
        "trial": bool(info.get("trial")), "trial_days_left": info.get("trial_days_left"),
        "expires_at": info.get("expires_at"),
        "trial_eligible": trial_eligible(user),
        "trial_days": _access.TRIAL_DAYS, "trial_plan": _access.PLAN_LABELS[TRIAL_PLAN],
        "trial_includes": _trial_items(),
        "feature": {"event": event, **feat}, "used": used, "limit": limit,
        "resets_on": resets, "plans": plans, "pricing_url": "/pricing.html#plans",
    }


@router.post("/api/me/trial")
def start_trial(user: dict = Depends(get_current_user)):
    if (user.get("role") or "student") != "student":
        raise HTTPException(403, "Trials are for student accounts.")
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=_access.TRIAL_DAYS)
    with _TRIAL_LOCK:                     # a double click can never grant two trials
        if not trial_eligible(user):
            raise HTTPException(409, {"code": "trial_used",
                                      "message": "You've already had your free trial - pick a plan to keep going."})
        _udb.record_usage(user["id"], TRIAL_EVENT)
        _udb.update_user_plan(user["id"], TRIAL_PLAN, expires.isoformat(),
                              started_at=now.isoformat(), trial=True)
    return {"ok": True, "plan": TRIAL_PLAN, "plan_label": _access.PLAN_LABELS[TRIAL_PLAN],
            "trial": True, "expires_at": expires.isoformat(), "days": _access.TRIAL_DAYS}
