"""Rebuild FBA lot consumption from immutable movements and current order facts.

This read model does not post sales back into the warehouse movement ledger:
reimports, corrections and deletion of sales facts therefore never double-deduct.
"""
from collections import defaultdict, deque
from datetime import date, timedelta

from sqlalchemy import func, select, tuple_

from app.core.security import aware
from app.reports.models import SalesRecord
from app.reports.routes import SALES_REPORT_TIMEZONE
from app.supply.models import InventoryMovement, Warehouse


def report_day(timestamp):
    return aware(timestamp).astimezone(SALES_REPORT_TIMEZONE).date().isoformat()


def allocate(movements, sales):
    """One store / exact SKU. Receipts and adjustments precede daily sales.

    Physical outbound movements consume only their own warehouse's lots.
    Unmatched demand stays on its original day; future receipts cannot cover it.
    """
    lots, daily, events = [], [], defaultdict(list)
    first_day = min((report_day(m.created_at) for m in movements if m.quantity > 0), default=None)
    for movement in sorted(movements, key=lambda m: (aware(m.created_at), m.id)):
        events[report_day(movement.created_at)].append(movement)
    orders = dict(sales)
    ignored = sum(quantity for day, quantity in sales if first_day and day < first_day)
    queue = deque()
    warehouse_queues = defaultdict(deque)

    def consume(quantity, kind, warehouse_id=None):
        allocations = []
        candidates = queue if warehouse_id is None else warehouse_queues[warehouse_id]
        while quantity and candidates:
            lot = candidates[0]
            if not lot['remaining_quantity']:
                candidates.popleft()
                continue
            taken = min(quantity, lot['remaining_quantity'])
            lot['remaining_quantity'] -= taken
            lot[kind + '_consumed'] += taken
            quantity -= taken
            allocations.append({'movement_id': lot['movement_id'], 'reference_number': lot['reference_number'],
                                'created_at': lot['created_at'], 'quantity': taken})
        return allocations, quantity

    other_shortage = 0
    for day in sorted(set(events) | set(orders)):
        for movement in events[day]:
            if movement.quantity > 0:
                lot = {'movement_id': movement.id, 'reference_number': movement.reference_number,
                       'warehouse_id': movement.warehouse_id, 'created_at': aware(movement.created_at).isoformat(),
                       'quantity': movement.quantity, 'remaining_quantity': movement.quantity,
                       'sales_consumed': 0, 'other_consumed': 0, 'is_current': False}
                lots.append(lot)
                queue.append(lot)
                warehouse_queues[movement.warehouse_id].append(lot)
            elif movement.quantity < 0:
                _, shortage = consume(-movement.quantity, 'other', movement.warehouse_id)
                other_shortage += shortage
        quantity = orders.get(day, 0)
        if quantity and (first_day is None or day >= first_day):
            allocations, shortage = consume(quantity, 'sales')
            daily.append({'date': day, 'quantity': quantity, 'consumed_quantity': quantity - shortage,
                          'shortage_quantity': shortage, 'allocations': allocations})
    current = next((lot for lot in lots if lot['remaining_quantity']), None)
    if current:
        current['is_current'] = True
    return {'start_date': first_day, 'inbound_quantity': sum(lot['quantity'] for lot in lots),
            'order_quantity': sum(row['quantity'] for row in daily),
            'consumed_quantity': sum(lot['sales_consumed'] for lot in lots),
            'other_consumed_quantity': sum(lot['other_consumed'] for lot in lots),
            'remaining_quantity': sum(lot['remaining_quantity'] for lot in lots),
            'shortage_quantity': sum(row['shortage_quantity'] for row in daily),
            'other_shortage_quantity': other_shortage,
            'ignored_order_quantity': ignored, 'current_lot': current, 'lots': lots, 'daily': daily}


def calculate(db, scopes):
    """scopes are already authorized (store_id, product_id, exact SKU) tuples."""
    if not scopes:
        return {}
    movements = defaultdict(list)
    for item in db.scalars(select(InventoryMovement).where(
            InventoryMovement.warehouse_id.in_(select(Warehouse.id).where(Warehouse.kind == 'fba')),
            tuple_(InventoryMovement.store_id, InventoryMovement.product_id).in_([(s, p) for s, p, _ in scopes]))):
        movements[(item.store_id, item.product_id)].append(item)
    day = (func.date(func.timezone('UTC', SalesRecord.purchase_date) - timedelta(hours=7))
           if db.bind.dialect.name == 'postgresql' else func.date(SalesRecord.purchase_date, '-7 hours'))
    query = select(SalesRecord.store_id, SalesRecord.sku, day, func.sum(SalesRecord.quantity)).where(
        tuple_(SalesRecord.store_id, SalesRecord.sku).in_([(s, sku) for s, _, sku in scopes]),
        SalesRecord.item_status == 'Shipped', SalesRecord.order_status.in_(['Shipped', 'Partially Shipped']),
        SalesRecord.data['fulfillment_channel'].as_string() == 'Amazon', SalesRecord.quantity > 0,
    ).group_by(SalesRecord.store_id, SalesRecord.sku, day)
    sales = defaultdict(list)
    for store, sku, source_day, quantity in db.execute(query):
        sales[(store, sku)].append((source_day.isoformat() if isinstance(source_day, date) else source_day, int(quantity)))
    return {(store, product): allocate(movements[(store, product)], sales[(store, sku)])
            for store, product, sku in scopes}
