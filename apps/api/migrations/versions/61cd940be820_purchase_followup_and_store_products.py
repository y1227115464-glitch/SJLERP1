"""Store assortments, purchase follow-up and shipment merge trace."""
from alembic import op
import sqlalchemy as sa

revision = '61cd940be820'
down_revision = '38b7c4209a61'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('product_stores',
        sa.Column('store_id', sa.String(36), sa.ForeignKey('stores.id'), primary_key=True),
        sa.Column('product_id', sa.String(36), sa.ForeignKey('products.id'), primary_key=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_index('ix_product_stores_product_id', 'product_stores', ['product_id'])
    op.add_column('purchase_orders', sa.Column('payment_status', sa.String(20), nullable=False, server_default='unpaid'))
    op.add_column('purchase_orders', sa.Column('invoice_status', sa.String(20), nullable=False, server_default='pending'))
    op.add_column('purchase_orders', sa.Column('finance_notes', sa.Text(), nullable=False, server_default=''))
    op.add_column('purchase_orders', sa.Column('finance_updated_at', sa.DateTime(timezone=True), nullable=True))
    op.create_table('purchase_finance_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('purchase_order_id', sa.String(36), sa.ForeignKey('purchase_orders.id'), nullable=False),
        sa.Column('payment_status', sa.String(20), nullable=False),
        sa.Column('invoice_status', sa.String(20), nullable=False),
        sa.Column('notes', sa.Text(), nullable=False),
        sa.Column('actor_name', sa.String(100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_purchase_finance_event_time', 'purchase_finance_events', ['purchase_order_id', 'created_at'])
    if op.get_bind().dialect.name == 'sqlite':
        # SQLite can add a nullable inline reference without rebuilding a referenced table.
        op.execute('ALTER TABLE shipments ADD COLUMN merged_into_id VARCHAR(36) REFERENCES shipments(id)')
    else:
        op.add_column('shipments', sa.Column('merged_into_id', sa.String(36),
            sa.ForeignKey('shipments.id', name='fk_shipment_merged_into'), nullable=True))


def downgrade():
    op.drop_column('shipments', 'merged_into_id')
    op.drop_table('purchase_finance_events')
    for column in ['finance_updated_at', 'finance_notes', 'invoice_status', 'payment_status']:
        op.drop_column('purchase_orders', column)
    op.drop_table('product_stores')
