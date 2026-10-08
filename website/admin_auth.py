"""Who may use the admin API, and a record of what they did.

Sign-in is the normal site session (Google or password) on an account whose
role is 'admin'. The role is read from the database on every request, not from
the session token, so taking the role away takes effect at once.

The shared admin key is for scripts only: it must be set in the environment
(no built-in default any more) and is accepted from the X-Admin-Key header
only - never a query string or cookie, where it ends up in logs and history.

Every POST/PUT/PATCH/DELETE on the admin API writes one admin_audit row:
who, what (method + route), which ids, when, and whether it succeeded.
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone

from fastapi import Cookie, Depends, Header, HTTPException, Request
from jose import JWTError, jwt as _jwt

import users_db as _udb

_JWT_SECRET = os.environ.get("SECRET_KEY", "dev-only-change-me-in-production")
_JWT_ALG = "HS256"
_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}



def admin_key() -> str:
    """Read per call so tests and a live env change are honoured."""
    return (os.environ.get("ADMIN_ACCESS_KEY") or os.environ.get("ADMIN_KEY") or "").strip()


def _session_admin(session: str | None) -> dict | None:
    if not session:
        return None
    try:
        payload = _jwt.decode(session, _JWT_SECRET, algorithms=[_JWT_ALG])
    except JWTError:
        return None
    uid = payload.get("sub")
    if not uid:
        return None
    user = _udb.get_user(uid)
    if not user or user.get("role") != "admin":
        return None
    return {"id": user["id"], "email": user.get("email"), "name": user.get("name"),
            "via": "session"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record(admin: dict, action: str, target: str | None = None,
           details: dict | None = None, ok: bool = True) -> None:
    """Write one audit row. Never lets a logging failure break the request."""
    try:
        _udb.add_admin_audit({
            "admin_id": admin.get("id"), "admin_email": admin.get("email"),
            "via": admin.get("via"), "action": action, "target": target,
            "details_json": json.dumps(details or {}, default=str)[:4000],
            "ok": 1 if ok else 0, "created_at": _now()})
    except Exception as exc:                       # pragma: no cover - logged, not raised
        print(f"[admin_audit] could not record {action}: {exc}", flush=True)


def require_admin(request: Request,
                  x_admin_key: str | None = Header(None),
                  session: str | None = Cookie(None)):
    """Dependency: the signed-in admin (or the script key). Audits mutations."""
    admin = _session_admin(session)
    if admin is None:
        key = admin_key()
        if key and x_admin_key and secrets.compare_digest(x_admin_key, key):
            admin = {"id": None, "email": None, "name": "Admin key", "via": "key"}
    if admin is None:
        raise HTTPException(401, "Sign in with an admin account")

    if request.method not in _MUTATING:
        yield admin
        return
    route = request.scope.get("route")
    action = f"{request.method} {getattr(route, 'path', request.url.path)}"
    params = dict(request.path_params)
    target = ",".join(f"{k}={v}" for k, v in params.items()) or None
    try:
        yield admin
    except Exception as exc:
        code = getattr(exc, "status_code", 500)
        record(admin, action, target, {"status": code, **params}, ok=False)
        raise
    # A route that wrote its own, more specific row (request.state.audited)
    # skips the generic "METHOD /path" one, so one action is one row.
    if not getattr(request.state, "audited", False):
        record(admin, action, target, params)
    try:                                   # the admin sees their own change at once
        import admin_students
        admin_students.invalidate()
    except Exception:
        pass
    try:                                   # teacher <-> student links may have changed
        import teaching
        teaching.clear()
    except Exception:
        pass


Admin = Depends(require_admin)
