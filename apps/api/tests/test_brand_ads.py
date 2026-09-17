from decimal import Decimal

import pytest
from fastapi import HTTPException

from conftest import login
from test_ad_daily import daily, daily_file
from test_report_parsers import ads_file, sale
from test_reports import preview, confirm
from test_sales_analysis import analysis, cost, imported
from app.reports.parsers import parse_report

ZH = ['日期', '广告组合名称', '货币', '广告活动名称', '费用类型', '国家/地区',
      '展示量', '点击量', '花费', '14天总销售额', '14天总订单数(#)', '14天总销售量(#)']
EN = ['Date', 'Portfolio name', 'Currency', 'Campaign Name', 'Cost type', 'Country',
      'Impressions', 'Clicks', 'Spend', '14 Day Total Sales ', '14 Day Total Orders (#)', '14 Day Total Units (#)']


def brand(**changes):
    return dict(zip(ZH, ['2025-09-26', '组合', 'USD', '品牌活动', 'VCPM', '美国', 1000, 10, 10, 50, 2, 3])) | changes


def brand_file(rows, english=False):
    if english:
        return ads_file([{en: row[zh] for zh, en in zip(ZH, EN)} for row in rows], headers=EN)
    return ads_file(rows, headers=ZH)


def configure(system, headers, items=None, **changes):
    return system['client'].put('/api/v1/brand-ad-campaigns', headers=headers, json={
        'store_id': system['ids']['a'], 'campaign': '品牌活动', 'revision': 0,
        'allocations': items if items is not None else [{'sku': 'SKU-A', 'percentage': '60'}, {'sku': 'SKU-B', 'percentage': '40'}], **changes})


def test_brand_headers_identity_and_window_are_distinct():
    zh = parse_report('ads', brand_file([brand()]))
    en = parse_report('ads', brand_file([brand()], True))
    assert zh == en and not zh['errors']
    row = zh['rows'][0]
    assert row['data']['ad_type'] == 'sponsored_brands' and row['data']['attribution_days'] == 14
    assert row['data']['sku'] == row['data']['ad_group'] == ''
    assert row['data']['attributed_sales'] == '50.0000'
    last = parse_report('ads', brand_file([brand(), brand(花费=12, 费用类型='CPC')]))
    assert last['duplicate_count'] == 1 and last['rows'][0]['data']['spend'] == '12.0000'
    assert parse_report('ads', brand_file([brand(广告活动名称='')]))['errors']
    assert parse_report('ads', brand_file([brand(花费=-1)]))['errors']
    with pytest.raises(HTTPException):
        parse_report('ads', ads_file([brand()], headers=[*ZH, 'Campaign Name']))
    with pytest.raises(HTTPException):
        parse_report('ads', ads_file([brand()], headers=[h.replace('14天', '7天') for h in ZH]))


def test_brand_import_overwrite_scope_type_summary_and_config_persistence(system):
    c = system['client']
    first, h = preview(system, brand_file([brand()], True), 'ads')
    assert confirm(c, first, h).json()['result']['created'] == 1
    assert configure(system, h).status_code == 200
    same, _ = preview(system, brand_file([brand()]), 'ads', h)
    assert confirm(c, same, h).json()['result']['skipped'] == 1
    changed, _ = preview(system, brand_file([brand(花费=12)]), 'ads', h)
    assert confirm(c, changed, h).json()['result']['updated'] == 1
    sp, _ = preview(system, daily_file([daily(日期='2025-09-26', 广告活动名称='品牌活动')]), 'ads', h)
    assert confirm(c, sp, h).json()['result']['created'] == 1
    other, _ = preview(system, brand_file([brand()]), 'ads', h, store=system['ids']['b'])
    assert confirm(c, other, h).json()['result']['created'] == 1
    assert c.get('/api/v1/ad-records?ad_type=sponsored_brands', headers=h).json()['total'] == 2
    groups = c.get('/api/v1/ad-records/summary', headers=h).json()['groups']
    assert {(g['ad_type'], g['attribution_days'], g['spend']) for g in groups} == {
        ('sponsored_brands', 14, '22.0000'), ('sponsored_products', 7, '3.0000')}
    mappings = c.get('/api/v1/brand-ad-campaigns', headers=h).json()['items']
    assert len(mappings) == 2 and sum(len(item['allocations']) for item in mappings) == 2
    assert c.get('/api/v1/ad-records/suggestions?ad_type=sponsored_brands', headers=h).json()['items'] == []
    op = login(c, 'operator')
    assert c.get('/api/v1/brand-ad-campaigns', headers=op).json()['total'] == 1
    assert configure(system, op, store_id=system['ids']['b']).status_code == 404
    assert c.get('/api/v1/brand-ad-campaigns/products', headers=op, params={'store_id': system['ids']['b']}).status_code == 404


