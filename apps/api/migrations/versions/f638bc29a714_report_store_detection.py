"""Keep previews whose store could not be identified."""
from alembic import op
import sqlalchemy as sa

revision = 'f638bc29a714'
down_revision = '12ac904bf831'
branch_labels = None
depends_on = None


def alter_store_nullable(nullable):
    if op.get_bind().dialect.name == 'sqlite':
        # SQLite rebuilds this table, which is referenced by existing facts.
        # Disable FK enforcement only on the migration connection, outside a
        # transaction, and restore it after the replacement has been checked.
        with op.get_context().autocommit_block():
            op.execute('PRAGMA foreign_keys=OFF')
            try:
                with op.batch_alter_table('report_imports') as batch:
                    batch.alter_column('store_id', existing_type=sa.String(36), nullable=nullable)
                if op.get_bind().exec_driver_sql('PRAGMA foreign_key_check').first():
                    raise RuntimeError('导入批次迁移后的外键校验失败')
            finally:
                op.execute('PRAGMA foreign_keys=ON')
        return
    with op.batch_alter_table('report_imports') as batch:
        batch.alter_column('store_id', existing_type=sa.String(36), nullable=nullable)


def upgrade():
    alter_store_nullable(True)


def downgrade():
    # Unresolved previews must be handled explicitly before downgrading; never
    # silently delete their source files or assign an arbitrary store.
    if op.get_bind().scalar(sa.text('SELECT COUNT(*) FROM report_imports WHERE store_id IS NULL')):
        raise RuntimeError('存在未识别店铺的导入批次，无法回退店铺非空约束')
    alter_store_nullable(False)
