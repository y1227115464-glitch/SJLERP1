"""Retain the supplier stock batch used by each shipment line."""
from alembic import op
import sqlalchemy as sa

revision = '12ac904bf831'
down_revision = '0e73a914cd62'
branch_labels = None
depends_on = None


def upgrade():
    checks = (sa.CheckConstraint('quantity > 0 AND received_quantity >= 0 AND received_quantity <= quantity'),) if op.get_bind().dialect.name == 'sqlite' else ()
    with op.batch_alter_table('shipment_lines', table_args=checks) as batch:
        batch.add_column(sa.Column('supplier_stock_id', sa.String(36), nullable=True))
        batch.create_foreign_key('fk_shipment_supplier_stock', 'supplier_stock', ['supplier_stock_id'], ['id'])
        batch.drop_constraint('uq_shipment_purchase_line', type_='unique')
        batch.create_unique_constraint('uq_shipment_supplier_stock', ['shipment_id', 'supplier_stock_id'])
    op.create_index('ix_shipment_lines_supplier_stock_id', 'shipment_lines', ['supplier_stock_id'])
    op.create_index('uq_shipment_purchase_line', 'shipment_lines', ['shipment_id', 'purchase_line_id'], unique=True,
                    sqlite_where=sa.text('supplier_stock_id IS NULL'), postgresql_where=sa.text('supplier_stock_id IS NULL'))


def downgrade():
    if op.get_bind().execute(sa.text('SELECT id FROM shipment_lines WHERE supplier_stock_id IS NOT NULL LIMIT 1')).first():
        raise RuntimeError('Supplier stock shipment sources exist; downgrade would lose provenance')
    op.drop_index('uq_shipment_purchase_line', table_name='shipment_lines')
    op.drop_index('ix_shipment_lines_supplier_stock_id', table_name='shipment_lines')
    checks = (sa.CheckConstraint('quantity > 0 AND received_quantity >= 0 AND received_quantity <= quantity'),) if op.get_bind().dialect.name == 'sqlite' else ()
    with op.batch_alter_table('shipment_lines', table_args=checks) as batch:
        batch.drop_constraint('uq_shipment_supplier_stock', type_='unique')
        batch.drop_constraint('fk_shipment_supplier_stock', type_='foreignkey')
        batch.drop_column('supplier_stock_id')
        batch.create_unique_constraint('uq_shipment_purchase_line', ['shipment_id', 'purchase_line_id'])
