from datetime import date

from pydantic import Field, model_validator

from app.core.api import audit, fail
from app.models import new_id, now
from app.supply.common import active_store, allocations, number, operation, purchase_out, purchase_status, scoped_record
from app.supply.line_changes import LineChange, check_version
from app.supply.models import PurchaseLine, PurchaseOrder
from app.supply.schemas import Identifier, Quantity
from app.schemas import Input
from app.tasks.events import enqueue


class TransferItem(Input):
    product_id: Identifier
    quantity: Quantity


class PurchaseTransferInput(LineChange):
    order_date: date
    expected_date: date | None = None
    planned_ship_date: date | None = Field(default=None, ge=date(1901, 1, 1), le=date(2199, 12, 31))
    notes: str = Field(default='', max_length=5000)
    lines: list[TransferItem] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def valid_dates(self):
        if self.expected_date and self.expected_date < self.order_date:
            raise ValueError('预计到货不能早于采购日期')
        return self


def transfer_remaining(identifier, payload, db, user):
    scoped_record(db, PurchaseOrder, identifier, user)
    inserted, target_id = operation(db, payload, user, f'purchase.transfer:{identifier}', new_id())
    source = scoped_record(db, PurchaseOrder, identifier, user, lock=True)
    if not inserted:
        return purchase_out(scoped_record(db, PurchaseOrder, target_id, user), user)
    if source.status not in {'ordered', 'partially_received'}:
        fail(409, 'purchase_locked', '仅待交付或部分到货的采购单可转出剩余商品')
    active_store(db, user, source.store_id)
    check_version(source, payload.expected_version)
    allocated = allocations(db, source.id)
    original = {line.product_id: line for line in source.lines}
    target = PurchaseOrder(id=target_id, number=number('PO'), source_purchase_order_id=source.id,
        store_id=source.store_id, supplier_id=source.supplier_id, currency=source.currency,
        payment_terms=source.payment_terms, status='ordered', ordered_at=source.ordered_at,
        order_date=payload.order_date, expected_date=payload.expected_date,
        planned_ship_date=payload.planned_ship_date, notes=payload.notes, lines=[])
    changes = []
    for position, item in enumerate(payload.lines):
        line = original.get(item.product_id)
        remaining = (line.quantity - line.received_quantity - line.cancelled_quantity
                     - line.transferred_quantity - allocated.get(item.product_id, 0)) if line else 0
        if item.quantity > remaining:
            fail(409, 'purchase_transfer_exceeds_remaining', '商品不在原采购单可转余量内，或转出数量超过最新余量，请刷新后重试')
        line.transferred_quantity += item.quantity
        target.lines.append(PurchaseLine(product_id=line.product_id, product_name=line.product_name,
            internal_sku=line.internal_sku, position=position, quantity=item.quantity, unit_price=line.unit_price,
            received_quantity=0, cancelled_quantity=0, transferred_quantity=0))
        changes.append({'product_id': line.product_id, 'internal_sku': line.internal_sku, 'quantity': item.quantity})
    source.status, source.updated_at = purchase_status(source), now()
    db.add(target)
    db.flush()
    summary = '；'.join(f"{item['internal_sku']}：{item['quantity']} 件" for item in changes)
    audit(db, user, 'purchases.transfer', 'purchase_order', source.id,
          f'剩余商品转入 {target.number}；{summary}'[:500], source.store_id)
    audit(db, user, 'purchases.create', 'purchase_order', target.id,
          f'由采购单 {source.number} 转入剩余商品'[:500], target.store_id)
    enqueue(db, source, 'purchase', user, 'updated', {'transfer_to': target.id, 'lines': changes})
    enqueue(db, target, 'purchase', user, 'created', {'transfer_from': source.id})
    enqueue(db, target, 'purchase', user, 'updated')
    db.commit()
    db.expire(target)
    return purchase_out(target, user)
