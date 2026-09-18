"""Archive deleted import batches and retain their source for audit."""
from alembic import op
import sqlalchemy as sa

revision = 'd82e61ac409f'
down_revision = 'c710feb294da'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('report_imports', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('report_imports', sa.Column('deletion_result', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('report_imports', 'deletion_result')
    op.drop_column('report_imports', 'deleted_at')
