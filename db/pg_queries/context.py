"""Async Postgres queries — context_entries table."""
from __future__ import annotations

import asyncpg

from db.pg_queries._motif import validate_motif


async def upsert_context_entry(
    conn: asyncpg.Connection,
    subject: str,
    body: str,
    motif: str | None = None,
) -> int:
    """Upsert a context entry. Returns the surrogate id.

    Pass motif=None to preserve the existing motif on update (or fall back to
    the column default 'anchor' on insert). Pass an explicit motif string to
    set/overwrite. Empty string and other invalid values raise ValueError —
    there is no way to clear motif to NULL because the column is NOT NULL.
    """
    if motif is not None:
        validate_motif(motif)
    if motif is None:
        row = await conn.fetchrow(
            """
            INSERT INTO context_entries (user_id, subject, body, updated_at)
            VALUES (current_setting('app.current_user_id', true)::uuid, $1, $2, now())
            ON CONFLICT (user_id, subject) DO UPDATE SET
                body       = EXCLUDED.body,
                updated_at = EXCLUDED.updated_at
            RETURNING id
            """,
            subject,
            body,
        )
    else:
        row = await conn.fetchrow(
            """
            INSERT INTO context_entries (user_id, subject, body, motif, updated_at)
            VALUES (current_setting('app.current_user_id', true)::uuid, $1, $2, $3, now())
            ON CONFLICT (user_id, subject) DO UPDATE SET
                body       = EXCLUDED.body,
                motif      = EXCLUDED.motif,
                updated_at = EXCLUDED.updated_at
            RETURNING id
            """,
            subject,
            body,
            motif,
        )
    return row["id"]


async def get_context_entries(
    conn: asyncpg.Connection,
    prefix: str | None = None,
    top_level_only: bool = False,
) -> list[dict]:
    if prefix:
        rows = await conn.fetch(
            """
            SELECT subject, body, motif, updated_at
            FROM context_entries
            WHERE (subject = $1 OR subject LIKE $2)
              AND user_id = current_setting('app.current_user_id', true)::uuid
            ORDER BY subject
            """,
            prefix,
            prefix + "/%",
        )
    elif top_level_only:
        rows = await conn.fetch(
            """
            SELECT subject, body, motif, updated_at
            FROM context_entries
            WHERE subject NOT LIKE '%/%'
              AND user_id = current_setting('app.current_user_id', true)::uuid
            ORDER BY subject
            """
        )
    else:
        rows = await conn.fetch(
            """
            SELECT subject, body, motif, updated_at
            FROM context_entries
            WHERE user_id = current_setting('app.current_user_id', true)::uuid
            ORDER BY subject
            """
        )
    return [dict(r) for r in rows]


async def delete_context_entry(conn: asyncpg.Connection, subject: str) -> None:
    """Delete a context entry and all children (subject LIKE prefix/%)."""
    await conn.execute(
        """
        DELETE FROM context_entries
        WHERE (subject = $1 OR subject LIKE $2)
          AND user_id = current_setting('app.current_user_id', true)::uuid
        """,
        subject,
        subject + "/%",
    )


async def rename_context_subject(
    conn: asyncpg.Connection, old_subject: str, new_subject: str
) -> None:
    """Rename a context subject. FK is on id so no cascade gymnastics needed."""
    await conn.execute(
        """
        UPDATE context_entries
        SET subject = $1
        WHERE subject = $2
          AND user_id = current_setting('app.current_user_id', true)::uuid
        """,
        new_subject,
        old_subject,
    )
    # Cascade child subjects (e.g. "foo/bar" → "new/bar")
    children = await conn.fetch(
        """
        SELECT subject FROM context_entries
        WHERE subject LIKE $1
          AND user_id = current_setting('app.current_user_id', true)::uuid
        """,
        old_subject + "/%",
    )
    for row in children:
        new_child = new_subject + row["subject"][len(old_subject):]
        await conn.execute(
            """
            UPDATE context_entries SET subject = $1
            WHERE subject = $2
              AND user_id = current_setting('app.current_user_id', true)::uuid
            """,
            new_child,
            row["subject"],
        )
