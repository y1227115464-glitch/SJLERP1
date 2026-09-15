"""Independent dated FBA fee tiers; preserve legacy flat fees unchanged."""
from alembic import op
import sqlalchemy as sa

revision = '83b1d6079a25'
down_revision = '79ec620ba134'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('fba_fee_rates',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('store_id', sa.String(36), sa.ForeignKey('stores.id'), nullable=True),
        sa.Column('scope_key', sa.String(36), nullable=False),
        sa.Column('sku', sa.String(120), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('low_price_fee', sa.Numeric(18, 9), nullable=False),
        sa.Column('high_price_fee', sa.Numeric(18, 9), nullable=False),
        sa.Column('source', sa.String(500), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.UniqueConstraint('scope_key', 'sku', 'effective_from', name='uq_fba_fee_scope_sku_date'),
        sa.CheckConstraint("(store_id IS NULL AND scope_key = '*') OR (store_id IS NOT NULL AND scope_key = store_id)", name='ck_fba_fee_scope'),
        sa.CheckConstraint('low_price_fee >= 0 AND high_price_fee >= 0', name='ck_fba_fee_nonnegative'))
    op.create_index('ix_fba_fee_rates_store_id', 'fba_fee_rates', ['store_id'])
    op.create_index('ix_fba_fee_rates_sku', 'fba_fee_rates', ['sku'])


def downgrade():
    op.drop_table('fba_fee_rates')
