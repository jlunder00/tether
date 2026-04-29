"""Async Postgres queries — anchors table."""
from __future__ import annotations
import uuid as _uuid

import asyncpg


async def upsert_anchor(conn: asyncpg.Connection, anchor: dict) -> None:
    await conn.execute(
        """
        INSERT INTO anchors
            (id, user_id, name, time, duration_minutes, flexibility,
             strictness, color, position, followup_config, motif)
        VALUES ($1, current_setting('app.current_user_id', true)::uuid,
                $2, $3, $4, $5, $6, $7, $8, $9, $10)
        ON CONFLICT (id) DO UPDATE SET
            name             = EXCLUDED.name,
            time             = EXCLUDED.time,
            duration_minutes = EXCLUDED.duration_minutes,
            flexibility      = EXCLUDED.flexibility,
            strictness       = EXCLUDED.strictness,
            color            = EXCLUDED.color,
            position         = EXCLUDED.position,
            followup_config  = EXCLUDED.followup_config,
            motif            = EXCLUDED.motif
        """,
        _uuid.UUID(anchor["id"]),
        anchor["name"],
        anchor["time"],
        anchor["duration_minutes"],
        anchor.get("flexibility", "flexible"),
        anchor.get("strictness", 3),
        anchor.get("color", "#888888"),
        anchor.get("position", 0),
        anchor.get("followup_config"),
        anchor.get("motif", "anchor"),
    )


async def delete_anchor(conn: asyncpg.Connection, anchor_id: str) -> None:
    await conn.execute("DELETE FROM anchors WHERE id = $1", _uuid.UUID(anchor_id))


async def seed_default_anchors(conn: asyncpg.Connection) -> None:
    count = await conn.fetchval("SELECT COUNT(*) FROM anchors")
    if count > 0:
        return
    defaults = [
        {"id": "00000000-0000-0000-0000-000000000001", "name": "Morning",   "time": "08:00", "duration_minutes": 120, "flexibility": "flexible", "strictness": 3, "color": "#5b8dee", "position": 0},
        {"id": "00000000-0000-0000-0000-000000000002", "name": "Midday",    "time": "10:00", "duration_minutes": 150, "flexibility": "flexible", "strictness": 3, "color": "#7c6af7", "position": 1},
        {"id": "00000000-0000-0000-0000-000000000003", "name": "Afternoon", "time": "13:00", "duration_minutes": 180, "flexibility": "flexible", "strictness": 3, "color": "#e05c5c", "position": 2},
        {"id": "00000000-0000-0000-0000-000000000004", "name": "Evening",   "time": "17:00", "duration_minutes": 120, "flexibility": "flexible", "strictness": 2, "color": "#4caf8c", "position": 3},
    ]
    for a in defaults:
        await upsert_anchor(conn, a)


async def get_anchors(conn: asyncpg.Connection) -> list[dict]:
    rows = await conn.fetch("SELECT * FROM anchors ORDER BY position")
    return [
        {**dict(r), "id": str(r["id"]), "followup_config": r["followup_config"]}
        for r in rows
    ]


async def patch_anchor(conn: asyncpg.Connection, anchor_id: str, fields: dict) -> None:
    allowed = {"name", "time", "duration_minutes", "flexibility", "strictness",
               "color", "position", "followup_config", "motif"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    params = list(updates.values())
    params.append(_uuid.UUID(anchor_id))
    set_clause = ", ".join(f"{k} = ${i+1}" for i, k in enumerate(updates))
    await conn.execute(
        f"UPDATE anchors SET {set_clause} WHERE id = ${len(params)}", *params
    )
