"""Persist removed SKU rows independently of FBA fee versions."""
from alembic import op
import sqlalchemy as sa

revision = 'e91f2a7b630d'
down_revision = 'd82e61ac409f'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('fba_catalog_deletions',
        sa.Column('scope_key', sa.String(36), primary_key=True),
        sa.Column('sku', sa.String(120), primary_key=True))


def downgrade():
    op.drop_table('fba_catalog_deletions')
