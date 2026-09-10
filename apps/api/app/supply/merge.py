"""Merge compatible planned shipments without moving stock or purchase allocations."""
from pydantic import Field, model_validator
from sqlalchemy import select

from app.core.api import audit, fail
from app.models import now
from app.supply.common import active_store, event, operation, scoped, scoped_record, shipment_detail
from app.supply.line_changes import check_version
from app.supply.models import PurchaseOrder, Shipment, ShipmentLine
from app.supply.packing import require_whole_cartons
from app.supply.schemas import ActionInput, Identifier
from app.tasks.events import enqueue


class MergeInput(ActionInput):
    shipment_ids: list[Identifier] = Field(min_length=2, max_length=100)
    expected_versions: dict[str, str] = Field(max_length=100)

    @model_validator(mode='after')
    def valid_selection(self):
        if len(set(self.shipment_ids)) != len(self.shipment_ids):
            raise ValueError('不能重复选择货件')
        if set(self.expected_versions) != set(self.shipment_ids):
            raise ValueError('请提供所有货件的当前版本')
        return self


def merge(payload, db, user):
    rows = db.execute(scoped(select(Shipment.id, Shipment.purchase_order_id).where(Shipment.id.in_(payload.shipment_ids)),
        user, Shipment.store_id)).all()
    if len(rows) != len(payload.shipment_ids):
        fail(404, 'not_found', '所选货件不存在或无权访问')
    inserted, identifier = operation(db, payload, user, 'shipment.merge', payload.shipment_ids[0])
    if not inserted:
        return shipment_detail(db, scoped_record(db, Shipment, identifier, user))
    # Match dispatch/receipt/amendment lock order and sort batches to prevent deadlocks.
    purchase_ids = sorted({row.purchase_order_id for row in rows if row.purchase_order_id})
    if purchase_ids:
        list(db.scalars(select(PurchaseOrder).where(PurchaseOrder.id.in_(purchase_ids)).order_by(PurchaseOrder.id)
            .with_for_update(of=PurchaseOrder).execution_options(populate_existing=True)))
    records = {row.id: row for row in db.scalars(scoped(select(Shipment).where(Shipment.id.in_(payload.shipment_ids)),
        user, Shipment.store_id).order_by(Shipment.id).with_for_update(of=Shipment).execution_options(populate_existing=True))}
    target = records[identifier]
    active_store(db, user, target.store_id)
    route = lambda row: (row.store_id, row.purchase_order_id, row.source_warehouse_id, row.destination_warehouse_id)
    quantities, samples = {}, {}
    for row in records.values():
        if row.status != 'planned' or row.merged_into_id or row.shipped_at or any(line.received_quantity for line in row.lines):
            fail(409, 'invalid_status', '只能合并尚未发出的待发货件')
        if route(row) != route(target):
            fail(409, 'merge_route_mismatch', '合并货件须属于同一店铺、同一采购单或发货仓、同一收货仓')
        check_version(row, payload.expected_versions[row.id])
        for line in row.lines:
            require_whole_cartons(line.quantity, line.units_per_carton)
            previous = samples.get(line.product_id)
            if previous and (previous.units_per_carton != line.units_per_carton or previous.purchase_line_id != line.purchase_line_id):
                fail(409, 'merge_packing_mismatch', '同一商品的箱规或采购明细不一致，请先统一后再合并')
            samples[line.product_id] = line
            quantities[line.product_id] = quantities.get(line.product_id, 0) + line.quantity
    if len(quantities) > 100 or any(quantity > 1000000000 for quantity in quantities.values()):
        fail(422, 'merge_quantity_limit', '合并后不能超过 100 种商品，单种数量不能超过 10 亿件')
    # A single header cannot retain conflicting tracking references or dates implicitly.
    for field in ['carrier', 'tracking_number', 'amazon_shipment_id', 'expected_date', 'planned_ship_date']:
        choices = {getattr(row, field) for row in records.values() if getattr(row, field)}
        if len(choices) > 1:
            fail(409, 'merge_logistics_conflict', '物流资料或预计日期不一致，请先统一后再合并')
        if choices:
            setattr(target, field, next(iter(choices)))
    existing = {line.product_id: line for line in target.lines}
    for product_id, quantity in quantities.items():
        if product_id in existing:
            existing[product_id].quantity = quantity
        else:
            line = samples[product_id]
            target.lines.append(ShipmentLine(product_id=product_id, purchase_line_id=line.purchase_line_id,
                product_name=line.product_name, internal_sku=line.internal_sku, units_per_carton=line.units_per_carton,
                position=len(target.lines), quantity=quantity, received_quantity=0))
    source_numbers = []
    for source_id in payload.shipment_ids[1:]:
        source = records[source_id]
        source.status, source.stage, source.merged_into_id = 'cancelled', 'cancelled', identifier
        source_numbers.append(source.number)
        event(db, source, user, 'note', f'已合并至 {target.number}，原商品明细保留备查')
        if source.notes:
            event(db, target, user, 'note', f'合并来源 {source.number} 备注：{source.notes}')
        audit(db, user, 'shipments.merge', 'shipment', source.id, f'合并至 {target.number}', source.store_id)
        enqueue(db, source, 'shipment', user, 'updated')
    target.updated_at = now()
    summary = '合并待发货件：' + '、'.join(source_numbers)
    event(db, target, user, 'note', summary)
    audit(db, user, 'shipments.merge', 'shipment', target.id, summary[:500], target.store_id)
    enqueue(db, target, 'shipment', user, 'updated')
    db.commit()
    db.expire(target)
    return shipment_detail(db, target)
