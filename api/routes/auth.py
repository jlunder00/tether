from __future__ import annotations


from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from api.auth import (
    auth_dependency,
    create_jwt,
    get_user_db_path,
    hash_password,
    verify_password,
)
import api.config as cfg
from db.auth_queries import (
    create_invite_token,
    create_oauth_connection,
    create_user,
    get_invite_tokens,
    get_user_by_email,
    get_user_by_oauth,
    get_user_by_username,
    get_user_count,
    set_telegram_connection,
    use_invite_token,
    verify_and_consume_link_code,
)
from db.auth_schema import init_auth_db
from db.schema import init_db
from db.queries import seed_default_anchors, seed_kanban_columns


def _init_user_db(user_db_path):
    """Initialize a new user's DB with schema, default anchors, and kanban columns."""
    init_db(user_db_path)
    seed_default_anchors(user_db_path)
    seed_kanban_columns(user_db_path)

router = APIRouter()

_COOKIE_NAME = "tether_token"
_COOKIE_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=_COOKIE_MAX_AGE,
    )


def _safe_user(user: dict) -> dict:
    return {
        "user_id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "is_admin": bool(user["is_admin"]),
    }


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

class RegisterBody(BaseModel):
    username: str
    email: str
    password: str
    invite_token: str | None = None


@router.post("/auth/register")
async def register(body: RegisterBody, response: Response):
    count = get_user_count(cfg.AUTH_DB_PATH)
    is_admin = False

    if count == 0:
        # First user — no invite needed, becomes admin
        is_admin = True
    else:
        if not body.invite_token:
            raise HTTPException(status_code=400, detail="invite_token required")
        # Validate token exists and is not expired/used (use a placeholder user_id for now)
        # We do a pre-check without consuming it yet
        import sqlite3
        from db.auth_schema import get_auth_db
        now = datetime.now(timezone.utc).isoformat()
        with get_auth_db(cfg.AUTH_DB_PATH) as conn:
            row = conn.execute(
                "SELECT used_by, expires_at FROM invite_tokens WHERE token = ?",
                (body.invite_token,),
            ).fetchone()
        if row is None or row["used_by"] is not None or row["expires_at"] < now:
            raise HTTPException(status_code=400, detail="Invalid or expired invite token")

    # Check uniqueness
    if get_user_by_email(cfg.AUTH_DB_PATH, body.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    if get_user_by_username(cfg.AUTH_DB_PATH, body.username):
        raise HTTPException(status_code=400, detail="Username already taken")

    password_hash = hash_password(body.password)
    user = create_user(cfg.AUTH_DB_PATH, body.username, body.email, password_hash, is_admin=is_admin)

    # Consume invite token now that user exists
    if count > 0 and body.invite_token:
        use_invite_token(cfg.AUTH_DB_PATH, body.invite_token, user["id"])

    # Create the user's personal DB
    user_db_path = get_user_db_path(user["id"])
    _init_user_db(user_db_path)

    token = create_jwt(user["id"], user["username"], bool(user["is_admin"]))
    _set_auth_cookie(response, token)
    return _safe_user(user)


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

class LoginBody(BaseModel):
    login: str  # email or username
    password: str


@router.post("/auth/login")
async def login(body: LoginBody, response: Response):
    # Try email first, then username
    user = get_user_by_email(cfg.AUTH_DB_PATH, body.login)
    if user is None:
        user = get_user_by_username(cfg.AUTH_DB_PATH, body.login)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.get("password_hash"):
        raise HTTPException(status_code=401, detail="Account uses OAuth login")
    if not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_jwt(user["id"], user["username"], bool(user["is_admin"]))
    _set_auth_cookie(response, token)
    return _safe_user(user)


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

@router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie(_COOKIE_NAME)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Me
# ---------------------------------------------------------------------------

@router.get("/auth/me")
async def me(request: Request, _auth=Depends(auth_dependency)):
    return {
        "user_id": request.state.user_id,
        "username": request.state.username,
        "is_admin": request.state.is_admin,
    }


# ---------------------------------------------------------------------------
# GitHub OAuth
# ---------------------------------------------------------------------------

@router.get("/auth/github")
async def github_oauth():
    if not cfg.GITHUB_CLIENT_ID:
        raise HTTPException(status_code=404, detail="OAuth not configured")
    callback_url = cfg.GITHUB_CALLBACK_URL
    url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={cfg.GITHUB_CLIENT_ID}"
        f"&redirect_uri={callback_url}"
        f"&scope=user:email"
    )
    return RedirectResponse(url)


