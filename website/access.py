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

from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException

from .auth import get_current_user
from . import users_db as _udb

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


def _plan_active(user: dict) -> str:
    """Return the user's effective plan, downgrading to 'free' if expired."""
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


def _resolve_limit(user: dict, event_type: str) -> tuple[dict, int | None, bool]:
    """Return (fresh_user, limit, is_trial). Internal helper."""
    try:
        fresh = _udb.get_user(user["id"])
        if fresh:
            user = fresh
    except Exception:
        pass
    effective = _plan_active(user)
    trial = bool(user.get("plan_trial")) and effective != "free"
    limit: int | None = TRIAL_QUOTAS.get(event_type) if trial else MONTHLY_QUOTAS.get(event_type, {}).get(effective)
    return user, limit, trial


def check_quota(user: dict, event_type: str):
    """Check the billing-cycle quota and record usage atomically.

    Raises HTTP 429 if the quota is exhausted.
    Use this for operations where you want to count the attempt (e.g. API calls).
    For file generation use check_quota_gate() + record_quota() so failures don't count.
    """
    if user.get("role") in ("teacher", "admin"):
        return
    user, limit, trial = _resolve_limit(user, event_type)
    period_start = billing_period_start(user.get("plan_started_at"))
    if limit is not None:
        used = _udb.count_usage_this_month(user["id"], event_type, period_start)
        if used >= limit:
            suffix = "trial period" if trial else "this billing period"
            raise HTTPException(
                429,
                detail={
                    "code": "quota_exceeded",
                    "event_type": event_type,
                    "used": used,
                    "limit": limit,
                    "plan": _plan_active(user),
                    "trial": trial,
                    "message": (
                        f"You've used {used}/{limit} {event_type.replace('_', ' ')}s "
                        f"{suffix}. "
                        + (
                            "Subscribe to a plan after your trial for unlimited access."
                            if trial
                            else f"Upgrade to {_upgrade_suggestion(_plan_active(user))} for more."
                        )
                    ),
                },
            )
    _udb.record_usage(user["id"], event_type)


def check_quota_gate(user: dict, event_type: str):
    """Check quota only — does NOT record usage.

    Call this before an expensive operation. If it passes, call record_quota()
    after success so a failure doesn't consume the user's allowance.
    """
    if user.get("role") in ("teacher", "admin"):
        return
    user, limit, trial = _resolve_limit(user, event_type)
    period_start = billing_period_start(user.get("plan_started_at"))
    if limit is not None:
        used = _udb.count_usage_this_month(user["id"], event_type, period_start)
        if used >= limit:
            suffix = "trial period" if trial else "this billing period"
            raise HTTPException(
                429,
                detail={
                    "code": "quota_exceeded",
                    "event_type": event_type,
                    "used": used,
                    "limit": limit,
                    "plan": _plan_active(user),
                    "trial": trial,
                    "message": (
                        f"You've used {used}/{limit} {event_type.replace('_', ' ')}s "
                        f"{suffix}. "
                        + (
                            "Subscribe to a plan after your trial for unlimited access."
                            if trial
                            else f"Upgrade to {_upgrade_suggestion(_plan_active(user))} for more."
                        )
                    ),
                },
            )


def record_quota(user: dict, event_type: str):
    """Record one usage event. Call after a successful expensive operation."""
    if user.get("role") in ("teacher", "admin"):
        return
    _udb.record_usage(user["id"], event_type)


def _upgrade_suggestion(current_plan: str) -> str:
    if current_plan == "free":
        return "Solo (PKR 1,000/mo)"
    if current_plan == "solo":
        return "3 Subjects (PKR 2,000/mo)"
    if current_plan == "three":
        return "All Subjects (PKR 3,000/mo)"
    return "a higher plan"
