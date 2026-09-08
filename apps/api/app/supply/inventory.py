from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.api import DB, Page, audit, fail, paginated, require
from app.models import Product, User, new_id
from app.supply.common import active_products, active_store, active_warehouse, operation, scoped, values
from app.supply.models import InventoryBalance, InventoryMovement, Shipment, ShipmentLine, Warehouse
from app.supply.schemas import AdjustmentInput, WarehouseInput
from app.supply.stock import StockChange, change_stock

router = APIRouter(prefix='/api/v1')
Reader = Annotated[User, Depends(require('inventory.view'))]
Writer = Annotated[User, Depends(require('inventory.adjust'))]
WarehouseWriter = Annotated[User, Depends(require('warehouses.manage'))]


@router.get('/warehouses')
def warehouses(db: DB, page: Page, user: Reader, q: str = '', is_active: bool | None = None):
    statement = select(Warehouse)
    if q.strip():
        statement = statement.where(Warehouse.name.ilike('%'+q.strip()+'%') | Warehouse.code.ilike('%'+q.strip()+'%'))
    if is_active is not None:
        statement = statement.where(Warehouse.is_active.is_(is_active))
    return paginated(db, statement.order_by(Warehouse.code, Warehouse.id), page,
                     lambda item: values(item, 'id code name kind address is_active created_at'))


@router.post('/warehouses', status_code=201)
def create_warehouse(payload: WarehouseInput, db: DB, user: WarehouseWriter):
    record = Warehouse(**payload.model_dump())
    record.code = record.code.upper()
    db.add(record)
    db.flush()
    audit(db, user, 'warehouses.create', 'warehouse', record.id, '创建仓库档案')
    db.commit()
    return values(record, 'id code name kind address is_active created_at')


@router.patch('/warehouses/{identifier}')
def edit_warehouse(identifier: str, changes: dict, db: DB, user: WarehouseWriter):
    record = db.get(Warehouse, identifier)
    if not record:
        fail(404, 'not_found', '仓库不存在')
    try:
        payload = WarehouseInput.model_validate({**{key: getattr(record, key) for key in WarehouseInput.model_fields}, **changes})
    except ValidationError:
        fail(422, 'invalid_warehouse', '请检查仓库编码、名称与类型')
    if payload.kind != record.kind and db.scalar(select(InventoryBalance.id).where(InventoryBalance.warehouse_id == identifier).limit(1)):
        fail(409, 'warehouse_in_use', '已有库存记录的仓库不能变更类型')
    for key, value in payload.model_dump().items():
        setattr(record, key, value)
    record.code = record.code.upper()
    audit(db, user, 'warehouses.update', 'warehouse', identifier, '更新仓库档案')
    db.commit()
    return values(record, 'id code name kind address is_active created_at')


def balance_out(item):
    return {**values(item, 'id store_id warehouse_id product_id quantity reserved updated_at'), 'available': item.quantity - item.reserved,
            'store_name': item.store.name, 'warehouse_name': item.warehouse.name, 'warehouse_kind': item.warehouse.kind,
            'product_name': item.product.name, 'internal_sku': item.product.internal_sku}


def stock_query(statement, model, user, store_id, warehouse_id, product_id):
    statement = scoped(statement, user, model.store_id, store_id)
    if warehouse_id:
        statement = statement.where(model.warehouse_id == warehouse_id)
    if product_id:
        statement = statement.where(model.product_id == product_id)
    return statement


@router.get('/inventory')
def inventory(db: DB, page: Page, user: Reader, store_id: str | None = None, warehouse_id: str | None = None,
              product_id: str | None = None, q: str = ''):
    statement = stock_query(select(InventoryBalance), InventoryBalance, user, store_id, warehouse_id, product_id)
    if q.strip():
        statement = statement.join(Product, Product.id == InventoryBalance.product_id).where(
            Product.name.ilike('%'+q.strip()+'%') | Product.internal_sku.ilike('%'+q.strip()+'%'))
    return paginated(db, statement.order_by(InventoryBalance.updated_at.desc(), InventoryBalance.id), page, balance_out)


@router.get('/inventory/summary')
def summary(db: DB, user: Reader, store_id: str | None = None):
    balances = scoped(select(func.coalesce(func.sum(InventoryBalance.quantity), 0), func.coalesce(func.sum(InventoryBalance.reserved), 0)), user, InventoryBalance.store_id, store_id)
    quantity, reserved = db.execute(balances).one()
    transit = scoped(select(func.coalesce(func.sum(ShipmentLine.quantity - ShipmentLine.received_quantity), 0)).join(
        Shipment, Shipment.id == ShipmentLine.shipment_id).where(Shipment.status.in_(['in_transit', 'partially_received'])), user, Shipment.store_id, store_id)
    return {'quantity': int(quantity), 'reserved': int(reserved), 'available': int(quantity - reserved), 'in_transit': int(db.scalar(transit))}


@router.get('/inventory/movements')
def movements(db: DB, page: Page, user: Reader, store_id: str | None = None, warehouse_id: str | None = None,
              product_id: str | None = None, kind: Literal['opening', 'adjustment', 'reserve', 'release', 'dispatch', 'receipt'] | None = None):
    statement = stock_query(select(InventoryMovement), InventoryMovement, user, store_id, warehouse_id, product_id)
    if kind:
        statement = statement.where(InventoryMovement.kind == kind)
    def output(item):
        return {**values(item, 'id store_id warehouse_id product_id kind quantity reserved_delta balance_after reserved_after reference_id reference_number reason actor_name created_at'),
                'store_name': item.store.name, 'warehouse_name': item.warehouse.name, 'internal_sku': item.product.internal_sku, 'product_name': item.product.name}
    return paginated(db, statement.order_by(InventoryMovement.created_at.desc(), InventoryMovement.id), page, output)


@router.post('/inventory/adjustments', status_code=201)
def adjust(payload: AdjustmentInput, db: DB, user: Writer):
    active_store(db, user, payload.store_id)
    inserted, identifier = operation(db, payload, user, 'inventory.adjustment', new_id())
    if inserted:
        active_warehouse(db, payload.warehouse_id)
        active_products(db, [payload.product_id])
        change_stock(db, user, StockChange(payload.store_id, payload.warehouse_id, {payload.product_id: (payload.quantity, 0)},
            payload.kind, identifier, '', payload.reason))
        audit(db, user, 'inventory.adjust', 'inventory', identifier, '登记期初库存或库存差异', payload.store_id)
        db.commit()
    return {'id': identifier, 'request_id': str(payload.request_id)}
