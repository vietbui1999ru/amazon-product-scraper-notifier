"""drop notification_lock — dead column, advisory lock used instead

Revision ID: 004
Revises: 003
Create Date: 2026-05-05
"""
from alembic import op

revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column('price_checks', 'notification_lock')


def downgrade() -> None:
    import sqlalchemy as sa
    op.add_column('price_checks',
        sa.Column('notification_lock', sa.Boolean(), nullable=False, server_default='false'))
