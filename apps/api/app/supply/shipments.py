from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import ValidationError
from sqlalchemy import select

from app.core.api import DB, Page, audit, fail, paginated, require
from app.core.security import has_permission
from app.models import User, new_id, now
from app.supply.common import active_products, active_store, active_warehouse, allocations, event, locked_shipment, number, operation, purchase_status, scoped, scoped_record, shipment_detail, shipment_out
from app.supply.models import PurchaseOrder, Shipment, ShipmentLine
from app.supply.schemas import ActionInput, EventInput, ReceiptInput, ShipmentInput, ShipmentUpdate
from app.supply.stock import StockChange, change_stock

router = APIRouter(prefix='/api/v1/shipments')
Reader = Annotated[User, Depends(require('shipments.view'))]
Writer = Annotated[User, Depends(require('shipments.manage'))]


@router.get('')
def listing(db: DB, page: Page, user: Reader, store_id: str | None = None, q: str = '',
            purchase_order_id: str | None = None, status: Literal['planned', 'in_transit', 'partially_received', 'received', 'cancelled'] | None = None):
    statement = scoped(select(Shipment), user, Shipment.store_id, store_id)
    if q.strip():
        term = '%'+q.strip()+'%'
        statement = statement.where(Shipment.number.ilike(term) | Shipment.tracking_number.ilike(term) | Shipment.amazon_shipment_id.ilike(term))
    if status:
        statement = statement.where(Shipment.status == status)
    if purchase_order_id:
        statement = statement.where(Shipment.purchase_order_id == purchase_order_id)
    return paginated(db, statement.order_by(Shipment.created_at.desc(), Shipment.id), page, shipment_out)


@router.get('/{identifier}')
def detail(identifier: str, db: DB, user: Reader):
    return shipment_detail(db, scoped_record(db, Shipment, identifier, user))


@router.post('', status_code=201)
def create(payload: ShipmentInput, db: DB, user: Writer):
    active_store(db, user, payload.store_id)
    # Claim the idempotency token before taking resource locks, on every path.
    inserted, identifier = operation(db, payload, user, 'shipment.create', new_id())
    if not inserted:
        return shipment_detail(db, scoped_record(db, Shipment, identifier, user))
    active_warehouse(db, payload.destination_warehouse_id)
    products = active_products(db, [line.product_id for line in payload.lines])
    purchase_lines = {}
    if payload.purchase_order_id:
        if not has_permission(user, 'purchases.view'):
            fail(403, 'permission_denied', '当前账号不能关联采购单')
        purchase = scoped_record(db, PurchaseOrder, payload.purchase_order_id, user, lock=True)
        if purchase.store_id != payload.store_id or purchase.status not in {'ordered', 'partially_received'}:
            fail(409, 'invalid_purchase', '采购单店铺不匹配，或采购单尚未提交/已经结束')
        purchase_lines = {line.product_id: line for line in purchase.lines}
        allocated = allocations(db, purchase.id)
        for line in payload.lines:
            ordered = purchase_lines.get(line.product_id)
            if not ordered or line.quantity > ordered.quantity - ordered.received_quantity - ordered.cancelled_quantity - allocated.get(line.product_id, 0):
                fail(409, 'purchase_overallocated', '商品不在采购单内，或发货数量超过尚未分配的采购余量')
    else:
        active_warehouse(db, payload.source_warehouse_id)
    record = Shipment(id=identifier, number=number('SH'), **payload.model_dump(exclude={'request_id', 'lines'}))
    record.lines = [ShipmentLine(position=i, product_name=products[line.product_id].name,
        internal_sku=products[line.product_id].internal_sku,
        purchase_line_id=purchase_lines[line.product_id].id if purchase_lines else None,
        **line.model_dump()) for i, line in enumerate(payload.lines)]
    db.add(record)
    db.flush()
    if payload.source_warehouse_id:
        change_stock(db, user, StockChange(record.store_id, record.source_warehouse_id,
            {line.product_id: (0, line.quantity) for line in payload.lines}, 'reserve', identifier, record.number, '发货计划占用'))
    event(db, record, user, 'preparing', '创建发货计划')
    audit(db, user, 'shipments.create', 'shipment', identifier, '创建发货计划', record.store_id)
    db.commit()
    db.expire(record)
    return shipment_detail(db, record)


@router.patch('/{identifier}')
def edit(identifier: str, changes: dict, db: DB, user: Writer):
    record, _ = locked_shipment(db, identifier, user)
    if record.status in {'received', 'cancelled'}:
        fail(409, 'shipment_closed', '已结束货件不能修改物流资料')
    try:
        payload = ShipmentUpdate.model_validate({**{key: getattr(record, key) for key in ShipmentUpdate.model_fields}, **changes})
    except ValidationError:
        fail(422, 'invalid_shipment', '只能修改承运商、运单、预计到货和物流备注')
    for key, value in payload.model_dump().items():
        setattr(record, key, value)
    event(db, record, user, 'note', '更新物流资料与预计到货日期')
    audit(db, user, 'shipments.update', 'shipment', identifier, '更新物流资料', record.store_id)
    db.commit()
    return shipment_detail(db, record)


