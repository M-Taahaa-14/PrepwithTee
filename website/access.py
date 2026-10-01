"""Access control helpers for PrepWithTee subscription tiers.

Plans (lowest to highest):
  'free'     — minimal access, tight monthly quotas
  'solo'     — PKR 1,000/mo, unlimited practice tools
  'three'    — PKR 2,000/mo, up to 3 subjects
  'all'      — PKR 3,000/mo, all subjects
  'tutoring' — PKR 20,000+/mo, everything + human teacher

Trial: any paid plan can start with a 7-day trial (plan_trial=1). Quota during
trial is capped at TRIAL_QUOTAS. After the trial period (plan_expires_at), the
effective plan falls back to 'free' automatically.

Billing cycle: quotas reset from plan_started_at, not the calendar month.
"""

import json
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException

from auth import get_current_user
import users_db as _udb

# ── Plan hierarchy ────────────────────────────────────────────────────────────

PLAN_RANK: dict[str, int] = {
    "free":     0,
    "solo":     1,
    "three":    2,
    "all":      3,
    "tutoring": 4,
}

PLAN_LABELS: dict[str, str] = {
    "free":     "Free",
    "solo":     "Solo",
    "three":    "3 Subjects",
    "all":      "All Subjects",
    "tutoring": "1-on-1 Tutoring",
}

PLAN_PRICES: dict[str, str] = {
    "solo":     "PKR 1,000/month",
    "three":    "PKR 2,000/month",
    "all":      "PKR 3,000/month",
    "tutoring": "PKR 20,000/month",
}

TRIAL_DAYS = 7
BILLING_CYCLE_DAYS = 30

# Plans that cover a fixed set of subjects (tutor, 2026-10-01: enforce Solo = 1 and
# 3 Subjects = 3 strictly). The student picks them when paying; paid access applies
# ONLY to those subjects, every other subject behaves exactly like the free plan.
# Only the admin can change the set.
PLAN_SUBJECT_LIMITS: dict[str, int] = {"solo": 1, "three": 3}


def plan_subjects(user: dict) -> list[str]:
    """The subjects a subject-limited plan covers.

    Accounts that bought the plan before subjects were recorded get their
    first N enrolled subjects (oldest first), saved so the set never drifts.
    """
    try:
        subs = json.loads(user.get("plan_subjects_json") or "[]")
    except (TypeError, ValueError):
        subs = []
    subs = [str(s) for s in subs if s]
    limit = PLAN_SUBJECT_LIMITS.get(user.get("plan") or "")
    if limit and not subs and user.get("id"):
        subs = _udb.get_enrollments(user["id"])[:limit]
        if subs:
            _udb.set_plan_subjects(user["id"], subs)
    return subs[:limit] if limit else subs


def clean_plan_subjects(plan: str, subjects: list[str] | None) -> list[str] | None:
    """Validate the subjects sent with a subject-limited plan.

    Returns the cleaned list (exactly N distinct known subject codes), None for
    plans without a subject limit, and raises 400 otherwise.
    """
    limit = PLAN_SUBJECT_LIMITS.get(plan)
    if not limit:
        return None
    clean: list[str] = []
    for code in subjects or []:
        code = str(code).strip()
        if code and code not in clean:
            clean.append(code)
    unknown = [c for c in clean if c not in _udb.BOARDS_MAP]
    if unknown:
        raise HTTPException(400, f"Unknown subject code(s): {', '.join(unknown)}")
    if len(clean) != limit:
        raise HTTPException(400, f"The {PLAN_LABELS.get(plan, plan)} plan covers exactly "
                                 f"{limit} subjects - choose {limit} (got {len(clean)}).")
    return clean


def covers_subject(user: dict, plan: str, syllabus: str | None) -> bool:
    """False when a subject-limited plan is used for a subject outside its set."""
    if not syllabus or plan not in PLAN_SUBJECT_LIMITS:
        return True
    return syllabus in plan_subjects(user)


