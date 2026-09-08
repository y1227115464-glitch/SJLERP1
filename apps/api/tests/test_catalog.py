import csv
import io
from decimal import Decimal

import pytest
from sqlalchemy import event, func, select

from app.catalog_import import SOURCE_COLUMNS
from app.models import Product, ProductImport, Supplier, SupplierQuote, User
from conftest import HEADERS, login


def source_csv(rows, columns=None):
    output = io.StringIO(newline="")
    columns = columns or SOURCE_COLUMNS
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for i, overrides in enumerate(rows):
        row = {key: "" for key in columns}
        row.update({"id": str(i + 1), "sku": f"SYNTHETIC-{i}", "name": "Synthetic 120 Pcs Label", "price": "725",
                    "original_price": "950", "stock": "123456", "monthly_sales": "987654", "brand": "Synthetic Brand",
                    "FNSKU": f"TEST-FNSKU-{i}", "asin": f"TEST-ASIN-{i}", "imagelist": "[]", "bullet_points": "[]"})
        row.update(overrides)
        writer.writerow(row)
    return output.getvalue().encode("utf-8-sig")


def preview(client, headers, rows, unit="unknown"):
    response = client.post("/api/v1/products/import/preview", files={"file": ("synthetic-products.csv", source_csv(rows), "text/csv")},
                           data={"price_unit": unit}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_product_crud_filters_pagination_readonly_source_and_scope(system):
    client = system["client"]
    headers = login(client, "operator")
    created = client.post("/api/v1/products", json={"internal_sku": "SYN-CAT-A", "name": "测试商品", "brand": "共享品牌",
        "sale_price": "12.3401", "image_url": "https://example.test/image.png", "review_notes": ["合成测试待核对"]}, headers=headers)
    assert created.status_code == 201, created.text
    item = created.json()
    assert Decimal(item["sale_price"]) == Decimal("12.3401")
    assert item["source_data"] is None
    assert client.post("/api/v1/products", json={"internal_sku": "SYN-CAT-A", "name": "重复SKU"}, headers=headers).status_code == 409
    assert client.post("/api/v1/products", json={"internal_sku": "SYN-CAT-B", "name": "另一商品"}, headers=headers).status_code == 201
    assert client.get("/api/v1/products", params={"q": "CAT-A", "needs_review": True, "brand": "共享品牌"}).json()["total"] == 1
    assert client.get("/api/v1/products", params={"limit": 1, "offset": 1}).json()["total"] == 2
    assert len(client.get("/api/v1/products", params={"limit": 1, "offset": 1}).json()["items"]) == 1
    assert client.patch(f"/api/v1/products/{item['id']}", json={"source_data": {"edited": True}}, headers=headers).status_code == 422
    assert client.patch(f"/api/v1/products/{item['id']}", json={"review_notes": [], "is_active": False, "sale_price": None}, headers=headers).status_code == 200
    assert client.get("/api/v1/products/meta").json() == {"brands": ["共享品牌"], "total": 2, "active": 1, "needs_review": 0}
    login(client, "finance")
    # Company-shared catalog remains visible even though the finance account has a different store.
    assert client.get(f"/api/v1/products/{item['id']}").status_code == 200


def test_catalog_role_boundaries_and_quote_cost_permission(system):
    client = system["client"]
    headers = login(client, "operator")
    assert client.get("/api/v1/suppliers").status_code == 403
    assert client.get("/api/v1/supplier-quotes").status_code == 403
    assert client.post("/api/v1/supplier-quotes", json={}, headers=headers).status_code == 403
    headers = login(client, "finance")
    assert client.post("/api/v1/products", json={"internal_sku": "DENIED", "name": "禁止"}, headers=headers).status_code == 403
    assert client.post("/api/v1/products/import/preview", files={"file": ("x.csv", source_csv([{}]))}, headers=headers).status_code == 403
    with system["app"].state.database.session() as db:
        user = db.get(User, system["ids"]["finance"])
        user.role = "warehouse"
        db.commit()
    assert client.get("/api/v1/products").status_code == 200
    assert client.get("/api/v1/suppliers").status_code == 200
    assert client.get("/api/v1/supplier-quotes").status_code == 403


def test_suppliers_alias_case_insensitive_uniqueness_and_inactive_filter(system):
    client = system["client"]
    headers = login(client, "finance")
    created = client.post("/api/v1/suppliers", json={"code": "x", "name": "x"}, headers=headers)
    assert created.status_code == 201
    supplier = created.json()
    assert supplier["code"] == "X" and supplier["name"] == "X" and "x" in supplier["notes"]
    assert client.post("/api/v1/suppliers", json={"code": "X2", "name": "X"}, headers=headers).status_code == 409
    assert client.post("/api/v1/suppliers", json={"code": "SYN-S", "name": "Synthetic Supply"}, headers=headers).status_code == 201
    assert client.post("/api/v1/suppliers", json={"code": "SYN-S2", "name": "synthetic supply"}, headers=headers).status_code == 409
    assert client.patch(f"/api/v1/suppliers/{supplier['id']}", json={"is_active": False}, headers=headers).status_code == 200
    assert client.get("/api/v1/suppliers", params={"is_active": False, "q": "X"}).json()["total"] == 1


def test_quotes_preserve_source_tiers_tax_labeling_and_relations(system):
    client = system["client"]
    headers = login(client)
    product = client.post("/api/v1/products", json={"internal_sku": "SYN-Q", "name": "报价测试商品"}, headers=headers).json()
    supplier = client.post("/api/v1/suppliers", json={"code": "SYN-QSUP", "name": "报价测试供应商"}, headers=headers).json()
    payload = {"supplier_id": supplier["id"], "product_ids": [product["id"], product["id"]], "label": "合成阶梯报价", "packaging": "测试包装",
               "includes_labeling": True, "labeling_fee": "0.1234", "tax_status": "mixed", "source_text": "  合成敏感报价原文 TEST-SOURCE-SECRET\n",
               "tiers": [{"min_quantity": 120, "unit_price": "7.321", "tax_inclusive_price": "8.4567", "unit": "包"},
                         {"min_quantity": None, "unit_price": None, "tax_inclusive_price": None, "unit": "待核对"}]}
    response = client.post("/api/v1/supplier-quotes", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    quote = response.json()
    assert quote["product_ids"] == [product["id"]]
    assert quote["product_names"] == [product["name"]]
    assert quote["tiers"][0]["unit_price"] == "7.321"
    assert quote["tiers"][0]["tax_inclusive_price"] == "8.4567"
    assert quote["tiers"][1]["min_quantity"] is None
    assert Decimal(quote["labeling_fee"]) == Decimal("0.1234")
    assert quote["source_text"] == payload["source_text"]
    assert client.get("/api/v1/supplier-quotes", params={"product_id": product["id"], "q": "SYN-Q", "unmatched": False}).json()["total"] == 1
    assert client.get("/api/v1/supplier-quotes", params={"unmatched": True}).json()["total"] == 0
    patched = client.patch(f"/api/v1/supplier-quotes/{quote['id']}", json={"product_ids": [], "is_active": False, "review_status": "confirmed"}, headers=headers)
    assert patched.status_code == 200 and patched.json()["product_ids"] == []
    assert client.get("/api/v1/supplier-quotes", params={"unmatched": True, "is_active": False, "review_status": "confirmed"}).json()["total"] == 1
    assert "TEST-SOURCE-SECRET" not in client.get("/api/v1/audit-logs").text
    login(client, "operator")
    assert client.get(f"/api/v1/supplier-quotes/{quote['id']}").status_code == 403
    assert "TEST-SOURCE-SECRET" not in client.get(f"/api/v1/products/{product['id']}").text


def test_quote_and_product_invalid_amounts_relations_and_tier_quantities(system):
    client = system["client"]
    headers = login(client)
    supplier = client.post("/api/v1/suppliers", json={"code": "AMOUNT-S", "name": "金额验证供应商"}, headers=headers).json()
    basic = {"supplier_id": supplier["id"], "label": "金额验证"}
    for amount in ["-1", "NaN", "Infinity", "1.12345", "100000000000000"]:
        assert client.post("/api/v1/supplier-quotes", json={**basic, "tiers": [{"unit_price": amount}]}, headers=headers).status_code == 422
        assert client.post("/api/v1/products", json={"internal_sku": "SYN-BAD", "name": "错误金额", "sale_price": amount}, headers=headers).status_code == 422
    for tiers in [[], [{"min_quantity": 0}], [{"min_quantity": -1}], [{"min_quantity": 1.5}], [{"min_quantity": True}], [{"min_quantity": 12}, {"min_quantity": 12}]]:
        assert client.post("/api/v1/supplier-quotes", json={**basic, "tiers": tiers}, headers=headers).status_code == 422
    assert client.post("/api/v1/supplier-quotes", json={**basic, "tiers": [{}], "product_ids": ["missing"]}, headers=headers).status_code == 422
    assert client.post("/api/v1/products", json={"internal_sku": "BAD-URL", "name": "错误链接", "image_url": "javascript:alert(1)"}, headers=headers).status_code == 422


def test_import_preview_preserves_source_unknown_units_duplicate_fnsku_and_json(system):
    client = system["client"]
    headers = login(client, "operator")
    rows = [{"sku": "  SYN-A  ", "FNSKU": " DUPLICATE-SYN ", "imagelist": "[broken-json", "specifications": "10 Pcs"},
            {"sku": "SYN-B", "FNSKU": "DUPLICATE-SYN"}]
    data = preview(client, headers, rows)
    assert data["total"] == 2 and data["create_count"] == 2 and data["errors"] == []
    assert any("JSON" in note for note in data["rows"][0]["review_notes"])
    assert all(any("多个 SKU" in note for note in row["review_notes"]) for row in data["rows"])
    assert any("件数不一致" in note for note in data["rows"][0]["review_notes"])
    assert client.get("/api/v1/products/meta").json()["total"] == 0
    confirmed = client.post("/api/v1/products/import/confirm", json={"token": data["token"]}, headers=headers)
    assert confirmed.status_code == 200 and confirmed.json() == {"created": 2, "skipped": 0, "needs_review": 2}
    products = client.get("/api/v1/products").json()["items"]
    source = next(product for product in products if product["internal_sku"] == "SYN-A")
    assert source["source_data"]["sku"] == "  SYN-A  "
    assert source["source_data"]["imagelist"] == "[broken-json"
    assert source["source_data"]["stock"] == "123456" and source["source_data"]["monthly_sales"] == "987654"
    assert "stock" not in source and "monthly_sales" not in source
    assert source["source_row"] == 2 and source["sale_price"] is None
    assert len(source["source_data"]) == len(SOURCE_COLUMNS)
    with system["app"].state.database.session() as db:
        record = db.get(ProductImport, data["token"])
        assert (system["settings"].storage_path / record.storage_key).read_bytes() == source_csv(rows)


def test_import_confirm_owner_permission_idempotency_and_no_overwrite(system):
    client = system["client"]
    headers = login(client, "operator")
    data = preview(client, headers, [{"sku": "SYN-KEEP"}], unit="cents")
    other = login(client)
    assert client.post("/api/v1/products/import/confirm", json={"token": data["token"]}, headers=other).status_code == 404
    headers = login(client, "operator")
    first = client.post("/api/v1/products/import/confirm", json={"token": data["token"]}, headers=headers)
    assert first.status_code == 200 and first.json()["created"] == 1
    assert client.post("/api/v1/products/import/confirm", json={"token": data["token"]}, headers=headers).json() == first.json()
    product = client.get("/api/v1/products").json()["items"][0]
    assert Decimal(product["sale_price"]) == Decimal("7.25")
    assert client.patch(f"/api/v1/products/{product['id']}", json={"name": "人工编辑保留", "review_notes": []}, headers=headers).status_code == 200
    same = preview(client, headers, [{"sku": "SYN-KEEP"}], unit="cents")
    assert same["token"] == data["token"] and same["skip_count"] == 1
    different = preview(client, headers, [{"sku": "SYN-KEEP", "name": "不同来源名"}], unit="dollars")
    assert client.post("/api/v1/products/import/confirm", json={"token": different["token"]}, headers=headers).json() == {"created": 0, "skipped": 1, "needs_review": 0}
    assert client.get(f"/api/v1/products/{product['id']}").json()["name"] == "人工编辑保留"
    pending = preview(client, headers, [{"sku": "SYN-REVOKE"}])
    with system["app"].state.database.session() as db:
        db.get(User, system["ids"]["operator"]).role = "warehouse"
        db.commit()
    assert client.post("/api/v1/products/import/confirm", json={"token": pending["token"]}, headers=headers).status_code == 403


def test_import_errors_are_atomic_and_reject_extra_private_columns(system):
    client = system["client"]
    headers = login(client)
    data = preview(client, headers, [{"sku": "SYN-OK"}, {"sku": "", "name": "缺SKU"}])
    assert data["errors"] and data["rows"][1]["action"] == "error"
    assert client.post("/api/v1/products/import/confirm", json={"token": data["token"]}, headers=headers).status_code == 409
    assert client.get("/api/v1/products/meta").json()["total"] == 0
    duplicate = preview(client, headers, [{"sku": "SYN-DUP"}, {"sku": "SYN-DUP"}])
    assert len(duplicate["errors"]) == 2
    extra = source_csv([{"purchase_cost": "SENSITIVE"}], SOURCE_COLUMNS + ["purchase_cost"])
    response = client.post("/api/v1/products/import/preview", files={"file": ("extra.csv", extra)}, headers=headers)
    assert response.status_code == 422 and "SENSITIVE" not in response.text
    assert client.post("/api/v1/products/import/preview", files={"file": ("bad.csv", b"\xff\xff")}, headers=headers).status_code == 422
    with system["app"].state.database.session() as db:
        assert db.scalar(select(func.count()).select_from(Product)) == 0


def test_import_decimal_extreme_exponents_are_row_errors(system):
    client = system["client"]
    headers = login(client)
    data = preview(client, headers, [{"sku": "SYN-HUGE", "price": "1e1000002"}, {"sku": "SYN-TINY", "price": "1e-1000002"}], unit="cents")
    assert len(data["errors"]) == 2
    assert client.post("/api/v1/products/import/confirm", json={"token": data["token"]}, headers=headers).status_code == 409


def test_import_unexpected_second_insert_failure_rolls_back_entire_batch(system):
    client = system["client"]
    headers = login(client)
    data = preview(client, headers, [{"sku": "SYN-ATOMIC-FIRST"}, {"sku": "SYN-ATOMIC-FAIL"}])

    def fail_second(mapper, connection, target):
        if target.internal_sku == "SYN-ATOMIC-FAIL":
            raise RuntimeError("synthetic persistence fault")

    event.listen(Product, "before_insert", fail_second)
    try:
        with pytest.raises(RuntimeError, match="synthetic persistence fault"):
            client.post("/api/v1/products/import/confirm", json={"token": data["token"]}, headers=headers)
    finally:
        event.remove(Product, "before_insert", fail_second)
    with system["app"].state.database.session() as db:
        assert db.scalar(select(func.count()).select_from(Product)) == 0
        assert db.get(ProductImport, data["token"]).result is None
    assert client.post("/api/v1/products/import/confirm", json={"token": data["token"]}, headers=headers).json()["created"] == 2


def test_postgres_competing_previews_cannot_duplicate_products(system):
    from concurrent.futures import ThreadPoolExecutor

    if system["app"].state.database.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL row locks and unique-key concurrency require PostgreSQL")
    client = system["client"]
    headers = login(client)
    first = preview(client, headers, [{"sku": "SYN-RACE"}], unit="unknown")
    second = preview(client, headers, [{"sku": "SYN-RACE", "name": "另一个合成来源"}], unit="unknown")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda token: client.post("/api/v1/products/import/confirm", json={"token": token}, headers=headers), [first["token"], second["token"]]))
    assert all(result.status_code == 200 for result in results)
    assert sum(result.json()["created"] for result in results) == 1
    assert sum(result.json()["skipped"] for result in results) == 1
    with system["app"].state.database.session() as db:
        assert db.scalar(select(func.count()).select_from(Product)) == 1