@router.get("/auth/github/callback")
async def github_callback(code: str, request: Request):
    if not cfg.GITHUB_CLIENT_ID or not cfg.GITHUB_CLIENT_SECRET:
        raise HTTPException(status_code=404, detail="OAuth not configured")

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": cfg.GITHUB_CLIENT_ID,
                "client_secret": cfg.GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": cfg.GITHUB_CALLBACK_URL,
            },
            headers={"Accept": "application/json"},
        )
        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(status_code=400, detail="GitHub OAuth failed")

        user_resp = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        github_user = user_resp.json()

    provider_user_id = str(github_user["id"])
    user = get_user_by_oauth(cfg.AUTH_DB_PATH, "github", provider_user_id)

    if user is None:
        # Create a new user
        username = github_user.get("login", f"github_{provider_user_id}")
        email = github_user.get("email") or f"{provider_user_id}@github.invalid"

        # Ensure unique username/email
        if get_user_by_username(cfg.AUTH_DB_PATH, username):
            username = f"{username}_{provider_user_id}"
        if get_user_by_email(cfg.AUTH_DB_PATH, email):
            email = f"{provider_user_id}@github.invalid"

        count = get_user_count(cfg.AUTH_DB_PATH)
        user = create_user(cfg.AUTH_DB_PATH, username, email, password_hash=None, is_admin=(count == 0))
        create_oauth_connection(cfg.AUTH_DB_PATH, user["id"], "github", provider_user_id, access_token)
        user_db_path = get_user_db_path(user["id"])
        _init_user_db(user_db_path)

    token = create_jwt(user["id"], user["username"], bool(user["is_admin"]))
    response = RedirectResponse("/plan/day")
    _set_auth_cookie(response, token)
    return response


# ---------------------------------------------------------------------------
# Google OAuth
# ---------------------------------------------------------------------------

@router.get("/auth/google")
async def google_oauth():
    if not cfg.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=404, detail="OAuth not configured")
    url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={cfg.GOOGLE_CLIENT_ID}"
        f"&redirect_uri={cfg.GOOGLE_CALLBACK_URL}"
        "&response_type=code"
        "&scope=openid%20email%20profile"
    )
    return RedirectResponse(url)


@router.get("/auth/google/callback")
async def google_callback(code: str, request: Request):
    if not cfg.GOOGLE_CLIENT_ID or not cfg.GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=404, detail="OAuth not configured")

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": cfg.GOOGLE_CLIENT_ID,
                "client_secret": cfg.GOOGLE_CLIENT_SECRET,
                "code": code,
                "redirect_uri": cfg.GOOGLE_CALLBACK_URL,
                "grant_type": "authorization_code",
            },
        )
        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(status_code=400, detail="Google OAuth failed")

        user_resp = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        google_user = user_resp.json()

    provider_user_id = str(google_user["id"])
    user = get_user_by_oauth(cfg.AUTH_DB_PATH, "google", provider_user_id)

    if user is None:
        email = google_user.get("email", f"{provider_user_id}@google.invalid")
        username_base = email.split("@")[0]
        username = username_base

        if get_user_by_username(cfg.AUTH_DB_PATH, username):
            username = f"{username_base}_{provider_user_id}"
        if get_user_by_email(cfg.AUTH_DB_PATH, email):
            email = f"{provider_user_id}@google.invalid"

        count = get_user_count(cfg.AUTH_DB_PATH)
        user = create_user(cfg.AUTH_DB_PATH, username, email, password_hash=None, is_admin=(count == 0))
        create_oauth_connection(cfg.AUTH_DB_PATH, user["id"], "google", provider_user_id, access_token)
        user_db_path = get_user_db_path(user["id"])
        _init_user_db(user_db_path)

    token = create_jwt(user["id"], user["username"], bool(user["is_admin"]))
    response = RedirectResponse("/plan/day")
    _set_auth_cookie(response, token)
    return response


# ---------------------------------------------------------------------------
# Invite tokens (admin only)
# ---------------------------------------------------------------------------

@router.post("/auth/invite")
async def create_invite(request: Request, _auth=Depends(auth_dependency)):
    if not request.state.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    token = create_invite_token(cfg.AUTH_DB_PATH, request.state.user_id, expires_at)
    return {"token": token, "expires_at": expires_at.isoformat()}


@router.get("/auth/invites")
async def list_invites(request: Request, _auth=Depends(auth_dependency)):
    if not request.state.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    tokens = get_invite_tokens(cfg.AUTH_DB_PATH, request.state.user_id)
    return tokens


# ---------------------------------------------------------------------------
# Telegram link verification
# ---------------------------------------------------------------------------

class TelegramLinkBody(BaseModel):
    code: str


@router.post("/auth/telegram-link")
async def telegram_link(body: TelegramLinkBody, request: Request, _auth=Depends(auth_dependency)):
    """Verify a 6-digit /link code from the Telegram bot and connect the user's account."""
    chat_id = verify_and_consume_link_code(cfg.AUTH_DB_PATH, body.code)
    if chat_id is None:
        raise HTTPException(status_code=400, detail="Invalid or expired link code")
    set_telegram_connection(cfg.AUTH_DB_PATH, request.state.user_id, chat_id)
    return {"ok": True, "telegram_chat_id": chat_id}