@router.post('/{identifier}/dispatch')
def dispatch(identifier: str, payload: ActionInput, db: DB, user: Writer):
    scoped_record(db, Shipment, identifier, user)
    inserted, _ = operation(db, payload, user, f'shipment.dispatch:{identifier}', identifier)
    record, _ = locked_shipment(db, identifier, user)
    if not inserted:
        return shipment_detail(db, record)
    if record.status != 'planned':
        fail(409, 'invalid_status', '只有待发货件可以确认发出')
    if record.source_warehouse_id:
        change_stock(db, user, StockChange(record.store_id, record.source_warehouse_id,
            {line.product_id: (-line.quantity, -line.quantity) for line in record.lines}, 'dispatch', identifier, record.number, '确认发货出库'))
    record.status, record.stage, record.shipped_at = 'in_transit', 'in_transit', now()
    event(db, record, user, 'in_transit', '确认发出，进入在途')
    audit(db, user, 'shipments.dispatch', 'shipment', identifier, '确认发货', record.store_id)
    db.commit()
    return shipment_detail(db, record)


@router.post('/{identifier}/cancel')
def cancel(identifier: str, payload: ActionInput, db: DB, user: Writer):
    scoped_record(db, Shipment, identifier, user)
    inserted, _ = operation(db, payload, user, f'shipment.cancel:{identifier}', identifier)
    record, _ = locked_shipment(db, identifier, user)
    if not inserted:
        return shipment_detail(db, record)
    if record.status != 'planned':
        fail(409, 'invalid_status', '只有待发货件可以取消；已发出货物须按实际接收登记')
    if record.source_warehouse_id:
        change_stock(db, user, StockChange(record.store_id, record.source_warehouse_id,
            {line.product_id: (0, -line.quantity) for line in record.lines}, 'release', identifier, record.number, '取消计划释放占用'))
    record.status, record.stage = 'cancelled', 'cancelled'
    event(db, record, user, 'cancelled', '取消待发计划')
    audit(db, user, 'shipments.cancel', 'shipment', identifier, '取消待发计划', record.store_id)
    db.commit()
    return shipment_detail(db, record)


@router.post('/{identifier}/events')
def add_event(identifier: str, payload: EventInput, db: DB, user: Writer):
    scoped_record(db, Shipment, identifier, user)
    inserted, _ = operation(db, payload, user, f'shipment.event:{identifier}', identifier)
    record, _ = locked_shipment(db, identifier, user)
    if not inserted:
        return shipment_detail(db, record)
    if record.status not in {'in_transit', 'partially_received'}:
        fail(409, 'invalid_status', '请先确认发货；已结束货件不能新增运输进度')
    record.stage = payload.stage
    event(db, record, user, payload.stage, payload.notes)
    audit(db, user, 'shipments.event', 'shipment', identifier, '登记物流进度', record.store_id)
    db.commit()
    return shipment_detail(db, record)


@router.post('/{identifier}/receive')
def receive(identifier: str, payload: ReceiptInput, db: DB, user: Writer):
    scoped_record(db, Shipment, identifier, user)
    inserted, _ = operation(db, payload, user, f'shipment.receive:{identifier}', identifier)
    record, purchase = locked_shipment(db, identifier, user)
    if not inserted:
        return shipment_detail(db, record)
    if record.status not in {'in_transit', 'partially_received'}:
        fail(409, 'invalid_status', '只有已发出且未收齐的货件可以登记接收')
    mapping = {line.id: line for line in record.lines}
    changes = {}
    for item in payload.lines:
        line = mapping.get(item.line_id)
        if not line or item.quantity > line.quantity - line.received_quantity:
            fail(409, 'receipt_exceeds_shipment', '接收行不属于此货件，或接收数量超过待收数量')
        line.received_quantity += item.quantity
        changes[line.product_id] = (item.quantity, 0)
    if purchase:
        purchased = {line.product_id: line for line in purchase.lines}
        for product_id, (quantity, _) in changes.items():
            line = purchased[product_id]
            if line.received_quantity + quantity + line.cancelled_quantity > line.quantity:
                fail(409, 'receipt_exceeds_purchase', '接收数量超过采购未收余量')
            line.received_quantity += quantity
        purchase.status = purchase_status(purchase)
    change_stock(db, user, StockChange(record.store_id, record.destination_warehouse_id, changes, 'receipt', identifier,
                                      record.number, payload.notes or '货件接收入库'))
    complete = all(line.received_quantity == line.quantity for line in record.lines)
    record.status = 'received' if complete else 'partially_received'
    if complete:
        record.stage, record.received_at = 'received', now()
    event(db, record, user, 'received' if complete else 'partially_received',
          f'本次接收 {sum(item.quantity for item in payload.lines)} 件。{payload.notes}')
    audit(db, user, 'shipments.receive', 'shipment', identifier, '登记分批接收并过账库存', record.store_id)
    db.commit()
    return shipment_detail(db, record)
