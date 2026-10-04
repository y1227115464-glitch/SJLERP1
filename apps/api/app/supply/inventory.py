from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.api import DB, Page, audit, fail, paginated, require
from app.models import Product, Store, User, new_id
from app.supply.common import active_products, active_store, operation, scoped, values
from app.supply.defaults import resolve_warehouse
from app.supply.fifo import calculate as calculate_fifo
from app.supply.models import InventoryBalance, InventoryMovement, Shipment, ShipmentLine, Warehouse
from app.supply.schemas import AdjustmentInput, WarehouseInput
from app.supply.stock import StockChange, change_stock

router = APIRouter(prefix='/api/v1')
Reader = Annotated[User, Depends(require('inventory.view'))]
Writer = Annotated[User, Depends(require('inventory.adjust'))]
WarehouseWriter = Annotated[User, Depends(require('warehouses.manage'))]
WarehouseKind = Literal['domestic', 'overseas', 'fba']


def warehouse_scope(statement, column, kind):
    if kind:
        statement = statement.where(column.in_(select(Warehouse.id).where(Warehouse.kind == kind)))
    return statement


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
              product_id: str | None = None, q: str = '', warehouse_kind: WarehouseKind | None = None):
    statement = stock_query(select(InventoryBalance), InventoryBalance, user, store_id, warehouse_id, product_id)
    statement = warehouse_scope(statement, InventoryBalance.warehouse_id, warehouse_kind)
    if q.strip():
        statement = statement.join(Product, Product.id == InventoryBalance.product_id).where(
            Product.name.ilike('%'+q.strip()+'%') | Product.internal_sku.ilike('%'+q.strip()+'%'))
    return paginated(db, statement.order_by(InventoryBalance.updated_at.desc(), InventoryBalance.id), page, balance_out)


@router.get('/inventory/summary')
def summary(db: DB, user: Reader, store_id: str | None = None, warehouse_kind: WarehouseKind | None = None):
    balances = scoped(select(func.coalesce(func.sum(InventoryBalance.quantity), 0), func.coalesce(func.sum(InventoryBalance.reserved), 0)), user, InventoryBalance.store_id, store_id)
    balances = warehouse_scope(balances, InventoryBalance.warehouse_id, warehouse_kind)
    quantity, reserved = db.execute(balances).one()
    transit = scoped(select(func.coalesce(func.sum(ShipmentLine.quantity - ShipmentLine.received_quantity), 0)).join(
        Shipment, Shipment.id == ShipmentLine.shipment_id).where(Shipment.status.in_(['in_transit', 'partially_received'])), user, Shipment.store_id, store_id)
    transit = warehouse_scope(transit, Shipment.destination_warehouse_id, warehouse_kind)
    return {'quantity': int(quantity), 'reserved': int(reserved), 'available': int(quantity - reserved), 'in_transit': int(db.scalar(transit))}


@router.get('/inventory/movements')
def movements(db: DB, page: Page, user: Reader, store_id: str | None = None, warehouse_id: str | None = None,
              product_id: str | None = None, kind: Literal['opening', 'adjustment', 'reserve', 'release', 'dispatch', 'receipt'] | None = None,
              warehouse_kind: WarehouseKind | None = None):
    statement = stock_query(select(InventoryMovement), InventoryMovement, user, store_id, warehouse_id, product_id)
    statement = warehouse_scope(statement, InventoryMovement.warehouse_id, warehouse_kind)
    if kind:
        statement = statement.where(InventoryMovement.kind == kind)
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    items = list(db.scalars(statement.order_by(InventoryMovement.created_at.desc(), InventoryMovement.id)
                           .limit(page.limit).offset(page.offset)))
    scopes = {(item.store_id, item.product_id, item.product.internal_sku) for item in items if item.warehouse.kind == 'fba'}
    fifo = calculate_fifo(db, scopes)
    lots = {lot['movement_id']: lot for result in fifo.values() for lot in result['lots']}
    def output(item):
        return {**values(item, 'id store_id warehouse_id product_id kind quantity reserved_delta balance_after reserved_after reference_id reference_number reason actor_name created_at'),
                'store_name': item.store.name, 'warehouse_name': item.warehouse.name, 'internal_sku': item.product.internal_sku,
                'product_name': item.product.name, 'fifo': lots.get(item.id)}
    return {'total': total, 'items': [output(item) for item in items]}


@router.get('/inventory/fifo')
def fifo_summary(db: DB, page: Page, user: Reader, store_id: str | None = None, product_id: str | None = None):
    groups = scoped(select(InventoryBalance.store_id, InventoryBalance.product_id)
        .where(InventoryBalance.warehouse_id.in_(select(Warehouse.id).where(Warehouse.kind == 'fba'))),
        user, InventoryBalance.store_id, store_id)
    if product_id:
        groups = groups.where(InventoryBalance.product_id == product_id)
    groups = groups.distinct().subquery()
    total = db.scalar(select(func.count()).select_from(groups))
    records = db.execute(select(groups.c.store_id, groups.c.product_id, Store.name, Product.internal_sku, Product.name)
        .join(Store, Store.id == groups.c.store_id).join(Product, Product.id == groups.c.product_id)
        .order_by(Product.internal_sku, groups.c.store_id).limit(page.limit).offset(page.offset)).all()
    results = calculate_fifo(db, [(s, p, sku) for s, p, _, sku, _ in records])
    return {'total': total, 'items': [{'store_id': store, 'product_id': product, 'store_name': store_name,
        'internal_sku': sku, 'product_name': name,
        **{key: value for key, value in results[(store, product)].items() if key not in ('lots', 'daily')}}
        for store, product, store_name, sku, name in records]}


@router.get('/inventory/fifo/daily')
def fifo_daily(db: DB, page: Page, user: Reader, store_id: str, product_id: str):
    # Authorize before loading order quantities or lot references.
    query = scoped(select(InventoryBalance).where(InventoryBalance.product_id == product_id,
        InventoryBalance.warehouse_id.in_(select(Warehouse.id).where(Warehouse.kind == 'fba'))),
        user, InventoryBalance.store_id, store_id)
    balance = db.scalar(query.limit(1))
    if balance is None:
        fail(404, 'not_found', '库存 SKU 不存在或无权访问')
    result = calculate_fifo(db, [(store_id, product_id, balance.product.internal_sku)])[(store_id, product_id)]
    days = list(reversed(result['daily']))
    return {'total': len(days), 'items': days[page.offset:page.offset + page.limit]}


@router.post('/inventory/adjustments', status_code=201)
def adjust(payload: AdjustmentInput, db: DB, user: Writer):
    active_store(db, user, payload.store_id)
    inserted, identifier = operation(db, payload, user, 'inventory.adjustment', new_id())
    if inserted:
        warehouse = resolve_warehouse(db, user, payload.warehouse_id)
        active_products(db, [payload.product_id])
        change_stock(db, user, StockChange(payload.store_id, warehouse.id, {payload.product_id: (payload.quantity, 0)},
            payload.kind, identifier, '', payload.reason))
        audit(db, user, 'inventory.adjust', 'inventory', identifier, '登记期初库存或库存差异', payload.store_id)
        db.commit()
    return {'id': identifier, 'request_id': str(payload.request_id)}
