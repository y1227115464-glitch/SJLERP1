from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.api import DB, Page, audit, fail, paginated, require
from app.models import Supplier, User, new_id, now
from app.supply.common import active_products, active_store, allocations, number, operation, purchase_out, purchase_status, scoped, scoped_record
from app.supply.models import PurchaseLine, PurchaseOrder, Shipment, ShipmentLine
from app.supply.schemas import PurchaseInput, PurchaseCreate, PurchaseScheduleInput

from app.tasks.events import enqueue
from app.tasks.schemas import ProgressInput

router = APIRouter(prefix='/api/v1/purchase-orders')
Reader = Annotated[User, Depends(require('purchases.view'))]
Writer = Annotated[User, Depends(require('purchases.manage'))]


def apply_purchase(db, record, payload, user):
    active_store(db, user, payload.store_id)
    supplier = db.get(Supplier, payload.supplier_id)
    if not supplier or not supplier.is_active:
        fail(422, 'invalid_supplier', '请选择启用中的供应商')
    products = active_products(db, [line.product_id for line in payload.lines])
    for key, value in payload.model_dump(exclude={'request_id', 'lines', 'already_ordered'}).items():
        setattr(record, key, value)
    # Flush removed draft rows before inserting replacements under the unique key.
    if record.lines:
        record.lines.clear()
        db.flush()
    record.lines = [PurchaseLine(position=i, product_name=products[line.product_id].name,
                    internal_sku=products[line.product_id].internal_sku, **line.model_dump()) for i, line in enumerate(payload.lines)]


@router.get('')
def list_orders(db: DB, page: Page, user: Reader, store_id: str | None = None, q: str = '',
                status: Literal['draft', 'ordered', 'partially_received', 'received', 'cancelled', 'closed'] | None = None,
                shippable: bool = False):
    statement = scoped(select(PurchaseOrder), user, PurchaseOrder.store_id, store_id)
    if q.strip():
        statement = statement.where(PurchaseOrder.number.ilike('%'+q.strip()+'%'))
    if status:
        statement = statement.where(PurchaseOrder.status == status)
    if shippable:
        allocated = select(func.coalesce(func.sum(ShipmentLine.quantity - ShipmentLine.received_quantity), 0)).join(
            Shipment, Shipment.id == ShipmentLine.shipment_id).where(Shipment.purchase_order_id == PurchaseLine.purchase_order_id,
            ShipmentLine.product_id == PurchaseLine.product_id, Shipment.status.in_(['planned', 'in_transit', 'partially_received'])).correlate(PurchaseLine).scalar_subquery()
        available = select(PurchaseLine.id).where(PurchaseLine.purchase_order_id == PurchaseOrder.id,
            PurchaseLine.quantity - PurchaseLine.received_quantity - PurchaseLine.cancelled_quantity > allocated).exists()
        statement = statement.where(PurchaseOrder.status.in_(['ordered', 'partially_received']), available)
    return paginated(db, statement.order_by(PurchaseOrder.created_at.desc(), PurchaseOrder.id), page, lambda item: purchase_out(item, user))


@router.get('/{identifier}')
def detail(identifier: str, db: DB, user: Reader):
    record = scoped_record(db, PurchaseOrder, identifier, user)
    result = purchase_out(record, user)
    from app.tasks.models import SourceEvent
    progress = db.execute(select(SourceEvent.created_at, SourceEvent.data, User.display_name).join(User, User.id == SourceEvent.actor_id)
        .where(SourceEvent.source_kind == 'purchase', SourceEvent.source_id == identifier, SourceEvent.kind == 'production')
        .order_by(SourceEvent.created_at.desc(), SourceEvent.id).limit(50)).all()
    result['production_history'] = [{'created_at': row.created_at, 'notes': row.data.get('notes', ''), 'actor_name': row.display_name} for row in progress]
    allocated = allocations(db, identifier)
    for line in result['lines']:
        line['allocated_quantity'] = allocated.get(line['product_id'], 0)
        line['unallocated_quantity'] = line['quantity'] - line['received_quantity'] - line['cancelled_quantity'] - line['allocated_quantity']
    return result


@router.post('', status_code=201)
def create(payload: PurchaseCreate, db: DB, user: Writer):
    active_store(db, user, payload.store_id)
    inserted, identifier = operation(db, payload, user, 'purchase.create', new_id())
    if not inserted:
        return purchase_out(scoped_record(db, PurchaseOrder, identifier, user), user)
    record = PurchaseOrder(id=identifier, number=number('PO'), lines=[])
    apply_purchase(db, record, payload, user)
    if payload.already_ordered:
        record.status, record.ordered_at = 'ordered', now()
    db.add(record)
    db.flush()
    enqueue(db, record, 'purchase', user, 'created')
    audit(db, user, 'purchases.create', 'purchase_order', identifier, '新增采购记录', payload.store_id)
    enqueue(db, record, 'purchase', user, 'updated')
    db.commit()
    db.expire(record)
    return purchase_out(record, user)


