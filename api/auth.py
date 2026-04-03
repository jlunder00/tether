from __future__ import annotations
import bcrypt
import jwt
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import Request, HTTPException
from db.auth_schema import init_auth_db
from db.auth_queries import get_user_by_id
import api.config as cfg


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_jwt(user_id: str, username: str, is_admin: bool) -> str:
    payload = {
        "user_id": user_id,
        "username": username,
        "is_admin": is_admin,
        "exp": datetime.utcnow() + timedelta(days=7),
    }
    return jwt.encode(payload, cfg.JWT_SECRET, algorithm="HS256")


def decode_jwt(token: str) -> dict:
    return jwt.decode(token, cfg.JWT_SECRET, algorithms=["HS256"])


def get_user_db_path(user_id: str) -> Path:
    return cfg.USERS_DB_DIR / f"{user_id}.db"


async def auth_dependency(request: Request):
    """FastAPI dependency — extracts JWT from cookie, sets request.state.user_id and request.state.db_path."""
    token = request.cookies.get("tether_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_jwt(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    request.state.user_id = payload["user_id"]
    request.state.username = payload["username"]
    request.state.is_admin = payload.get("is_admin", False)
    request.state.db_path = get_user_db_path(payload["user_id"])
    return payload
