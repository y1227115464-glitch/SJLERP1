"""Brand-derived store ownership and supplier eligibility for purchasing."""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import Boolean, ForeignKey, func, select
from sqlalchemy.orm import Mapped, mapped_column

from app.core.api import DB, fail, require, require_store
from app.models import Base, Product, QuoteProduct, Store, Supplier, SupplierQuote, User
from app.schemas import Input
from app.supply.common import active_products, scoped


class ProductStore(Base):
    # Retained for history; current ownership comes from the store's brand.
    __tablename__ = 'product_stores'
    store_id: Mapped[str] = mapped_column(ForeignKey('stores.id'), primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey('products.id'), primary_key=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


def store_condition(store_id):
    matching_stores = select(func.count()).select_from(Store).where(
        Store.brand == Product.brand).correlate(Product).scalar_subquery()
    return (func.trim(Product.brand) != '') & (matching_stores == 1) & select(Store.id).where(
        Store.id == store_id, Store.brand == Product.brand).correlate(Product).exists()


def supplier_condition(supplier_id):
    return select(QuoteProduct.product_id).join(SupplierQuote, SupplierQuote.id == QuoteProduct.quote_id).join(
        Supplier, Supplier.id == SupplierQuote.supplier_id).where(QuoteProduct.product_id == Product.id,
        SupplierQuote.supplier_id == supplier_id, SupplierQuote.is_active.is_(True), Supplier.is_active.is_(True)).exists()


def purchase_products(db, identifiers, store_id, supplier_id):
    identifiers = set(identifiers)
    products = active_products(db, identifiers)
    if not identifiers:
        return products
    eligible = set(db.scalars(select(Product.id).where(Product.id.in_(identifiers),
        store_condition(store_id), supplier_condition(supplier_id))))
    if eligible != identifiers:
        fail(422, 'product_not_purchasable', '商品品牌须唯一对应当前店铺，且关联当前供应商的启用报价；请核对商品品牌、店铺品牌和供应商报价')
    return products


router = APIRouter(prefix='/api/v1/products')
Reader = Annotated[User, Depends(require('products.view'))]
Writer = Annotated[User, Depends(require('products.manage'))]


class StoreSaleInput(Input):
    is_active: bool


@router.get('/{identifier}/stores')
def stores(identifier: str, db: DB, user: Reader):
    product = db.get(Product, identifier)
    if product is None:
        fail(404, 'not_found', '商品不存在')
    if not product.brand.strip():
        return {'brand': product.brand, 'items': []}
    matches = select(Store).where(Store.brand == product.brand)
    if db.scalar(select(func.count()).select_from(Store).where(Store.brand == product.brand)) > 1:
        fail(409, 'ambiguous_store_brand', '商品品牌对应多个店铺，请在店铺管理中核对品牌绑定，确保一对一关联')
    rows = db.scalars(scoped(matches, user, Store.id)).all()
    return {'brand': product.brand, 'items': [{'store_id': row.id, 'store_name': row.name,
        'store_active': row.is_active} for row in rows]}


@router.put('/{identifier}/stores/{store_id}')
def set_store(identifier: str, store_id: str, payload: StoreSaleInput, db: DB, user: Writer):
    require_store(db, user, store_id)
    if db.get(Product, identifier) is None:
        fail(404, 'not_found', '商品不存在')
    fail(409, 'store_ownership_read_only', '售卖店铺由商品品牌与店铺品牌自动关联，无需手工设置')
