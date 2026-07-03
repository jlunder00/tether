"""Async Postgres queries — token_usage table.

Token counts are captured from the agent SDK ResultMessage.usage dict on
handle release and written here asynchronously (off the hot path).

These feed:
  - The trial counter display (remaining turns for free-tier users)
  - Future billing enforcement
  - Analytics / cost attribution
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


async def record_token_usage(
    user_id: str,
    input_tokens: int,
    output_tokens: int,
    *,
    pg_pool: object | None = None,
) -> None:
    """Insert one token_usage row for the given user.

    Accepts an optional ``pg_pool`` (asyncpg pool) — if not provided, the
    function attempts to acquire one from the app-level singleton.  Silent
    no-op if no pool is available (avoids crashing the release path).

    ``input_tokens`` and ``output_tokens`` map directly to the SDK's
    ``ResultMessage.usage`` dict keys.
    """
    try:
        pool = pg_pool or _get_default_pool()
        if pool is None:
            log.debug("token_usage: no pg_pool available, skipping write")
            return
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO token_usage (user_id, input_tokens, output_tokens)
                VALUES ($1, $2, $3)
                """,
                user_id,
                input_tokens,
                output_tokens,
            )
        log.debug(
            "token_usage recorded user_id=%s in=%d out=%d",
            user_id, input_tokens, output_tokens,
        )
    except Exception:
        # Never raise from the async write — the release path must not fail
        log.warning(
            "token_usage write failed for user_id=%s — dropping record",
            user_id, exc_info=True,
        )


def _get_default_pool() -> object | None:
    """Best-effort fetch of the app-level asyncpg pool singleton.

    Returns None if the pool is not yet initialised (e.g. in unit tests).
    """
    try:
        from db.connection import get_pool  # type: ignore[import]
        return get_pool()
    except Exception:
        return None


async def get_token_usage_totals(
    conn: object,
    user_id: str,
    since_iso: str | None = None,
) -> dict[str, int]:
    """Return aggregated token totals for a user.

    ``since_iso``: ISO-8601 timestamp lower bound (e.g. start of current month).
    Returns ``{"input_tokens": N, "output_tokens": N, "row_count": N}``.
    """
    if since_iso is not None:
        row = await conn.fetchrow(  # type: ignore[attr-defined]
            """
            SELECT
                COALESCE(SUM(input_tokens), 0)  AS input_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens,
                COUNT(*)                         AS row_count
            FROM token_usage
            WHERE user_id = $1 AND recorded_at >= $2::timestamptz
            """,
            user_id,
            since_iso,
        )
    else:
        row = await conn.fetchrow(  # type: ignore[attr-defined]
            """
            SELECT
                COALESCE(SUM(input_tokens), 0)  AS input_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens,
                COUNT(*)                         AS row_count
            FROM token_usage
            WHERE user_id = $1
            """,
            user_id,
        )
    return {
        "input_tokens": int(row["input_tokens"]),
        "output_tokens": int(row["output_tokens"]),
        "row_count": int(row["row_count"]),
    }
