"""api_keys: unique index on key_hash + SECURITY DEFINER validate function

Two hardening changes:

1. UNIQUE INDEX on key_hash
   - Prevents duplicate hashes (hash collision / implementation bug)
   - Turns validate_key lookups from O(n) full scans into O(log n) index seeks
   - Eliminates timing variance between "found" and "not found" paths

2. validate_api_key() SECURITY DEFINER function
   - api_keys has RLS enabled (from initial schema) which is correct — it
     prevents one user from reading another user's key metadata.
   - validate_key() must run WITHOUT a user context (it bootstraps identity
     from the key itself). An unscoped tether_app connection (NOBYPASSRLS)
     sees zero rows → every valid key rejected 401.
   - SECURITY DEFINER executes as the function owner (postgres/superuser,
     BYPASSRLS) for this one operation only, leaving RLS intact everywhere else.
   - The function also handles last_used_at atomically, so no second UPDATE
     is needed from application code on an unscoped connection.

Revision ID: c7d8e9f0a1b2
Revises: a1b2c3d4e5f6
Create Date: 2026-04-23
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'c7d8e9f0a1b2'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Unique index — lookup performance + collision prevention
    op.execute(
        "CREATE UNIQUE INDEX api_keys_key_hash_idx ON api_keys (key_hash)"
    )

    # 2. SECURITY DEFINER function — bypasses RLS for the auth bootstrap query only.
    #    SET search_path pins execution to public so search_path injection is not possible.
    op.execute("""
        CREATE OR REPLACE FUNCTION validate_api_key(p_key_hash text)
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public
        AS $$
        DECLARE
            v_id   uuid;
            v_user uuid;
        BEGIN
            SELECT id, user_id
              INTO v_id, v_user
              FROM api_keys
             WHERE key_hash = p_key_hash
               AND revoked_at IS NULL;

            IF v_id IS NOT NULL THEN
                UPDATE api_keys SET last_used_at = now() WHERE id = v_id;
            END IF;

            RETURN v_user;  -- NULL when key not found or revoked
        END;
        $$
    """)

    # Grant EXECUTE to the application role so tether_app can call it.
    # SECURITY DEFINER runs as the function owner regardless of who calls it.
    op.execute("GRANT EXECUTE ON FUNCTION validate_api_key(text) TO tether_app")


def downgrade() -> None:
    op.execute("REVOKE EXECUTE ON FUNCTION validate_api_key(text) FROM tether_app")
    op.execute("DROP FUNCTION IF EXISTS validate_api_key(text)")
    op.execute("DROP INDEX IF EXISTS api_keys_key_hash_idx")
