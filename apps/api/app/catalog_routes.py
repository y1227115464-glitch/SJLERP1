from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import ValidationError
from sqlalchemy import func, or_, select

from app.catalog_schemas import ImportConfirm, ProductCreate, QuoteCreate, SupplierCreate, validate_patch
from app.core.api import DB, Page, audit, fail, paginated, require, serialize
from app.core.security import has_permission
from app.models import Product, Supplier, SupplierQuote, User

router = APIRouter(prefix="/api/v1")
ProductReader = Annotated[User, Depends(require("products.view"))]
ProductWriter = Annotated[User, Depends(require("products.manage"))]
SupplierReader = Annotated[User, Depends(require("suppliers.view"))]
SupplierWriter = Annotated[User, Depends(require("suppliers.manage"))]


def require_quotes(permission):
    def dependency(user: Annotated[User, Depends(require(permission))]):
        if not has_permission(user, "costs.view"):
            fail(403, "permission_denied", "当前账号无权查看或维护采购报价")
        return user
    return dependency


QuoteReader = Annotated[User, Depends(require_quotes("quotes.view"))]
QuoteWriter = Annotated[User, Depends(require_quotes("quotes.manage"))]


def money(value):
    return format(value, "f") if value is not None else None


def product_out(record):
    fields = "id internal_sku name name_zh units_per_carton brand category specifications material title description asin fnsku image_url image_urls bullet_points amazon_url currency is_active notes review_notes source_data source_filename source_row created_at updated_at"
    return {**serialize(record, fields), "unit_weight_kg": money(record.unit_weight_kg), "sale_price": money(record.sale_price), "original_sale_price": money(record.original_sale_price)}


def supplier_out(record):
    return serialize(record, "id code name contact_name phone email address payment_terms notes is_active created_at updated_at")


def quote_out(record):
    fields = "id supplier_id label packaging currency tax_status includes_shipping includes_labeling review_status review_notes notes source_text source_reference is_active tiers created_at updated_at"
    return {**serialize(record, fields), "labeling_fee": money(record.labeling_fee), "supplier_name": record.supplier.name,
            "product_ids": [product.id for product in record.products], "product_names": [product.name for product in record.products]}


def get_record(db, model, identifier):
    record = db.get(model, identifier)
    if record is None:
        fail(404, "not_found", "档案不存在")
    return record


def merged_input(schema, record, changes, serializer):
    stored = {key: value for key, value in serializer(record).items() if key in schema.model_fields}
    try:
        return validate_patch(schema, stored, changes)
    except ValidationError:
        fail(422, "validation_error", "请检查字段类型、长度、金额或阶梯数量；来源字段不可修改")


def product_values(payload):
    values = payload.model_dump()
    values["needs_review"] = bool(values["review_notes"])
    return values


def add_duplicate_fnsku_note(db, values, exclude_id=None):
    if not values.get("fnsku"):
        return
    statement = select(Product.internal_sku).where(Product.fnsku == values["fnsku"])
    if exclude_id:
        statement = statement.where(Product.id != exclude_id)
    duplicates = list(db.scalars(statement))
    if duplicates:
        note = "FNSKU 与其他商品重复（" + "、".join(duplicates[:10]) + "），请人工核对；商品未合并。"
        if note not in values["review_notes"]:
            values["review_notes"] = [*values["review_notes"], note]
        values["needs_review"] = True


@router.get("/products/meta")
def product_meta(db: DB, user: ProductReader):
    return {"brands": list(db.scalars(select(Product.brand).where(Product.brand != "").distinct().order_by(Product.brand))),
            "total": db.scalar(select(func.count()).select_from(Product)),
            "active": db.scalar(select(func.count()).select_from(Product).where(Product.is_active.is_(True))),
            "needs_review": db.scalar(select(func.count()).select_from(Product).where(Product.needs_review.is_(True)))}


@router.get("/products")
def products(db: DB, page: Page, user: ProductReader, q: str = "", brand: str | None = None,
             is_active: bool | None = None, needs_review: bool | None = None):
    statement = select(Product)
    if q.strip():
        term = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        statement = statement.where(or_(*(getattr(Product, key).ilike(term, escape="\\") for key in ["internal_sku", "name", "name_zh", "asin", "fnsku", "brand"])))
    if brand is not None:
        statement = statement.where(Product.brand == brand)
    if is_active is not None:
        statement = statement.where(Product.is_active.is_(is_active))
    if needs_review is not None:
        statement = statement.where(Product.needs_review.is_(needs_review))
    return paginated(db, statement.order_by(Product.created_at.desc(), Product.id), page, product_out)


@router.post("/products/import/preview")
def preview_products(request: Request, db: DB, user: ProductWriter, file: Annotated[UploadFile, File()],
                     price_unit: Annotated[Literal["unknown", "cents", "dollars"], Form()] = "unknown"):
    from app.catalog_import import create_preview
    return create_preview(db, user, file, price_unit, request.app.state.settings)


@router.post("/products/import/confirm")
def confirm_products(payload: ImportConfirm, db: DB, user: ProductWriter):
    from app.catalog_import import confirm_import
    return confirm_import(db, user, payload.token)


@router.get("/products/{product_id}")
def product_detail(product_id: str, db: DB, user: ProductReader):
    return product_out(get_record(db, Product, product_id))


@router.post("/products", status_code=201)
def create_product(payload: ProductCreate, db: DB, user: ProductWriter):
    values = product_values(payload)
    add_duplicate_fnsku_note(db, values)
    record = Product(**values)
    db.add(record)
    db.flush()
    audit(db, user, "products.create", "product", record.id, "创建共享商品档案")
    db.commit()
    return product_out(record)


