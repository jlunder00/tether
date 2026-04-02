from __future__ import annotations
import uuid
from datetime import datetime, timezone
from pathlib import Path
from db.auth_schema import get_auth_db


def create_user(
    db_path: Path,
    username: str,
    email: str,
    password_hash: str | None = None,
    is_admin: bool = False,
) -> dict:
    user_id = str(uuid.uuid4())
    with get_auth_db(db_path) as conn:
        conn.execute(
            """
            INSERT INTO users (id, username, email, password_hash, is_admin)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, username, email, password_hash, 1 if is_admin else 0),
        )
    return get_user_by_id(db_path, user_id)


def get_user_by_id(db_path: Path, user_id: str) -> dict | None:
    with get_auth_db(db_path) as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_email(db_path: Path, email: str) -> dict | None:
    with get_auth_db(db_path) as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None


def get_user_by_username(db_path: Path, username: str) -> dict | None:
    with get_auth_db(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
    return dict(row) if row else None


def get_user_count(db_path: Path) -> int:
    with get_auth_db(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
    return row[0]


def create_oauth_connection(
    db_path: Path,
    user_id: str,
    provider: str,
    provider_user_id: str,
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> None:
    with get_auth_db(db_path) as conn:
        conn.execute(
            """
            INSERT INTO oauth_connections
                (user_id, provider, provider_user_id, access_token, refresh_token)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, provider, provider_user_id, access_token, refresh_token),
        )


def get_user_by_oauth(
    db_path: Path, provider: str, provider_user_id: str
) -> dict | None:
    with get_auth_db(db_path) as conn:
        row = conn.execute(
            """
            SELECT u.*
            FROM users u
            JOIN oauth_connections o ON o.user_id = u.id
            WHERE o.provider = ? AND o.provider_user_id = ?
            """,
            (provider, provider_user_id),
        ).fetchone()
    return dict(row) if row else None


def create_invite_token(
    db_path: Path, created_by: str, expires_at: datetime
) -> str:
    token = str(uuid.uuid4())
    expires_str = expires_at.isoformat() if isinstance(expires_at, datetime) else expires_at
    with get_auth_db(db_path) as conn:
        conn.execute(
            """
            INSERT INTO invite_tokens (token, created_by, expires_at)
            VALUES (?, ?, ?)
            """,
            (token, created_by, expires_str),
        )
    return token


def use_invite_token(db_path: Path, token: str, user_id: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    with get_auth_db(db_path) as conn:
        row = conn.execute(
            "SELECT used_by, expires_at FROM invite_tokens WHERE token = ?", (token,)
        ).fetchone()
        if row is None:
            return False
        if row["used_by"] is not None:
            return False
        if row["expires_at"] < now:
            return False
        conn.execute(
            "UPDATE invite_tokens SET used_by = ? WHERE token = ?", (user_id, token)
        )
    return True


def get_invite_tokens(db_path: Path, created_by: str) -> list[dict]:
    with get_auth_db(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM invite_tokens WHERE created_by = ? ORDER BY created_at",
            (created_by,),
        ).fetchall()
    return [dict(r) for r in rows]


def set_telegram_connection(db_path: Path, user_id: str, chat_id: str) -> None:
    with get_auth_db(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO telegram_connections (user_id, telegram_chat_id)
            VALUES (?, ?)
            """,
            (user_id, chat_id),
        )


def get_user_by_telegram_chat_id(db_path: Path, chat_id: str) -> dict | None:
    with get_auth_db(db_path) as conn:
        row = conn.execute(
            """
            SELECT u.*
            FROM users u
            JOIN telegram_connections t ON t.user_id = u.id
            WHERE t.telegram_chat_id = ?
            """,
            (chat_id,),
        ).fetchone()
    return dict(row) if row else None
