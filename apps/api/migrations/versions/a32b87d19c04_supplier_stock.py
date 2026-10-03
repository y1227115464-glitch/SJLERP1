"""Supplier-held purchase stock and immutable movement history."""
from alembic import op
import sqlalchemy as sa

revision = 'a32b87d19c04'
down_revision = 'f20d3a5b816c'
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == 'sqlite':
        op.execute('ALTER TABLE purchase_lines ADD COLUMN supplier_stock_quantity BIGINT NOT NULL DEFAULT 0 '
                   'CONSTRAINT ck_purchase_supplier_stock CHECK (supplier_stock_quantity >= 0 AND '
                   'received_quantity + cancelled_quantity + transferred_quantity + supplier_stock_quantity <= quantity)')
    else:
        op.add_column('purchase_lines', sa.Column('supplier_stock_quantity', sa.BigInteger(), nullable=False, server_default='0'))
        op.create_check_constraint('ck_purchase_supplier_stock', 'purchase_lines',
            'supplier_stock_quantity >= 0 AND received_quantity + cancelled_quantity + transferred_quantity + supplier_stock_quantity <= quantity')
    op.create_table('supplier_stock',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('store_id', sa.String(36), sa.ForeignKey('stores.id'), nullable=False),
        sa.Column('supplier_id', sa.String(36), sa.ForeignKey('suppliers.id'), nullable=False),
        sa.Column('purchase_order_id', sa.String(36), sa.ForeignKey('purchase_orders.id'), nullable=False),
        sa.Column('purchase_line_id', sa.String(36), sa.ForeignKey('purchase_lines.id'), nullable=False),
        sa.Column('quantity', sa.BigInteger(), nullable=False),
        sa.Column('remaining_quantity', sa.BigInteger(), nullable=False),
        sa.Column('payment_status', sa.String(20), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('quantity > 0 AND remaining_quantity >= 0 AND remaining_quantity <= quantity'))
    for field in ['store_id', 'supplier_id', 'purchase_order_id', 'purchase_line_id']:
        op.create_index('ix_supplier_stock_' + field, 'supplier_stock', [field])
    op.create_table('supplier_stock_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('stock_id', sa.String(36), sa.ForeignKey('supplier_stock.id'), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('quantity', sa.BigInteger(), nullable=False),
        sa.Column('balance_after', sa.BigInteger(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('payment_status', sa.String(20), nullable=False),
        sa.Column('actor_name', sa.String(100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_supplier_stock_events_stock_id', 'supplier_stock_events', ['stock_id'])


def downgrade():
    op.drop_table('supplier_stock_events')
    op.drop_table('supplier_stock')
    if op.get_bind().dialect.name != 'sqlite':
        op.drop_constraint('ck_purchase_supplier_stock', 'purchase_lines', type_='check')
    op.drop_column('purchase_lines', 'supplier_stock_quantity')
