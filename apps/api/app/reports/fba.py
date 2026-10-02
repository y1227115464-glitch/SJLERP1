"""Independent dated USD fulfillment fees, keyed by exact Seller SKU."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from fastapi import Query
from pydantic import Field, field_validator
from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, Numeric, String, UniqueConstraint, delete, func, or_, select, union
from sqlalchemy.orm import Mapped, mapped_column

from app.core.api import DB, Page, audit, fail, require_store, store_filter
from app.core.security import has_permission
from app.models import Base, Product, Store, new_id
from app.reports.costs import Money, Reader, SalesCostRate, router, visible_rates
from app.reports.models import AdRecord, SalesRecord
from app.reports.sku import normalized_sku
from app.schemas import Input

FBA_PRICE_THRESHOLD = Decimal('9.99')


class FbaFeeRate(Base):
    __tablename__ = 'fba_fee_rates'
    __table_args__ = (
        UniqueConstraint('scope_key', 'sku', 'effective_from', name='uq_fba_fee_scope_sku_date'),
        CheckConstraint("(store_id IS NULL AND scope_key = '*') OR (store_id IS NOT NULL AND scope_key = store_id)", name='ck_fba_fee_scope'),
        CheckConstraint('low_price_fee >= 0 AND high_price_fee >= 0', name='ck_fba_fee_nonnegative'),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    store_id: Mapped[str | None] = mapped_column(ForeignKey('stores.id'), nullable=True, index=True)
    scope_key: Mapped[str] = mapped_column(String(36))
    sku: Mapped[str] = mapped_column(String(120), index=True)
    effective_from: Mapped[date] = mapped_column(Date)
    low_price_fee: Mapped[Decimal] = mapped_column(Numeric(18, 9))
    high_price_fee: Mapped[Decimal] = mapped_column(Numeric(18, 9))
    source: Mapped[str] = mapped_column(String(500), default='')
    revision: Mapped[int] = mapped_column(Integer, default=1)


class FbaFeeInput(Input):
    store_id: str | None = Field(default=None, max_length=36)
    sku: str = Field(min_length=1, max_length=120, pattern=r'^[^\x00-\x1f\x7f]+$')
    effective_from: date
    low_price_fee: Money
    high_price_fee: Money
    source: str = Field(default='', max_length=500)
    revision: int = Field(default=0, ge=0)

    @field_validator('sku')
    @classmethod
    def exact_sku(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('SKU 不能为空')
        return value


class FbaCatalogDeletion(Base):
    """Persist row removals even when products/reports still contain the SKU."""
    __tablename__ = 'fba_catalog_deletions'
    scope_key: Mapped[str] = mapped_column(String(36), primary_key=True)
    sku: Mapped[str] = mapped_column(String(120), primary_key=True)


class FbaFeeDeletion(Input):
    revision: int = Field(ge=1)


class FbaSkuDeletion(Input):
    sku: str = Field(min_length=1, max_length=120)
    store_id: str | None = Field(default=None, max_length=36)
    versions: dict[str, int]


def manageable_fba_rates(user, store_id=None):
    query = visible_fba_rates(user, store_id)
    if user.role != 'admin':
        query = query.where(FbaFeeRate.store_id.is_not(None))
    return query


def visible_fba_rates(user, store_id=None):
    query = select(FbaFeeRate)
    if user.role != 'admin':
        query = query.where(or_(FbaFeeRate.store_id.is_(None), store_filter(user, FbaFeeRate.store_id)))
    if store_id:
        query = query.where(or_(FbaFeeRate.store_id.is_(None), FbaFeeRate.store_id == store_id))
    return query


def fee_out(row, effective_until=None):
    values = {key: getattr(row, key) for key in ['id', 'store_id', 'sku', 'effective_from',
        'low_price_fee', 'high_price_fee', 'source', 'revision']}
    values['effective_until'] = effective_until
    return {key: format(value, 'f') if isinstance(value, Decimal) else value.isoformat() if isinstance(value, date)
        else value for key, value in values.items()}


def fee_versions(rows):
    """Compute inclusive end dates before pagination, within each SKU/scope."""
    next_start = {}
    values = []
    for row in sorted(rows, key=lambda row: (row.sku, row.scope_key, row.effective_from), reverse=True):
        key = (row.scope_key, row.sku)
        end = next_start[key] - timedelta(days=1) if key in next_start else None
        values.append(fee_out(row, end))
        next_start[key] = row.effective_from
    return values


def applicable(rows, store_id, day):
    for scope in [store_id, None] if store_id else [None]:
        candidates = [row for row in rows if row.store_id == scope and row.effective_from <= day]
        if candidates:
            return max(candidates, key=lambda row: row.effective_from)
    return None


@router.get('/fba-fees')
def fees(db: DB, user: Reader, page: Page, store_id: str | None = None, sku: str = Query('', max_length=120)):
    if store_id:
        require_store(db, user, store_id)
    query = visible_fba_rates(user, store_id)
    if sku:
        query = query.where(FbaFeeRate.sku == sku.strip())
    rows = fee_versions(db.scalars(query).all())
    rows.sort(key=lambda row: (row['sku'], row['store_id'] or '', -date.fromisoformat(row['effective_from']).toordinal()))
    return {'items': rows[page.offset:page.offset + page.limit], 'total': len(rows)}


def catalog_skus(user, store_id=None):
    sources = [select(Product.internal_sku.label('sku')),
        visible_rates(user, store_id).with_only_columns(SalesCostRate.sku.label('sku')),
        visible_fba_rates(user, store_id).with_only_columns(FbaFeeRate.sku.label('sku'))]
    for model in [SalesRecord, AdRecord]:
        query = select(model.sku.label('sku'))
        if user.role != 'admin':
            query = query.where(store_filter(user, model.store_id))
        if store_id:
            query = query.where(model.store_id == store_id)
        sources.append(query)
    catalog = union(*sources).subquery()
    hidden = select(FbaCatalogDeletion.sku).where(FbaCatalogDeletion.scope_key == '*')
    if store_id:
        hidden = select(FbaCatalogDeletion.sku).where(FbaCatalogDeletion.scope_key.in_(['*', store_id]))
    else:
        stores = select(Store.id)
        if user.role != 'admin':
            stores = stores.where(store_filter(user, Store.id))
        # An aggregate view omits a row once every visible store removed it.
        all_stores_hidden = select(FbaCatalogDeletion.sku).where(FbaCatalogDeletion.scope_key.in_(stores)).group_by(
            FbaCatalogDeletion.sku).having(func.count() == select(func.count()).select_from(stores.subquery()).scalar_subquery())
        hidden = union(hidden, all_stores_hidden)
    return select(catalog.c.sku).where(catalog.c.sku.not_in(hidden))


@router.get('/fba-fees/catalog')
def fee_catalog(db: DB, user: Reader, page: Page, store_id: str | None = None,
                as_of: date = Query(default_factory=date.today), q: str = Query('', max_length=120),
                is_active: bool | None = None):
    if store_id:
        require_store(db, user, store_id)
    catalog = catalog_skus(user, store_id).subquery()
    query = select(catalog.c.sku).where(catalog.c.sku.icontains(q.strip(), autoescape=True))
    if is_active is not None:
        query = query.where(catalog.c.sku.in_(select(Product.internal_sku).where(Product.is_active == is_active)))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    skus = db.scalars(query.order_by(catalog.c.sku).limit(page.limit).offset(page.offset)).all()
    rates = defaultdict(list)
    for row in db.scalars(visible_fba_rates(user, store_id).where(FbaFeeRate.sku.in_(skus))):
        rates[row.sku].append(row)
    legacy = defaultdict(list)
    for row in db.scalars(visible_rates(user, store_id).where(SalesCostRate.sku.in_([normalized_sku(sku) for sku in skus]))):
        legacy[row.sku].append(row)
    items = []
    for sku in skus:
        current = applicable(rates[sku], store_id, as_of)
        old = applicable(legacy[normalized_sku(sku)], store_id, as_of) if current is None else None
        versions = fee_versions(rates[sku])
        items.append({'sku': sku, 'current': next((row for row in versions if current and row['id'] == current.id), None),
            'legacy_fee': format(old.fba_fee, 'f') if old and old.fba_fee is not None else None,
            'deletable_versions': {row.id: row.revision for row in rates[sku]
                if has_permission(user, 'quotes.manage') and (row.store_id is not None or user.role == 'admin')},
            'version_count': len(versions), 'scheduled_count': sum(row.effective_from > as_of for row in rates[sku])})
    return {'items': items, 'total': total}


@router.post('/fba-fees')
def save_fee(payload: FbaFeeInput, db: DB, user: Reader):
    if not has_permission(user, 'quotes.manage') or (payload.store_id is None and user.role != 'admin'):
        fail(403, 'permission_denied', '仅管理员可维护通用物流费；经理和财务可维护授权店铺物流费')
    if payload.store_id:
        require_store(db, user, payload.store_id)
        db.scalar(select(Store).where(Store.id == payload.store_id).with_for_update())
    else:
        db.scalar(select(Store).order_by(Store.id).limit(1).with_for_update())
    scope = payload.store_id or '*'
    row = db.scalar(select(FbaFeeRate).where(FbaFeeRate.scope_key == scope, FbaFeeRate.sku == payload.sku,
        FbaFeeRate.effective_from == payload.effective_from).with_for_update())
    if (row.revision if row else 0) != payload.revision:
        fail(409, 'fee_changed', '该物流费版本已存在或已被修改，请刷新后编辑')
    if row is None:
        row = FbaFeeRate(scope_key=scope, revision=0)
        db.add(row)
    for key, value in payload.model_dump(exclude={'revision'}).items():
        setattr(row, key, value)
    row.revision += 1
    # Explicitly adding a fee restores the removed row in this scope.
    restore = delete(FbaCatalogDeletion).where(FbaCatalogDeletion.sku == payload.sku)
    if payload.store_id:
        restore = restore.where(FbaCatalogDeletion.scope_key.in_(['*', scope]))
    db.execute(restore)
    db.flush()
    audit(db, user, 'sales.fba_fee.update', 'fba_fee', row.id, '维护亚马逊物流费版本', payload.store_id)
    next_start = db.scalar(select(func.min(FbaFeeRate.effective_from)).where(FbaFeeRate.scope_key == scope,
        FbaFeeRate.sku == payload.sku, FbaFeeRate.effective_from > payload.effective_from))
    result = fee_out(row, next_start - timedelta(days=1) if next_start else None)
    db.commit()
    return result


@router.delete('/fba-fees/catalog')
def delete_sku_fees(payload: FbaSkuDeletion, db: DB, user: Reader):
    if not has_permission(user, 'quotes.manage'):
        fail(403, 'permission_denied', '无权删除物流费')
    if payload.store_id:
        require_store(db, user, payload.store_id)
    # Use the same store locks as save_fee/delete_fee, in a stable order. This
    # also prevents newly created versions from escaping the snapshot check.
    locks = select(Store).order_by(Store.id)
    if user.role != 'admin':
        locks = locks.where(store_filter(user, Store.id))
    db.scalars(locks.with_for_update()).all()
    catalog = catalog_skus(user, payload.store_id).subquery()
    if db.scalar(select(catalog.c.sku).where(catalog.c.sku == payload.sku)) is None:
        fail(404, 'not_found', '该 SKU 不在当前物流费列表中，请刷新列表')
    rows = db.scalars(manageable_fba_rates(user, payload.store_id).where(
        FbaFeeRate.sku == payload.sku).with_for_update().execution_options(populate_existing=True)).all()
    if {row.id: row.revision for row in rows} != payload.versions:
        fail(409, 'fee_changed', '该 SKU 的物流费版本已变化，请刷新列表并核对后删除')
    for row in rows:
        audit(db, user, 'sales.fba_fee.delete', 'fba_fee', row.id,
              f'清除 SKU 物流费：SKU {row.sku}，生效日期 {row.effective_from}，低价档 USD {row.low_price_fee}，高价档 USD {row.high_price_fee}，版本 {row.revision}', row.store_id)
        db.delete(row)
    scopes = [payload.store_id] if payload.store_id else (['*'] if user.role == 'admin' else
        list(db.scalars(select(Store.id).where(store_filter(user, Store.id)))))
    if not scopes:
        fail(403, 'permission_denied', '没有可管理的店铺')
    for scope in scopes:
        if db.get(FbaCatalogDeletion, (scope, payload.sku)) is None:
            db.add(FbaCatalogDeletion(scope_key=scope, sku=payload.sku))
    audit(db, user, 'sales.fba_sku.delete', 'fba_sku', new_id(),
          f'删除物流费 SKU 行：{payload.sku}，清除 {len(rows)} 个版本', payload.store_id)
    db.commit()
    return {'deleted': True, 'deleted_count': len(rows)}


@router.delete('/fba-fees/{identifier}')
def delete_fee(identifier: str, payload: FbaFeeDeletion, db: DB, user: Reader):
    row = db.scalar(visible_fba_rates(user).where(FbaFeeRate.id == identifier))
    if row is None:
        fail(404, 'not_found', '物流费版本不存在或无权访问')
    if not has_permission(user, 'quotes.manage') or (row.store_id is None and user.role != 'admin'):
        fail(403, 'permission_denied', '仅管理员可删除通用物流费；经理和财务可删除授权店铺物流费')
    # Serialize with save_fee before re-reading the version, including concurrent edits.
    lock = select(Store).where(Store.id == row.store_id) if row.store_id else select(Store).order_by(Store.id).limit(1)
    db.scalar(lock.with_for_update())
    row = db.scalar(select(FbaFeeRate).where(FbaFeeRate.id == identifier).with_for_update().execution_options(populate_existing=True))
    if row is None:
        fail(404, 'not_found', '物流费版本已删除，请刷新历史版本')
    if row.revision != payload.revision:
        fail(409, 'fee_changed', '该物流费版本已被修改，请刷新历史版本并核对后删除')
    audit(db, user, 'sales.fba_fee.delete', 'fba_fee', row.id,
          f'删除物流费版本：SKU {row.sku}，生效日期 {row.effective_from}，低价档 USD {row.low_price_fee}，高价档 USD {row.high_price_fee}，版本 {row.revision}', row.store_id)
    db.delete(row)
    db.commit()
    return {'deleted': True}
