from app.core.api import audit, fail
from app.models import now
from app.supply.common import active_products, active_store, allocations, event, locked_shipment, operation, scoped_record, shipment_detail
from app.supply.line_changes import check_version
from app.supply.models import Shipment, ShipmentLine
from app.supply.packing import require_whole_cartons
from app.supply.stock import StockChange, change_stock
from app.tasks.events import enqueue


def validate_lines(db, record, purchase, items):
    existing = {line.product_id: line for line in record.lines}
    requested = {item.product_id: item for item in items}
    for product_id, line in existing.items():
        if line.received_quantity and (product_id not in requested or requested[product_id].quantity < line.received_quantity):
            fail(409, 'received_line_locked', f'{line.internal_sku} 已接收 {line.received_quantity} 件，不能移除或减少到已接收数量以下')
    products = active_products(db, requested.keys() - existing.keys())
    purchased = {line.product_id: line for line in purchase.lines} if purchase else {}
    allocated = allocations(db, purchase.id) if purchase else {}
    packing = {}
    for item in items:
        line = existing.get(item.product_id)
        size = item.units_per_carton
        if size is None:
            size = line.units_per_carton if line else products[item.product_id].units_per_carton
        packing[item.product_id] = require_whole_cartons(item.quantity, size)
        if purchase:
            ordered = purchased.get(item.product_id)
            own_pending = line.quantity - line.received_quantity if line else 0
            others = allocated.get(item.product_id, 0) - own_pending
            pending = item.quantity - (line.received_quantity if line else 0)
            if not ordered or pending > ordered.quantity - ordered.received_quantity - ordered.cancelled_quantity - others:
                fail(409, 'purchase_overallocated', '商品不在采购单内，或修改后的数量超过采购可分配余量；请先调整采购单')
    return existing, requested, products, purchased, packing


def amend_shipment(identifier, payload, db, user):
    scoped_record(db, Shipment, identifier, user)
    inserted, _ = operation(db, payload, user, f'shipment.lines:{identifier}', identifier)
    record, purchase = locked_shipment(db, identifier, user)
    if not inserted:
        return shipment_detail(db, record)
    if record.status not in {'planned', 'in_transit', 'partially_received'}:
        fail(409, 'shipment_closed', '仅待发、在途和部分接收货件可修改商品；已收齐或取消的货件不可修改')
    active_store(db, user, record.store_id)
    check_version(record, payload.expected_version)
    existing, requested, products, purchased, packing = validate_lines(db, record, purchase, payload.lines)
    notes, deltas = [], {}
    for product_id in sorted(existing.keys() | requested.keys()):
        before = existing[product_id].quantity if product_id in existing else 0
        after = requested[product_id].quantity if product_id in requested else 0
        sku = existing[product_id].internal_sku if product_id in existing else products[product_id].internal_sku
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
    for position, item in enumerate(payload.lines):
        line = existing.get(item.product_id)
        if line:
            line.position, line.quantity, line.units_per_carton = position, item.quantity, packing[item.product_id]
        else:
            product = products[item.product_id]
            record.lines.append(ShipmentLine(product_id=product.id, product_name=product.name,
                internal_sku=product.internal_sku, position=position, quantity=item.quantity, received_quantity=0,
                units_per_carton=packing[item.product_id], purchase_line_id=purchased[item.product_id].id if purchase else None))
    if record.status != 'planned':
        complete = all(line.quantity == line.received_quantity for line in record.lines)
        record.status = 'received' if complete else 'partially_received' if any(line.received_quantity for line in record.lines) else 'in_transit'
        if complete:
            record.stage, record.received_at = 'received', now()
    record.updated_at = now()
    event(db, record, user, 'note', reason)
    audit(db, user, 'shipments.lines.update', 'shipment', identifier, reason[:500], record.store_id)
    enqueue(db, record, 'shipment', user, 'updated')
    db.commit()
    db.expire(record)
    return shipment_detail(db, record)
