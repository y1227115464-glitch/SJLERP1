"""Allow multiple purchase orders per shipment, retaining line-level provenance."""
from alembic import op
import sqlalchemy as sa

revision = '0e73a914cd62'
down_revision = 'a32b87d19c04'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('shipment_purchases',
        sa.Column('shipment_id', sa.String(36), sa.ForeignKey('shipments.id'), primary_key=True),
        sa.Column('purchase_order_id', sa.String(36), sa.ForeignKey('purchase_orders.id'), primary_key=True))
    op.create_index('ix_shipment_purchases_purchase_order_id', 'shipment_purchases', ['purchase_order_id'])
    op.execute('INSERT INTO shipment_purchases (shipment_id, purchase_order_id) '
               'SELECT id, purchase_order_id FROM shipments WHERE purchase_order_id IS NOT NULL')
    naming = {'uq': 'uq_%(table_name)s_%(column_0_name)s_%(column_1_name)s'}
    constraints = sa.inspect(op.get_bind()).get_unique_constraints('shipment_lines')
    old_name = next((c['name'] for c in constraints if c['column_names'] == ['shipment_id', 'product_id']), None)
    checks = (sa.CheckConstraint('quantity > 0 AND received_quantity >= 0 AND received_quantity <= quantity'),) if op.get_bind().dialect.name == 'sqlite' else ()
    with op.batch_alter_table('shipment_lines', naming_convention=naming, table_args=checks) as batch:
        batch.drop_constraint(old_name or 'uq_shipment_lines_shipment_id_product_id', type_='unique')
        batch.create_unique_constraint('uq_shipment_purchase_line', ['shipment_id', 'purchase_line_id'])
    op.create_index('uq_shipment_warehouse_product', 'shipment_lines', ['shipment_id', 'product_id'], unique=True,
                    sqlite_where=sa.text('purchase_line_id IS NULL'), postgresql_where=sa.text('purchase_line_id IS NULL'))


def downgrade():
    if op.get_bind().execute(sa.text('SELECT shipment_id FROM shipment_purchases GROUP BY shipment_id HAVING COUNT(*) > 1')).first():
        raise RuntimeError('Multiple-purchase shipments exist; downgrade would lose their provenance')
    op.drop_index('uq_shipment_warehouse_product', table_name='shipment_lines')
    checks = (sa.CheckConstraint('quantity > 0 AND received_quantity >= 0 AND received_quantity <= quantity'),) if op.get_bind().dialect.name == 'sqlite' else ()
    with op.batch_alter_table('shipment_lines', table_args=checks) as batch:
        batch.drop_constraint('uq_shipment_purchase_line', type_='unique')
        batch.create_unique_constraint('uq_shipment_lines_shipment_id_product_id', ['shipment_id', 'product_id'])
    op.drop_table('shipment_purchases')