@router.patch('/{identifier}')
def edit(identifier: str, changes: dict, db: DB, user: Writer):
    record = scoped_record(db, PurchaseOrder, identifier, user, lock=True)
    if record.status != 'draft':
        fail(409, 'purchase_locked', '已提交采购单不能编辑数量金额；请取消余量后另建单据')
    stored = {key: getattr(record, key) for key in PurchaseInput.model_fields if key not in {'request_id', 'lines'}}
    stored.update(request_id=new_id(), lines=[{'product_id': line.product_id, 'quantity': line.quantity, 'unit_price': line.unit_price} for line in record.lines])
    if {'request_id', 'store_id'} & changes.keys():
        fail(422, 'immutable_field', '采购单不能变更店铺或请求编号')
    try:
        payload = PurchaseInput.model_validate({**stored, **changes})
    except ValidationError:
        fail(422, 'invalid_purchase', '请检查采购日期、数量、金额和商品明细')
    apply_purchase(db, record, payload, user)
    audit(db, user, 'purchases.update', 'purchase_order', identifier, '修改采购草稿', record.store_id)
    enqueue(db, record, 'purchase', user, 'updated')
    db.commit()
    db.expire(record)
    return purchase_out(record, user)


@router.post('/{identifier}/confirm')
def confirm(identifier: str, db: DB, user: Writer):
    record = scoped_record(db, PurchaseOrder, identifier, user, lock=True)
    if record.status != 'draft':
        fail(409, 'invalid_status', '只有草稿可以提交')
    active_store(db, user, record.store_id)
    record.status = 'ordered'
    record.ordered_at = now()
    audit(db, user, 'purchases.confirm', 'purchase_order', identifier, '登记已向供应商下单', record.store_id)
    enqueue(db, record, 'purchase', user, 'updated')
    db.commit()
    return purchase_out(record, user)


@router.post('/{identifier}/cancel')
def cancel(identifier: str, db: DB, user: Writer):
    record = scoped_record(db, PurchaseOrder, identifier, user, lock=True)
    if record.status in {'received', 'cancelled', 'closed'}:
        fail(409, 'invalid_status', '采购单已结束')
    allocated = allocations(db, identifier)
    cancelled = 0
    for line in record.lines:
        remaining = line.quantity - line.received_quantity - line.cancelled_quantity - allocated.get(line.product_id, 0)
        line.cancelled_quantity += remaining
        cancelled += remaining
    if not cancelled:
        fail(409, 'no_unallocated_quantity', '没有尚未分配给货件的采购余量可取消')
    record.status = purchase_status(record)
    audit(db, user, 'purchases.cancel', 'purchase_order', identifier, '取消采购未交付余量', record.store_id)
    enqueue(db, record, 'purchase', user, 'updated')
    db.commit()
    return purchase_out(record, user)


@router.post('/{identifier}/schedule')
def schedule(identifier: str, payload: PurchaseScheduleInput, db: DB, user: Writer):
    scoped_record(db, PurchaseOrder, identifier, user)
    inserted, _ = operation(db, payload, user, f'purchase.schedule:{identifier}', identifier)
    record = scoped_record(db, PurchaseOrder, identifier, user, lock=True)
    if inserted:
        if record.status in {'received', 'cancelled', 'closed'}:
            fail(409, 'purchase_closed', '已结束采购单不能改期')
        record.planned_ship_date = payload.planned_ship_date
        enqueue(db, record, 'purchase', user, 'updated')
        audit(db, user, 'purchases.schedule', 'purchase_order', identifier, '调整预计发货日', record.store_id)
    db.commit()
    return purchase_out(record, user)


@router.post('/{identifier}/production')
def production(identifier: str, payload: ProgressInput, db: DB, user: Writer):
    scoped_record(db, PurchaseOrder, identifier, user)
    inserted, _ = operation(db, payload, user, f'purchase.production:{identifier}', identifier)
    record = scoped_record(db, PurchaseOrder, identifier, user, lock=True)
    if inserted:
        if record.status in {'received', 'cancelled', 'closed'}:
            fail(409, 'purchase_closed', '已结束采购单不能登记生产进度')
        enqueue(db, record, 'purchase', user, 'production', {'notes': payload.notes})
        audit(db, user, 'purchases.production', 'purchase_order', identifier, payload.notes, record.store_id)
    db.commit()
    return purchase_out(record, user)
