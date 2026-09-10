"""Product packing defaults and independent shipment line carton snapshots."""
from alembic import op
import sqlalchemy as sa

revision = '38b7c4209a61'
down_revision = '48b7a65dc109'
branch_labels = None
depends_on = None


def upgrade():
    # Existing records have unknown packing; never invent historical carton sizes.
    op.add_column('products', sa.Column('units_per_carton', sa.Integer(), nullable=True))
    op.add_column('products', sa.Column('unit_weight_kg', sa.Numeric(18, 4), nullable=True))
    op.add_column('shipment_lines', sa.Column('units_per_carton', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('shipment_lines', 'units_per_carton')
    op.drop_column('products', 'unit_weight_kg')
    op.drop_column('products', 'units_per_carton')
