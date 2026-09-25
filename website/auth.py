"""Authentication for PrepWithTee.

Google OAuth 2.0 + email/password.  Sessions are HTTP-only JWT cookies.
Supabase is the datastore; psycopg2 reads/writes the `profiles` table.

Endpoints:
  GET  /auth/google           → redirect to Google consent screen
  GET  /auth/google/callback  → exchange code → set cookie → redirect to app
  POST /auth/login            → email+password → set cookie
  POST /auth/register         → create account → set cookie
  POST /auth/logout           → clear cookie
  GET  /auth/me               → {id, email, name, ...} or 401

Cookie name: "session"  (HTTP-only, SameSite=Lax, 30-day expiry)
"""

import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
import bcrypt
from jose import JWTError, jwt
from pydantic import BaseModel

import users_db as _udb

router = APIRouter()

# ── Config ───────────────────────────────────────────────────────────────────
_DEV_SECRET = "dev-only-change-me-in-production"
SECRET_KEY = os.environ.get("SECRET_KEY", _DEV_SECRET)
ALGORITHM = "HS256"
SESSION_DAYS = 30

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8017").rstrip("/")
REDIRECT_URI = f"{APP_BASE_URL}/auth/google/callback"

# One switch drives both "are we in production" answers: whether session
# cookies may travel over plaintext, and whether the placeholder signing key
# is tolerable. Anyone who knows the placeholder can mint a cookie for any
# account, so refuse to start with it on a public origin rather than run
# something that looks fine and is wide open.
IS_HTTPS = APP_BASE_URL.startswith("https://")

if IS_HTTPS and SECRET_KEY == _DEV_SECRET:
    raise RuntimeError(
        "SECRET_KEY is still the development placeholder while APP_BASE_URL is "
        "https. Set a real SECRET_KEY (e.g. `python -c \"import secrets; "
        "print(secrets.token_urlsafe(48))\"`) before serving over HTTPS."
    )


def hash_password(password: str) -> str:
    # bcrypt silently ignores bytes past 72; truncate so long passwords
    # can't collide on their first 72 bytes.
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def _validate_password(password: str) -> None:
    """Raise 400 if the password fails strength requirements."""
    if not password or len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    if not re.search(r'[A-Za-z]', password):
        raise HTTPException(400, "Password must contain at least one letter")
    if not re.search(r'\d', password):
        raise HTTPException(400, "Password must contain at least one number")


# ── JWT helpers ───────────────────────────────────────────────────────────────

# Fields embedded in the token so /auth/me never needs a Supabase round-trip.
_FAST_FIELDS = ("id", "email", "name", "grade", "picture_url", "profile_complete",
                "birthday", "gender", "phone", "plan", "plan_expires_at", "role",
                "persona", "flags_json")


def _make_token(user_id: str, user: dict | None = None) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    payload: dict = {"sub": user_id, "exp": exp}
    if user:
        payload["u"] = {k: user[k] for k in _FAST_FIELDS
                        if k in user and user[k] is not None}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _set_cookie(response, user_id: str, user: dict | None = None):
    token = _make_token(user_id, user)
    response.set_cookie(
        "session", token,
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=IS_HTTPS,    # follows APP_BASE_URL; no manual flip to forget
    )
    return response


# ── Dependency: current user ──────────────────────────────────────────────────

