"""add_row_level_security_policies

Revision ID: 7c452c5db37e
Revises: e3717630f2ce
Create Date: 2026-03-31 14:10:56.599749

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c452c5db37e'
down_revision: Union[str, Sequence[str], None] = 'e3717630f2ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Enable RLS on events
    op.execute("ALTER TABLE events ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE events FORCE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY tenant_isolation_events ON events
        USING (
            tenant_id::text = current_setting('app.tenant_id', true) 
            OR current_setting('app.bypass_rls', true) = 'on'
        )
    """)

    # Enable RLS on users
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY tenant_isolation_users ON users
        USING (
            tenant_id::text = current_setting('app.tenant_id', true) 
            OR current_setting('app.bypass_rls', true) = 'on'
        )
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE events NO FORCE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE users NO FORCE ROW LEVEL SECURITY;")
    
    op.execute("DROP POLICY IF EXISTS tenant_isolation_events ON events;")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_users ON users;")
    
    op.execute("ALTER TABLE events DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY;")
