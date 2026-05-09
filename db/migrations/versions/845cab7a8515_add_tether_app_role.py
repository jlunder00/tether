"""add tether_app role

Revision ID: 845cab7a8515
Revises: 853542d7b568
Create Date: 2026-04-19 22:50:39.808595
"""
import os
from typing import Sequence, Union
from alembic import op

revision: str = '845cab7a8515'
down_revision: Union[str, Sequence[str], None] = '11983a904a79'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    app_password = os.environ.get("TETHER_APP_PASSWORD", "tether_app_dev")

    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tether_app') THEN
                CREATE ROLE tether_app
                    WITH LOGIN
                         NOSUPERUSER
                         NOCREATEDB
                         NOCREATEROLE
                         NOINHERIT
                         NOBYPASSRLS
                         PASSWORD '{app_password}';
            END IF;
        END
        $$
    """)

    db_name = op.get_bind().engine.url.database
    op.execute(f'GRANT CONNECT ON DATABASE {db_name} TO tether_app')
    op.execute("GRANT USAGE ON SCHEMA public TO tether_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO tether_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO tether_app")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tether_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT USAGE, SELECT ON SEQUENCES TO tether_app"
    )


def downgrade() -> None:
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM tether_app")
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM tether_app")
    op.execute("REVOKE USAGE ON SCHEMA public FROM tether_app")
    db_name = op.get_bind().engine.url.database
    op.execute(f'REVOKE CONNECT ON DATABASE {db_name} FROM tether_app')
    op.execute("DROP ROLE IF EXISTS tether_app")
