"""Resolve legacy identities without changing facts during an import preview."""
import hashlib
from collections import defaultdict

from sqlalchemy import select

from app.reports.models import ReportImport, SalesRecord
from app.reports.parsers import fingerprint, sales_key, sales_legacy_key, sales_row, text_rows


def recover_source_data(db, records, settings):
    recovered = {}
    if settings is None:
        return recovered
    by_import = defaultdict(dict)
    for record in records:
        if not record.data.get('order_item_id'):
            by_import[record.import_id][record.source_row] = record
    for import_id, wanted in by_import.items():
        source = db.get(ReportImport, import_id)
        if source is None:
            continue
        path = settings.storage_path.resolve() / source.storage_key
        if path.parent != settings.storage_path.resolve():
            continue
        try:
            with path.open('rb') as stream:
                content = stream.read(settings.max_upload_bytes + 1)
            if len(content) > settings.max_upload_bytes or hashlib.sha256(content).hexdigest() != source.file_hash:
                continue
            generator = text_rows(content)
            try:
                headers = [value.strip() for value in next(generator)]
                if 'order-item-id' not in headers:
                    continue
                for index, values in enumerate(generator, 2):
                    record = wanted.get(index)
                    if record is None or len(values) != len(headers):
                        continue
                    data = sales_row(dict(zip(headers, values)))[2]
                    legacy_data = {key: value for key, value in data.items() if key != 'order_item_id'}
                    if data.get('order_item_id') and fingerprint(legacy_data) == record.value_hash:
                        recovered[record.id] = data
            finally:
                generator.close()
        except (OSError, ValueError, TypeError, StopIteration):
            # Missing/unverifiable archives must never cause an unguarded insert.
            continue
    return recovered


def sales_existing(db, batch, settings, chunks):
    incoming = defaultdict(list)
    for row in batch.parsed_rows:
        incoming[sales_legacy_key(row['data'])].append(row)
    records = []
    for orders in chunks({row['data']['amazon_order_id'] for row in batch.parsed_rows}):
        records.extend(db.scalars(select(SalesRecord).where(
            SalesRecord.store_id == batch.store_id, SalesRecord.amazon_order_id.in_(orders))))
    restored = recover_source_data(db, records, settings)
    existing, conflicts = {}, {}
    by_group = defaultdict(list)
    for record in records:
        data = restored.get(record.id, record.data)
        by_group[sales_legacy_key(data)].append(record)
        key = sales_key(data)
        if key in existing:
            conflicts[key] = '历史记录对应同一订单明细编号，请核对历史来源后重新导入'
        existing[key] = record
    for group, rows in incoming.items():
        previous = by_group[group]
        explicit = [old for old in previous if restored.get(old.id, old.data).get('order_item_id')]
        unknown = [old for old in previous if not restored.get(old.id, old.data).get('order_item_id')]
        has_item_id = any(row['data'].get('order_item_id') for row in rows)
        message = None
        if not has_item_id and explicit:
            message = '已有带订单明细编号的记录，本次缺少 order-item-id，请上传含明细编号的报告'
        elif has_item_id and unknown:
            # Only a unique exact content match can associate an unnumbered fact.
            # Never infer identity from a later timestamp or sum split line amounts.
            matches = [row for row in rows if len(unknown) == 1 and
                       fingerprint({k: v for k, v in row['data'].items() if k != 'order_item_id'}) == unknown[0].value_hash]
            if len(matches) == 1 and not explicit and matches[0]['key'] not in existing:
                row, old = matches[0], unknown[0]
                restored[old.id] = row['data']
                existing[row['key']] = old
            else:
                message = '历史记录缺少订单明细编号，无法唯一对应本次明细；请核对历史原始报告后重新导入'
        if message:
            conflicts.update({row['key']: message for row in rows})
    return existing, conflicts, restored