def get_current_user(session: str | None = Cookie(None)) -> dict:
    if not session:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(session, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if not user_id:
            raise HTTPException(401)
        # Fast path: user data is in the token — skip the Supabase round-trip.
        if "u" in payload:
            return payload["u"]
        # Slow path: old token without embedded data.
        user = _udb.get_user(user_id)
        if not user:
            raise HTTPException(401, "Account not found")
        return user
    except JWTError:
        raise HTTPException(401, "Session expired — please sign in again")


def maybe_user(session: str | None = Cookie(None)) -> dict | None:
    """Optional dependency — returns None instead of 401."""
    try:
        return get_current_user(session)
    except HTTPException:
        return None


# ── /auth/me ─────────────────────────────────────────────────────────────────

@router.get("/auth/me")
def auth_me(session: str | None = Cookie(None), response: Response = None, fresh: bool = False):
    if not session:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(session, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if not user_id:
            raise HTTPException(401)
        # Fast path: user data is embedded in the token — zero DB round-trips.
        if "u" in payload and not fresh:
            return payload["u"]
        # Slow path/Fresh check: fetch from DB.
        user = _udb.get_user(user_id)
        if not user:
            raise HTTPException(401, "Account not found")
        # Self-heal / Update: re-issue the cookie with fresh details
        if response is not None:
            _set_cookie(response, user_id, user)
        return {k: v for k, v in user.items() if k != "password_hash"}
    except JWTError:
        raise HTTPException(401, "Session expired — please sign in again")


# ── Google OAuth ──────────────────────────────────────────────────────────────

@router.get("/auth/google")
def auth_google(request: Request, role: str = "student"):
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(503, "Google OAuth is not configured (GOOGLE_CLIENT_ID missing)")
    try:
        from authlib.integrations.requests_client import OAuth2Session
    except ImportError:
        raise HTTPException(503, "authlib is not installed")

    # Only student and parent may self-register via Google.
    safe_role = role if role in {"student", "parent"} else "student"

    oauth = OAuth2Session(
        GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
        scope="openid email profile",
        redirect_uri=REDIRECT_URI,
    )
    uri, state = oauth.create_authorization_url(
        "https://accounts.google.com/o/oauth2/auth",
        access_type="online",
    )
    response = RedirectResponse(uri)
    response.set_cookie("oauth_state", state, max_age=600, httponly=True,
                        samesite="lax", secure=IS_HTTPS)
    # Carry the chosen role through the redirect so the callback can use it
    # for new accounts (existing accounts keep whatever role they already have).
    response.set_cookie("oauth_role", safe_role, max_age=600, httponly=True,
                        samesite="lax", secure=IS_HTTPS)
    return response


@router.get("/auth/google/callback")
def auth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        return RedirectResponse("/login.html?error=google_denied")
    if not code:
        return RedirectResponse("/login.html?error=missing_code")

    stored_state = request.cookies.get("oauth_state", "")
    try:
        from authlib.integrations.requests_client import OAuth2Session
    except ImportError:
        raise HTTPException(503, "authlib is not installed")

    oauth = OAuth2Session(
        GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
        state=stored_state,
        redirect_uri=REDIRECT_URI,
    )
    try:
        oauth.fetch_token(
            "https://oauth2.googleapis.com/token",
            code=code,
        )
        info = oauth.get("https://openidconnect.googleapis.com/v1/userinfo").json()
    except Exception as exc:
        return RedirectResponse(f"/login.html?error=oauth_failed")

    # Role cookie is only used for brand-new accounts; existing accounts
    # ignore it and keep whatever role the admin assigned.
    chosen_role = request.cookies.get("oauth_role", "student")
    if chosen_role not in {"student", "parent"}:
        chosen_role = "student"

    existing_user = _udb.get_user_by_email(info.get("email", ""))
    is_new = existing_user is None
    # True when an existing email/password account is being linked to Google
    # for the very first time (they had no google_id before now).
    is_first_link = (not is_new and existing_user
                     and not existing_user.get("google_id"))

    user = _udb.upsert_google_user(
        google_id=info.get("sub", ""),
        email=info.get("email", ""),
        name=info.get("name", info.get("email", "Student")),
        picture_url=info.get("picture"),
        role=chosen_role,
    )
    if is_new:
        send_welcome_email(user)

    role = user.get("role", "student")
    if role == "admin":
        dest = "/admin.html"
    elif role == "teacher":
        dest = "/teacher-dashboard.html"
    elif role == "parent":
        dest = "/parent-dashboard.html"
    elif not user.get("profile_complete"):
        dest = "/profile.html"
    else:
        dest = "/dashboard.html"

    # Append a one-time notice so the landing page can show a toast.
    if is_first_link:
        dest += ("&" if "?" in dest else "?") + "pwt_notice=google_linked"
    elif is_new:
        dest += ("&" if "?" in dest else "?") + "pwt_notice=google_new"

    response = RedirectResponse(dest)
    response.delete_cookie("oauth_state")
    response.delete_cookie("oauth_role")
    _set_cookie(response, user["id"], user)
    return response


# ── Email / password ──────────────────────────────────────────────────────────

class RegisterReq(BaseModel):
    email: str
    password: str
    name: str
    role: str = "student"   # only "student" or "parent" accepted from self-registration


class LoginReq(BaseModel):
    email: str
    password: str


def send_welcome_email(user: dict) -> bool:
    email = (user.get("email") or "").strip()
    if not email:
        return False
    name = (user.get("name") or "Student").split()[0]
    base = "https://prepwithtee.com"

    subject = f"[PrepWithTee] Welcome, {name}! Your Cambridge prep journey starts now"

    # ── Plain-text fallback ─────────────────────────────────────────────────
    body = (
        f"Hi {name},\n\n"
        f"Welcome to PrepWithTee — Cambridge O Level, IGCSE & A Level exam prep, all in one place.\n\n"
        f"Your free account is ready. Here's what you have access to right now:\n\n"
        f"  📄  5,000+ Topical Past Paper Questions\n"
        f"      Every question sorted by chapter and topic — Physics, Maths, CS & Chemistry.\n"
        f"      Original question crops with the official mark scheme right beneath.\n\n"
        f"  🤖  AI Tutor\n"
        f"      Stuck on a concept? Ask the AI Tutor for a clear, step-by-step walkthrough\n"
        f"      tailored to Cambridge syllabi.\n\n"
        f"  📐  Formula Sheets & Study Tools\n"
        f"      169 exam formulas, a scientific calculator, periodic table, command-word\n"
        f"      glossary, graph plotter and more — all free.\n\n"
        f"  📊  Progress Tracking\n"
        f"      Mark chapters as Learning or Confident. Track past paper scores.\n"
        f"      See exactly where you stand before exam day.\n\n"
        f"  🗂️  Flashcard Spaced Repetition\n"
        f"      Build long-term memory with smart review scheduling.\n\n"
        f"── Your first three steps ──────────────────────────────────────────\n"
        f"  1. Enrol in your subjects  →  {base}/dashboard.html\n"
        f"  2. Browse topical papers    →  {base}/papers\n"
        f"  3. Try the AI Tutor         →  {base}/tutor.html\n\n"
        f"Want unlimited papers, AI queries and 1-on-1 tutoring? Upgrade at any time:\n"
        f"  {base}/pricing.html\n\n"
        f"We're here if you need anything — just reply to this email.\n\n"
        f"Good luck with your studies!\n"
        f"Tee  ·  PrepWithTee\n"
        f"{base}"
    )

    # ── Rich HTML email ─────────────────────────────────────────────────────
    features = [
        ("📄", "5,000+ Past Paper Questions",
         "Every question sorted by chapter — Physics, Maths, CS & Chemistry — "
         "with the official Cambridge mark scheme attached."),
        ("🤖", "AI Tutor",
         "Stuck on a concept? Get a clear, step-by-step explanation tailored "
         "to your exact Cambridge syllabus."),
        ("📐", "Formula Sheets & Tools",
         "169 exam formulas, scientific calculator, periodic table, graph "
         "plotter and command-word glossary — all free."),
        ("📊", "Progress Tracking",
         "Mark topics as Learning or Confident. Track paper scores. Know "
         "exactly where you stand before exam day."),
        ("🗂️", "Spaced-Repetition Flashcards",
         "Build long-term memory with smart review scheduling that surfaces "
         "the formulas you're most likely to forget."),
        ("🏆", "Achievements & Streaks",
         "Stay motivated with XP, badges and daily study streaks that make "
         "grinding for exams feel less like grinding."),
    ]

    feat_html = ""
    for icon, title, desc in features:
        feat_html += (
            f'<tr><td style="padding:0 0 16px 0">'
            f'<table cellpadding="0" cellspacing="0" width="100%"><tr>'
            f'<td style="width:40px;vertical-align:top;font-size:1.25rem;padding-top:2px">{icon}</td>'
            f'<td style="vertical-align:top;padding-left:10px">'
            f'<p style="margin:0 0 3px;font-size:.88rem;font-weight:700;color:#1a1a2e">{title}</p>'
            f'<p style="margin:0;font-size:.82rem;color:#555;line-height:1.5">{desc}</p>'
            f'</td></tr></table>'
            f'</td></tr>'
        )

    steps = [
        ("1", "Enrol in your subjects", f"{base}/dashboard.html"),
        ("2", "Browse topical past papers", f"{base}/papers"),
        ("3", "Try the AI Tutor", f"{base}/tutor.html"),
    ]
    steps_html = ""
    for num, label, url in steps:
        steps_html += (
            f'<tr><td style="padding:0 0 10px 0">'
            f'<table cellpadding="0" cellspacing="0"><tr>'
            f'<td style="width:26px;height:26px;background:#2E1B4A;border-radius:50%;'
            f'text-align:center;color:#fff;font-size:.72rem;font-weight:700;'
            f'vertical-align:middle;line-height:26px;flex-shrink:0">{num}</td>'
            f'<td style="padding-left:10px;font-size:.85rem;color:#1a1a2e;vertical-align:middle">'
            f'<a href="{url}" style="color:#2E1B4A;font-weight:600;text-decoration:none">{label}</a>'
            f'</td></tr></table>'
            f'</td></tr>'
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Welcome to PrepWithTee</title></head>
<body style="margin:0;padding:0;background:#f4f0ea;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" role="presentation">
<tr><td style="padding:32px 16px">
<table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="max-width:560px;margin:0 auto">

  <!-- Header -->
  <tr><td style="background:#2E1B4A;border-radius:14px 14px 0 0;padding:28px 32px 24px">
    <table cellpadding="0" cellspacing="0" width="100%"><tr>
      <td>
        <p style="margin:0 0 4px;color:#C9BDF0;font-size:.68rem;letter-spacing:.1em;text-transform:uppercase;font-weight:700">PrepWithTee</p>
        <h1 style="margin:0;color:#fff;font-size:1.3rem;font-weight:800;line-height:1.3">
          Welcome, {name}!<br>
          <span style="color:#E8913A">Your Cambridge prep starts today.</span>
        </h1>
      </td>
      <td style="text-align:right;padding-left:16px;width:60px">
        <img src="{base}/logo-nav.webp" width="52" height="52" alt="PrepWithTee owl" style="border-radius:10px;display:block">
      </td>
    </tr></table>
  </td></tr>

  <!-- Body -->
  <tr><td style="background:#fff;padding:28px 32px 0;border-left:1px solid #eee;border-right:1px solid #eee">
    <p style="margin:0 0 20px;font-size:.92rem;color:#333;line-height:1.6">
      PrepWithTee is a dedicated exam-prep platform for Cambridge O Level, IGCSE and A Level students —
      built around <strong>real past papers</strong>, <strong>AI-powered tutoring</strong>, and the kind of
      structured review that actually moves grades.
    </p>

    <!-- Feature list -->
    <p style="margin:0 0 14px;font-size:.78rem;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:.07em">What's inside your account</p>
    <table cellpadding="0" cellspacing="0" width="100%" role="presentation">
      {feat_html}
    </table>
  </td></tr>

  <!-- Next steps -->
  <tr><td style="background:#f9f7ff;border:1px solid #e8e0f8;border-radius:0;padding:22px 32px">
    <p style="margin:0 0 14px;font-size:.78rem;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:.07em">Your first three steps</p>
    <table cellpadding="0" cellspacing="0" width="100%" role="presentation">
      {steps_html}
    </table>
  </td></tr>

  <!-- CTA -->
  <tr><td style="background:#fff;padding:24px 32px 28px;border-left:1px solid #eee;border-right:1px solid #eee;text-align:center">
    <a href="{base}/dashboard.html" style="display:inline-block;background:#E8913A;color:#fff;
       text-decoration:none;font-weight:800;font-size:.95rem;padding:13px 32px;
       border-radius:10px;letter-spacing:.01em">Go to Your Dashboard →</a>
    <p style="margin:16px 0 0;font-size:.78rem;color:#aaa">
      Want unlimited past papers, AI queries and 1-on-1 sessions?
      <a href="{base}/pricing.html" style="color:#2E1B4A;font-weight:600">See upgrade plans →</a>
    </p>
  </td></tr>

  <!-- Footer -->
  <tr><td style="background:#2E1B4A;border-radius:0 0 14px 14px;padding:18px 32px;text-align:center">
    <p style="margin:0;color:#C9BDF0;font-size:.75rem;line-height:1.6">
      PrepWithTee &nbsp;·&nbsp; One student at a time.<br>
      <a href="{base}" style="color:#C9BDF0;text-decoration:none">{base}</a>
      &nbsp;·&nbsp;
      <a href="mailto:nexgentutors6@gmail.com" style="color:#C9BDF0;text-decoration:none">nexgentutors6@gmail.com</a>
      &nbsp;·&nbsp;
      <a href="https://wa.me/923204884375" style="color:#C9BDF0;text-decoration:none">WhatsApp</a>
    </p>
    <p style="margin:8px 0 0;color:#7B6F98;font-size:.68rem">
      Have a question or want 1-on-1 tutoring?
      <a href="https://wa.me/923204884375" style="color:#7B6F98;text-decoration:underline">Chat with us on WhatsApp</a>.<br>
      You received this because you created a PrepWithTee account.
      If this wasn't you, you can safely ignore this email.
    </p>
  </td></tr>

  <!-- Spacer -->
  <tr><td style="height:24px"></td></tr>

</table>
</td></tr></table>
</body></html>"""

    try:
        from app import _notify
        return _notify(subject, body, to=email, html_override=html)
    except Exception as exc:
        print(f"[welcome_email] failed to notify {email}: {exc}", flush=True)
        return False


@router.post("/auth/register")
def register(req: RegisterReq, request: Request):
    email = (req.email or "").strip().lower()
    if not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
        raise HTTPException(400, "Invalid email address")
    _validate_password(req.password)
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(400, "Name is required")

    allowed_self_register = {"student", "parent"}
    role = req.role if req.role in allowed_self_register else "student"

    existing = _udb.get_user_by_email(email)
    if existing:
        raise HTTPException(409, "An account with that email already exists")

    pw_hash = hash_password(req.password)
    user = _udb.create_user(
        email=email,
        name=name,
        password_hash=pw_hash,
        role=role,
    )
    send_welcome_email(user)
    ref_code = request.cookies.get("ref_code")
    if ref_code:
        _udb.record_referral(user["id"], ref_code)

    resp = JSONResponse({k: v for k, v in user.items() if k != "password_hash"})
    _set_cookie(resp, user["id"], user)
    return resp


@router.post("/auth/login")
def login(req: LoginReq):
    email = (req.email or "").strip().lower()
    user = _udb.get_user_by_email(email)
    if not user or not user.get("password_hash"):
        raise HTTPException(401, "Invalid email or password")
    if not verify_password(req.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")
    resp = JSONResponse({k: v for k, v in user.items() if k != "password_hash"})
    _set_cookie(resp, user["id"], user)
    return resp


# ── Logout ────────────────────────────────────────────────────────────────────

@router.post("/auth/logout")
def logout():
    response = JSONResponse({"status": "logged out"})
    response.delete_cookie("session")
    return response


# ── First-login / voluntary password change ───────────────────────────────────

class SetPasswordReq(BaseModel):
    password: str
    current_password: str | None = None


@router.post("/auth/set-password")
def set_password(req: SetPasswordReq, session: str | None = Cookie(None)):
    import json as _json
    user = get_current_user(session)
    _validate_password(req.password)

    flags: dict = {}
    try:
        flags = _json.loads(user.get("flags_json") or "{}")
    except (ValueError, TypeError):
        pass

    must_change = flags.get("must_change_password", False)
    if not must_change:
        if not req.current_password:
            raise HTTPException(400, "Current password is required to change it")
        db_user = _udb.get_user(user["id"])
        if not db_user or not verify_password(req.current_password,
                                              db_user.get("password_hash", "")):
            raise HTTPException(401, "Current password is incorrect")

    flags.pop("must_change_password", None)
    updated = _udb.update_profile(user["id"], {
        "password_hash": hash_password(req.password),
        "flags_json": _json.dumps(flags),
    })
    resp = JSONResponse({"ok": True, "role": updated.get("role", "student")})
    _set_cookie(resp, user["id"], updated)
    return resp


# ── Role-guard dependency factory ─────────────────────────────────────────────

def require_role(*roles: str):
    """Return a FastAPI dependency that requires the user to have one of the given roles."""
    from fastapi import Depends
    def _guard(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in roles:
            raise HTTPException(403, "Access denied")
        return user
    return Depends(_guard)


# ── Password reset ────────────────────────────────────────────────────────────

import secrets as _secrets
import smtplib as _smtplib
import logging as _logging
from email.mime.text import MIMEText as _MIMEText

_reset_log = _logging.getLogger(__name__)


def _send_reset_email(to_email: str, name: str, reset_link: str) -> None:
    subject = "Reset your PrepWithTee password"
    body = (
        f"Hi {name},\n\n"
        f"You requested a password reset for your PrepWithTee account.\n\n"
        f"Click the link below to set a new password (valid for 1 hour):\n"
        f"{reset_link}\n\n"
        f"If you did not request this, you can safely ignore this email.\n\n"
        f"PrepWithTee Team"
    )
    smtp_user = os.environ.get("SMTP_USER", "")
    resend_key = os.environ.get("RESEND_API_KEY")
    if resend_key:
        from_addr = (f"PrepWithTee <{smtp_user}>" if smtp_user else
                     "PrepWithTee <onboarding@resend.dev>")
        try:
            import requests as _req
            r = _req.post(
                "https://api.resend.com/emails",
                json={"from": from_addr, "to": [to_email],
                      "subject": subject, "text": body},
                headers={"Authorization": f"Bearer {resend_key}"},
                timeout=10,
            )
            if r.status_code < 300:
                return
            _reset_log.warning("_send_reset_email Resend %s: %s", r.status_code, r.text[:200])
        except Exception as exc:
            _reset_log.warning("_send_reset_email Resend exception: %s", exc)
    smtp_pass = os.environ.get("SMTP_PASS")
    if smtp_user and smtp_pass:
        try:
            msg = _MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = smtp_user
            msg["To"] = to_email
            with _smtplib.SMTP("smtp.gmail.com", 587, timeout=8) as srv:
                srv.starttls()
                srv.login(smtp_user, smtp_pass)
                srv.sendmail(smtp_user, to_email, msg.as_string())
            return
        except Exception as exc:
            _reset_log.warning("_send_reset_email SMTP exception: %s", exc)


class ForgotPasswordReq(BaseModel):
    email: str


class ResetPasswordReq(BaseModel):
    token: str
    new_password: str


@router.post("/auth/forgot-password")
def forgot_password(req: ForgotPasswordReq):
    email = req.email.strip().lower()
    user = _udb.get_user_by_email(email)
    if not user:
        raise HTTPException(404, "No account found with that email address.")
    if not user.get("password_hash"):
        raise HTTPException(400,
            "That account uses Google Sign-in and doesn't have a password to reset.")
    token = _secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    _udb.create_reset_token(user["id"], token, expires_at)
    reset_link = f"{APP_BASE_URL}/reset-password.html?token={token}"
    _send_reset_email(user["email"], user.get("name", "there"), reset_link)
    return {"ok": True}


@router.post("/auth/reset-password")
def reset_password(req: ResetPasswordReq, response: Response):
    record = _udb.get_reset_token(req.token)
    if not record:
        raise HTTPException(400, "Invalid or expired reset link. Please request a new one.")
    try:
        exp = datetime.fromisoformat(record["expires_at"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > exp:
            _udb.delete_reset_token(req.token)
            raise HTTPException(400, "This reset link has expired. Please request a new one.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "Invalid reset link.")
    _validate_password(req.new_password)
    pw_hash = hash_password(req.new_password)
    _udb.update_password(record["user_id"], pw_hash)
    _udb.delete_reset_token(req.token)
    user = _udb.get_user(record["user_id"])
    if user:
        _set_cookie(response, user["id"], user)
    return {"ok": True}
