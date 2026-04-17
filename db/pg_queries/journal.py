"""Async Postgres queries — mutation_journal table (stub).

mutation_journal:
    id                BIGSERIAL PRIMARY KEY
    user_id           UUID NOT NULL
    source            TEXT
    op_class          TEXT
    forward_op        TEXT
    before_image      JSONB
    after_image       JSONB
    scope             TEXT
    session_id        TEXT
    turn_number       INT
    checkpoint_label  TEXT
    rolled_back_by    BIGINT
    ts                TIMESTAMPTZ NOT NULL DEFAULT now()
"""
from __future__ import annotations

import asyncpg


async def append_journal_entry(
    conn: asyncpg.Connection,
    source: str,
    op_class: str,
    forward_op: str,
    before_image=None,
    after_image=None,
    scope: str | None = None,
    session_id: str | None = None,
    turn_number: int | None = None,
    checkpoint_label: str | None = None,
) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO mutation_journal
            (user_id, source, op_class, forward_op,
             before_image, after_image, scope, session_id,
             turn_number, checkpoint_label)
        VALUES
            (current_setting('app.current_user_id', true)::uuid,
             $1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING id
        """,
        source,
        op_class,
        forward_op,
        before_image,
        after_image,
        scope,
        session_id,
        turn_number,
        checkpoint_label,
    )
    return row["id"]


async def get_journal(
    conn: asyncpg.Connection, limit: int = 50, since_id: int | None = None
) -> list[dict]:
    if since_id is not None:
        rows = await conn.fetch(
            """
            SELECT *
            FROM mutation_journal
            WHERE user_id = current_setting('app.current_user_id', true)::uuid
              AND id > $1
            ORDER BY id DESC
            LIMIT $2
            """,
            since_id,
            limit,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT *
            FROM mutation_journal
            WHERE user_id = current_setting('app.current_user_id', true)::uuid
            ORDER BY id DESC
            LIMIT $1
            """,
            limit,
        )
    return [dict(r) for r in rows]


async def rollback_journal_entry(
    conn: asyncpg.Connection, entry_id: int
) -> None:
    """Mark a journal entry as rolled back. No-op in the current schema."""
    # Placeholder: set rolled_back_by = entry_id on a later compensating entry
    # when the full rollback engine is implemented.
    pass
