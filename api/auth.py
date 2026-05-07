from __future__ import annotations
import bcrypt
import jwt
from datetime import datetime, timedelta
from fastapi import Request, HTTPException, WebSocket, WebSocketException, status
import api.config as cfg
import db.postgres as pg
import db.pg_queries.api_keys as key_queries


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_jwt(
    user_id: str,
    username: str,
    is_admin: bool,
    is_bot_service: bool = False,
    expires_in: timedelta | None = None,
) -> str:
    exp = datetime.utcnow() + (expires_in if expires_in is not None else timedelta(days=7))
    payload: dict = {
        "user_id": user_id,
        "username": username,
        "is_admin": is_admin,
        "exp": exp,
    }
    if is_bot_service:
        payload["is_bot_service"] = True
    return jwt.encode(payload, cfg.JWT_SECRET, algorithm="HS256")


def decode_jwt(token: str) -> dict:
    return jwt.decode(token, cfg.JWT_SECRET, algorithms=["HS256"])


def _decode_token_from_cookies(cookies: dict) -> dict:
    token = cookies.get('tether_token')
    if not token:
        raise ValueError("missing")
    return decode_jwt(token)


async def _validate_bearer_key(pool, raw_key: str) -> str | None:
    """Validate a ttr_ prefixed API key against the database.

    Uses an unscoped connection (no RLS user set) because identity is bootstrapped
    from the key itself — user_id is unknown until validation completes.
    Returns the owner's user_id as a string, or None if the key is invalid/revoked.
    """
    async with pg.get_conn(pool, user_id=None) as conn:
        return await key_queries.validate_key(conn, raw_key)


async def auth_dependency(request: Request):
    """FastAPI dependency — authenticates via JWT cookie or Bearer API key.

    Resolution order:
    1. tether_token cookie (JWT) — takes precedence if present and valid.
    2. Authorization: Bearer ttr_<key> header — validated against api_keys table.
    3. Neither present → 401.

    On success, sets request.state.user_id, request.state.username, and
    request.state.is_admin. Bearer-authenticated requests have username=None.
    """
    # --- Cookie path (existing behavior) ---
    cookie_token = request.cookies.get("tether_token")
    if cookie_token:
        try:
            payload = decode_jwt(cookie_token)
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token")
        request.state.user_id = payload["user_id"]
        request.state.username = payload["username"]
        request.state.is_admin = payload.get("is_admin", False)
        request.state.auth_method = "cookie"
        return payload

    # --- Bearer API key path ---
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer ttr_"):
        raw_key = auth_header[len("Bearer "):]
        pool = request.app.state.pool
        user_id = await _validate_bearer_key(pool, raw_key)
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid API key")
        request.state.user_id = user_id
        request.state.username = None
        request.state.is_admin = False
        request.state.auth_method = "bearer"
        return {"user_id": user_id, "is_admin": False}

    raise HTTPException(status_code=401, detail="Not authenticated")


async def ws_auth_dependency(websocket: WebSocket):
    try:
        payload = _decode_token_from_cookies(websocket.cookies)
    except ValueError:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized")
    except jwt.ExpiredSignatureError:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized")
    except jwt.InvalidTokenError:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized")
    websocket.state.user_id = payload["user_id"]
    websocket.state.username = payload["username"]
    websocket.state.is_admin = payload.get("is_admin", False)
    return payload
