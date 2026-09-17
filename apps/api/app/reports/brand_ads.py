"""Campaign-name mappings shared by brand imports and SKU profit analysis."""
from decimal import Decimal

from fastapi import Query
from pydantic import Field, field_validator, model_validator
from sqlalchemy import func, select, union

from app.core.api import DB, Page, audit, fail, require_store
from app.models import Product, Store
from app.reports.models import AdRecord, BrandAdAllocation, SalesRecord
from app.reports.routes import Reader, Writer, router, scope
from app.reports.sku import normalized_sku
from app.schemas import Input


class AllocationItem(Input):
    sku: str = Field(min_length=1, max_length=120, pattern=r'^[^\x00-\x1f\x7f]+$')
    percentage: Decimal = Field(gt=0, le=100, max_digits=7, decimal_places=4)

    @field_validator('sku')
    @classmethod
    def normalize(cls, value):
        value = normalized_sku(value)
        if not value:
            raise ValueError('商品 SKU 不能为空')
        return value


class AllocationInput(Input):
    store_id: str = Field(min_length=1, max_length=36)
    campaign: str = Field(min_length=1, max_length=500, pattern=r'^[^\x00-\x1f\x7f]+$')
    revision: int = Field(default=0, ge=0)
    allocations: list[AllocationItem] = Field(min_length=1, max_length=200)

    @field_validator('campaign')
    @classmethod
    def trim(cls, value):
        if not value.strip():
            raise ValueError('广告活动名称不能为空')
        return value.strip()

    @model_validator(mode='after')
    def ratios(self):
        if len({item.sku for item in self.allocations}) != len(self.allocations):
            raise ValueError('商品 SKU 重复（含尺寸别名归并），请合并比例')
        if sum(item.percentage for item in self.allocations) != Decimal(100):
            raise ValueError('商品分担比例合计必须为 100%')
        return self


@router.get('/brand-ad-campaigns')
def campaigns(db: DB, user: Reader, page: Page, store_id: str | None = None, q: str = Query('', max_length=500)):
    facts = scope(select(AdRecord.store_id, AdRecord.campaign), AdRecord, user, store_id).where(AdRecord.ad_type == 'sponsored_brands')
    configured = scope(select(BrandAdAllocation.store_id, BrandAdAllocation.campaign), BrandAdAllocation, user, store_id)
    source = union(facts, configured).subquery()
    query = select(source.c.store_id, Store.name.label('store_name'), source.c.campaign,
        BrandAdAllocation.allocations, BrandAdAllocation.revision).join(Store, Store.id == source.c.store_id).outerjoin(
        BrandAdAllocation, (BrandAdAllocation.store_id == source.c.store_id) & (BrandAdAllocation.campaign == source.c.campaign))
    if q:
        query = query.where(source.c.campaign.icontains(q, autoescape=True))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(query.order_by(Store.name, source.c.campaign).offset(page.offset).limit(page.limit))
    return {'items': [{'store_id': row.store_id, 'store_name': row.store_name, 'campaign': row.campaign,
        'allocations': row.allocations or [], 'revision': row.revision or 0} for row in rows], 'total': total}


@router.get('/brand-ad-campaigns/products')
def product_options(db: DB, user: Reader, store_id: str, q: str = Query('', max_length=120)):
    require_store(db, user, store_id)
    products = db.execute(select(Product.internal_sku, Product.name).where(Product.is_active.is_(True),
        Product.internal_sku.icontains(q, autoescape=True) | Product.name.icontains(q, autoescape=True))
        .order_by(Product.internal_sku).limit(50))
    options = {sku: name for sku, name in products}
    options.update({sku: options.get(sku, '') for sku in db.scalars(select(SalesRecord.sku).where(
        SalesRecord.store_id == store_id, SalesRecord.sku.icontains(q, autoescape=True)).distinct().order_by(SalesRecord.sku).limit(50))})
    return {'items': [{'sku': sku, 'name': name} for sku, name in sorted(options.items())][:50]}


@router.put('/brand-ad-campaigns')
def save_allocation(payload: AllocationInput, db: DB, user: Writer):
    store = require_store(db, user, payload.store_id)
    if not store.is_active:
        fail(409, 'inactive_store', '店铺已停用，不能维护广告分摊')
    if db.bind.dialect.name == 'sqlite':
        connection = db.connection()
        if not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
    db.scalar(select(Store).where(Store.id == store.id).with_for_update())
    row = db.scalar(select(BrandAdAllocation).where(BrandAdAllocation.store_id == store.id,
        BrandAdAllocation.campaign == payload.campaign).with_for_update())
    if (row.revision if row else 0) != payload.revision:
        fail(409, 'allocation_changed', '该活动分摊已被修改，请关闭后刷新列表再编辑')
    if row is None:
        row = BrandAdAllocation(store_id=store.id, campaign=payload.campaign, revision=0)
        db.add(row)
    row.allocations = [item.model_dump(mode='json') for item in payload.allocations]
    row.revision += 1
    db.flush()
    audit(db, user, 'ads.allocation.update', 'brand_ad_allocation', row.id,
        f'维护品牌广告商品分摊，第 {row.revision} 版，共 {len(row.allocations)} 个 SKU', store.id)
    db.commit()
    return {'store_id': store.id, 'store_name': store.name, 'campaign': row.campaign,
        'allocations': row.allocations, 'revision': row.revision}
