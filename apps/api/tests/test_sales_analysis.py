from decimal import Decimal

from conftest import login
from test_ad_daily import daily, daily_file
from test_report_parsers import sale, sales_file, ad, ads_file
from test_reports import preview, confirm


def cost(c, h, sku='SKU-A', **changes):
    response = c.post('/api/v1/sales-analysis/costs', headers=h, json={
        'sku': sku, 'effective_from': '2000-01-01', 'product_cost': '1.25', 'inbound_fee': '0.1',
        'fba_fee': '2.5', 'commission_rate': '.15', 'source': '合成测试费用', **changes})
    assert response.status_code == 200, response.text
    return response.json()


def imported(system, rows, kind='sales', h=None, store=None):
    content = sales_file(rows) if kind == 'sales' else daily_file(rows)
    p, h = preview(system, content, kind, headers=h, store=store)
    r = confirm(system['client'], p, h)
    assert r.status_code == 200, r.text
    return h


def analysis(c, h, **params):
    r = c.get('/api/v1/sales-analysis', headers=h, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_formula_uses_line_sales_minus_discount_not_shipping_or_quantity(system):
    c = system['client']
    h = imported(system, [sale(**{'item-price': '30', 'item-promotion-discount': '2', 'shipping-price': '10', 'gift-wrap-price': '5'})])
    imported(system, [daily(日期='2025-09-26', 花费=8)], 'ads', h)
    cost(c, h)
    r = analysis(c, h)['items'][0]
    assert r['quantity'] == 2 and r['sales'] == '28.00'
    assert r['product_cost'] == '2.70' and r['fba_fee'] == '5.00' and r['commission'] == '4.20'
    assert r['sales_profit'] == '16.10' and r['actual_profit'] == '8.10'
    assert r['sales_profit_rate'] == '0.575000' and r['actual_profit_rate'] == '0.289286'
    assert r['issues'] == []


def test_exact_skus_multiple_stores_ad_only_and_all_pages_totals(system):
    c = system['client']
    h = imported(system, [sale()])
    imported(system, [sale(**{'item-price': '40'})], h=h, store=system['ids']['b'])
    imported(system, [daily(日期='2025-09-26', 花费=3), daily(日期='2025-09-26', 广告SKU='AD-ONLY', 花费=4)], 'ads', h)
    imported(system, [daily(日期='2025-09-26', 花费=5)], 'ads', h, system['ids']['b'])
    cost(c, h)
    result = analysis(c, h, limit=1)
    assert len(result['items']) == 1 and result['total'] == 3
    assert result['totals']['quantity'] == 4 and result['totals']['sales'] == '59.98'
    assert result['totals']['ad_spend'] == '12.00'
    assert result['totals']['product_cost'] == '5.40' and result['totals']['fba_fee'] == '10.00'
    assert result['totals']['commission'] == '9.00'
    assert result['totals']['actual_profit'] == '23.58'
    assert result['totals']['actual_profit_rate'] == '0.393131'
    only = analysis(c, h, sku='AD-ONLY')['items'][0]
    assert only['sales'] == '0.00' and only['actual_profit'] == '-4.00' and only['actual_profit_rate'] == '0.000000'
    options = c.get('/api/v1/sales-analysis/suggestions', headers=h).json()['items']
    assert options == ['AD-ONLY', 'SKU-A']


def test_missing_cost_or_ad_data_stays_unknown_and_zero_cost_is_valid(system):
    c = system['client']
    h = imported(system, [sale()])
    r = analysis(c, h)
    assert r['items'][0]['product_cost'] is None and r['items'][0]['ad_spend'] is None
    assert r['totals']['actual_profit'] is None and r['totals']['incomplete_rows'] == 1
    cost(c, h, product_cost='0', inbound_fee='0', fba_fee='0')
    r = analysis(c, h)['items'][0]
    assert r['product_cost'] == '0.00' and r['sales_profit'] == '16.98' and r['actual_profit'] is None
    imported(system, [daily(日期='2025-09-26', 广告SKU='OTHER', 花费=0)], 'ads', h)
    assert analysis(c, h, sku='SKU-A')['items'][0]['ad_spend'] == '0.00'


def test_dated_rates_store_override_and_missing_values_do_not_fall_back(system):
    c = system['client']
    h = imported(system, [sale(), sale(**{'amazon-order-id': 'SECOND', 'purchase-date': '2025-09-27T00:00:00Z', 'last-updated-date': '2025-09-28T00:00:00Z'})])
    cost(c, h, product_cost='1', inbound_fee='0', fba_fee='2')
    cost(c, h, effective_from='2025-09-27', product_cost='2', inbound_fee='0', fba_fee='3')
    assert analysis(c, h)['items'][0]['product_cost'] == '6.00'
    cost(c, h, store_id=system['ids']['a'], effective_from='2025-09-27', product_cost='5', inbound_fee='0', fba_fee=None)
    r = analysis(c, h)['items'][0]
    assert r['product_cost'] == '12.00' and r['fba_fee'] is None and r['cost_versions'] == 2
    imported(system, [sale(**{'purchase-date': '2025-09-27T00:00:00Z', 'last-updated-date': '2025-09-28T00:00:00Z'})], h=h, store=system['ids']['b'])
    assert analysis(c, h, store_id=system['ids']['b'])['items'][0]['product_cost'] == '4.00'


def test_filters_exclude_cancelled_pending_unsupported_currency_and_period_ads(system):
    c = system['client']
    h = imported(system, [sale(), sale(sku='CANCEL', **{'order-status': 'Cancelled'}), sale(sku='ITEM-CANCEL', **{'item-status': 'Cancelled'}),
        sale(sku='PENDING', **{'order-status': 'Pending', 'item-status': 'Unshipped'}), sale(sku='EUR', currency='EUR')])
    p, _ = preview(system, ads_file([ad(花费=99)]), 'ads', h)
    assert confirm(c, p, h).status_code == 200
    imported(system, [daily(日期='2025-09-26', 花费=1), daily(日期='2025-09-27', 花费=2)], 'ads', h)
    r = analysis(c, h, start_date='2025-09-26', end_date='2025-09-26')
    assert [row['sku'] for row in r['items']] == ['SKU-A']
    assert r['items'][0]['ad_spend'] == '1.00' and r['excluded']['unsupported_sales_rows'] == 1
    assert analysis(c, h, order_scope='non_cancelled')['total'] == 2
    assert analysis(c, h, start_date='2025-09-28')['total'] == 0
    assert c.get('/api/v1/sales-analysis?start_date=2025-09-27&end_date=2025-09-26', headers=h).status_code == 422


def test_permissions_scope_and_no_cost_leaks(system):
    c = system['client']
    h = imported(system, [sale()])
    cost(c, h, store_id=system['ids']['a'])
    cost(c, h)
    fin = login(c, 'finance')
    assert analysis(c, fin)['total'] == 0
    assert analysis(c, fin, store_id=system['ids']['a'])['total'] == 0
    assert c.get('/api/v1/sales-analysis/suggestions', headers=fin).json()['items'] == []
    assert c.get('/api/v1/sales-analysis/costs', headers=fin).json()['total'] == 1
    assert c.get('/api/v1/sales-analysis/costs', headers=fin, params={'store_id': system['ids']['a']}).status_code == 404
    payload = {'sku': 'SKU-A', 'effective_from': '2000-01-01'}
    assert c.post('/api/v1/sales-analysis/costs', headers=fin, json=payload).status_code == 403
    assert c.post('/api/v1/sales-analysis/costs', headers=fin, json={**payload, 'store_id': system['ids']['a']}).status_code == 404
    cost(c, fin, store_id=system['ids']['b'])
    op = login(c, 'operator')
    for endpoint in ['', '/costs', '/suggestions']:
        assert c.get('/api/v1/sales-analysis' + endpoint, headers=op).status_code == 403
    assert c.get('/api/v1/sales-records', headers=op).status_code == 200


def test_cost_validation_revision_and_precision(system):
    c = system['client']; h = login(c)
    saved = cost(c, h, product_cost='0.962123326')
    assert Decimal(str(saved['product_cost'])) == Decimal('0.962123326')
    payload = {k: v for k, v in saved.items() if k != 'id'}
    assert c.post('/api/v1/sales-analysis/costs', headers=h, json={**payload, 'revision': 0}).status_code == 409
    assert c.post('/api/v1/sales-analysis/costs', headers=h, json={**payload, 'fba_fee': '-1'}).status_code == 422
    assert c.post('/api/v1/sales-analysis/costs', headers=h, json={**payload, 'commission_rate': '1.1'}).status_code == 422
    changed = c.post('/api/v1/sales-analysis/costs', headers=h, json={**payload, 'source': '修订'}).json()
    assert changed['revision'] == 2
    assert c.post('/api/v1/sales-analysis/costs', headers=h, json=payload).status_code == 409
    large = cost(c, h, sku='PRECISE', product_cost='999999998.999999999')
    assert large['product_cost'] == '999999998.999999999'


def test_missing_sales_amount_and_rounding_totals(system):
    c = system['client']
    h = imported(system, [sale(), sale(**{'amazon-order-id': 'MISSING', 'item-price': ''})])
    cost(c, h)
    r = analysis(c, h)
    assert r['items'][0]['sales'] is None and r['totals']['sales'] is None
    assert r['items'][0]['commission'] is None and r['items'][0]['product_cost'] == '5.40'


def test_total_margin_is_weighted_and_sku_search_is_literal(system):
    c = system['client']
    h = imported(system, [sale(sku='SKU_%', **{'item-price': '10'}), sale(sku='SKU-B', **{'item-price': '100'})])
    imported(system, [daily(日期='2025-09-26', 广告SKU='SKU_%', 花费=10), daily(日期='2025-09-26', 广告SKU='SKU-B', 花费=0)], 'ads', h)
    cost(c, h, sku='SKU_%', product_cost='0', inbound_fee='0', fba_fee='0')
    cost(c, h, sku='SKU-B', product_cost='0', inbound_fee='0', fba_fee='0')
    r = analysis(c, h)
    assert r['totals']['actual_profit'] == '83.50'
    assert r['totals']['actual_profit_rate'] == '0.759091'
    assert analysis(c, h, q='_%')['total'] == 1
    assert analysis(c, h, sku='SKU')['total'] == 0


def test_postgres_concurrent_cost_create_is_not_lost(system):
    import pytest
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
            return separate.post('/api/v1/sales-analysis/costs', headers=h,
                json={'sku': 'CONCURRENT', 'store_id': system['ids']['a'], 'effective_from': '2000-01-01'}).status_code
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(create, range(2))) == [200, 409]


