"""Supplier-held goods remain owned by their original purchase order."""
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, Text, func, select
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.api import DB, Page, audit, fail, paginated, require
from app.core.security import has_permission
from app.models import Base, Product, Supplier, User, new_id, now
from app.supply.common import active_store, allocations, operation, purchase_out, purchase_status, scoped, scoped_record, values
from app.supply.line_changes import LineChange, check_version
from app.supply.models import PurchaseLine, PurchaseOrder
from app.supply.purchase_transfer import TransferItem
from app.supply.schemas import ActionInput, Quantity
from app.tasks.events import enqueue


class SupplierStock(Base):
    __tablename__ = 'supplier_stock'
    __table_args__ = (CheckConstraint('quantity > 0 AND remaining_quantity >= 0 AND remaining_quantity <= quantity'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    store_id: Mapped[str] = mapped_column(ForeignKey('stores.id'), index=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey('suppliers.id'), index=True)
    purchase_order_id: Mapped[str] = mapped_column(ForeignKey('purchase_orders.id'), index=True)
    purchase_line_id: Mapped[str] = mapped_column(ForeignKey('purchase_lines.id'), index=True)
    quantity: Mapped[int] = mapped_column(BigInteger)
    remaining_quantity: Mapped[int] = mapped_column(BigInteger)
    payment_status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    purchase: Mapped[PurchaseOrder] = relationship(lazy='joined')
    line: Mapped[PurchaseLine] = relationship(lazy='joined')


class SupplierStockEvent(Base):
    __tablename__ = 'supplier_stock_events'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    stock_id: Mapped[str] = mapped_column(ForeignKey('supplier_stock.id'), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[int] = mapped_column(BigInteger)
    balance_after: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(Text)
    payment_status: Mapped[str] = mapped_column(String(20))
    actor_name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


StockPayment = Literal['unknown', 'unpaid', 'partial', 'paid']


class StockTransfer(LineChange):
    reason: str = Field(min_length=1, max_length=1000)
    payment_status: StockPayment
    lines: list[TransferItem] = Field(min_length=1, max_length=100)


class StockRelease(ActionInput):
    quantity: Quantity
    reason: str = Field(min_length=1, max_length=1000)


class StockPaymentUpdate(ActionInput):
    payment_status: StockPayment
    reason: str = Field(min_length=1, max_length=1000)


router = APIRouter(prefix='/api/v1')
Reader = Annotated[User, Depends(require('purchases.view'))]
Writer = Annotated[User, Depends(require('purchases.manage'))]


def stock_out(stock, user):
    result = values(stock, 'id store_id supplier_id purchase_order_id purchase_line_id quantity remaining_quantity payment_status reason created_at')
    result.update(supplier_name=stock.purchase.supplier.name, store_name=stock.purchase.store.name,
                  purchase_number=stock.purchase.number, product_id=stock.line.product_id,
                  internal_sku=stock.line.internal_sku,
                  product_name=stock.line.product.name_zh or stock.line.product_name, units_per_carton=stock.line.product.units_per_carton)
    if has_permission(user, 'costs.view'):
        result.update(unit_price=format(stock.line.unit_price, '.4f'), currency=stock.purchase.currency)
    return result


def record_event(db, stock, user, kind, quantity, reason):
    db.add(SupplierStockEvent(stock_id=stock.id, kind=kind, quantity=quantity,
        balance_after=stock.remaining_quantity, payment_status=stock.payment_status,
        reason=reason, actor_name=user.display_name))
    audit(db, user, f'supplier_stock.{kind}', 'purchase_order', stock.purchase_order_id,
          f'供应商库存 {quantity:+d} 件；{reason}'[:500], stock.store_id)


@router.post('/purchase-orders/{identifier}/supplier-stock', status_code=201)
def transfer(identifier: str, payload: StockTransfer, db: DB, user: Writer):
    scoped_record(db, PurchaseOrder, identifier, user)
    inserted, _ = operation(db, payload, user, f'supplier_stock.transfer:{identifier}', identifier)
    order = scoped_record(db, PurchaseOrder, identifier, user, lock=True)
    if not inserted:
        return purchase_out(order, user)
    active_store(db, user, order.store_id)
    if order.status not in {'ordered', 'partially_received'}:
        fail(409, 'purchase_locked', '仅待交付或部分到货的采购单可转入供应商库存')
    check_version(order, payload.expected_version)
    allocated = allocations(db, order.id)
    lines = {line.product_id: line for line in order.lines}
    for item in payload.lines:
        line = lines.get(item.product_id)
        available = (line.quantity - line.received_quantity - line.cancelled_quantity
                     - line.transferred_quantity - line.supplier_stock_quantity - allocated.get(item.product_id, 0)) if line else 0
        if item.quantity > available:
            fail(409, 'stock_exceeds_remaining', '转入数量超过最新可用余量，请刷新采购单后重试')
        line.supplier_stock_quantity += item.quantity
        stock = SupplierStock(id=new_id(), store_id=order.store_id, supplier_id=order.supplier_id,
            purchase_order_id=order.id, purchase_line_id=line.id, quantity=item.quantity,
            remaining_quantity=item.quantity, payment_status=payload.payment_status, reason=payload.reason)
        db.add(stock)
        db.flush()
        record_event(db, stock, user, 'transfer', item.quantity, payload.reason)
    order.status, order.updated_at = purchase_status(order), now()
    enqueue(db, order, 'purchase', user, 'updated')
    db.commit()
    return purchase_out(order, user)


def stock_query(user, store_id, supplier_id, q, include_empty):
    statement = scoped(select(SupplierStock), user, SupplierStock.store_id, store_id)
    if supplier_id:
        statement = statement.where(SupplierStock.supplier_id == supplier_id)
    if not include_empty:
        statement = statement.where(SupplierStock.remaining_quantity > 0)
    if q.strip():
        term = '%' + q.strip() + '%'
        statement = statement.join(PurchaseOrder, SupplierStock.purchase_order_id == PurchaseOrder.id).join(
            PurchaseLine, SupplierStock.purchase_line_id == PurchaseLine.id).join(Supplier, SupplierStock.supplier_id == Supplier.id).join(
            Product, PurchaseLine.product_id == Product.id).where(
            PurchaseOrder.number.ilike(term) | Product.internal_sku.ilike(term) | PurchaseLine.product_name.ilike(term)
            | Product.name_zh.ilike(term) | Product.name.ilike(term) | Supplier.name.ilike(term))
    return statement


@router.get('/supplier-stock')
def stock_list(db: DB, page: Page, user: Reader, store_id: str | None = None,
               supplier_id: str | None = None, q: str = '', include_empty: bool = False, product_id: str | None = None):
    statement = stock_query(user, store_id, supplier_id, q, include_empty)
    if product_id:
        statement = statement.where(SupplierStock.purchase_line_id.in_(
            select(PurchaseLine.id).where(PurchaseLine.product_id == product_id)))
    return paginated(db, statement.order_by(SupplierStock.created_at.desc(), SupplierStock.id), page, lambda row: stock_out(row, user))


@router.get('/supplier-stock/skus')
def sku_list(db: DB, page: Page, user: Reader, store_id: str | None = None,
             supplier_id: str | None = None, q: str = ''):
    # Aggregate all accessible matching batches before pagination, excluding empty lots.
    batches = stock_query(user, store_id, supplier_id, q, False).with_only_columns(
        SupplierStock.purchase_line_id, SupplierStock.supplier_id, SupplierStock.remaining_quantity).subquery()
    grouped = select(PurchaseLine.product_id.label('id'),
        func.sum(batches.c.remaining_quantity).label('quantity'),
        func.count().label('batches'), func.count(func.distinct(batches.c.supplier_id)).label('suppliers')).join(
        batches, batches.c.purchase_line_id == PurchaseLine.id).group_by(PurchaseLine.product_id).subquery()
    statement = select(Product.internal_sku, Product.name, Product.name_zh,
        grouped.c.id, grouped.c.quantity, grouped.c.batches, grouped.c.suppliers).join(grouped, Product.id == grouped.c.id)
    total = db.scalar(select(func.count()).select_from(grouped))
    rows = db.execute(statement.order_by(Product.internal_sku, grouped.c.id).limit(page.limit).offset(page.offset))
    return {'items': [dict(id=row.id, internal_sku=row.internal_sku, product_name=row.name_zh or row.name,
                          quantity=int(row.quantity), batches=row.batches, suppliers=row.suppliers) for row in rows], 'total': total}


@router.get('/supplier-stock/summary')
def summary(db: DB, page: Page, user: Reader, store_id: str | None = None):
    # Pagination counts grouped suppliers, not individual stock batches.
    grouped = scoped(select(SupplierStock.supplier_id.label('id'), func.sum(SupplierStock.remaining_quantity).label('quantity'),
        func.count(SupplierStock.id).label('batches')).where(SupplierStock.remaining_quantity > 0), user,
        SupplierStock.store_id, store_id).group_by(SupplierStock.supplier_id).subquery()
    statement = select(Supplier.name, grouped.c.id, grouped.c.quantity, grouped.c.batches).join(grouped, Supplier.id == grouped.c.id)
    total = db.scalar(select(func.count()).select_from(grouped))
    rows = db.execute(statement.order_by(Supplier.name, grouped.c.id).limit(page.limit).offset(page.offset))
    return {'items': [dict(id=row.id, supplier_name=row.name, quantity=int(row.quantity), batches=row.batches) for row in rows], 'total': total}


@router.get('/supplier-stock/{identifier}/events')
def events(identifier: str, db: DB, page: Page, user: Reader):
    scoped_record(db, SupplierStock, identifier, user)
    return paginated(db, select(SupplierStockEvent).where(SupplierStockEvent.stock_id == identifier)
        .order_by(SupplierStockEvent.created_at.desc(), SupplierStockEvent.id), page,
        lambda row: values(row, 'id kind quantity balance_after payment_status reason actor_name created_at'))


def locked_stock(db, identifier, user):
    stock = scoped_record(db, SupplierStock, identifier, user)
    # Match shipment lock ordering, so releasing/allocating stock cannot race.
    order = scoped_record(db, PurchaseOrder, stock.purchase_order_id, user, lock=True)
    return scoped_record(db, SupplierStock, identifier, user, lock=True), order


@router.post('/supplier-stock/{identifier}/release')
def release(identifier: str, payload: StockRelease, db: DB, user: Writer):
    scoped_record(db, SupplierStock, identifier, user)
    inserted, _ = operation(db, payload, user, f'supplier_stock.release:{identifier}', identifier)
    stock, order = locked_stock(db, identifier, user)
    if inserted:
        active_store(db, user, order.store_id)
        if payload.quantity > stock.remaining_quantity:
            fail(409, 'insufficient_supplier_stock', '转回数量超过供应商库存余量，请刷新后重试')
        stock.remaining_quantity -= payload.quantity
        line = next(line for line in order.lines if line.id == stock.purchase_line_id)
        line.supplier_stock_quantity -= payload.quantity
        order.status, order.updated_at = purchase_status(order), now()
        record_event(db, stock, user, 'release', -payload.quantity, payload.reason)
        enqueue(db, order, 'purchase', user, 'updated')
    db.commit()
    return stock_out(stock, user)


@router.post('/supplier-stock/{identifier}/payment')
def payment(identifier: str, payload: StockPaymentUpdate, db: DB, user: Writer):
    scoped_record(db, SupplierStock, identifier, user)
    inserted, _ = operation(db, payload, user, f'supplier_stock.payment:{identifier}', identifier)
    stock, _ = locked_stock(db, identifier, user)
    if inserted:
        stock.payment_status = payload.payment_status
        record_event(db, stock, user, 'payment', 0, payload.reason)
    db.commit()
    return stock_out(stock, user)
