"""add price_check source column

Revision ID: 002
Revises: 001_add_product_metadata
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa

revision = '002'
down_revision = '001_add_product_metadata'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'price_checks',
        sa.Column('source', sa.String(20), nullable=False, server_default='amazon')
    )


def downgrade() -> None:
    op.drop_column('price_checks', 'source')
