import hashlib
import json
from datetime import date, datetime
from decimal import Decimal, localcontext

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.api import fail, require_store, store_filter
from app.core.security import aware, has_permission
from app.models import Product, new_id, now
from app.supply.models import PurchaseOrder, Shipment, ShipmentEvent, ShipmentLine, SupplyOperation, Warehouse


def scoped(statement, user, column, store_id=None):
    if user.role != 'admin':
        statement = statement.where(store_filter(user, column))
    if store_id:
        statement = statement.where(column == store_id)
    return statement


def scoped_record(db, model, identifier, user, *, lock=False):
    statement = scoped(select(model).where(model.id == identifier), user, model.store_id)
    if lock:
        statement = statement.with_for_update(of=model).execution_options(populate_existing=True)
    record = db.scalar(statement)
    if record is None:
        fail(404, 'not_found', '单据不存在或无权访问')
    return record


def active_store(db, user, identifier):
    record = require_store(db, user, identifier)
    if not record.is_active:
        fail(409, 'inactive_store', '店铺已停用，不能新建单据')
    return record


def active_warehouse(db, identifier):
    warehouse = db.get(Warehouse, identifier)
    if not warehouse or not warehouse.is_active:
        fail(422, 'invalid_warehouse', '请选择启用中的仓库')
    return warehouse


def active_products(db, identifiers):
    records = {item.id: item for item in db.scalars(select(Product).where(Product.id.in_(identifiers)))}
    if any(identifier not in records or not records[identifier].is_active for identifier in identifiers):
        fail(422, 'invalid_product', '商品不存在或已停用')
    return records


def values(record, fields):
    result = {}
    for field in fields.split():
        value = getattr(record, field)
        if isinstance(value, datetime):
            value = aware(value)
        result[field] = value.isoformat() if hasattr(value, 'isoformat') else format(value, 'f') if isinstance(value, Decimal) else value
    return result


def insert_ignore(db, model, rows, keys):
    insert = pg_insert if db.bind.dialect.name == 'postgresql' else sqlite_insert
    return list(db.scalars(insert(model).values(rows).on_conflict_do_nothing(index_elements=keys).returning(model.id)))


def operation(db, payload, user, kind, result_id):
    body = {'user': user.id, 'kind': kind, 'body': payload.model_dump(mode='json')}
    fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    # The unique insert waits for an in-flight matching request to commit or roll back.
    inserted = insert_ignore(db, SupplyOperation, [{'id': str(payload.request_id), 'fingerprint': fingerprint,
                              'result_id': result_id, 'created_at': now()}], ['id'])
    record = db.get(SupplyOperation, str(payload.request_id))
    if record.fingerprint != fingerprint:
        fail(409, 'idempotency_conflict', '此请求编号已用于其他内容，请刷新后重试')
    return bool(inserted), record.result_id


def purchase_status(record):
    if all(line.received_quantity + line.cancelled_quantity == line.quantity for line in record.lines):
        if not any(line.received_quantity for line in record.lines):
            return 'cancelled'
        return 'closed' if any(line.cancelled_quantity for line in record.lines) else 'received'
    return 'partially_received' if any(line.received_quantity for line in record.lines) else 'ordered'


def number(prefix):
    return f'{prefix}-{now():%Y%m%d}-{new_id().replace("-", "")[:12].upper()}'


def overdue(record):
    return bool(record.expected_date and record.expected_date < date.today()
                and record.status not in {'draft', 'received', 'cancelled', 'closed'})


def purchase_out(record, user):
    result = values(record, 'id number store_id supplier_id status order_date expected_date planned_ship_date ordered_at notes created_at updated_at')
    result.update(store_name=record.store.name, supplier_name=record.supplier.name, overdue=overdue(record))
    fields = 'id product_id product_name internal_sku quantity received_quantity cancelled_quantity'
    costs = has_permission(user, 'costs.view')
    result['lines'] = [values(line, fields + (' unit_price' if costs else '')) for line in record.lines]
    for output, line in zip(result['lines'], record.lines):
        product = line.product
        output.update(product_name_zh=product.name_zh, units_per_carton=product.units_per_carton,
                      unit_weight_kg=format(product.unit_weight_kg, '.4f') if product.unit_weight_kg is not None else None)
        with localcontext() as context:
            context.prec = 40
            output['total_weight_kg'] = format(product.unit_weight_kg * line.quantity, '.4f') if product.unit_weight_kg is not None else None
    if costs:
        with localcontext() as context:
            context.prec = 40
            total = sum((line.quantity * line.unit_price for line in record.lines), Decimal(0))
        result.update(currency=record.currency, payment_terms=record.payment_terms, total_amount=format(total, '.4f'))
    return result


def shipment_out(record):
    result = values(record, 'id number store_id purchase_order_id source_warehouse_id destination_warehouse_id status stage carrier tracking_number amazon_shipment_id expected_date planned_ship_date notes shipped_at received_at created_at updated_at')
    result.update(store_name=record.store.name, source_name=record.source.name if record.source else '供应商',
                  destination_name=record.destination.name, destination_kind=record.destination.kind, overdue=overdue(record))
    result['lines'] = [{**values(line, 'id product_id product_name internal_sku quantity received_quantity units_per_carton'),
                        'carton_count': line.quantity // line.units_per_carton if line.units_per_carton else None} for line in record.lines]
    return result


def event(db, shipment, user, stage, notes):
    db.add(ShipmentEvent(shipment_id=shipment.id, stage=stage, notes=notes, actor_name=user.display_name))


def shipment_detail(db, shipment):
    result = shipment_out(shipment)
    events = list(db.scalars(select(ShipmentEvent).where(ShipmentEvent.shipment_id == shipment.id)
                            .order_by(ShipmentEvent.created_at.desc(), ShipmentEvent.id.desc()).limit(200)))
    result['events'] = [values(item, 'id stage notes actor_name created_at') for item in reversed(events)]
    return result


def locked_shipment(db, identifier, user):
    # All supplier actions lock PO before shipment to keep receipt/allocation lock order identical.
    row = db.execute(scoped(select(Shipment.id, Shipment.purchase_order_id).where(Shipment.id == identifier), user, Shipment.store_id)).first()
    if row is None:
        fail(404, 'not_found', '货件不存在或无权访问')
    purchase = scoped_record(db, PurchaseOrder, row.purchase_order_id, user, lock=True) if row.purchase_order_id else None
    return scoped_record(db, Shipment, identifier, user, lock=True), purchase


def allocations(db, purchase_id):
    statement = select(ShipmentLine.product_id, func.sum(ShipmentLine.quantity - ShipmentLine.received_quantity)).join(
        Shipment, Shipment.id == ShipmentLine.shipment_id).where(Shipment.purchase_order_id == purchase_id,
        Shipment.status.in_(['planned', 'in_transit', 'partially_received'])).group_by(ShipmentLine.product_id)
    # PostgreSQL SUM(bigint) is numeric; API quantities must remain JSON integers.
    return {product_id: int(quantity) for product_id, quantity in db.execute(statement)}
