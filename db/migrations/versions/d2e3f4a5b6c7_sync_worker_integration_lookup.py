"""sync worker: SECURITY DEFINER lookup for user_integrations

The GCal sync worker is a background system process that must fetch
(user_id, access_token) from user_integrations before it knows the
user_id — so it cannot set app.current_user_id first. tether_app is
NOBYPASSRLS and user_integrations has FORCE ROW LEVEL SECURITY, meaning
an unscoped connection sees zero rows.

Solution mirrors api_keys (c7d8e9f0a1b2): a SECURITY DEFINER function
owned by postgres (BYPASSRLS) that performs this one lookup, returning
only the columns the sync worker needs. RLS remains intact for all other
access paths.

Revision ID: d2e3f4a5b6c7
Revises: c7d8e9f0a1b2
Create Date: 2026-04-26
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, Sequence[str], None] = 'c7d8e9f0a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION get_integration_for_sync(p_id uuid)
        RETURNS TABLE(user_id uuid, access_token text)
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
    op.execute(
        "REVOKE EXECUTE ON FUNCTION get_integration_for_sync(uuid) FROM tether_app"
    )
    op.execute("DROP FUNCTION IF EXISTS get_integration_for_sync(uuid)")
