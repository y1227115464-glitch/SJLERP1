from app.core.api import audit, fail
from app.models import now
from app.supply.common import active_products, active_store, allocations, operation, purchase_out, purchase_status, scoped_record
from app.supply.line_changes import check_version
from app.supply.models import PurchaseLine, PurchaseOrder
from app.tasks.events import enqueue


def amend_purchase(identifier, payload, db, user):
    scoped_record(db, PurchaseOrder, identifier, user)
    inserted, _ = operation(db, payload, user, f'purchase.lines:{identifier}', identifier)
    record = scoped_record(db, PurchaseOrder, identifier, user, lock=True)
    if not inserted:
        return purchase_out(record, user)
    if record.status not in {'ordered', 'partially_received', 'received'}:
        fail(409, 'purchase_locked', '仅已下单、部分到货或全部到货的采购单可调整商品；已取消或关闭的单据不可修改')
    active_store(db, user, record.store_id)
    check_version(record, payload.expected_version)
    existing = {line.product_id: line for line in record.lines}
    requested = {line.product_id: line for line in payload.lines}
    if existing.keys() - requested.keys():
        fail(409, 'purchase_line_required', '已提交采购单须保留原商品行，可调整数量或追加商品')
    products = active_products(db, requested.keys() - existing.keys())
    allocated = allocations(db, identifier)
    notes = []
    for position, item in enumerate(payload.lines):
        line = existing.get(item.product_id)
        if line:
            minimum = line.received_quantity + line.cancelled_quantity + allocated.get(item.product_id, 0)
            if item.quantity < minimum:
                fail(409, 'purchase_quantity_committed', f'{line.internal_sku} 数量不能少于已收货、已取消及已分配的合计 {minimum} 件')
            if item.unit_price is not None and item.unit_price != line.unit_price:
                fail(422, 'purchase_price_locked', '原商品单价保持不变，新增商品须填写单价')
            if line.quantity != item.quantity:
                notes.append(f'{line.internal_sku}：{line.quantity} → {item.quantity} 件')
            line.quantity, line.position = item.quantity, position
        else:
            if item.unit_price is None:
                fail(422, 'missing_price', '新增商品须填写采购单价')
            product = products[item.product_id]
            record.lines.append(PurchaseLine(product_id=product.id, product_name=product.name,
                internal_sku=product.internal_sku, position=position, quantity=item.quantity,
                unit_price=item.unit_price, received_quantity=0, cancelled_quantity=0))
            notes.append(f'新增 {product.internal_sku}：{item.quantity} 件')
    record.status = purchase_status(record)
    record.updated_at = now()
    # Money is deliberately excluded from audit summaries.
    audit(db, user, 'purchases.lines.update', 'purchase_order', identifier,
          ('调整采购商品；' + '；'.join(notes) + (f'。原因：{payload.reason}' if payload.reason else ''))[:500], record.store_id)
    enqueue(db, record, 'purchase', user, 'updated', {'line_changes': notes, 'reason': payload.reason})
    db.commit()
    db.expire(record)
    return purchase_out(record, user)
