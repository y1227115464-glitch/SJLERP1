"""Advertising daily identity; retain period summaries separately.

Revision ID: 2c638fa481b9
Revises: de1aefc77089
"""
import hashlib
import json

from alembic import op
import sqlalchemy as sa

revision = '2c638fa481b9'
down_revision = 'de1aefc77089'
branch_labels = None
depends_on = None


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def rekey(connection, daily):
    table = sa.Table('ad_records', sa.MetaData(), autoload_with=connection)
    last_id = ''
    while True:
        rows = connection.execute(sa.select(table.c.id, table.c.start_date, table.c.data)
            .where(table.c.start_date == table.c.end_date, table.c.id > last_id).order_by(table.c.id).limit(300)).all()
        if not rows:
            break
        updates = []
        for identifier, day, source in rows:
            data = dict(source)
            if daily:
                data['report_date'] = day.isoformat()
                identity = digest(['daily', data['sku'], data['campaign'], data['ad_group']])
                key = digest([identity, data['report_date']])
            else:
                data.pop('report_date', None)
                identity = digest([data[field] for field in ['retailer', 'country', 'currency', 'campaign', 'ad_group', 'sku', 'asin']])
                key = digest([identity, data['start_date'], data['end_date']])
            updates.append({'record_id': identifier, 'new_key': key, 'identity': identity,
                            'payload': data, 'value_hash': digest(data), 'day': day if daily else None})
        connection.execute(sa.update(table).where(table.c.id == sa.bindparam('record_id')).values(
            natural_key=sa.bindparam('new_key'), identity_key=sa.bindparam('identity'), data=sa.bindparam('payload'),
            value_hash=sa.bindparam('value_hash'), report_date=sa.bindparam('day')), updates)
        last_id = rows[-1].id


def upgrade():
    op.add_column('ad_records', sa.Column('report_date', sa.Date(), nullable=True))
    connection = op.get_bind()
    table = sa.Table('ad_records', sa.MetaData(), autoload_with=connection)
    ranked = sa.select(table.c.id, sa.func.row_number().over(
        partition_by=[table.c.store_id, table.c.start_date, table.c.sku, table.c.campaign, table.c.ad_group],
        order_by=[table.c.latest_report_at.desc(), table.c.source_row.desc(), table.c.id.desc()]).label('position'))
    ranked = ranked.where(table.c.start_date == table.c.end_date).subquery()
    # Original confirmed import batches retain the source rows of replaced records.
    connection.execute(sa.delete(table).where(table.c.id.in_(sa.select(ranked.c.id).where(ranked.c.position > 1))))
    rekey(connection, daily=True)
    with op.batch_alter_table('ad_records') as batch:
        batch.create_unique_constraint('uq_ad_daily_identity', ['store_id', 'report_date', 'identity_key'])
        batch.create_index('ix_ad_store_report_date', ['store_id', 'report_date'])


def downgrade():
    with op.batch_alter_table('ad_records') as batch:
        batch.drop_constraint('uq_ad_daily_identity', type_='unique')
        batch.drop_index('ix_ad_store_report_date')
    rekey(op.get_bind(), daily=False)
    with op.batch_alter_table('ad_records') as batch:
        batch.drop_column('report_date')
