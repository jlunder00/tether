from __future__ import annotations
import bcrypt
import jwt
from datetime import datetime, timedelta
from fastapi import Request, HTTPException, WebSocket, WebSocketException, status
import api.config as cfg


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_jwt(
    user_id: str,
    username: str,
    is_admin: bool,
    expires_in: timedelta | None = None,
) -> str:
    exp = datetime.utcnow() + (expires_in if expires_in is not None else timedelta(days=7))
    payload = {
        "user_id": user_id,
        "username": username,
        "is_admin": is_admin,
        "exp": exp,
    }
    return jwt.encode(payload, cfg.JWT_SECRET, algorithm="HS256")


def decode_jwt(token: str) -> dict:
    return jwt.decode(token, cfg.JWT_SECRET, algorithms=["HS256"])

def _decode_token_from_cookies(cookies: dict) -> dict:
    token = cookies.get('tether_token')
    if not token:
        raise ValueError("missing")
    return decode_jwt(token)

async def auth_dependency(request: Request):
    """FastAPI dependency — extracts JWT from cookie, sets request.state.user_id."""
    try:
        payload = _decode_token_from_cookies(request.cookies)
    except ValueError:
        raise HTTPException(status_code=401, detail="Not authenticated")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    request.state.user_id = payload["user_id"]
    request.state.username = payload["username"]
    request.state.is_admin = payload.get("is_admin", False)
    return payload

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
