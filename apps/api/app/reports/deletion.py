from sqlalchemy import delete, select

from app.core.api import audit, fail
from app.core.security import has_permission
from app.models import Store, User, now
from app.reports.models import AdRecord, SalesRecord
from app.reports.parsers import fingerprint
from app.reports.service import batch_out, get_batch


def deletion_preview(db, batch):
    model = SalesRecord if batch.kind == 'sales' else AdRecord
    # Provenance is transferred on updates, but not on duplicate/skipped imports.
    rows = db.execute(select(model.id, model.value_hash).where(
        model.import_id == batch.id, model.store_id == batch.store_id).order_by(model.id)).all()
    return {'affected_rows': len(rows), 'verification_token': fingerprint([
        batch.id, batch.result, str(batch.deleted_at), [list(row) for row in rows]])}


def delete_import(db, user, identifier, verification_token):
    if db.bind.dialect.name == 'sqlite':
        connection = db.connection()
        if not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
    actor = db.scalar(select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True))
    if not actor or not has_permission(actor, 'reports.import'):
        fail(403, 'permission_denied', '账号权限已变化，不能删除导入数据')
    batch = get_batch(db, actor, identifier)
    # Use the same store lock as confirmation, so the checked records cannot change mid-delete.
    store = db.scalar(select(Store).where(Store.id == batch.store_id).with_for_update().execution_options(populate_existing=True))
    if not store.is_active:
        fail(409, 'inactive_store', '店铺已停用，不能删除导入数据')
    db.refresh(batch)
    if batch.deleted_at:
        return batch_out(batch)
    preview = deletion_preview(db, batch)
    if preview['verification_token'] != verification_token:
        fail(409, 'preview_changed', '批次或关联数据已变化，请刷新删除预览并重新核对')
    model = SalesRecord if batch.kind == 'sales' else AdRecord
    db.execute(delete(model).where(model.import_id == batch.id, model.store_id == batch.store_id))
    batch.deleted_at = now()
    batch.deletion_result = {'deleted_rows': preview['affected_rows']}
    audit(db, actor, 'reports.delete', 'report_import', batch.id,
          f"删除导入批次及当前归属的 {preview['affected_rows']} 条{batch.kind}记录；保留来源供追溯", batch.store_id)
    db.commit()
    return batch_out(batch)
