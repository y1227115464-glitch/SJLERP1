from datetime import date, timedelta

import pytest

from conftest import login
from test_sales_analysis import analysis, cost, imported
from test_report_parsers import sale


def fee(c, h, **changes):
    result = c.post('/api/v1/sales-analysis/fba-fees', headers=h, json={
        'sku': 'SKU-A', 'effective_from': '2025-09-26', 'low_price_fee': '2', 'high_price_fee': '4', **changes})
    assert result.status_code == 200, result.text
    return result.json()


def order(identifier, day='2025-09-26', price='9.99', quantity='1', **changes):
    return sale(**{'amazon-order-id': identifier, 'purchase-date': day + 'T00:00:00Z',
        'last-updated-date': (date.fromisoformat(day) + timedelta(days=1)).isoformat() + 'T00:00:00Z',
        'item-price': price, 'quantity': quantity, **changes})


def catalog(c, h, **params):
    result = c.get('/api/v1/sales-analysis/fba-fees/catalog', headers=h, params={'as_of': '2025-09-26', **params})
    assert result.status_code == 200, result.text
    return result.json()


def test_price_tiers_use_unrounded_pre_discount_unit_price_per_order(system):
    c = system['client']
    h = imported(system, [order('LOW-MULTI', price='19.98', quantity='2'),
        order('HIGH-DISCOUNT', price='10', **{'item-promotion-discount': '8', 'shipping-price': '4', 'item-tax': '1'}),
        order('JUST-OVER', price='9.9901'), order('BELOW', price='9.98')])
    cost(c, h)
    fee(c, h)
    row = analysis(c, h)['items'][0]
    assert row['quantity'] == 5 and row['fba_fee'] == '14.00'
    assert row['product_cost'] == '6.75' and row['sales'] == '41.95'
    assert analysis(c, h)['totals']['fba_fee'] == '14.00'


def test_effective_intervals_backdated_insert_and_legacy_fallback(system):
    c = system['client']
    h = imported(system, [order(str(day), day=f'2025-09-{day}') for day in range(25, 29)])
    cost(c, h)
    old_cost = c.get('/api/v1/sales-analysis/costs', headers=h).json()['items']
    fee(c, h)
    fee(c, h, effective_from='2025-09-28', low_price_fee='4')
    middle = fee(c, h, effective_from='2025-09-27', low_price_fee='3')
    assert middle['effective_until'] == '2025-09-27'
    r = analysis(c, h)['items'][0]
    assert r['fba_fee'] == '11.50' and r['product_cost'] == '5.40'
    history = c.get('/api/v1/sales-analysis/fba-fees?sku=SKU-A&limit=1&offset=2', headers=h).json()
    assert history['total'] == 3 and history['items'][0]['effective_until'] == '2025-09-26'
    # UTC midnight orders fall on the previous PDT date; fee versions still use UTC.
    assert analysis(c, h, end_date='2025-09-24')['items'][0]['fba_fee'] == '2.50'
    assert analysis(c, h, end_date='2025-09-25')['items'][0]['fba_fee'] == '4.50'
    fee(c, h, effective_from='2025-09-27', low_price_fee='3.5', revision=middle['revision'])
    assert analysis(c, h)['items'][0]['fba_fee'] == '12.00'
    assert c.get('/api/v1/sales-analysis/costs', headers=h).json()['items'] == old_cost


def test_store_versions_override_common_independently_of_product_cost(system):
    c = system['client']
    h = imported(system, [order('FIRST'), order('SECOND', day='2025-09-27')])
    cost(c, h, store_id=system['ids']['a'], fba_fee='9')
    fee(c, h)
    fee(c, h, effective_from='2025-09-27', store_id=system['ids']['a'], low_price_fee='3')
    # A newer common version must not override a store-specific version.
    fee(c, h, effective_from='2025-09-27', low_price_fee='6')
    assert analysis(c, h)['items'][0]['fba_fee'] == '5.00'
    imported(system, [order('OTHER', day='2025-09-27')], h=h, store=system['ids']['b'])
    assert analysis(c, h, store_id=system['ids']['b'])['items'][0]['fba_fee'] == '6.00'
    active = catalog(c, h, store_id=system['ids']['a'], as_of='2025-09-27')['items'][0]['current']
    assert active['store_id'] == system['ids']['a'] and active['low_price_fee'] == '3.000000000'


