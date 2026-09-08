import csv
import hashlib
import io
import json
import os
import re
from collections import Counter, defaultdict
from decimal import Decimal, DecimalException
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.catalog_schemas import ProductCreate, http_url
from app.core.api import audit, fail
from app.core.security import has_permission, token
from app.models import Product, ProductImport, User, new_id, now

# Source export contract: accepting arbitrary columns here could expose procurement
# values through product.source_data to roles allowed to view products only.
SOURCE_COLUMNS = ["id", "created_at", "name", "price", "original_price", "description", "image_url", "stock", "brand", "title", "sku", "asin", "FNSKU", "category", "imagelist", "bullet_points", "rating_avg", "review_count", "monthly_sales", "material", "specifications", "amazon_url", "templates", "sort", "tags", "template_instructions"]


def json_list(raw, field, notes, url=False):
    if not raw:
        return []
    try:
        value = json.loads(raw)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError()
        if url:
            for item in value:
                http_url(item)
        return value
    except (ValueError, TypeError):
        notes.append(f"{field} 的 JSON 内容或链接格式异常，原文已保留，请人工核对。")
        return []


def source_url(value, field, notes):
    try:
        return http_url(value.strip())
    except ValueError:
        notes.append(f"{field} 链接格式异常，原文已保留，未作为可点击链接导入。")
        return ""


def source_money(value, price_unit):
    if price_unit == "unknown" or not value.strip():
        return None
    amount = Decimal(value.strip())
    if not amount.is_finite() or amount < 0:
        raise ValueError("金额必须是有限非负数")
    multiplier = Decimal(100) if price_unit == "cents" else Decimal(1)
    if amount > Decimal("99999999999999.9999") * multiplier:
        raise ValueError("金额超出可存储范围")
    if amount and amount.adjusted() < (-2 if price_unit == "cents" else -4):
        raise ValueError("换算后金额小于可支持的四位小数精度")
    return amount / Decimal(100) if price_unit == "cents" else amount


def quantity_notes(raw):
    notes = []
    def quantity(value, expression):
        match = re.search(expression, value, flags=re.IGNORECASE)
        return int(match.group(1).replace(",", "")) if match else None
    total_pattern = r"\b([0-9][0-9,]*)\s*(?:pcs|pieces|labels)\b"
    spec_total = quantity(raw["specifications"], total_pattern)
    name_total = quantity(raw["name"], total_pattern)
    title_total = quantity(raw["title"], total_pattern)
    if spec_total and ((name_total and name_total != spec_total) or (title_total and title_total != spec_total)):
        notes.append("名称或标题与规格中的件数不一致，请人工核对；未自动修改数量。")
    up = quantity(raw["name"] + " " + raw["title"], r"\b([0-9]+)\s*up\b")
    sheets = quantity(raw["specifications"], r"\b([0-9]+)\s*sheets?\b")
    if up and sheets and spec_total and up * sheets != spec_total:
        notes.append("每张标签数 × 张数与规格件数不一致，请核对包装规格。")
    return notes


