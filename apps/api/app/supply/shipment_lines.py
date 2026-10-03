from app.core.api import audit, fail
from app.core.security import has_permission
from app.models import now
from app.supply.common import active_products, active_store, allocations, event, locked_shipment, operation, scoped_record, shipment_detail
from app.supply.line_changes import check_version
from app.supply.models import Shipment, ShipmentLine
from app.supply.packing import require_whole_cartons
from app.supply.shipment_sources import line_key, resolve_items
from app.supply.stock import StockChange, change_stock
from app.tasks.events import enqueue


def validate_lines(db, record, purchases, items):
    existing = {line_key(line): line for line in record.lines}
    requested = {line_key(item): item for item in items}
    for product_id, line in existing.items():
        if line.received_quantity and (product_id not in requested or requested[product_id].quantity < line.received_quantity):
            fail(409, 'received_line_locked', f'{line.internal_sku} 已接收 {line.received_quantity} 件，不能移除或减少到已接收数量以下')
    products = active_products(db, {item.product_id for item in items if line_key(item) not in existing})
    purchased = {line.id: line for order in purchases for line in order.lines}
    allocated = {order.id: allocations(db, order.id) for order in purchases}
    packing = {}
    for item in items:
        line = existing.get(line_key(item))
        size = item.units_per_carton
        if size is None:
            size = line.units_per_carton if line else products[item.product_id].units_per_carton
        packing[line_key(item)] = require_whole_cartons(item.quantity, size)
        if purchases:
            ordered = purchased.get(item.purchase_line_id)
            own_pending = line.quantity - line.received_quantity if line else 0
            others = allocated[ordered.purchase_order_id].get(item.product_id, 0) - own_pending
            pending = item.quantity - (line.received_quantity if line else 0)
            if not ordered or pending > ordered.quantity - ordered.received_quantity - ordered.cancelled_quantity - ordered.transferred_quantity - ordered.supplier_stock_quantity - others:
                fail(409, 'purchase_overallocated', '商品不在采购单内，或修改后的数量超过采购可分配余量；请先调整采购单')
    return existing, requested, products, purchased, packing


def amend_shipment(identifier, payload, db, user):
    snapshot = scoped_record(db, Shipment, identifier, user)
    if payload.purchase_order_ids is not None:
        if snapshot.source_warehouse_id:
            fail(422, 'warehouse_source_locked', '仓库发货不能改为采购单发货')
        if set(payload.purchase_order_ids) != {order.id for order in snapshot.purchases} and not has_permission(user, 'purchases.view'):
            fail(403, 'permission_denied', '当前账号不能更换关联采购单')
    inserted, _ = operation(db, payload, user, f'shipment.lines:{identifier}', identifier)
    record, locked_purchases = locked_shipment(db, identifier, user, additional_purchase_ids=payload.purchase_order_ids or ())
    if not inserted:
        return shipment_detail(db, record)
    if record.status not in {'planned', 'in_transit', 'partially_received'}:
        fail(409, 'shipment_closed', '仅待发、在途和部分接收货件可修改商品；已收齐或取消的货件不可修改')
    active_store(db, user, record.store_id)
    check_version(record, payload.expected_version)
    original_purchases = list(record.purchases)
    original_ids = {order.id for order in original_purchases}
    selected_ids = set(payload.purchase_order_ids) if payload.purchase_order_ids is not None else original_ids
    purchases = [order for order in locked_purchases if order.id in selected_ids]
    for order in purchases:
        if order.store_id != record.store_id or (order.id not in original_ids and order.status not in {'ordered', 'partially_received'}):
            fail(409, 'invalid_purchase', '采购单店铺不匹配，或采购单尚未提交/已经结束')
    removed = [order for order in original_purchases if order.id not in selected_ids]
    removed_lines = {line.id for order in removed for line in order.lines}
    if any(line.received_quantity and line.purchase_line_id in removed_lines for line in record.lines):
        fail(409, 'received_purchase_locked', '已有商品接收的来源采购单不能移除，请保留该采购单及已接收商品')
    items, _ = resolve_items(purchases, payload.lines)
    existing, requested, products, purchased, packing = validate_lines(db, record, purchases, items)
    notes, deltas = [], {}
    if selected_ids != original_ids:
        notes.append('来源采购单：' + '、'.join(order.number for order in original_purchases)
                     + ' → ' + '、'.join(order.number for order in purchases))
        record.purchases = purchases
        record.purchase_order_id = purchases[0].id

    for product_id in sorted(existing.keys() | requested.keys()):
        before = existing[product_id].quantity if product_id in existing else 0
        after = requested[product_id].quantity if product_id in requested else 0
        sku = existing[product_id].internal_sku if product_id in existing else products[requested[product_id].product_id].internal_sku
        if after != before:
            notes.append(f'{sku}：{before} → {after} 件')
            deltas[product_id] = (0, after - before) if record.status == 'planned' else (before - after, 0)
        if product_id in existing and product_id in requested and existing[product_id].units_per_carton != packing[product_id]:
            notes.append(f'{sku} 箱规：{existing[product_id].units_per_carton or "未维护"} → {packing[product_id]} 件/箱')
    reason = '修改发货商品及数量（不建议操作）；' + '；'.join(notes) + (f'。原因：{payload.reason}' if payload.reason else '')
    if record.source_warehouse_id and deltas:
        change_stock(db, user, StockChange(record.store_id, record.source_warehouse_id,
                     deltas, 'adjustment', identifier, record.number, reason))
    for product_id, line in existing.items():
        if product_id not in requested:
            record.lines.remove(line)
    for position, item in enumerate(items):
        line = existing.get(line_key(item))
        if line:
            line.position, line.quantity, line.units_per_carton = position, item.quantity, packing[line_key(item)]
        else:
            product = products[item.product_id]
            record.lines.append(ShipmentLine(product_id=product.id, product_name=product.name,
                internal_sku=product.internal_sku, position=position, quantity=item.quantity, received_quantity=0,
                units_per_carton=packing[line_key(item)], purchase_line_id=item.purchase_line_id))
    if record.status != 'planned':
        complete = all(line.quantity == line.received_quantity for line in record.lines)
        record.status = 'received' if complete else 'partially_received' if any(line.received_quantity for line in record.lines) else 'in_transit'
        if complete:
            record.stage, record.received_at = 'received', now()
    record.updated_at = now()
    event(db, record, user, 'note', reason)
    audit(db, user, 'shipments.lines.update', 'shipment', identifier, reason[:500], record.store_id)
    for order in removed:
        enqueue(db, order, 'purchase', user, 'updated')
    enqueue(db, record, 'shipment', user, 'sources_changed' if selected_ids != original_ids else 'updated')
    db.commit()
    db.expire(record)
    return shipment_detail(db, record)
