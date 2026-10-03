"""Move supplier-held quantities into shipment allocations in the same transaction."""
from app.core.api import fail
from app.core.security import has_permission
from app.models import now
from app.supply.common import purchase_status, scoped_record
from app.supply.supplier_stock import SupplierStock, record_event
from app.tasks.events import enqueue


def stock_sources(db, user, items, store_id):
    ids = {line.supplier_stock_id for line in items if line.supplier_stock_id}
    if ids and not has_permission(user, 'purchases.view'):
        fail(403, 'permission_denied', '当前账号不能使用供应商库存')
    stocks = {identifier: scoped_record(db, SupplierStock, identifier, user) for identifier in sorted(ids)}
    if any(stock.store_id != store_id for stock in stocks.values()):
        fail(409, 'invalid_supplier_stock', '供应商库存必须属于发货店铺')
    return stocks


def apply_stock_changes(db, user, purchases, before, after, number):
    # Caller holds all affected purchase locks before these batch locks.
    old = {line.supplier_stock_id: line.quantity for line in before if line.supplier_stock_id}
    new = {line.supplier_stock_id: line.quantity for line in after if line.supplier_stock_id}
    orders = {order.id: order for order in purchases}
    changed = set()
    for identifier in sorted(old.keys() | new.keys()):
        delta = new.get(identifier, 0) - old.get(identifier, 0)
        if not delta:
            continue
        stock = scoped_record(db, SupplierStock, identifier, user, lock=True)
        order = orders.get(stock.purchase_order_id)
        if not order or not 0 <= stock.remaining_quantity - delta <= stock.quantity:
            fail(409, 'insufficient_supplier_stock', '发货数量超过供应商库存批次余量，请刷新后重试')
        stock.remaining_quantity -= delta
        line = next(line for line in order.lines if line.id == stock.purchase_line_id)
        line.supplier_stock_quantity -= delta
        record_event(db, stock, user, 'shipment', -delta, f'货件 {number} 分配调整 {delta:+d} 件')
        changed.add(order.id)
    for identifier in changed:
        order = orders[identifier]
        order.status, order.updated_at = purchase_status(order), now()
        enqueue(db, order, 'purchase', user, 'updated')