def parse_source(content: bytes, price_unit: str):
    try:
        source = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        fail(422, "invalid_encoding", "文件必须为 UTF-8 或 UTF-8 BOM 编码的 CSV")
    try:
        reader = csv.DictReader(io.StringIO(source, newline=""), strict=True)
        columns = reader.fieldnames or []
        if len(columns) != len(SOURCE_COLUMNS) or set(columns) != set(SOURCE_COLUMNS):
            fail(422, "unsupported_csv", "CSV 表头不符合商品来源格式，请使用原商品导出文件；不允许附加其他业务或采购字段")
        rows = []
        for index, raw in enumerate(reader, start=2):
            if index > 2001:
                fail(422, "too_many_rows", "一次最多导入 2000 条商品")
            rows.append((index, raw))
    except csv.Error:
        fail(422, "invalid_csv", "CSV 引号、列数或字段大小异常，未导入任何商品")
    if not rows:
        fail(422, "empty_csv", "文件中没有商品数据")
    parsed = []
    errors = []
    fnskus = defaultdict(list)
    skus = Counter((raw.get("sku") or "").strip() for _, raw in rows)
    for index, raw in rows:
        notes = []
        error = None
        cleaned_sku = (raw.get("sku") or "").strip()
        entry = {"row": index, "internal_sku": cleaned_sku, "name": (raw.get("name") or "").strip(),
                 "review_notes": notes, "source_data": raw, "data": None, "error": None}
        if None in raw or any(value is None for value in raw.values()):
            error = "列数与表头不一致"
        elif skus[cleaned_sku] > 1:
            error = "同一文件中的内部 SKU 重复，请先核对来源行"
        else:
            for field in ["sku", "FNSKU", "asin"]:
                if raw[field] != raw[field].strip():
                    notes.append(f"{field} 已清理首尾空格，原始值保留在来源资料。")
            notes.extend(quantity_notes(raw))
            if price_unit == "unknown" and (raw["price"].strip() or raw["original_price"].strip()):
                notes.append("来源价格单位未确认，售价留空，原值仅保留用于核对。")
            if raw["FNSKU"].strip() == raw["asin"].strip() and raw["asin"].strip():
                notes.append("来源 FNSKU 与 ASIN 相同，请核对标识类型。")
            image_urls = json_list(raw["imagelist"], "imagelist", notes, url=True)
            bullet_points = json_list(raw["bullet_points"], "bullet_points", notes)
            for field in ["templates", "tags"]:
                if raw[field].strip():
                    try:
                        json.loads(raw[field])
                    except ValueError:
                        notes.append(f"{field} 不是有效 JSON，来源原文已完整保留。")
            try:
                payload = ProductCreate(internal_sku=cleaned_sku, name=raw["name"], brand=raw["brand"], category=raw["category"],
                    specifications=raw["specifications"], material=raw["material"], title=raw["title"], description=raw["description"],
                    asin=raw["asin"].strip(), fnsku=raw["FNSKU"].strip(), image_url=source_url(raw["image_url"], "image_url", notes),
                    image_urls=image_urls, bullet_points=bullet_points, amazon_url=source_url(raw["amazon_url"], "amazon_url", notes),
                    sale_price=source_money(raw["price"], price_unit), original_sale_price=source_money(raw["original_price"], price_unit),
                    review_notes=notes)
                entry["data"] = payload.model_dump(mode="json")
                if payload.fnsku:
                    fnskus[payload.fnsku].append(entry)
            except (ValidationError, DecimalException, ValueError):
                error = "必填字段、长度、链接或金额无效；金额必须非负且最多 4 位小数"
        if error:
            entry["error"] = error
            errors.append(f"第 {index} 行：{error}")
        parsed.append(entry)
    for fnsku, entries in fnskus.items():
        if len(entries) > 1:
            note = f"FNSKU {fnsku} 对应多个 SKU，请人工核对；商品将分别保留，不自动合并。"
            for entry in entries:
                entry["review_notes"].append(note)
                entry["data"]["review_notes"] = entry["review_notes"]
    warnings = ["商品为公司共享档案；品牌不推断店铺，来源 stock/monthly_sales 不计入经营库存或销量。"]
    if price_unit == "unknown":
        warnings.append("价格单位未确认，本批次商品售价留空；可后续核对并编辑。")
    return parsed, errors, warnings


def preview_out(db, record):
    skus = [row["internal_sku"] for row in record.parsed_rows]
    existing = set(db.scalars(select(Product.internal_sku).where(Product.internal_sku.in_(skus))))
    rows = []
    for row in record.parsed_rows:
        action = "error" if row["error"] else "skip" if row["internal_sku"] in existing else "create"
        notes = list(row["review_notes"])
        if action == "skip":
            notes.append("该内部 SKU 已存在，本次跳过，不覆盖已有编辑。")
        if row["error"]:
            notes.append(row["error"])
        rows.append({key: row[key] for key in ["row", "internal_sku", "name"]} | {"action": action, "review_notes": notes})
    return {"token": record.id, "filename": record.filename, "total": len(rows),
            "create_count": sum(row["action"] == "create" for row in rows), "skip_count": sum(row["action"] == "skip" for row in rows),
            "rows": rows, "errors": record.errors, "warnings": record.warnings}


