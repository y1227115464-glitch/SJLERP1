from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base, Product, Store, Supplier, new_id, now


class Warehouse(Base):
    __tablename__ = 'warehouses'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20), default='fba')
    address: Mapped[str] = mapped_column(String(1000), default='')
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PurchaseOrder(Base):
    __tablename__ = 'purchase_orders'
    planned_ship_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (Index('ix_purchase_store_created', 'store_id', 'created_at'), Index('ix_purchase_status_expected', 'status', 'expected_date'))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    number: Mapped[str] = mapped_column(String(50), unique=True)
    store_id: Mapped[str] = mapped_column(ForeignKey('stores.id'))
    supplier_id: Mapped[str] = mapped_column(ForeignKey('suppliers.id'), index=True)
    status: Mapped[str] = mapped_column(String(30), default='draft')
    order_date: Mapped[date] = mapped_column(Date)
    expected_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default='CNY')
    payment_terms: Mapped[str] = mapped_column(String(2000), default='')
    notes: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    store: Mapped[Store] = relationship(lazy='joined')
    supplier: Mapped[Supplier] = relationship(lazy='joined')
    lines: Mapped[list['PurchaseLine']] = relationship(lazy='selectin', cascade='all, delete-orphan', order_by='PurchaseLine.position')


class PurchaseLine(Base):
    __tablename__ = 'purchase_lines'
    __table_args__ = (UniqueConstraint('purchase_order_id', 'product_id'),
                     CheckConstraint('quantity > 0 AND received_quantity >= 0 AND cancelled_quantity >= 0 AND received_quantity + cancelled_quantity <= quantity'))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    purchase_order_id: Mapped[str] = mapped_column(ForeignKey('purchase_orders.id'), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey('products.id'), index=True)
    position: Mapped[int] = mapped_column(Integer)
    product_name: Mapped[str] = mapped_column(String(500))
    internal_sku: Mapped[str] = mapped_column(String(120))
    quantity: Mapped[int] = mapped_column(BigInteger)
    received_quantity: Mapped[int] = mapped_column(BigInteger, default=0)
    cancelled_quantity: Mapped[int] = mapped_column(BigInteger, default=0)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    product: Mapped[Product] = relationship(lazy='joined')


class Shipment(Base):
    __tablename__ = 'shipments'
    planned_ship_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    __table_args__ = (Index('ix_shipment_store_created', 'store_id', 'created_at'), Index('ix_shipment_status_expected', 'status', 'expected_date'),
                     CheckConstraint('(purchase_order_id IS NULL) <> (source_warehouse_id IS NULL)'),
                     CheckConstraint('source_warehouse_id IS NULL OR source_warehouse_id <> destination_warehouse_id'))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    number: Mapped[str] = mapped_column(String(50), unique=True)
    store_id: Mapped[str] = mapped_column(ForeignKey('stores.id'))
    purchase_order_id: Mapped[str | None] = mapped_column(ForeignKey('purchase_orders.id'), nullable=True, index=True)
    source_warehouse_id: Mapped[str | None] = mapped_column(ForeignKey('warehouses.id'), nullable=True, index=True)
    destination_warehouse_id: Mapped[str] = mapped_column(ForeignKey('warehouses.id'), index=True)
    status: Mapped[str] = mapped_column(String(30), default='planned')
    stage: Mapped[str] = mapped_column(String(30), default='preparing')
    carrier: Mapped[str] = mapped_column(String(120), default='')
    tracking_number: Mapped[str] = mapped_column(String(120), default='')
    amazon_shipment_id: Mapped[str] = mapped_column(String(120), default='')
    expected_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default='')
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    store: Mapped[Store] = relationship(lazy='joined')
    source: Mapped[Warehouse | None] = relationship(foreign_keys=[source_warehouse_id], lazy='joined')
    destination: Mapped[Warehouse] = relationship(foreign_keys=[destination_warehouse_id], lazy='joined')
    lines: Mapped[list['ShipmentLine']] = relationship(lazy='selectin', cascade='all, delete-orphan', order_by='ShipmentLine.position')


class ShipmentLine(Base):
    __tablename__ = 'shipment_lines'
    units_per_carton: Mapped[int | None] = mapped_column(Integer, nullable=True)
    __table_args__ = (UniqueConstraint('shipment_id', 'product_id'), CheckConstraint('quantity > 0 AND received_quantity >= 0 AND received_quantity <= quantity'))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    shipment_id: Mapped[str] = mapped_column(ForeignKey('shipments.id'), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey('products.id'), index=True)
    purchase_line_id: Mapped[str | None] = mapped_column(ForeignKey('purchase_lines.id'), nullable=True, index=True)
    position: Mapped[int] = mapped_column(Integer)
    product_name: Mapped[str] = mapped_column(String(500))
    internal_sku: Mapped[str] = mapped_column(String(120))
    quantity: Mapped[int] = mapped_column(BigInteger)
    received_quantity: Mapped[int] = mapped_column(BigInteger, default=0)


class ShipmentEvent(Base):
    __tablename__ = 'shipment_events'
    __table_args__ = (Index('ix_shipment_event_time', 'shipment_id', 'created_at'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    shipment_id: Mapped[str] = mapped_column(ForeignKey('shipments.id'))
    stage: Mapped[str] = mapped_column(String(30))
    notes: Mapped[str] = mapped_column(Text, default='')
    actor_name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class InventoryBalance(Base):
    __tablename__ = 'inventory_balances'
    __table_args__ = (UniqueConstraint('store_id', 'warehouse_id', 'product_id', name='uq_inventory_scope'),
                     CheckConstraint('quantity >= 0 AND reserved >= 0 AND reserved <= quantity'))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    store_id: Mapped[str] = mapped_column(ForeignKey('stores.id'), index=True)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey('warehouses.id'), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey('products.id'), index=True)
    quantity: Mapped[int] = mapped_column(BigInteger, default=0)
    reserved: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    store: Mapped[Store] = relationship(lazy='joined')
    warehouse: Mapped[Warehouse] = relationship(lazy='joined')
    product: Mapped[Product] = relationship(lazy='joined')


class InventoryMovement(Base):
    __tablename__ = 'inventory_movements'
    __table_args__ = (Index('ix_movement_scope_time', 'store_id', 'warehouse_id', 'created_at'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    store_id: Mapped[str] = mapped_column(ForeignKey('stores.id'))
    warehouse_id: Mapped[str] = mapped_column(ForeignKey('warehouses.id'))
    product_id: Mapped[str] = mapped_column(ForeignKey('products.id'), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    quantity: Mapped[int] = mapped_column(BigInteger)
    reserved_delta: Mapped[int] = mapped_column(BigInteger, default=0)
    balance_after: Mapped[int] = mapped_column(BigInteger)
    reserved_after: Mapped[int] = mapped_column(BigInteger)
    reference_id: Mapped[str] = mapped_column(String(36), index=True)
    reference_number: Mapped[str] = mapped_column(String(50), default='')
    reason: Mapped[str] = mapped_column(Text)
    actor_name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    store: Mapped[Store] = relationship(lazy='joined')
    warehouse: Mapped[Warehouse] = relationship(lazy='joined')
    product: Mapped[Product] = relationship(lazy='joined')


class SupplyOperation(Base):
    __tablename__ = 'supply_operations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    result_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
