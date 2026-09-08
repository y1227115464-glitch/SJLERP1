from dataclasses import dataclass

from sqlalchemy import and_, case, or_, select, update

from app.core.api import fail
from app.models import new_id, now
from app.supply.common import insert_ignore
from app.supply.models import InventoryBalance, InventoryMovement


@dataclass
class StockChange:
    store_id: str
    warehouse_id: str
    quantities: dict[str, tuple[int, int]]
    kind: str
    reference_id: str
    reference_number: str
    reason: str


def change_stock(db, user, change: StockChange):
    identifiers = sorted(change.quantities)
    timestamp = now()
    insert_ignore(db, InventoryBalance, [dict(id=new_id(), store_id=change.store_id, warehouse_id=change.warehouse_id,
                  product_id=identifier, quantity=0, reserved=0, updated_at=timestamp) for identifier in identifiers],
                  ['store_id', 'warehouse_id', 'product_id'])
    # Stable order prevents multi-item shipments from deadlocking each other.
    rows = db.execute(select(InventoryBalance.id, InventoryBalance.product_id, InventoryBalance.quantity, InventoryBalance.reserved)
        .where(InventoryBalance.store_id == change.store_id, InventoryBalance.warehouse_id == change.warehouse_id,
               InventoryBalance.product_id.in_(identifiers)).order_by(InventoryBalance.product_id).with_for_update()).all()
    if change.kind == 'opening' and db.scalar(select(InventoryMovement.id).where(
        InventoryMovement.store_id == change.store_id, InventoryMovement.warehouse_id == change.warehouse_id,
        InventoryMovement.product_id.in_(identifiers)).limit(1)):
        fail(409, 'opening_exists', '该商品已有库存流水，请使用库存调整登记差异')
    quantities, reservations, guards, movements = {}, {}, [], []
    for row in rows:
        delta, reserved_delta = change.quantities[row.product_id]
        quantity, reserved = row.quantity + delta, row.reserved + reserved_delta
        if quantity < 0 or reserved < 0 or quantity < reserved:
            fail(409, 'insufficient_stock', '可用库存不足，或变动会占用已分配给其他货件的库存')
        quantities[row.id], reservations[row.id] = quantity, reserved
        guards.append(and_(InventoryBalance.id == row.id, InventoryBalance.quantity == row.quantity, InventoryBalance.reserved == row.reserved))
        movements.append(InventoryMovement(store_id=change.store_id, warehouse_id=change.warehouse_id, product_id=row.product_id,
            kind=change.kind, quantity=delta, reserved_delta=reserved_delta, balance_after=quantity, reserved_after=reserved,
            reference_id=change.reference_id, reference_number=change.reference_number, reason=change.reason,
            actor_name=user.display_name, created_at=timestamp))
    updated = db.execute(update(InventoryBalance).where(or_(*guards)).values(
        quantity=case(quantities, value=InventoryBalance.id), reserved=case(reservations, value=InventoryBalance.id), updated_at=timestamp)
        .execution_options(synchronize_session=False))
    if updated.rowcount != len(rows):
        fail(409, 'stock_changed', '库存已被其他操作更新，请刷新后重试')
    db.add_all(movements)