def create_preview(db, user, file, price_unit, settings):
    try:
        content = file.file.read(settings.max_upload_bytes + 1)
    finally:
        file.file.close()
    if len(content) > settings.max_upload_bytes:
        fail(413, "file_too_large", "文件超过上传大小限制")
    if not content:
        fail(422, "empty_file", "不能上传空文件")
    file_hash = hashlib.sha256(content).hexdigest()
    existing = db.scalar(select(ProductImport).where(ProductImport.owner_id == user.id, ProductImport.file_hash == file_hash, ProductImport.price_unit == price_unit))
    if existing:
        return preview_out(db, existing)
    rows, errors, warnings = parse_source(content, price_unit)
    fnskus = {row["data"]["fnsku"] for row in rows if row["data"] and row["data"]["fnsku"]}
    duplicates = defaultdict(list)
    for existing_product in db.scalars(select(Product).where(Product.fnsku.in_(fnskus))):
        duplicates[existing_product.fnsku].append(existing_product.internal_sku)
    for row in rows:
        if row["data"] and any(sku != row["internal_sku"] for sku in duplicates[row["data"]["fnsku"]]):
            row["review_notes"].append("FNSKU 已被其他现有商品使用，请人工核对；不会合并商品。")
            row["data"]["review_notes"] = row["review_notes"]
    filename = Path((file.filename or "products.csv").replace("\\", "/")).name
    filename = "".join(character for character in filename if ord(character) >= 32 and ord(character) != 127)[:255] or "products.csv"
    root = settings.storage_path.resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    storage_key = new_id()
    path = root / storage_key
    with path.open("xb") as output:
        os.chmod(path, 0o600)
        output.write(content)
    record = ProductImport(id=token(), owner_id=user.id, file_hash=file_hash, price_unit=price_unit, filename=filename,
                           storage_key=storage_key, parsed_rows=rows, errors=errors, warnings=warnings)
    try:
        db.add(record)
        db.flush()
        audit(db, user, "products.import_preview", "product_import", record.id, "预览商品来源文件；尚未创建商品")
        db.commit()
    except IntegrityError:
        db.rollback()
        path.unlink(missing_ok=True)
        record = db.scalar(select(ProductImport).where(ProductImport.owner_id == user.id, ProductImport.file_hash == file_hash, ProductImport.price_unit == price_unit))
        if not record:
            raise
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return preview_out(db, record)


def confirm_import(db, user, import_token):
    if db.bind.dialect.name == "sqlite":
        connection = db.connection()
        if not connection.connection.driver_connection.in_transaction:
            # Python SQLite's legacy mode does not BEGIN for SELECT. Without an
            # explicit outer transaction, releasing a nested savepoint can commit
            # one row before the whole import succeeds.
            connection.exec_driver_sql("BEGIN IMMEDIATE")
    actor = db.scalar(select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True))
    if not actor or not has_permission(actor, "products.manage"):
        fail(403, "permission_denied", "账号权限已变化，不能确认商品导入")
    record = db.scalar(select(ProductImport).where(ProductImport.id == import_token, ProductImport.owner_id == user.id).with_for_update())
    if not record:
        fail(404, "not_found", "导入预览不存在或不属于当前账号")
    if record.result is not None:
        return record.result
    if record.errors:
        fail(409, "import_has_errors", "预览包含数据错误，请修正文件后重新上传；未创建任何商品")
    created = skipped = review = 0
    # The lock on this import prevents repeated confirmation. Unique SKU constraints
    # and savepoints also protect competing previews or a concurrent manual create.
    for row in record.parsed_rows:
        if db.scalar(select(Product.id).where(Product.internal_sku == row["internal_sku"])):
            skipped += 1
            continue
        payload = ProductCreate.model_validate(row["data"])
        from app.catalog_routes import add_duplicate_fnsku_note, product_values
        values = product_values(payload)
        add_duplicate_fnsku_note(db, values)
        try:
            with db.begin_nested():
                product = Product(**values, source_data=row["source_data"], source_filename=record.filename, source_row=row["row"])
                db.add(product)
                db.flush()
            created += 1
            review += int(product.needs_review)
        except IntegrityError:
            # Only treat a verified SKU collision as a skip; other failures roll
            # back the entire confirmation so no partial batch becomes visible.
            if db.scalar(select(Product.id).where(Product.internal_sku == row["internal_sku"])):
                skipped += 1
            else:
                raise
    record.result = {"created": created, "skipped": skipped, "needs_review": review}
    record.confirmed_at = now()
    audit(db, user, "products.import_confirm", "product_import", record.id, "确认商品来源文件导入；保留源文件与逐行来源")
    db.commit()
    return record.result