def test_allocation_validation_revision_and_aliases(system):
    h = login(system['client'])
    for items in [[], [{'sku': 'SKU-A', 'percentage': '90'}], [{'sku': '', 'percentage': '100'}],
                  [{'sku': 'SKU-A', 'percentage': '-1'}, {'sku': 'SKU-B', 'percentage': '101'}],
                  [{'sku': 'CMBQ-M-250S', 'percentage': '50'}, {'sku': 'CMBQ-L-250S', 'percentage': '50'}],
                  [{'sku': 'SKU-A', 'percentage': 'NaN'}]]:
        assert configure(system, h, items).status_code == 422
    r = configure(system, h)
    assert r.status_code == 200 and r.json()['revision'] == 1
    assert configure(system, h).status_code == 409
    r = configure(system, h, [{'sku': 'CMBQ-M-250S', 'percentage': '100'}], revision=1)
    assert r.status_code == 200 and r.json()['allocations'][0]['sku'] == 'CMBQ-L-250S'


def test_brand_allocation_profit_missing_mapping_filters_and_recalculation(system):
    c = system['client']
    h = imported(system, [sale()])
    cost(c, h)
    p, _ = preview(system, brand_file([brand()]), 'ads', h)
    assert confirm(c, p, h).status_code == 200
    missing = analysis(c, h)
    assert missing['items'][0]['ad_spend'] is None and missing['totals']['actual_profit'] is None
    assert missing['excluded']['unallocated_brand_campaigns'][0]['spend'] == '10.0000'
    assert configure(system, h).status_code == 200
    result = analysis(c, h)
    assert result['totals']['ad_spend'] == '10.00'
    assert {row['sku']: row['ad_spend'] for row in result['items']} == {'SKU-A': '6.00', 'SKU-B': '4.00'}
    assert analysis(c, h, sku='SKU-B')['items'][0]['actual_profit'] == '-4.00'
    assert analysis(c, h, q='SKU-B')['totals']['ad_spend'] == '4.00'
    assert c.get('/api/v1/sales-analysis/suggestions', headers=h).json()['items'] == ['SKU-A', 'SKU-B']
    assert analysis(c, h, start_date='2025-09-27')['total'] == 0
    assert configure(system, h, [{'sku': 'SKU-A', 'percentage': 100}], revision=1).status_code == 200
    assert analysis(c, h)['items'][0]['ad_spend'] == '10.00'
    assert c.get('/api/v1/ad-records', headers=h).json()['items'][0]['spend'] == '10.0000'


def test_brand_rounding_conserves_spend_and_currency_conversion(system):
    c = system['client']
    p, h = preview(system, brand_file([brand(货币='CAD', 花费=0.068)]), 'ads')
    assert confirm(c, p, h).status_code == 200
    assert configure(system, h, [{'sku': 'A', 'percentage': '33.3333'}, {'sku': 'B', 'percentage': '33.3333'},
        {'sku': 'C', 'percentage': '33.3334'}]).status_code == 200
    result = analysis(c, h)
    assert result['totals']['ad_spend'] == '0.05'
    assert sum(Decimal(row['ad_spend']) for row in result['items']) == Decimal('.05')
    for row in result['items']:
        assert analysis(c, h, sku=row['sku'])['totals']['ad_spend'] == row['ad_spend']


