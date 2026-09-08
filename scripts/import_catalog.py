#!/usr/bin/env python3
"""Import a private product CSV and supplier manifest through the local ERP API.

This script contains no business data. Existing products and quotes are never
overwritten. Source files and generated receipts belong in the ignored .local/.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]


def load_inputs(product_file: Path, supplier_file: Path):
    with product_file.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    skus = [row.get('sku', '').strip() for row in rows]
    if not skus or not all(skus) or len(set(skus)) != len(skus):
        raise SystemExit('商品文件的 SKU 为空或重复，未执行导入。')
    manifest = json.loads(supplier_file.read_text(encoding='utf-8'))
    codes = [supplier['code'] for supplier in manifest['suppliers']]
    if len(set(codes)) != len(codes):
        raise SystemExit('供应商编号重复，未执行导入。')
    refs = set()
    for quote in manifest['quotes']:
        reference = quote['payload']['source_reference']
        if not reference or reference in refs:
            raise SystemExit('报价来源编号为空或重复，未执行导入。')
        refs.add(reference)
        if quote['supplier_code'] not in codes or not set(quote['product_skus']).issubset(skus):
            raise SystemExit('报价关联的供应商或 SKU 未包含在本次资料中，未执行导入。')
    if any(product['internal_sku'] not in skus for product in manifest.get('products', [])):
        raise SystemExit('商品补充说明包含未知 SKU，未执行导入。')
    return rows, manifest


def credentials(path: Path):
    values = dict(line.split('：', 1) for line in path.read_text().splitlines() if '：' in line)
    if not values.get('账号') or not values.get('密码'):
        raise SystemExit('本地登录信息缺少账号或密码。')
    return {'email': values['账号'], 'password': values['密码']}


def call(client, method, path, **kwargs):
    response = client.request(method, '/api/v1' + path, **kwargs)
    if response.is_error:
        try:
            error = response.json().get('error', {})
            detail = error.get('message', '请求失败')
            fields = ', '.join(item.get('field', '') for item in error.get('details', []) if isinstance(item, dict))
        except (ValueError, AttributeError, TypeError):
            detail, fields = '响应格式异常', ''
        raise RuntimeError(f'{method} {path}: HTTP {response.status_code}, {detail}' + (f' ({fields})' if fields else ''))
    return response.json() if response.content else None


def all_records(client, path):
    items = []
    while True:
        result = call(client, 'GET', path, params={'limit': 200, 'offset': len(items)})
        items.extend(result['items'])
        if len(items) >= result['total']:
            return items
        if not result['items']:
            raise RuntimeError('读取分页数据时提前结束，未继续写入。')


def import_data(client, args, manifest):
    previous_products = {row['internal_sku']: row for row in all_records(client, '/products')}
    previous_suppliers = all_records(client, '/suppliers')
    previous_quotes = all_records(client, '/supplier-quotes')
    with args.products.open('rb') as stream:
        preview = call(client, 'POST', '/products/import/preview',
                       files={'file': (args.products.name, stream, 'text/csv')},
                       data={'price_unit': args.price_unit})
    if preview['errors'] or any(row['action'] == 'error' for row in preview['rows']):
        raise RuntimeError('商品预览存在错误，未确认导入：' + '; '.join(preview['errors'][:5]))
    print(f"商品预览：{preview['total']} 条，新增 {preview['create_count']} 条，跳过 {preview['skip_count']} 条。")
    products_result = (call(client, 'POST', '/products/import/confirm', json={'token': preview['token']})
                       if preview['create_count'] else {'created': 0, 'skipped': preview['skip_count'], 'needs_review': 0})
    products = {row['internal_sku']: row for row in all_records(client, '/products')}
    # Only annotate newly created rows; a repeated run must preserve human edits
    # and must not reopen review notes the user has already resolved.
    for extra in manifest.get('products', []):
        sku = extra['internal_sku']
        if sku in previous_products:
            continue
        product = products[sku]
        notes = list(dict.fromkeys(product['review_notes'] + extra.get('review_notes', [])))
        call(client, 'PATCH', f"/products/{product['id']}",
             json={'name_zh': extra.get('name_zh', ''), 'review_notes': notes})

    suppliers_by_code = {row['code']: row for row in previous_suppliers}
    suppliers_by_name = {row['name'].casefold(): row for row in previous_suppliers}
    supplier_ids = {}
    suppliers_created = 0
    for supplier in manifest['suppliers']:
        existing = suppliers_by_code.get(supplier['code'])
        named = suppliers_by_name.get(supplier['name'].casefold())
        if existing and existing['name'].casefold() != supplier['name'].casefold():
            raise RuntimeError('供应商编号已被不同名称使用，停止后续报价写入。')
        current = existing or named
        if current is None:
            current = call(client, 'POST', '/suppliers', json=supplier)
            suppliers_created += 1
        supplier_ids[supplier['code']] = current['id']

    quotes_by_reference = {}
    for item in previous_quotes:
        reference = item.get('source_reference')
        if reference:
            quotes_by_reference.setdefault(reference, []).append(item)
    quotes_created = quotes_skipped = 0
    for quote in manifest['quotes']:
        payload = quote['payload']
        reference = payload['source_reference']
        existing = quotes_by_reference.get(reference, [])
        if len(existing) > 1:
            raise RuntimeError('已有重复报价来源编号，停止后续写入以便人工核对。')
        if existing:
            quotes_skipped += 1
            continue
        call(client, 'POST', '/supplier-quotes', json={
            **payload, 'supplier_id': supplier_ids[quote['supplier_code']],
            'product_ids': [products[sku]['id'] for sku in quote['product_skus']],
        })
        quotes_created += 1
    return {
        'products': products_result,
        'suppliers_created': suppliers_created,
        'quotes_created': quotes_created, 'quotes_skipped': quotes_skipped,
        'source_rows': len(manifest.get('source_rows', [])),
        'unmatched_quotes': sum(not quote['product_skus'] for quote in manifest['quotes']),
        'quotes_needing_review': sum(quote['payload']['review_status'] == 'needs_review' for quote in manifest['quotes']),
    }


def main():
    parser = argparse.ArgumentParser(description='通过本地 ERP 导入商品与供应商资料；不覆盖已有数据')
    parser.add_argument('--products', type=Path, required=True)
    parser.add_argument('--suppliers', type=Path, required=True)
    parser.add_argument('--price-unit', choices=['unknown', 'cents', 'dollars'], default='unknown')
    parser.add_argument('--credentials-file', type=Path, default=ROOT / '.local/admin-credentials.txt')
    parser.add_argument('--base-url', default='http://127.0.0.1:5173')
    parser.add_argument('--check', action='store_true', help='仅核对文件与关联，不连接 API')
    args = parser.parse_args()
    target = urlsplit(args.base_url)
    if target.scheme != 'http' or target.hostname not in {'127.0.0.1', 'localhost'} or target.username or target.password:
        raise SystemExit('此导入脚本仅允许通过 HTTP 连接本机 ERP。')
    rows, manifest = load_inputs(args.products, args.suppliers)
    print(f"资料核对通过：{len(rows)} 商品，{len(manifest['suppliers'])} 供应商，{len(manifest['quotes'])} 报价。")
    if args.check:
        return
    with httpx.Client(base_url=args.base_url, timeout=90, headers={
        'Origin': args.base_url.rstrip('/'), 'X-Requested-With': 'SJLERP',
    }) as client:
        auth = call(client, 'POST', '/auth/login', json=credentials(args.credentials_file))
        client.headers['X-CSRF-Token'] = auth['csrf_token']
        try:
            required = {'products.manage', 'suppliers.manage', 'quotes.manage', 'quotes.view', 'costs.view'}
            if not required.issubset(auth['user']['permissions']):
                raise RuntimeError('当前账号缺少本次商品、供应商或报价管理权限。')
            result = import_data(client, args, manifest)
            print(json.dumps(result, ensure_ascii=False))
            receipt_dir = ROOT / '.local/imports'
            receipt_dir.mkdir(parents=True, exist_ok=True)
            receipt = receipt_dir / ('catalog-receipt-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
            with receipt.open('x') as stream:
                receipt.chmod(0o600)
                json.dump({'created_at': datetime.now(timezone.utc).isoformat(), **result}, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
        finally:
            try:
                call(client, 'POST', '/auth/logout')
            except (RuntimeError, httpx.HTTPError):
                pass


if __name__ == '__main__':
    main()
