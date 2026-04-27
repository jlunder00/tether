"""fix get_integration_for_sync return type: user_id text not uuid

user_integrations.user_id is TEXT (created in a1b2c3d4e5f6), but the
SECURITY DEFINER function introduced in d2e3f4a5b6c7 incorrectly declared
RETURNS TABLE(user_id uuid, ...).  PostgreSQL raises
DatatypeMismatchError on every call because the actual column is text.

Fix: CREATE OR REPLACE FUNCTION with the correct return type (text).

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-04-26
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, Sequence[str], None] = 'd2e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # DROP first because PostgreSQL treats the return type as part of the
    # function signature — CREATE OR REPLACE cannot change return types.
    op.execute("DROP FUNCTION IF EXISTS get_integration_for_sync(uuid)")
    op.execute("""
        CREATE FUNCTION get_integration_for_sync(p_id uuid)
        RETURNS TABLE(user_id text, access_token text)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public
        AS $$
        BEGIN
            RETURN QUERY
            SELECT ui.user_id, ui.access_token
              FROM user_integrations ui
             WHERE ui.id = p_id;
        END;
        $$
    """)
    op.execute(
        "GRANT EXECUTE ON FUNCTION get_integration_for_sync(uuid) TO tether_app"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS get_integration_for_sync(uuid)")
    op.execute("""
        CREATE FUNCTION get_integration_for_sync(p_id uuid)
        RETURNS TABLE(user_id uuid, access_token text)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public
        AS $$
        BEGIN
            RETURN QUERY
            SELECT ui.user_id::uuid, ui.access_token
              FROM user_integrations ui
             WHERE ui.id = p_id;
        END;
        $$
    """)
    op.execute(
        "GRANT EXECUTE ON FUNCTION get_integration_for_sync(uuid) TO tether_app"
    )
