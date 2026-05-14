from __future__ import annotations


import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

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
from db.pg_queries import seed_default_anchors, seed_kanban_columns, get_user_is_paid
from db.pool_middleware import get_db_conn


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


def _safe_user(user: dict, is_paid: bool) -> dict:
    return {
        "user_id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "is_admin": bool(user["is_admin"]),
        "is_paid": is_paid,
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
            is_paid = await get_user_is_paid(user_conn)
    except Exception:
        logging.getLogger(__name__).error(
            "Failed to seed defaults for new user %s — account exists but may be missing defaults",
            user["id"],
        )
        raise

    token = create_jwt(user["id"], user["username"], bool(user["is_admin"]))
    _set_auth_cookie(response, token)
    return _safe_user(user, is_paid)


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

    async with pg.get_conn(pool, user_id=user["id"]) as user_conn:
        is_paid = await get_user_is_paid(user_conn)

    token = create_jwt(user["id"], user["username"], bool(user["is_admin"]))
    _set_auth_cookie(response, token)
    return _safe_user(user, is_paid)


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
async def me(request: Request, _auth=Depends(auth_dependency), conn=Depends(get_db_conn)):
    is_paid = await get_user_is_paid(conn)
    return {
        "user_id": request.state.user_id,
        "username": request.state.username,
        "is_admin": request.state.is_admin,
        "is_paid": is_paid,
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


# ---------------------------------------------------------------------------
# Telegram bot token registration (Phase 2 — per-user bot tokens)
# ---------------------------------------------------------------------------

_TELEGRAM_API = "https://api.telegram.org"
_log = logging.getLogger(__name__)


class TelegramBotBody(BaseModel):
    token: str


async def _get_me(bot_token: str) -> dict:
    """Call Telegram getMe for bot_token. Returns the result dict on success.

    Raises HTTPException(400) if the token is invalid or Telegram returns an error.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{_TELEGRAM_API}/bot{bot_token}/getMe")

    if resp.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid bot token: Telegram returned HTTP {resp.status_code}",
        )
    data = resp.json()
    if not data.get("ok"):
        description = data.get("description", "unknown error")
        raise HTTPException(
            status_code=400,
            detail=f"Invalid bot token: {description}",
        )
    return data["result"]


@router.post("/auth/telegram-bot")
async def register_telegram_bot(
    body: TelegramBotBody,
    request: Request,
    _auth=Depends(auth_dependency),
):
    """Validate a BotFather token, encrypt it, and store it for this user.

    Steps:
    1. Calls Telegram getMe to validate the token.
    2. Fernet-encrypts the token using the existing CredentialsVault key.
    3. Generates a webhook_secret UUID and upserts into telegram_connections.
    4. If TELEGRAM_WEBHOOK_URL is set, calls webhook_setup.register_webhook
       (no-ops gracefully if Phase E is not merged yet).
    5. Returns {ok: true, bot_username: "@..."}
    """
    vault = request.app.state.vault
    if vault is None:
        raise HTTPException(status_code=500, detail="Vault not configured")

    bot_info = await _get_me(body.token)
    bot_username = "@" + bot_info["username"]

    webhook_secret = str(uuid4())

    async with pg.get_conn(request.app.state.pool) as conn:
        await auth_queries.upsert_telegram_bot_token(
            conn,
            request.state.user_id,
            vault._fernet,
            body.token,
            webhook_secret,
        )

    webhook_url = os.environ.get("TELEGRAM_WEBHOOK_URL")
    if webhook_url:
        try:
            from bot.webhook_setup import register_webhook  # type: ignore[import]
            await register_webhook(body.token, webhook_url, webhook_secret)
        except ImportError:
            _log.debug("bot.webhook_setup not available — webhook registration deferred")
        except Exception:
            _log.exception("register_webhook failed — token stored, webhook not registered")

    return {"ok": True, "bot_username": bot_username}


@router.delete("/auth/telegram-bot")
async def deregister_telegram_bot(
    request: Request,
    _auth=Depends(auth_dependency),
):
    """Disconnect this user's personal Telegram bot.

    Decrypts the stored token to call Telegram's deleteWebhook (if Phase E is
    available and TELEGRAM_WEBHOOK_URL is set), then clears both columns.
    Always returns 200 — idempotent even if no bot is registered.
    """
    vault = request.app.state.vault

    async with pg.get_conn(request.app.state.pool) as conn:
        row = await auth_queries.get_telegram_bot_row(conn, request.state.user_id)

    encrypted = row.get("bot_token_encrypted") if row else None

    if encrypted and os.environ.get("TELEGRAM_WEBHOOK_URL") and vault is not None:
        try:
            from bot.webhook_setup import deregister_webhook  # type: ignore[import]
            raw_token = vault._fernet.decrypt(bytes(encrypted)).decode()
            await deregister_webhook(raw_token)
        except ImportError:
            _log.debug("bot.webhook_setup not available — skipping deregister_webhook")
        except Exception:
            _log.exception("deregister_webhook failed — clearing token regardless")

    async with pg.get_conn(request.app.state.pool) as conn:
        await auth_queries.clear_telegram_bot_token(conn, request.state.user_id)

    return {"ok": True}


@router.get("/auth/telegram-bot")
async def get_telegram_bot_status(
    request: Request,
    _auth=Depends(auth_dependency),
):
    """Return the connection status for this user's personal Telegram bot.

    If connected (bot_token_encrypted IS NOT NULL), calls Telegram getMe to
    retrieve the current bot username.  Returns:
      {connected: bool, bot_username: string | null}
    """
    vault = request.app.state.vault

    async with pg.get_conn(request.app.state.pool) as conn:
        row = await auth_queries.get_telegram_bot_row(conn, request.state.user_id)

    encrypted = row.get("bot_token_encrypted") if row else None
    if not encrypted:
        return {"connected": False, "bot_username": None}

    if vault is None:
        # Vault not configured — report connected but can't retrieve username
        return {"connected": True, "bot_username": None}

    try:
        raw_token = vault._fernet.decrypt(bytes(encrypted)).decode()
        bot_info = await _get_me(raw_token)
        bot_username = "@" + bot_info["username"]
    except Exception:
        _log.exception("getMe failed for stored bot token")
        return {"connected": True, "bot_username": None}

    return {"connected": True, "bot_username": bot_username}