@router.patch("/products/{product_id}")
def update_product(product_id: str, changes: dict, db: DB, user: ProductWriter):
    record = get_record(db, Product, product_id)
    values = product_values(merged_input(ProductCreate, record, changes, product_out))
    if "fnsku" in changes and "review_notes" not in changes:
        add_duplicate_fnsku_note(db, values, record.id)
    for key, value in values.items():
        setattr(record, key, value)
    audit(db, user, "products.update", "product", record.id, "更新共享商品档案")
    db.commit()
    return product_out(record)


def supplier_values(payload):
    values = payload.model_dump()
    aliases = []
    for field in ["name", "code"]:
        if values[field].casefold() == "x":
            if values[field] != "X":
                aliases.append(values[field])
            values[field] = "X"
    if aliases:
        alias_note = "来源别名：" + "、".join(dict.fromkeys(aliases))
        if alias_note not in values["notes"]:
            values["notes"] = (values["notes"] + "\n" + alias_note).strip()
    values["name_key"] = values["name"].casefold()
    return values


@router.get("/suppliers")
def suppliers(db: DB, page: Page, user: SupplierReader, q: str = "", is_active: bool | None = None):
    statement = select(Supplier)
    if q.strip():
        statement = statement.where(or_(Supplier.name.icontains(q.strip(), autoescape=True), Supplier.code.icontains(q.strip(), autoescape=True), Supplier.contact_name.icontains(q.strip(), autoescape=True)))
    if is_active is not None:
        statement = statement.where(Supplier.is_active.is_(is_active))
    return paginated(db, statement.order_by(Supplier.created_at.desc(), Supplier.id), page, supplier_out)


@router.get("/suppliers/{supplier_id}")
def supplier_detail(supplier_id: str, db: DB, user: SupplierReader):
    return supplier_out(get_record(db, Supplier, supplier_id))


@router.post("/suppliers", status_code=201)
def create_supplier(payload: SupplierCreate, db: DB, user: SupplierWriter):
    record = Supplier(**supplier_values(payload))
    db.add(record)
    db.flush()
    audit(db, user, "suppliers.create", "supplier", record.id, "创建供应商档案")
    db.commit()
    return supplier_out(record)


@router.patch("/suppliers/{supplier_id}")
def update_supplier(supplier_id: str, changes: dict, db: DB, user: SupplierWriter):
    record = get_record(db, Supplier, supplier_id)
    values = supplier_values(merged_input(SupplierCreate, record, changes, supplier_out))
    for key, value in values.items():
        setattr(record, key, value)
    audit(db, user, "suppliers.update", "supplier", record.id, "更新供应商档案")
    db.commit()
    return supplier_out(record)


def quote_values(db, payload):
    get_record(db, Supplier, payload.supplier_id)
    products = list(db.scalars(select(Product).where(Product.id.in_(payload.product_ids))))
    if len(products) != len(payload.product_ids):
        fail(422, "invalid_product", "关联列表包含不存在的商品")
    values = payload.model_dump(exclude={"product_ids", "tiers"})
    values["tiers"] = [tier.model_dump(mode="json") | {"unit_price": money(tier.unit_price), "tax_inclusive_price": money(tier.tax_inclusive_price)} for tier in payload.tiers]
    values["products"] = products
    return values


@router.get("/supplier-quotes")
def quotes(db: DB, page: Page, user: QuoteReader, supplier_id: str | None = None, product_id: str | None = None,
           q: str = "", review_status: Literal["confirmed", "needs_review"] | None = None, is_active: bool | None = None,
           unmatched: bool | None = None):
    statement = select(SupplierQuote)
    if supplier_id:
        statement = statement.where(SupplierQuote.supplier_id == supplier_id)
    if product_id:
        statement = statement.where(SupplierQuote.products.any(Product.id == product_id))
    if unmatched is not None:
        statement = statement.where(~SupplierQuote.products.any() if unmatched else SupplierQuote.products.any())
    if q.strip():
        statement = statement.where(or_(SupplierQuote.label.icontains(q.strip(), autoescape=True), SupplierQuote.supplier.has(Supplier.name.icontains(q.strip(), autoescape=True)), SupplierQuote.products.any(or_(Product.name.icontains(q.strip(), autoescape=True), Product.internal_sku.icontains(q.strip(), autoescape=True)))))
    if review_status:
        statement = statement.where(SupplierQuote.review_status == review_status)
    if is_active is not None:
        statement = statement.where(SupplierQuote.is_active.is_(is_active))
    return paginated(db, statement.order_by(SupplierQuote.created_at.desc(), SupplierQuote.id), page, quote_out)


@router.get("/supplier-quotes/{quote_id}")
def quote_detail(quote_id: str, db: DB, user: QuoteReader):
    return quote_out(get_record(db, SupplierQuote, quote_id))


@router.post("/supplier-quotes", status_code=201)
def create_quote(payload: QuoteCreate, db: DB, user: QuoteWriter):
    record = SupplierQuote(**quote_values(db, payload))
    db.add(record)
    db.flush()
    db.refresh(record)
    audit(db, user, "quotes.create", "supplier_quote", record.id, "创建供应商采购报价参考")
    db.commit()
    return quote_out(record)


@router.patch("/supplier-quotes/{quote_id}")
def update_quote(quote_id: str, changes: dict, db: DB, user: QuoteWriter):
    record = get_record(db, SupplierQuote, quote_id)
    payload = merged_input(QuoteCreate, record, changes, quote_out)
    for key, value in quote_values(db, payload).items():
        setattr(record, key, value)
    db.flush()
    db.refresh(record)
    audit(db, user, "quotes.update", "supplier_quote", record.id, "更新供应商采购报价参考")
    db.commit()
    return quote_out(record)
