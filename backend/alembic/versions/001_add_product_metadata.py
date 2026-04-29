"""add product metadata columns

Revision ID: 001_add_product_metadata
Revises:
Create Date: 2026-04-28
"""

from alembic import op
import sqlalchemy as sa

revision = "001_add_product_metadata"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS image_url VARCHAR(2048)")
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS rating VARCHAR(50)")


def downgrade() -> None:
    op.drop_column("products", "rating")
    op.drop_column("products", "image_url")
