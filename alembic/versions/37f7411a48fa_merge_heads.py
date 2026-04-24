"""merge heads

Revision ID: 37f7411a48fa
Revises: a1b2c3d4e5f6, a24b6fe0e8b6
Create Date: 2026-04-24 16:34:35.173233

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '37f7411a48fa'
down_revision: Union[str, Sequence[str], None] = ('a1b2c3d4e5f6', 'a24b6fe0e8b6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
