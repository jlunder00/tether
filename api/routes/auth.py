from __future__ import annotations


import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from api.auth import (
    auth_dependency,
    create_jwt,
    hash_password,
    verify_password,
)
from api.limiter import limiter
from api.oauth_state import make_signed_state, verify_signed_state
import api.config as cfg
import db.postgres as pg
import db.pg_auth_queries as auth_queries
from db.pg_queries import seed_default_anchors, seed_kanban_columns


router = APIRouter()

_COOKIE_NAME = "tether_token"
_COOKIE_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


def _set_auth_cookie(response: Response, token: str) -> None:
    # samesite="lax" (not "strict"): strict breaks OAuth login because the
    # browser treats the post-callback redirect chain (google.com → tether) as
    # cross-site and won't include the cookie.  Lax allows top-level navigation
    # while still blocking CSRF from cross-origin sub-requests.
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=cfg.COOKIE_SECURE,
        samesite="lax",
        max_age=_COOKIE_MAX_AGE,
    )


def _safe_user(user: dict) -> dict:
    return {
        "user_id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "is_admin": bool(user["is_admin"]),
        "is_paid": cfg.IS_COMMUNITY_EDITION,
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
@limiter.limit("5/hour")
async def register(body: RegisterBody, response: Response, request: Request):
    pool = request.app.state.pool
    async with pg.get_conn(pool) as conn:
        count = await auth_queries.get_user_count(conn)
        is_admin = count == 0

        if not is_admin:
            if not body.invite_token:
                raise HTTPException(status_code=400, detail="invite_token required")
            # Validate token before creating user (within same transaction for atomicity)
            valid = await auth_queries.check_invite_token(conn, body.invite_token)
            if not valid:
                raise HTTPException(status_code=400, detail="Invalid or expired invite token")

        if await auth_queries.get_user_by_email(conn, body.email):
            raise HTTPException(status_code=400, detail="Email already registered")
        if await auth_queries.get_user_by_username(conn, body.username):
            raise HTTPException(status_code=400, detail="Username already taken")

        password_hash = hash_password(body.password)
        user = await auth_queries.create_user(conn, body.username, body.email, password_hash, is_admin=is_admin)

        if body.invite_token:
            ok = await auth_queries.use_invite_token(conn, body.invite_token, user["id"])
            if not ok:
                raise HTTPException(status_code=400, detail="Invalid or expired invite token")

    # Seed user data with user-scoped connection (RLS)
    try:
        async with pg.get_conn(pool, user_id=user["id"]) as user_conn:
            await seed_default_anchors(user_conn)
            await seed_kanban_columns(user_conn)
    except Exception:
        logging.getLogger(__name__).error(
            "Failed to seed defaults for new user %s — account exists but may be missing defaults",
            user["id"],
        )
        raise

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
@limiter.limit("10/minute")
async def login(body: LoginBody, response: Response, request: Request):
    pool = request.app.state.pool
    async with pg.get_conn(pool) as conn:
        # Try email first, then username
        user = await auth_queries.get_user_by_email(conn, body.login)
        if user is None:
            user = await auth_queries.get_user_by_username(conn, body.login)
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
        "is_paid": cfg.IS_COMMUNITY_EDITION,
    }


# ---------------------------------------------------------------------------
# GitHub OAuth
# ---------------------------------------------------------------------------

@router.get("/auth/github")
@limiter.limit("20/minute")
async def github_oauth(
    request: Request,
    invite_token: Optional[str] = Query(default=None),
):
    if not cfg.GITHUB_CLIENT_ID:
        raise HTTPException(status_code=404, detail="OAuth not configured")
    # Build a signed CSRF state; include invite token if provided
    payload: dict = {"invite_token": invite_token} if invite_token else {"mode": "login"}
    state = make_signed_state(payload)
    callback_url = cfg.GITHUB_CALLBACK_URL
    url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={cfg.GITHUB_CLIENT_ID}"
        f"&redirect_uri={callback_url}"
        f"&scope=user:email"
        f"&state={state}"
    )
    return RedirectResponse(url)