def test_missing_price_cannot_select_a_tier_and_zero_quantity_has_no_fee(system):
    c = system['client']
    h = imported(system, [order('UNKNOWN', price=''), order('KNOWN')])
    fee(c, h)
    row = analysis(c, h)['items'][0]
    assert row['fba_fee'] is None
    assert '缺少商品金额，无法判断物流费档位' in row['issues']
    assert analysis(c, h)['totals']['fba_fee'] is None
    imported(system, [order('ZERO', sku='ZERO', quantity='0', price='')], h=h)
    fee(c, h, sku='ZERO', low_price_fee='0', high_price_fee='0')
    assert analysis(c, h, sku='ZERO')['items'][0]['fba_fee'] == '0.00'


def test_non_usd_price_threshold_uses_analysis_exchange_rate(system):
    c = system['client']
    h = imported(system, [order('EXACT', currency='CAD', price='13.5864'), order('HIGH', currency='CAD', price='13.6')])
    fee(c, h, low_price_fee='3', high_price_fee='5')
    assert analysis(c, h)['items'][0]['fba_fee'] == '8.00'
    assert analysis(c, h, cad_per_usd='2.72')['items'][0]['fba_fee'] == '6.00'


def test_fba_matches_exact_source_sku_before_analysis_size_grouping(system):
    c = system['client']
    h = imported(system, [order('L', sku='CMBQ-L-250S'), order('M', sku='CMBQ-M-250S')])
    fee(c, h, sku='CMBQ-L-250S', low_price_fee='2')
    fee(c, h, sku='CMBQ-M-250S', low_price_fee='3')
    rows = analysis(c, h)['items']
    assert len(rows) == 1 and rows[0]['fba_fee'] == '5.00'
    assert catalog(c, h, q='CMBQ-')['total'] == 2


def test_catalog_includes_unpriced_products_and_future_versions(system):
    from app.models import Product
    c = system['client']; h = login(c)
    with system['app'].state.database.session() as db:
        db.add(Product(internal_sku='NEW_%', name='新商品'))
        db.commit()
    items = catalog(c, h, q='_%')['items']
    assert [item['sku'] for item in items] == ['NEW_%']
    assert items[0]['current'] is None and items[0]['legacy_fee'] is None
    cost(c, h, sku='OLD')
    assert catalog(c, h, q='OLD')['items'][0]['legacy_fee'] == '2.500000000'
    fee(c, h, sku='NEW_%', effective_from='2025-10-01', low_price_fee='0')
    item = catalog(c, h, q='_%')['items'][0]
    assert item['current'] is None and item['scheduled_count'] == 1 and item['version_count'] == 1
    assert catalog(c, h, q='_%', as_of='2025-10-01')['items'][0]['current']['low_price_fee'] == '0.000000000'
    assert catalog(c, h, limit=1)['total'] == 2


def test_fba_validation_revision_scope_and_no_cost_leaks(system):
    c = system['client']; h = login(c)
    saved = fee(c, h, low_price_fee='0.962123326')
    payload = {key: value for key, value in saved.items() if key not in {'id', 'effective_until'}}
    assert saved['low_price_fee'] == '0.962123326'
    endpoint = '/api/v1/sales-analysis/fba-fees'
    for change in [{'low_price_fee': None}, {'low_price_fee': '-1'}, {'high_price_fee': 'NaN'}, {'sku': '   '}]:
        assert c.post(endpoint, headers=h, json={**payload, **change}).status_code == 422
    assert c.post(endpoint, headers=h, json={**payload, 'revision': 0}).status_code == 409
    edited = c.post(endpoint, headers=h, json={**payload, 'high_price_fee': '6'}).json()
    assert edited['revision'] == 2
    assert c.post(endpoint, headers=h, json=payload).status_code == 409
    fee(c, h, sku='PRIVATE-A', store_id=system['ids']['a'])
    fin = login(c, 'finance')
    assert c.post(endpoint, headers=fin, json=payload).status_code == 403
    assert c.post(endpoint, headers=fin, json={**payload, 'store_id': system['ids']['a']}).status_code == 404
    fee(c, fin, store_id=system['ids']['b'])
    assert c.get(endpoint, headers=fin, params={'store_id': system['ids']['a']}).status_code == 404
    assert catalog(c, fin, q='PRIVATE-A')['total'] == 0
    assert c.get(endpoint, headers=fin).json()['total'] == 2
    assert c.post(endpoint, headers={}, json=payload).status_code == 403
    op = login(c, 'operator')
    assert c.get(endpoint, headers=op).status_code == 403
    assert c.get(endpoint + '/catalog', headers=op).status_code == 403
    assert c.post(endpoint, headers=op, json=payload).status_code == 403


def test_postgres_concurrent_fee_create_is_not_lost(system):
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
            return separate.post('/api/v1/sales-analysis/fba-fees', headers=h,
                json={'sku': 'CONCURRENT', 'store_id': system['ids']['a'], 'effective_from': '2025-09-26',
                      'low_price_fee': '2', 'high_price_fee': '4'}).status_code
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(create, range(2))) == [200, 409]


