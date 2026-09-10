"""Explicit store assortment and supplier eligibility for purchasing."""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import Boolean, ForeignKey, select
from sqlalchemy.orm import Mapped, mapped_column

from app.core.api import DB, audit, fail, require
from app.models import Base, Product, QuoteProduct, Store, Supplier, SupplierQuote, User
from app.schemas import Input
from app.supply.common import active_products, active_store, scoped


class ProductStore(Base):
    __tablename__ = 'product_stores'
    store_id: Mapped[str] = mapped_column(ForeignKey('stores.id'), primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey('products.id'), primary_key=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


def store_condition(store_id):
    return select(ProductStore.product_id).where(ProductStore.product_id == Product.id,
        ProductStore.store_id == store_id, ProductStore.is_active.is_(True)).exists()


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
        fail(422, 'product_not_purchasable', '商品须在当前店铺售卖，且关联当前供应商的启用报价；请先维护商品售卖店铺和供应商报价')
    return products


router = APIRouter(prefix='/api/v1/products')
Reader = Annotated[User, Depends(require('products.view'))]
Writer = Annotated[User, Depends(require('products.manage'))]


class StoreSaleInput(Input):
    is_active: bool


@router.get('/{identifier}/stores')
def stores(identifier: str, db: DB, user: Reader):
    if db.get(Product, identifier) is None:
        fail(404, 'not_found', '商品不存在')
    rows = db.execute(scoped(select(Store.id, Store.name, Store.is_active, ProductStore.is_active.label('selling'))
        .outerjoin(ProductStore, (ProductStore.store_id == Store.id) & (ProductStore.product_id == identifier)),
        user, Store.id).order_by(Store.name, Store.id).limit(200)).all()
    return {'items': [{'store_id': row.id, 'store_name': row.name, 'store_active': row.is_active,
        'is_active': bool(row.selling)} for row in rows]}


@router.put('/{identifier}/stores/{store_id}')
def set_store(identifier: str, store_id: str, payload: StoreSaleInput, db: DB, user: Writer):
    active_store(db, user, store_id)
    # Serialize concurrent edits to this product's assortment.
    product = db.scalar(select(Product).where(Product.id == identifier).with_for_update())
    if product is None:
        fail(404, 'not_found', '商品不存在')
    record = db.get(ProductStore, (store_id, identifier))
    if record is None:
        record = ProductStore(store_id=store_id, product_id=identifier)
        db.add(record)
    record.is_active = payload.is_active
    audit(db, user, 'products.store.update', 'product', identifier,
        '启用店铺售卖' if payload.is_active else '停用店铺售卖', store_id)
    db.commit()
    return {'store_id': store_id, 'product_id': identifier, 'is_active': record.is_active}