def billing_period_start(plan_started_at: str | None) -> str:
    """Return ISO datetime of the current billing period's start.

    If plan_started_at is set we find the most recent N*30-day anniversary.
    Otherwise fall back to the calendar month.
    """
    now = datetime.now(timezone.utc)
    if not plan_started_at:
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    try:
        started = datetime.fromisoformat(plan_started_at.replace("Z", "+00:00"))
        elapsed_days = (now - started).days
        cycles_elapsed = elapsed_days // BILLING_CYCLE_DAYS
        period_start = started + timedelta(days=cycles_elapsed * BILLING_CYCLE_DAYS)
        return period_start.isoformat()
    except (ValueError, AttributeError):
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


def _plan_active(user: dict, syllabus: str | None = None) -> str:
    """Return the user's effective plan, downgrading to 'free' if expired.

    With a syllabus, a subject-limited plan ('three') counts as 'free' for any
    subject outside the ones it was bought for.
    """
    if user.get("role") in ("teacher", "admin"):
        return "all"

    try:
        fresh = _udb.get_user(user["id"])
        if fresh:
            user = fresh
    except Exception:
        pass

    plan = user.get("plan") or "free"
    expires = user.get("plan_expires_at")
    if expires and plan != "free":
        try:
            exp_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if exp_dt < datetime.now(timezone.utc):
                return "free"
        except (ValueError, AttributeError):
            pass
    if not covers_subject(user, plan, syllabus):
        return "free"
    return plan


def plan_info(user: dict) -> dict:
    """Return full plan state dict for API responses."""
    if user.get("role") in ("teacher", "admin"):
        return {"plan": "all", "trial": False, "expires_at": None, "started_at": None}
    try:
        fresh = _udb.get_user(user["id"])
        if fresh:
            user = fresh
    except Exception:
        pass

    plan = user.get("plan") or "free"
    expires = user.get("plan_expires_at")
    started = user.get("plan_started_at")
    trial = bool(user.get("plan_trial"))
    now = datetime.now(timezone.utc)
    expired = False

    if expires and plan != "free":
        try:
            exp_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if exp_dt < now:
                expired = True
                plan = "free"
                trial = False
        except (ValueError, AttributeError):
            pass

    trial_days_left = None
    if trial and expires and not expired:
        try:
            exp_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            trial_days_left = max(0, (exp_dt - now).days)
        except (ValueError, AttributeError):
            pass

    return {
        "plan": plan,
        "trial": trial,
        "trial_days_left": trial_days_left,
        "expires_at": expires,
        "started_at": started,
        "expired": expired,
        "period_start": billing_period_start(started),
        "subject_limit": PLAN_SUBJECT_LIMITS.get(plan),
        "plan_subjects": plan_subjects(user) if plan in PLAN_SUBJECT_LIMITS else [],
    }


def require_plan(min_plan: str):
    """FastAPI dependency factory. Raises 403 if the user's plan is too low."""
    def dep(user: dict = Depends(get_current_user)) -> dict:
        effective = _plan_active(user)
        if PLAN_RANK.get(effective, 0) < PLAN_RANK.get(min_plan, 0):
            raise HTTPException(
                403,
                detail={
                    "code": "upgrade_required",
                    "current_plan": effective,
                    "min_plan": min_plan,
                    "message": (
                        f"This feature requires the {PLAN_LABELS.get(min_plan, min_plan)} plan "
                        f"or higher."
                    ),
                },
            )
        return user
    return dep


def require_role(role: str):
    """FastAPI dependency factory. Raises 403 if the user's role doesn't match."""
    def dep(user: dict = Depends(get_current_user)) -> dict:
        if (user.get("role") or "student") != role:
            raise HTTPException(403, detail={"code": "wrong_role", "required": role})
        return user
    return dep


# ── Monthly quota ─────────────────────────────────────────────────────────────

# Free: intentionally tight — just enough to preview the platform
MONTHLY_QUOTAS: dict[str, dict[str, int | None]] = {
    "topical_paper": {"free": 3,  "solo": None, "three": None, "all": None},
    "yearly_paper":  {"free": None, "solo": None, "three": None, "all": None},
    "ai_tutor":      {"free": None, "solo": None, "three": None, "all": None},
    "ai_quiz":       {"free": 1,  "solo": None, "three": None, "all": None},
    "topic_test":    {"free": 2,  "solo": None, "three": None, "all": None},
    "mcq_drill":     {"free": 20, "solo": None, "three": None, "all": None},
}

