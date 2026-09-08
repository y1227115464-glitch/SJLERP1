from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base, Store, new_id, now


class ReportImport(Base):
    __tablename__ = 'report_imports'
    __table_args__ = (Index('ix_report_import_store_time', 'store_id', 'created_at'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    store_id: Mapped[str] = mapped_column(ForeignKey('stores.id'), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    kind: Mapped[str] = mapped_column(String(10))
    filename: Mapped[str] = mapped_column(String(255))
    file_hash: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(36), unique=True)
    parser_version: Mapped[str] = mapped_column(String(20), default='amazon-v1')
    parsed_rows: Mapped[list] = mapped_column(JSON)
    errors: Mapped[list] = mapped_column(JSON)
    duplicate_count: Mapped[int] = mapped_column(BigInteger, default=0)
    source_total: Mapped[int] = mapped_column(BigInteger)
    row_count: Mapped[int] = mapped_column(BigInteger)
    error_count: Mapped[int] = mapped_column(BigInteger)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    store: Mapped[Store] = relationship(lazy='joined')


class SalesRecord(Base):
    __tablename__ = 'sales_records'
    __table_args__ = (UniqueConstraint('store_id', 'natural_key', name='uq_sales_record_key'),
        Index('ix_sales_store_date', 'store_id', 'purchase_date'), Index('ix_sales_store_sku', 'store_id', 'sku'),
        CheckConstraint('quantity >= 0'))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    store_id: Mapped[str] = mapped_column(ForeignKey('stores.id'))
    natural_key: Mapped[str] = mapped_column(String(64))
    value_hash: Mapped[str] = mapped_column(String(64))
    import_id: Mapped[str] = mapped_column(ForeignKey('report_imports.id'), index=True)
    source_row: Mapped[int] = mapped_column(BigInteger)
    amazon_order_id: Mapped[str] = mapped_column(String(120), index=True)
    sales_channel: Mapped[str] = mapped_column(String(120))
    sku: Mapped[str] = mapped_column(String(120))
    asin: Mapped[str] = mapped_column(String(120))
    product_name: Mapped[str] = mapped_column(String(2000))
    order_status: Mapped[str] = mapped_column(String(120))
    item_status: Mapped[str] = mapped_column(String(120))
    purchase_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_updated_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    quantity: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    net_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    data: Mapped[dict] = mapped_column(JSON)
    store: Mapped[Store] = relationship(lazy='joined')


class AdRecord(Base):
    __tablename__ = 'ad_records'
    __table_args__ = (UniqueConstraint('store_id', 'natural_key', name='uq_ad_record_key'),
        UniqueConstraint('store_id', 'report_date', 'identity_key', name='uq_ad_daily_identity'),
        Index('ix_ad_store_report_date', 'store_id', 'report_date'),
        Index('ix_ad_store_identity_period', 'store_id', 'identity_key', 'start_date', 'end_date'),
        Index('ix_ad_store_period', 'store_id', 'start_date', 'end_date'),
        CheckConstraint('start_date <= end_date AND impressions >= 0 AND clicks >= 0 AND spend >= 0'))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    store_id: Mapped[str] = mapped_column(ForeignKey('stores.id'))
    natural_key: Mapped[str] = mapped_column(String(64))
    identity_key: Mapped[str] = mapped_column(String(64))
    value_hash: Mapped[str] = mapped_column(String(64))
    import_id: Mapped[str] = mapped_column(ForeignKey('report_imports.id'), index=True)
    source_row: Mapped[int] = mapped_column(BigInteger)
    latest_report_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    report_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    campaign: Mapped[str] = mapped_column(String(500))
    ad_group: Mapped[str] = mapped_column(String(500))
    sku: Mapped[str] = mapped_column(String(120))
    asin: Mapped[str] = mapped_column(String(120))
    country: Mapped[str] = mapped_column(String(120))
    currency: Mapped[str] = mapped_column(String(3))
    impressions: Mapped[int] = mapped_column(BigInteger)
    clicks: Mapped[int] = mapped_column(BigInteger)
    spend: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    attributed_sales: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    orders: Mapped[int] = mapped_column(BigInteger)
    units: Mapped[int] = mapped_column(BigInteger)
    data: Mapped[dict] = mapped_column(JSON)
    store: Mapped[Store] = relationship(lazy='joined')
