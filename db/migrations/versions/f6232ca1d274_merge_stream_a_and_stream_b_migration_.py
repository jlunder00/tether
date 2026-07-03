"""merge stream A and stream B migration heads

Revision ID: f6232ca1d274
Revises: l1m2n3o4p5q6, k1l2m3n4o5p6
Create Date: 2026-06-04 12:35:25.837234

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6232ca1d274'
down_revision: Union[str, Sequence[str], None] = ('l1m2n3o4p5q6', 'k1l2m3n4o5p6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