def remove_fee(c, h, row):
    return c.request('DELETE', f"/api/v1/sales-analysis/fba-fees/{row['id']}", headers=h,
                     json={'revision': row['revision']})


def test_delete_fee_rejoins_intervals_and_recalculates_profit(system):
    c = system['client']
    h = imported(system, [order(str(day), day=f'2025-09-{day}') for day in range(26, 29)])
    cost(c, h)
    first = fee(c, h)
    middle = fee(c, h, effective_from='2025-09-27', low_price_fee='3')
    latest = fee(c, h, effective_from='2025-09-28', low_price_fee='4')
    before = analysis(c, h)
    assert before['totals']['fba_fee'] == '9.00'
    assert remove_fee(c, h, middle).status_code == 200
    history = c.get('/api/v1/sales-analysis/fba-fees?sku=SKU-A', headers=h).json()
    assert history['total'] == 2
    assert history['items'][1]['id'] == first['id'] and history['items'][1]['effective_until'] == '2025-09-27'
    assert analysis(c, h)['totals']['fba_fee'] == '8.00'
    assert analysis(c, h)['totals']['sales_profit'] != before['totals']['sales_profit']
    assert remove_fee(c, h, latest).status_code == 200
    assert catalog(c, h, as_of='2025-09-28')['items'][0]['current']['effective_until'] is None
    assert analysis(c, h)['totals']['fba_fee'] == '6.00'
    # No dual-tier version remains: fall back to the original single-tier cost.
    assert remove_fee(c, h, first).status_code == 200
    assert analysis(c, h)['totals']['fba_fee'] == '7.50'
    assert catalog(c, h)['items'][0]['version_count'] == 0
    recreated = fee(c, h)
    assert recreated['id'] != first['id'] and recreated['revision'] == 1
    assert remove_fee(c, h, first).status_code == 404


def test_delete_store_fee_falls_back_to_common_then_missing(system):
    c = system['client']; h = imported(system, [order('FIRST')])
    common = fee(c, h)
    specific = fee(c, h, store_id=system['ids']['a'], low_price_fee='3')
    assert analysis(c, h)['totals']['fba_fee'] == '3.00'
    assert remove_fee(c, h, specific).status_code == 200
    assert analysis(c, h)['totals']['fba_fee'] == '2.00'
    assert remove_fee(c, h, common).status_code == 200
    assert analysis(c, h)['totals']['fba_fee'] is None
    assert analysis(c, h)['totals']['actual_profit'] is None


def test_delete_fee_permissions_csrf_and_stale_revision(system):
    from app.models import AuditLog
    from sqlalchemy import select
    c = system['client']; h = login(c)
    common = fee(c, h)
    a = fee(c, h, store_id=system['ids']['a'])
    b = fee(c, h, store_id=system['ids']['b'])
    updated = fee(c, h, revision=common['revision'], high_price_fee='5')
    assert remove_fee(c, h, common).status_code == 409
    assert remove_fee(c, {}, updated).status_code == 403
    fin = login(c, 'finance')
    assert remove_fee(c, fin, updated).status_code == 403
    assert remove_fee(c, fin, a).status_code == 404
    assert remove_fee(c, fin, b).status_code == 200
    assert remove_fee(c, fin, b).status_code == 404
    op = login(c, 'operator')
    assert remove_fee(c, op, a).status_code == 403
    h = login(c)
    assert remove_fee(c, h, updated).status_code == 200
    with system['app'].state.database.session() as db:
        logs = db.scalars(select(AuditLog).where(AuditLog.action == 'sales.fba_fee.delete')).all()
        assert len(logs) == 2


def test_postgres_concurrent_fee_delete_and_edit(system):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi.testclient import TestClient
    if system['app'].state.database.engine.dialect.name != 'postgresql':
        pytest.skip('PostgreSQL row locking')
    c = system['client']; h = login(c)
    saved = fee(c, h, store_id=system['ids']['a'])
    payload = {key: value for key, value in saved.items() if key not in {'id', 'effective_until'}}
    barrier = Barrier(2)
    def run(action):
        with TestClient(system['app']) as separate:
            separate.cookies.update(c.cookies)
            barrier.wait()
            result = remove_fee(separate, h, saved) if action == 'delete' else separate.post(
                '/api/v1/sales-analysis/fba-fees', headers=h, json={**payload, 'low_price_fee': '7'})
            return result.status_code
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(run, ['delete', 'edit'])) == [200, 409]
