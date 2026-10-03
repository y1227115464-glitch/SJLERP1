"""Resolve supplier rows by purchase line, including legacy single-order requests."""
from app.core.api import fail
from app.supply.common import allocations
from app.supply.schemas import ShipmentItem


def line_key(line):
    return ('stock:' + line.supplier_stock_id) if line.supplier_stock_id else (line.purchase_line_id or line.product_id)


def resolve_items(purchases, items, stocks=None):
    purchased = {line.id: line for order in purchases for line in order.lines}
    resolved = []
    for item in items:
        if item.supplier_stock_id:
            stock = (stocks or {}).get(item.supplier_stock_id)
            if not stock or stock.line.product_id != item.product_id or (item.purchase_line_id and item.purchase_line_id != stock.purchase_line_id):
                fail(422, 'invalid_supplier_stock', '供应商库存批次与商品或采购明细不匹配')
            item = item.model_copy(update={'purchase_line_id': stock.purchase_line_id})
        if purchases:
            matches = [line for line in purchased.values() if line.product_id == item.product_id
                       and (not item.purchase_line_id or line.id == item.purchase_line_id)]
            if len(matches) != 1:
                fail(409, 'purchase_overallocated', '商品不在所选采购单内，或同一商品来自多个采购单，请指定采购明细')
            item = item.model_copy(update={'purchase_line_id': matches[0].id})
        elif item.purchase_line_id:
            fail(422, 'invalid_purchase_line', '仓库发货不能关联采购明细')
        resolved.append(item)
    if len({line_key(item) for item in resolved}) != len(resolved):
        fail(422, 'duplicate_shipment_line', '同一采购商品只能填写一行')
    return resolved, purchased


def default_items(db, purchases):
    items = []
    for order in purchases:
        allocated = allocations(db, order.id)
        for line in order.lines:
            remaining = (line.quantity - line.received_quantity - line.cancelled_quantity
                         - line.transferred_quantity - line.supplier_stock_quantity - allocated.get(line.product_id, 0))
            if remaining > 0:
                items.append(ShipmentItem(product_id=line.product_id, purchase_line_id=line.id, quantity=remaining))
    if not items:
        fail(409, 'purchase_overallocated', '所选采购单没有可安排的商品余量')
    if len(items) > 1000:
        fail(422, 'shipment_line_limit', '单个发货计划最多包含 1000 行商品')
    return items
