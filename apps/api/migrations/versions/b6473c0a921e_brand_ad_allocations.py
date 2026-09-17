"""Brand campaign facts and editable SKU allocation ratios."""
from alembic import op
import sqlalchemy as sa

revision = 'b6473c0a921e'
down_revision = '83b1d6079a25'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('ad_records', sa.Column('ad_type', sa.String(30), nullable=False, server_default='sponsored_products'))
    op.create_table('brand_ad_allocations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('store_id', sa.String(36), sa.ForeignKey('stores.id'), nullable=False),
        sa.Column('campaign', sa.String(500), nullable=False),
        sa.Column('allocations', sa.JSON(), nullable=False),
        sa.Column('revision', sa.BigInteger(), nullable=False),
        sa.UniqueConstraint('store_id', 'campaign', name='uq_brand_allocation_store_campaign'))
    op.create_index('ix_brand_ad_allocations_store_id', 'brand_ad_allocations', ['store_id'])


def downgrade():
    op.drop_table('brand_ad_allocations')
    op.drop_column('ad_records', 'ad_type')