# Trial: moderate — enough to evaluate the product meaningfully
TRIAL_QUOTAS: dict[str, int] = {
    "topical_paper": 8,
    "ai_tutor":      10,
    "ai_quiz":       5,
    "topic_test":    5,
    "mcq_drill":     50,
}


def _resolve_limit(user: dict, event_type: str,
                   syllabus: str | None = None) -> tuple[dict, int | None, bool]:
    """Return (fresh_user, limit, is_trial). Internal helper."""
    try:
        fresh = _udb.get_user(user["id"])
        if fresh:
            user = fresh
    except Exception:
        pass
    effective = _plan_active(user, syllabus)
    trial = bool(user.get("plan_trial")) and effective != "free"
    limit: int | None = TRIAL_QUOTAS.get(event_type) if trial else MONTHLY_QUOTAS.get(event_type, {}).get(effective)
    return user, limit, trial


def _quota_detail(user: dict, event_type: str, used: int, limit: int, trial: bool,
                  syllabus: str | None) -> dict:
    plan = _plan_active(user)
    outside = plan in PLAN_SUBJECT_LIMITS and not covers_subject(user, plan, syllabus)
    if outside:
        subs = ", ".join(plan_subjects(user))
        tail = (f"{syllabus} isn't covered by your {PLAN_LABELS.get(plan, plan)} plan "
                f"({subs}), so the free allowance applies to it. "
                f"Upgrade to {_upgrade_suggestion(plan)} to cover more subjects.")
    elif trial:
        tail = "Subscribe to a plan after your trial for unlimited access."
    else:
        tail = f"Upgrade to {_upgrade_suggestion(plan)} for more."
    suffix = "trial period" if trial else "this billing period"
    return {
        "code": "quota_exceeded",
        "event_type": event_type,
        "used": used,
        "limit": limit,
        "plan": plan,
        "trial": trial,
        "outside_plan_subjects": outside,
        "message": f"You've used {used}/{limit} {event_type.replace('_', ' ')}s {suffix}. {tail}",
    }


def check_quota_gate(user: dict, event_type: str, syllabus: str | None = None):
    """Check quota only - does NOT record usage.

    Call this before an expensive operation. If it passes, call record_quota()
    after success so a failure doesn't consume the user's allowance.
    Pass the subject: a subject-limited plan is only unlimited for its own
    subjects, and the free allowance for the others counts only their usage.
    """
    if user.get("role") in ("teacher", "admin"):
        return
    user, limit, trial = _resolve_limit(user, event_type, syllabus)
    if limit is None:
        return
    base = _plan_active(user)
    exclude = plan_subjects(user) if base in PLAN_SUBJECT_LIMITS else None
    used = _udb.count_usage_this_month(
        user["id"], event_type, billing_period_start(user.get("plan_started_at")),
        exclude_syllabi=exclude)
    if used >= limit:
        raise HTTPException(429, detail=_quota_detail(user, event_type, used, limit,
                                                      trial, syllabus))


def check_quota(user: dict, event_type: str, syllabus: str | None = None):
    """Check the billing-cycle quota and record usage atomically.

    Raises HTTP 429 if the quota is exhausted.
    Use this for operations where you want to count the attempt (e.g. API calls).
    For file generation use check_quota_gate() + record_quota() so failures don't count.
    """
    if user.get("role") in ("teacher", "admin"):
        return
    check_quota_gate(user, event_type, syllabus)
    _udb.record_usage(user["id"], event_type, syllabus)


def record_quota(user: dict, event_type: str, syllabus: str | None = None):
    """Record one usage event. Call after a successful expensive operation."""
    if user.get("role") in ("teacher", "admin"):
        return
    _udb.record_usage(user["id"], event_type, syllabus)


def _upgrade_suggestion(current_plan: str) -> str:
    if current_plan == "free":
        return "Solo (PKR 1,000/mo)"
    if current_plan == "solo":
        return "3 Subjects (PKR 2,000/mo)"
    if current_plan == "three":
        return "All Subjects (PKR 3,000/mo)"
    return "a higher plan"
