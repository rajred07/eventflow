"""Add tagline and support fields to microsites

Revision ID: a1b2c3d4e5f6
Revises: 661a5e92feda
Create Date: 2026-04-10

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = '661a5e92feda'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add channel column only if it doesn't exist yet (safe guard)
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='notification_logs' AND column_name='channel'"
    ))
    if not result.fetchone():
        op.add_column('notification_logs', sa.Column('channel', sa.String(20), server_default='email', nullable=False))

    # Add new microsite fields
    op.add_column('microsites', sa.Column('tagline', sa.String(255), nullable=True))
    op.add_column('microsites', sa.Column('support_email', sa.String(255), nullable=True))
    op.add_column('microsites', sa.Column('support_phone', sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column('microsites', 'tagline')
    op.drop_column('microsites', 'support_email')
    op.drop_column('microsites', 'support_phone')
