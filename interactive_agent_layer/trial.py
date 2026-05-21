"""Per-user monthly trial counter for tether-agent-2.5.

Backed by the `premium_trial_usage` Postgres table. Concurrent session-starts
for the same user are serialised via `SELECT ... FOR UPDATE` so they cannot
race past the configured quota.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from interactive_agent_layer.config import get_trial_monthly_quota


class TrialCounter:
    """DB-backed per-user monthly trial counter for tether-agent-2.5."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def check_and_increment(self, user_id: str) -> tuple[bool, int]:
        """Atomically check quota and increment if there is room.

        Returns `(allowed, remaining)`:
        - `(True, N)`  — quota had room; counter was incremented, N sessions left.
        - `(False, 0)` — quota exhausted; counter was NOT incremented.
        """
        year_month = datetime.now(timezone.utc).strftime("%Y-%m")
        quota = get_trial_monthly_quota()

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT used_count FROM premium_trial_usage
                    WHERE user_id = $1 AND year_month = $2
                    FOR UPDATE
                    """,
                    user_id,
                    year_month,
                )
                current = row["used_count"] if row else 0

                if current >= quota:
                    return False, 0

                new_count = current + 1
                await conn.execute(
                    """
                    INSERT INTO premium_trial_usage (user_id, year_month, used_count)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (user_id, year_month) DO UPDATE
                        SET used_count = EXCLUDED.used_count
                    """,
                    user_id,
                    year_month,
                    new_count,
                )
                return True, quota - new_count
