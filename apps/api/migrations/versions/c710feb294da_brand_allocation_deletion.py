"""Recoverable deletion of campaign allocations, including discovered campaigns."""
from alembic import op
import sqlalchemy as sa

revision = 'c710feb294da'
down_revision = 'b6473c0a921e'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('brand_ad_allocations', sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column('brand_ad_allocations', 'is_deleted')
