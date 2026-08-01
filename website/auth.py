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

from fastapi import APIRouter, Cookie, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
import bcrypt
from jose import JWTError, jwt
from pydantic import BaseModel

from . import users_db as _udb

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


# ── JWT helpers ───────────────────────────────────────────────────────────────

def _make_token(user_id: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    return jwt.encode({"sub": user_id, "exp": exp}, SECRET_KEY, algorithm=ALGORITHM)


def _set_cookie(response, user_id: str):
    token = _make_token(user_id)
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
    except JWTError:
        raise HTTPException(401, "Session expired — please sign in again")
    user = _udb.get_user(user_id)
    if not user:
        raise HTTPException(401, "Account not found")
    return user


def maybe_user(session: str | None = Cookie(None)) -> dict | None:
    """Optional dependency — returns None instead of 401."""
    try:
        return get_current_user(session)
    except HTTPException:
        return None


# ── /auth/me ─────────────────────────────────────────────────────────────────

@router.get("/auth/me")
def auth_me(session: str | None = Cookie(None)):
    user = maybe_user(session)
    if not user:
        raise HTTPException(401, "Not authenticated")
    return {k: v for k, v in user.items() if k != "password_hash"}


# ── Google OAuth ──────────────────────────────────────────────────────────────

@router.get("/auth/google")
def auth_google(request: Request):
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(503, "Google OAuth is not configured (GOOGLE_CLIENT_ID missing)")
    try:
        from authlib.integrations.requests_client import OAuth2Session
    except ImportError:
        raise HTTPException(503, "authlib is not installed")

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

    user = _udb.upsert_google_user(
        google_id=info.get("sub", ""),
        email=info.get("email", ""),
        name=info.get("name", info.get("email", "Student")),
        picture_url=info.get("picture"),
    )
    dest = "/profile.html" if not user.get("profile_complete") else "/dashboard.html"
    response = RedirectResponse(dest)
    response.delete_cookie("oauth_state")
    _set_cookie(response, user["id"])
    return response


# ── Email / password ──────────────────────────────────────────────────────────

class RegisterReq(BaseModel):
    email: str
    password: str
    name: str


class LoginReq(BaseModel):
    email: str
    password: str


@router.post("/auth/register")
def register(req: RegisterReq):
    email = (req.email or "").strip().lower()
    if not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
        raise HTTPException(400, "Invalid email address")
    if len(req.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(400, "Name is required")

    existing = _udb.get_user_by_email(email)
    if existing:
        raise HTTPException(409, "An account with that email already exists")

    pw_hash = hash_password(req.password)
    user = _udb.create_user(
        email=email,
        name=name,
        password_hash=pw_hash,
    )
    resp = JSONResponse({k: v for k, v in user.items() if k != "password_hash"})
    _set_cookie(resp, user["id"])
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
    _set_cookie(resp, user["id"])
    return resp


# ── Logout ────────────────────────────────────────────────────────────────────

@router.post("/auth/logout")
def logout():
    response = JSONResponse({"status": "logged out"})
    response.delete_cookie("session")
    return response
