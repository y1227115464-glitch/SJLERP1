import hashlib
import os
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import insert, select, update

from app.core.api import audit, fail, require_store
from app.core.security import aware, can_access_store, has_permission
from app.models import Store, User, new_id, now
from app.reports.comparison import chunks, compare
from app.reports.models import AdRecord, ReportImport, SalesRecord
from app.reports.parsers import AD_PARSER_VERSION, ad_keys, parse_report


def batch_out(batch, comparison=None):
    result = {'id': batch.id, 'store_id': batch.store_id, 'store_name': batch.store.name, 'kind': batch.kind,
              'filename': batch.filename, 'source_total': batch.source_total, 'unique_rows': batch.row_count,
              'duplicate_count': batch.duplicate_count, 'error_count': batch.error_count, 'parser_version': batch.parser_version,
              'created_at': aware(batch.created_at).isoformat(), 'confirmed_at': aware(batch.confirmed_at).isoformat() if batch.confirmed_at else None,
              'result': batch.result}
    if comparison:
        result.update(counts=comparison['counts'], verification_token=comparison['verification_token'])
    return result


def get_batch(db, user, identifier):
    batch = db.get(ReportImport, identifier)
    if batch is None or not can_access_store(user, batch.store_id):
        fail(404, 'not_found', '导入批次不存在或无权访问')
    return batch


def create_preview(db, user, file, kind, store_id, settings):
    store = require_store(db, user, store_id)
    if not store.is_active:
        fail(409, 'inactive_store', '店铺已停用，不能导入')
    try:
        content = file.file.read(settings.max_upload_bytes + 1)
    finally:
        file.file.close()
    if len(content) > settings.max_upload_bytes:
        fail(413, 'file_too_large', '文件超过上传大小限制')
    filename = Path((file.filename or 'report').replace('\\', '/')).name
    filename = ''.join(ch for ch in filename if ord(ch) >= 32 and ord(ch) != 127)[:255]
    extension = Path(filename).suffix.lower()
    if extension not in ({'.txt', '.tsv'} if kind == 'sales' else {'.xlsx'}):
        fail(422, 'invalid_extension', '销售请选择 TXT / TSV，广告请选择 XLSX 文件')
    parsed = parse_report(kind, content)
    batch = ReportImport(id=new_id(), owner_id=user.id, store_id=store_id, store=store, kind=kind, filename=filename,
        file_hash=hashlib.sha256(content).hexdigest(), storage_key=new_id(), created_at=now(),
        parser_version=AD_PARSER_VERSION if kind == 'ads' else 'amazon-v1',
        parsed_rows=parsed['rows'], errors=parsed['errors'], source_total=parsed['source_total'], duplicate_count=parsed['duplicate_count'],
        row_count=len(parsed['rows']), error_count=len(parsed['errors']))
    root = settings.storage_path.resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / batch.storage_key
    try:
        with path.open('xb') as output:
            os.chmod(path, 0o600)
            output.write(content)
        db.add(batch)
        db.flush()
        comparison = compare(db, batch)
        audit(db, user, 'reports.preview', 'report_import', batch.id, '预览亚马逊报表；未变更销售或广告事实', store_id)
        db.commit()
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return batch_out(batch, comparison)


def fact_values(batch, row):
    data = row['data']
    result = {'id': row['existing_id'] or new_id(), 'store_id': batch.store_id, 'natural_key': row['key'],
              'value_hash': next_hash(row), 'import_id': batch.id, 'source_row': row['row'], 'data': data}
    if batch.kind == 'sales':
        fields = ['amazon_order_id', 'sales_channel', 'sku', 'asin', 'product_name', 'order_status', 'item_status', 'quantity', 'currency', 'net_amount']
        result.update({field: data[field] for field in fields})
        result.update({field: datetime.fromisoformat(data[field]) for field in ['purchase_date', 'last_updated_date']})
    else:
        fields = ['campaign', 'ad_group', 'sku', 'asin', 'country', 'currency', 'impressions', 'clicks', 'spend', 'attributed_sales', 'orders', 'units']
        result.update({field: data[field] for field in fields})
        result.update({field: date.fromisoformat(data[field]) for field in ['start_date', 'end_date']})
        result.update(identity_key=ad_keys(data)[1], latest_report_at=batch.created_at,
                      report_date=date.fromisoformat(data['report_date']) if data.get('report_date') else None)
    return result


def next_hash(row):
    from app.reports.parsers import fingerprint
    return fingerprint(row['data'])


def confirm_import(db, user, identifier, verification_token):
    if db.bind.dialect.name == 'sqlite':
        connection = db.connection()
        if not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
    actor = db.scalar(select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True))
    if not actor or not has_permission(actor, 'reports.import'):
        fail(403, 'permission_denied', '账号权限已变化，不能确认导入')
    batch = get_batch(db, actor, identifier)
    if batch.owner_id != actor.id:
        fail(404, 'not_found', '只有上传者可确认此批次')
    store = db.scalar(select(Store).where(Store.id == batch.store_id).with_for_update().execution_options(populate_existing=True))
    if not store.is_active:
        fail(409, 'inactive_store', '店铺已停用，不能确认导入')
    # All confirmations serialize on the store, including different users and batches.
    db.refresh(batch)
    if batch.result is not None:
        return batch_out(batch)
    comparison = compare(db, batch)
    if batch.errors or comparison['counts']['conflict']:
        fail(409, 'import_has_errors', '存在错误或冲突，未导入任何记录；请查看批次明细')
    if comparison['verification_token'] != verification_token:
        fail(409, 'preview_changed', '预览后已有数据变化，请刷新预览并核对后再次确认')
    model = SalesRecord if batch.kind == 'sales' else AdRecord
    for action in ('create', 'update'):
        rows = [fact_values(batch, row) for row in comparison['rows'] if row['action'] == action]
        for group in chunks(rows):
            db.execute(insert(model) if action == 'create' else update(model), group)
    if batch.kind == 'ads':
        # A newer identical report confirms the version even when its metrics are unchanged.
        watermarks = [{'id': row['existing_id'], 'latest_report_at': batch.created_at}
                      for row in comparison['rows'] if row['action'] == 'skip' and row['advance_watermark']]
        for group in chunks(watermarks):
            db.execute(update(AdRecord), group)
    batch.result = {'created': comparison['counts']['create'], 'updated': comparison['counts']['update'],
                    'skipped': comparison['counts']['skip'], 'file_duplicates': batch.duplicate_count}
    batch.confirmed_at = now()
    audit(db, actor, 'reports.confirm', 'report_import', batch.id, '确认亚马逊报表；按业务键新增、更新或跳过', batch.store_id)
    db.commit()
    return batch_out(batch)
