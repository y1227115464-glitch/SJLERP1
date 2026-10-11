#!/usr/bin/env python3
"""Export only master data; atomically import into a new, migrated database.

Source transactions are read-only. No delete, truncate, or overwrite option exists.
The import receipt makes bootstrap safe to rerun after the NAS has gone into use.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import Date, DateTime, MetaData, Numeric, create_engine, func, select, text


TABLES = frozenset({
    'users', 'user_stores', 'stores', 'suppliers', 'products', 'product_stores',
    'supplier_quotes', 'quote_products', 'sales_cost_rates', 'fba_fee_rates',
    'fba_catalog_deletions',
})
RECEIPT = 'nas_master_data_receipt'
IGNORED = {'alembic_version', RECEIPT}


def json_value(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat() if value.tzinfo else value.isoformat()
    if isinstance(value, (date, Decimal)):
        return str(value)
    raise TypeError(type(value).__name__)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=json_value)


def clean_row(name, row):
    row = dict(row)
    if name == 'products' and isinstance(row.get('source_data'), dict):
        # The original product CSV also contains historical stock and monthly sales.
        row['source_data'] = {k: v for k, v in row['source_data'].items()
                              if k not in {'stock', 'monthly_sales'}}
    return row


def metadata(connection):
    result = MetaData()
    result.reflect(connection)
    return result


def counts(connection, tables):
    return {t.name: connection.scalar(select(func.count()).select_from(t)) for t in tables}


def export_data(engine):
    with engine.connect() as connection:
        if engine.dialect.name == 'postgresql':
            connection = connection.execution_options(isolation_level='REPEATABLE READ')
            connection.execute(text('SET TRANSACTION READ ONLY'))
        meta = metadata(connection)
        if not TABLES <= meta.tables.keys():
            raise ValueError('Source is missing required master-data tables')
        rows = {}
        for name in sorted(TABLES):
            table = meta.tables[name]
            rows[name] = [clean_row(name, row) for row in connection.execute(
                select(table).order_by(*table.primary_key.columns)).mappings()]
        return json.loads(canonical({
            'format': 'sjlerp-master-data-v1',
            'schema_revision': connection.scalar(select(meta.tables['alembic_version'].c.version_num)),
            'exported_at': datetime.now(timezone.utc),
            'tables': rows,
            'excluded_counts': counts(connection, [t for t in meta.sorted_tables
                                                   if t.name not in TABLES | IGNORED]),
        }))


def validate_payload(payload):
    if payload.get('format') != 'sjlerp-master-data-v1' or set(payload.get('tables', {})) != TABLES:
        raise ValueError('Unexpected migration format or table allowlist')
    for name, rows in payload['tables'].items():
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError(f'Invalid rows: {name}')
    for row in payload['tables']['products']:
        if isinstance(row.get('source_data'), dict) and {'stock', 'monthly_sales'} & row['source_data'].keys():
            raise ValueError('Historical stock/sales remain in product source data')


def decode_row(table, row):
    if set(row) != set(table.columns.keys()):
        raise ValueError(f'Column mismatch: {table.name}')
    result = dict(row)
    for col in table.columns:
        value = result[col.name]
        if value is None:
            continue
        if isinstance(col.type, DateTime):
            result[col.name] = datetime.fromisoformat(value)
        elif isinstance(col.type, Date):
            result[col.name] = date.fromisoformat(value)
        elif isinstance(col.type, Numeric):
            result[col.name] = Decimal(value)
    return result


def fingerprint(rows):
    return sorted(canonical(row) for row in rows)


def verify_data(connection, meta, payload):
    for name, rows in payload['tables'].items():
        table = meta.tables[name]
        expected = [decode_row(table, row) for row in rows]
        actual = [dict(row) for row in connection.execute(select(table)).mappings()]
        if fingerprint(actual) != fingerprint(expected):
            raise ValueError(f'Imported content differs: {name}')
    excluded = counts(connection, [t for t in meta.sorted_tables if t.name not in TABLES | IGNORED])
    if any(excluded.values()):
        raise ValueError('Operational tables must be empty at initial migration verification')
    return {'kept': {name: len(rows) for name, rows in payload['tables'].items()},
            'excluded': excluded}


def import_data(engine, payload):
    validate_payload(payload)
    digest = hashlib.sha256(canonical(payload).encode()).hexdigest()
    with engine.begin() as connection:
        if engine.dialect.name == 'postgresql':
            connection.execute(text('SELECT pg_advisory_xact_lock(734520261011)'))
        meta = metadata(connection)
        if RECEIPT in meta.tables:
            prior = connection.scalar(select(meta.tables[RECEIPT].c.digest))
            if prior == digest:
                return {'status': 'already_imported', 'sha256': digest}
            if prior is not None:
                raise ValueError('A different package was already imported; refusing overwrite')
        if not TABLES <= meta.tables.keys() or 'alembic_version' not in meta.tables:
            raise ValueError('Run alembic upgrade head before importing')
        revision = connection.scalar(select(meta.tables['alembic_version'].c.version_num))
        if revision != payload['schema_revision']:
            raise ValueError('Database migration revision differs from package')
        tables = [t for t in meta.sorted_tables if t.name not in IGNORED]
        if engine.dialect.name == 'postgresql':
            names = ', '.join(connection.dialect.identifier_preparer.quote(t.name) for t in tables)
            connection.execute(text(f'LOCK TABLE {names} IN SHARE ROW EXCLUSIVE MODE'))
        if any(counts(connection, tables).values()):
            raise ValueError('Target contains data; refusing import into a nonempty database')
        for table in tables:
            if table.name in TABLES:
                rows = [decode_row(table, row) for row in payload['tables'][table.name]]
                if rows:
                    connection.execute(table.insert(), rows)
        verified = verify_data(connection, meta, payload)
        connection.execute(text(f'CREATE TABLE IF NOT EXISTS {RECEIPT} '
                                '(id INTEGER PRIMARY KEY CHECK (id = 1), digest VARCHAR(64) NOT NULL)'))
        connection.execute(text(f'INSERT INTO {RECEIPT} (id, digest) VALUES (1, :digest)'), {'digest': digest})
        return {'status': 'imported', 'sha256': digest, **verified}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['export', 'import', 'verify'])
    parser.add_argument('file', type=Path)
    parser.add_argument('--env-file', type=Path, help='Explicit source .env; otherwise use process environment')
    args = parser.parse_args()
    config = dict(os.environ)
    if args.env_file:
        from dotenv import dotenv_values
        config.update({k: v for k, v in dotenv_values(args.env_file).items() if v is not None})
    engine = create_engine(config['SJL_DATABASE_URL'])
    if args.action == 'export':
        payload = export_data(engine)
        args.file.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(args.file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(canonical(payload) + '\n')
        result = {'kept': {name: len(rows) for name, rows in payload['tables'].items()},
                  'excluded': payload['excluded_counts']}
    else:
        payload = json.loads(args.file.read_text())
        validate_payload(payload)
        if args.action == 'import':
            result = import_data(engine, payload)
        else:
            with engine.connect() as connection:
                result = verify_data(connection, metadata(connection), payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