@router.get("/auth/github/callback")
async def github_callback(
    code: str,
    request: Request,
    state: Optional[str] = Query(default=None),
):
    if not cfg.GITHUB_CLIENT_ID or not cfg.GITHUB_CLIENT_SECRET:
        raise HTTPException(status_code=404, detail="OAuth not configured")

    # --- Validate CSRF state ---
    if not state:
        raise HTTPException(status_code=400, detail="Missing OAuth state parameter")
    try:
        state_data = verify_signed_state(state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    invite_token: Optional[str] = state_data.get("invite_token")

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

    pool = request.app.state.pool
    provider_user_id = str(github_user["id"])
    new_user = False

    async with pg.get_conn(pool) as conn:
        user = await auth_queries.get_user_by_oauth(conn, "github", provider_user_id)
        if user is None:
            # New account — require a valid invite token (unless first user)
            count = await auth_queries.get_user_count(conn)
            is_admin = count == 0
            if not is_admin:
                if not invite_token:
                    raise HTTPException(
                        status_code=400,
                        detail="An invite token is required to register. Ask an admin for an invite link.",
                    )
                valid = await auth_queries.check_invite_token(conn, invite_token)
                if not valid:
                    raise HTTPException(status_code=400, detail="Invalid or expired invite token")

            username = github_user.get("login", f"github_{provider_user_id}")
            email = github_user.get("email") or f"{provider_user_id}@github.invalid"
            if await auth_queries.get_user_by_username(conn, username):
                username = f"{username}_{provider_user_id}"
            if await auth_queries.get_user_by_email(conn, email):
                email = f"{provider_user_id}@github.invalid"
            user = await auth_queries.create_user(
                conn, username, email, password_hash=None, is_admin=is_admin
            )
            await auth_queries.create_oauth_connection(conn, user["id"], "github", provider_user_id, access_token)
            if invite_token:
                await auth_queries.use_invite_token(conn, invite_token, user["id"])
            new_user = True

    if new_user:
        try:
            async with pg.get_conn(pool, user_id=user["id"]) as user_conn:
                await seed_default_anchors(user_conn)
                await seed_kanban_columns(user_conn)
        except Exception:
            logging.getLogger(__name__).error(
                "Failed to seed defaults for new user %s — account exists but may be missing defaults",
                user["id"],
            )
            raise

    token = create_jwt(user["id"], user["username"], bool(user["is_admin"]))
    response = RedirectResponse("/plan/day")
    _set_auth_cookie(response, token)
    return response


# ---------------------------------------------------------------------------
# Google OAuth
# ---------------------------------------------------------------------------

@router.get("/auth/google")
@limiter.limit("20/minute")
async def google_oauth(
    request: Request,
    invite_token: Optional[str] = Query(default=None),
):
    if not cfg.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=404, detail="OAuth not configured")
    payload: dict = {"invite_token": invite_token} if invite_token else {"mode": "login"}
    state = make_signed_state(payload)
    url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={cfg.GOOGLE_CLIENT_ID}"
        f"&redirect_uri={cfg.GOOGLE_CALLBACK_URL}"
        "&response_type=code"
        "&scope=openid%20email%20profile"
        f"&state={state}"
    )
    return RedirectResponse(url)


@router.get("/auth/google/callback")
async def google_callback(
    code: str,
    request: Request,
    state: Optional[str] = Query(default=None),
):
    if not cfg.GOOGLE_CLIENT_ID or not cfg.GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=404, detail="OAuth not configured")

    # --- Validate CSRF state ---
    if not state:
        raise HTTPException(status_code=400, detail="Missing OAuth state parameter")
    try:
        state_data = verify_signed_state(state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    invite_token: Optional[str] = state_data.get("invite_token")

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

    pool = request.app.state.pool
    provider_user_id = str(google_user["id"])
    new_user = False

    async with pg.get_conn(pool) as conn:
        user = await auth_queries.get_user_by_oauth(conn, "google", provider_user_id)
        if user is None:
            # New account — require a valid invite token (unless first user)
            count = await auth_queries.get_user_count(conn)
            is_admin = count == 0
            if not is_admin:
                if not invite_token:
                    raise HTTPException(
                        status_code=400,
                        detail="An invite token is required to register. Ask an admin for an invite link.",
                    )
                valid = await auth_queries.check_invite_token(conn, invite_token)
                if not valid:
                    raise HTTPException(status_code=400, detail="Invalid or expired invite token")

            email = google_user.get("email", f"{provider_user_id}@google.invalid")
            username_base = email.split("@")[0]
            username = username_base
            if await auth_queries.get_user_by_username(conn, username):
                username = f"{username_base}_{provider_user_id}"
            if await auth_queries.get_user_by_email(conn, email):
                email = f"{provider_user_id}@google.invalid"
            user = await auth_queries.create_user(
                conn, username, email, password_hash=None, is_admin=is_admin
            )
            await auth_queries.create_oauth_connection(conn, user["id"], "google", provider_user_id, access_token)
            if invite_token:
                await auth_queries.use_invite_token(conn, invite_token, user["id"])
            new_user = True

    if new_user:
        try:
            async with pg.get_conn(pool, user_id=user["id"]) as user_conn:
                await seed_default_anchors(user_conn)
                await seed_kanban_columns(user_conn)
        except Exception:
            logging.getLogger(__name__).error(
                "Failed to seed defaults for new user %s — account exists but may be missing defaults",
                user["id"],
            )
            raise

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
    async with pg.get_conn(request.app.state.pool) as conn:
        token = await auth_queries.create_invite_token(conn, request.state.user_id, expires_at)
    return {"token": token, "expires_at": expires_at.isoformat()}


@router.get("/auth/invites")
async def list_invites(request: Request, _auth=Depends(auth_dependency)):
    if not request.state.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    async with pg.get_conn(request.app.state.pool) as conn:
        tokens = await auth_queries.get_invite_tokens(conn, request.state.user_id)
    return tokens


# ---------------------------------------------------------------------------
# Telegram link verification
# ---------------------------------------------------------------------------

class TelegramLinkBody(BaseModel):
    code: str


@router.post("/auth/telegram-link")
async def telegram_link(body: TelegramLinkBody, request: Request, _auth=Depends(auth_dependency)):
    """Verify a 6-digit /link code from the Telegram bot and connect the user's account."""
    async with pg.get_conn(request.app.state.pool) as conn:
        chat_id = await auth_queries.verify_and_consume_link_code(conn, body.code)
        if chat_id is None:
            raise HTTPException(status_code=400, detail="Invalid or expired link code")
        await auth_queries.set_telegram_connection(conn, request.state.user_id, chat_id)
    return {"ok": True, "telegram_chat_id": chat_id}
