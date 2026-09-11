"""Dated, explicit USD cost assumptions for sales analysis."""
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import Field, field_validator
from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, Numeric, String, UniqueConstraint, or_, select
from sqlalchemy.orm import Mapped, mapped_column

from app.core.api import DB, Page, audit, fail, paginated, require, require_store, store_filter
from app.core.security import has_permission
from app.models import Base, Store, User, new_id
from app.schemas import Input
from app.reports.sku import normalized_sku


class SalesCostRate(Base):
    __tablename__ = 'sales_cost_rates'
    __table_args__ = (
        UniqueConstraint('scope_key', 'sku', 'effective_from', name='uq_sales_cost_scope_sku_date'),
        CheckConstraint("(store_id IS NULL AND scope_key = '*') OR (store_id IS NOT NULL AND scope_key = store_id)"),
        CheckConstraint('product_cost >= 0 AND inbound_fee >= 0 AND fba_fee >= 0 AND commission_rate >= 0 AND commission_rate <= 1'),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    store_id: Mapped[str | None] = mapped_column(ForeignKey('stores.id'), nullable=True, index=True)
    scope_key: Mapped[str] = mapped_column(String(36))
    sku: Mapped[str] = mapped_column(String(120), index=True)
    effective_from: Mapped[date] = mapped_column(Date)
    product_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 9), nullable=True)
    inbound_fee: Mapped[Decimal | None] = mapped_column(Numeric(18, 9), nullable=True)
    fba_fee: Mapped[Decimal | None] = mapped_column(Numeric(18, 9), nullable=True)
    commission_rate: Mapped[Decimal] = mapped_column(Numeric(8, 6), default=Decimal('.15'))
    source: Mapped[str] = mapped_column(String(500), default='')
    revision: Mapped[int] = mapped_column(Integer, default=1)


Money = Annotated[Decimal, Field(ge=0, le=999999999, max_digits=18, decimal_places=9)]


class CostInput(Input):
    store_id: str | None = Field(default=None, max_length=36)
    sku: str = Field(min_length=1, max_length=120, pattern=r'^[^\x00-\x1f\x7f]+$')
    effective_from: date
    product_cost: Money | None = None
    inbound_fee: Money | None = None
    fba_fee: Money | None = None
    commission_rate: Decimal = Field(default=Decimal('.15'), ge=0, le=1, max_digits=8, decimal_places=6)
    source: str = Field(default='', max_length=500)
    revision: int = Field(default=0, ge=0)

    @field_validator('sku')
    @classmethod
    def normalize(cls, value):
        return normalized_sku(value)


def analysis_reader(user: Annotated[User, Depends(require('reports.view'))]):
    if not has_permission(user, 'costs.view'):
        fail(403, 'permission_denied', '当前账号没有成本及利润分析权限，可查看订单明细')
    return user


Reader = Annotated[User, Depends(analysis_reader)]
router = APIRouter(prefix='/api/v1/sales-analysis', tags=['Sales analysis'])


def visible_rates(user, store_id=None):
    query = select(SalesCostRate)
    if user.role != 'admin':
        query = query.where(or_(SalesCostRate.store_id.is_(None), store_filter(user, SalesCostRate.store_id)))
    if store_id:
        query = query.where(or_(SalesCostRate.store_id.is_(None), SalesCostRate.store_id == store_id))
    return query


def cost_out(row):
    values = {key: getattr(row, key) for key in ['id', 'store_id', 'sku', 'effective_from', 'product_cost',
        'inbound_fee', 'fba_fee', 'commission_rate', 'source', 'revision']}
    return {key: format(value, 'f') if isinstance(value, Decimal) else value.isoformat() if isinstance(value, date)
        else value for key, value in values.items()}


@router.get('/costs')
def costs(db: DB, user: Reader, page: Page, store_id: str | None = None, sku: str = '', q: str = Query('', max_length=120)):
    if store_id:
        require_store(db, user, store_id)
    query = visible_rates(user, store_id)
    if sku:
        query = query.where(SalesCostRate.sku == normalized_sku(sku))
    if q:
        query = query.where(SalesCostRate.sku.icontains(normalized_sku(q), autoescape=True))
    return paginated(db, query.order_by(SalesCostRate.sku, SalesCostRate.scope_key, SalesCostRate.effective_from.desc()), page, cost_out)


@router.post('/costs')
def save_cost(payload: CostInput, db: DB, user: Reader):
    if not has_permission(user, 'quotes.manage') or (payload.store_id is None and user.role != 'admin'):
        fail(403, 'permission_denied', '仅管理员可维护通用成本；经理和财务可维护授权店铺成本')
    if payload.store_id:
        require_store(db, user, payload.store_id)
        db.scalar(select(Store).where(Store.id == payload.store_id).with_for_update())
    else:
        # A shared lock target serializes administrator edits, including first insert.
        db.scalar(select(Store).order_by(Store.id).limit(1).with_for_update())
    key = payload.store_id or '*'
    row = db.scalar(select(SalesCostRate).where(SalesCostRate.scope_key == key, SalesCostRate.sku == payload.sku,
        SalesCostRate.effective_from == payload.effective_from).with_for_update())
    if (row.revision if row else 0) != payload.revision:
        fail(409, 'cost_changed', '该成本版本已存在或已被修改，请刷新后编辑')
    if row is None:
        row = SalesCostRate(scope_key=key, revision=0)
        db.add(row)
    for key, value in payload.model_dump(exclude={'revision'}).items():
        setattr(row, key, value)
    row.revision += 1
    db.flush()
    audit(db, user, 'sales.cost.update', 'sales_cost', row.id, '维护销售分析成本版本', payload.store_id)
    db.commit()
    return cost_out(row)