def test_postgres_concurrent_allocation_creation(system):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi.testclient import TestClient
    if system['app'].state.database.engine.dialect.name != 'postgresql':
        pytest.skip('PostgreSQL row locking')
    c = system['client']; h = login(c)
    gate = Barrier(2)
    def create(_):
        with TestClient(system['app']) as separate:
            separate.cookies.update(c.cookies)
            gate.wait()
            return separate.put('/api/v1/brand-ad-campaigns', headers=h, json={
                'store_id': system['ids']['a'], 'campaign': '同一品牌活动', 'revision': 0,
                'allocations': [{'sku': 'SKU-A', 'percentage': 100}]}).status_code
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(create, range(2))) == [200, 409]


def test_configured_products_show_in_upload_and_records_without_changing_source(system):
    from app.models import Product
    from app.reports.models import AdRecord, ReportImport
    from sqlalchemy import select
    c = system['client']; h = login(c)
    with system['app'].state.database.session() as db:
        db.add(Product(internal_sku='SKU-A', name='商品 A', asin='B000000001'))
        db.commit()
    assert configure(system, h).status_code == 200
    batch, _ = preview(system, brand_file([brand()], True), 'ads', h)
    path = f"/api/v1/report-imports/{batch['id']}/rows"
    rows = c.get(path, headers=h).json()['items']
    products = rows[0]['data']['allocation_products']
    assert products == [
        {'sku': 'SKU-A', 'percentage': '60', 'name': '商品 A', 'asins': ['B000000001']},
        {'sku': 'SKU-B', 'percentage': '40', 'name': '', 'asins': []}]
    assert rows[0]['data']['sku'] == ''
    assert confirm(c, batch, h).status_code == 200
    assert c.get('/api/v1/ad-records', headers=h).json()['items'][0]['allocation_products'] == products
    assert c.get(path, headers=h).json()['items'][0]['data']['allocation_products'] == products
    assert configure(system, h, [{'sku': 'SKU-A', 'percentage': '100'}], revision=1).status_code == 200
    assert len(c.get(path, headers=h).json()['items'][0]['data']['allocation_products']) == 1
    assert c.get('/api/v1/ad-records', headers=h).json()['items'][0]['allocation_products'][0]['percentage'] == '100'
    repeated, _ = preview(system, brand_file([brand()]), 'ads', h)
    assert repeated['counts']['skip'] == 1
    repeated_rows = c.get(f"/api/v1/report-imports/{repeated['id']}/rows", headers=h).json()['items']
    assert repeated_rows[0]['data']['allocation_products'][0]['percentage'] == '100'
    assert confirm(c, repeated, h).status_code == 200
    with system['app'].state.database.session() as db:
        assert 'allocation_products' not in db.scalar(select(AdRecord)).data
        assert 'allocation_products' not in db.get(ReportImport, batch['id']).parsed_rows[0]['data']


def test_product_resolution_uses_store_mapping_and_store_scoped_asin_fallback(system):
    c = system['client']
    h = imported(system, [sale(sku='SKU-A', asin='BSTOREAAAA')])
    imported(system, [sale(sku='SKU-A', asin='BSTOREBBBB')], h=h, store=system['ids']['b'])
    assert configure(system, h, [{'sku': 'SKU-A', 'percentage': 100}]).status_code == 200
    for store, expected in [(system['ids']['a'], ['BSTOREAAAA']), (system['ids']['b'], None)]:
        p, _ = preview(system, brand_file([brand()]), 'ads', h, store=store)
        resolved = c.get(f"/api/v1/report-imports/{p['id']}/rows", headers=h).json()['items'][0]['data']['allocation_products']
        assert (resolved[0]['asins'] if resolved else None) == expected
    operator = login(c, 'operator')
    assert c.get(f"/api/v1/report-imports/{p['id']}/rows", headers=operator).status_code == 404
