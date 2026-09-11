"""Dated sales analysis cost assumptions; no business data seeds."""
from alembic import op
import sqlalchemy as sa

revision = '79ec620ba134'
down_revision = '61cd940be820'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('sales_cost_rates',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('store_id', sa.String(36), sa.ForeignKey('stores.id'), nullable=True),
        sa.Column('scope_key', sa.String(36), nullable=False),
        sa.Column('sku', sa.String(120), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('product_cost', sa.Numeric(18, 9), nullable=True),
        sa.Column('inbound_fee', sa.Numeric(18, 9), nullable=True),
        sa.Column('fba_fee', sa.Numeric(18, 9), nullable=True),
        sa.Column('commission_rate', sa.Numeric(8, 6), nullable=False),
        sa.Column('source', sa.String(500), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.UniqueConstraint('scope_key', 'sku', 'effective_from', name='uq_sales_cost_scope_sku_date'),
        sa.CheckConstraint("(store_id IS NULL AND scope_key = '*') OR (store_id IS NOT NULL AND scope_key = store_id)"),
        sa.CheckConstraint('product_cost >= 0 AND inbound_fee >= 0 AND fba_fee >= 0 AND commission_rate >= 0 AND commission_rate <= 1'))
    op.create_index('ix_sales_cost_rates_store_id', 'sales_cost_rates', ['store_id'])
    op.create_index('ix_sales_cost_rates_sku', 'sales_cost_rates', ['sku'])


def downgrade():
    op.drop_table('sales_cost_rates')