def test_size_aliases_merge_sales_ads_costs_and_search_but_keep_colors(system):
    c = system['client']
    h = imported(system, [sale(sku='CMBQ-L-250S'), sale(sku='CMBQ-M-250S'), sale(sku='CMBQ-XXL-250S'),
        sale(sku='gfss-0210-200-g'), sale(sku='gfss-0210-200-s')])
    imported(system, [daily(日期='2025-09-26', 广告SKU='CMBQ-XL-250S', 花费=3), daily(日期='2025-09-26', 广告SKU='CMBQ-M-250S', 花费=4)], 'ads', h)
    saved = cost(c, h, sku='CMBQ-XXXL-250S')
    assert saved['sku'] == 'CMBQ-L-250S'
    r = analysis(c, h)
    assert r['total'] == 3
    merged = analysis(c, h, sku='CMBQ-M-250S')['items'][0]
    assert merged['sku'] == 'CMBQ-L-250S' and merged['quantity'] == 6
    assert merged['sales'] == '59.94' and merged['ad_spend'] == '7.00' and merged['product_cost'] == '8.10'
    assert len(merged['source_skus']) == 4
    options = c.get('/api/v1/sales-analysis/suggestions?q=CMBQ-XXL-250S', headers=h).json()['items']
    assert options == ['CMBQ-L-250S']


def test_explicit_currency_conversion_applies_to_sales_and_ads(system):
    c = system['client']
    h = imported(system, [sale(currency='CAD', **{'item-price': '27.2'}),
        sale(currency='MXN', **{'amazon-order-id': 'MX', 'item-price': '176.6'})])
    imported(system, [daily(日期='2025-09-26', 货币='CAD', 花费=6.8),
        daily(日期='2025-09-26', 货币='MXN', 花费=17.66, 广告活动名称='MX')], 'ads', h)
    cost(c, h)
    r = analysis(c, h)['items'][0]
    assert r['sales'] == '30.00' and r['ad_spend'] == '6.00' and r['actual_profit'] == '4.10'
    r = analysis(c, h, cad_per_usd='2.72')['items'][0]
    assert r['sales'] == '20.00' and r['ad_spend'] == '3.50' and r['actual_profit'] == '-1.90'
    assert c.get('/api/v1/sales-analysis?cad_per_usd=0', headers=h).status_code == 422
