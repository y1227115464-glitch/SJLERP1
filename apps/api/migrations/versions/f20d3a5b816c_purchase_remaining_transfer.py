"""Track purchase remainder transfers without erasing original lines."""
from alembic import op
import sqlalchemy as sa

revision = 'f20d3a5b816c'
down_revision = 'e91f2a7b630d'
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == 'sqlite':
        op.execute('ALTER TABLE purchase_orders ADD COLUMN source_purchase_order_id VARCHAR(36) REFERENCES purchase_orders(id)')
        op.execute('ALTER TABLE purchase_lines ADD COLUMN transferred_quantity BIGINT NOT NULL DEFAULT 0 '
                   'CONSTRAINT ck_purchase_transfer_quantity CHECK (transferred_quantity >= 0 AND '
                   'received_quantity + cancelled_quantity + transferred_quantity <= quantity)')
    else:
        op.add_column('purchase_orders', sa.Column('source_purchase_order_id', sa.String(36),
            sa.ForeignKey('purchase_orders.id', name='fk_purchase_source'), nullable=True))
        op.add_column('purchase_lines', sa.Column('transferred_quantity', sa.BigInteger(), nullable=False, server_default='0'))
        op.create_check_constraint('ck_purchase_transfer_quantity', 'purchase_lines',
            'transferred_quantity >= 0 AND received_quantity + cancelled_quantity + transferred_quantity <= quantity')


def downgrade():
    if op.get_bind().dialect.name != 'sqlite':
        op.drop_constraint('ck_purchase_transfer_quantity', 'purchase_lines', type_='check')
    op.drop_column('purchase_lines', 'transferred_quantity')
    op.drop_column('purchase_orders', 'source_purchase_order_id')
