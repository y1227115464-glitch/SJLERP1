from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from conftest import login
from test_report_parsers import sale, sales_file, ad, ads_file


def preview(system, content, kind='sales', headers=None, store=None):
    client = system['client']
    headers = headers or login(client)
    response = client.post('/api/v1/report-imports/preview', headers=headers,
        data={'kind': kind, 'store_id': store or system['ids']['a']},
        files={'file': ('report.txt' if kind == 'sales' else 'report.xlsx', content)})
    assert response.status_code == 201, response.text
    return response.json(), headers


def confirm(client, p, h):
    return client.post(f"/api/v1/report-imports/{p['id']}/confirm", headers=h, json={'verification_token': p['verification_token']})


def test_sales_cross_file_dedup_newer_updates_and_old_or_ambiguous_versions(system):
    c = system['client']
    p, h = preview(system, sales_file([sale(), sale()]))
    assert p['counts']['create'] == 1 and p['duplicate_count'] == 1
    result = confirm(c, p, h)
    assert result.status_code == 200 and result.json()['result']['created'] == 1
    assert confirm(c, p, h).json()['result'] == result.json()['result']
    p, _ = preview(system, sales_file([sale(), sale(**{'amazon-order-id': '222-1234567-1234567'})]), headers=h)
    assert p['counts']['create'] == 1 and p['counts']['skip'] == 1
    assert confirm(c, p, h).status_code == 200
    changed = sale(**{'last-updated-date': '2025-09-28T00:00:00Z', 'order-status': 'Cancelled', 'item-status': 'Cancelled'})
    p, _ = preview(system, sales_file([changed]), headers=h)
    assert p['counts']['update'] == 1
    assert confirm(c, p, h).status_code == 200
    p, _ = preview(system, sales_file([sale()]), headers=h)
    assert p['counts']['skip'] == 1
    assert confirm(c, p, h).status_code == 200
    p, _ = preview(system, sales_file([dict(changed, quantity='5')]), headers=h)
    assert p['counts']['conflict'] == 1 and confirm(c, p, h).status_code == 409
    rows = c.get('/api/v1/sales-records', headers=h).json()
    assert rows['total'] == 2
    amounts = c.get('/api/v1/sales-records/summary', headers=h).json()['groups']
    assert sum(g['rows'] for g in amounts) == 2


def test_ads_exact_period_replaces_and_overlaps_rejected(system):
    c = system['client']
    p, h = preview(system, ads_file([ad()]), 'ads')
    assert confirm(c, p, h).status_code == 200
    p, _ = preview(system, ads_file([ad(花费=5)]), 'ads', h)
    assert p['counts']['update'] == 1 and confirm(c, p, h).status_code == 200
    p, _ = preview(system, ads_file([ad(开始日期='2026-06-15', 结束日期='2026-07-15')]), 'ads', h)
    assert p['counts']['conflict'] == 1 and confirm(c, p, h).status_code == 409
    assert c.get('/api/v1/ad-records?granularity=period', headers=h).json()['total'] == 1
    assert c.get('/api/v1/ad-records/summary?granularity=period', headers=h).json()['groups'][0]['spend'] == '5.0000'


def test_import_is_atomic_scoped_and_preview_change_needs_reconfirmation(system):
    c = system['client']
    p, h = preview(system, sales_file([sale(), sale(sku='BROKEN', quantity='1.5')]))
    assert p['error_count'] == 1 and confirm(c, p, h).status_code == 409
    assert c.get('/api/v1/sales-records', headers=h).json()['total'] == 0
    first, _ = preview(system, sales_file([sale()]), headers=h)
    second, _ = preview(system, sales_file([sale()]), headers=h)
    assert confirm(c, first, h).status_code == 200
    assert confirm(c, second, h).status_code == 409
    refreshed = c.get(f"/api/v1/report-imports/{second['id']}", headers=h).json()
    assert refreshed['counts']['skip'] == 1
    assert confirm(c, refreshed, h).json()['result']['created'] == 0
    other = login(c, 'finance')
    assert c.get(f"/api/v1/report-imports/{first['id']}", headers=other).status_code == 404
    assert confirm(c, first, other).status_code == 404
    assert c.get('/api/v1/sales-records', headers=other).json()['total'] == 0
    assert c.get('/api/v1/sales-records/summary', headers=other).json()['groups'] == []


def test_postgres_concurrent_report_imports_do_not_duplicate(system):
    if system['app'].state.database.engine.dialect.name != 'postgresql':
        pytest.skip('PostgreSQL store locking concurrency')
    c = system['client']
    one, h = preview(system, sales_file([sale()]))
    two, _ = preview(system, sales_file([sale()]), headers=h)
    gate = Barrier(2)
    def run(p):
        with TestClient(system['app']) as separate:
            separate.cookies.update(c.cookies)
            gate.wait()
            return confirm(separate, p, h).status_code
    with ThreadPoolExecutor(2) as pool:
        statuses = list(pool.map(run, [one, two]))
    assert sorted(statuses) == [200, 409]
    assert c.get('/api/v1/sales-records', headers=h).json()['total'] == 1


def test_currency_totals_missing_amounts_dates_and_same_order_different_store(system):
    c = system['client']
    data = sales_file([sale(), sale(sku='SKU-B', currency='CAD', **{'sales-channel': 'Amazon.ca', 'item-price': '5.00'}),
        sale(sku='SKU-C', currency='', **{'order-status': 'Cancelled', 'item-status': 'Cancelled', 'item-price': ''})])
    p, h = preview(system, data)
    assert confirm(c, p, h).status_code == 200
    groups = c.get('/api/v1/sales-records/summary', headers=h).json()['groups']
    amounts = {g['currency']: g for g in groups}
    assert amounts['USD']['net_amount'] == '19.9800'  # Source is line amount, not unit price × 2.
    assert amounts['CAD']['net_amount'] == '5.0000'
    assert amounts[None]['net_amount'] is None and amounts[None]['missing_amount_rows'] == 1
    assert c.get('/api/v1/sales-records?start_date=2025-09-27', headers=h).json()['total'] == 0
    assert c.get('/api/v1/sales-records?start_date=2025-09-27&end_date=2025-09-26', headers=h).status_code == 422
    p, _ = preview(system, sales_file([sale()]), headers=h, store=system['ids']['b'])
    assert p['counts']['create'] == 1 and confirm(c, p, h).status_code == 200
    operator = login(c, 'operator')
    p, _ = preview(system, data, headers=operator)
    assert p['counts']['skip'] == 3 and confirm(c, p, operator).status_code == 200
    assert c.get('/api/v1/sales-records?limit=1', headers=operator).json()['total'] == 3
    assert len(c.get('/api/v1/sales-records?limit=1', headers=operator).json()['items']) == 1


def test_ad_preview_order_formula_atomicity_and_weighted_ratios(system):
    c = system['client']
    old, h = preview(system, ads_file([ad(花费=2)]), 'ads')
    new, _ = preview(system, ads_file([ad(花费=5), ad(广告SKU='SKU-B', 展示量=100, 点击量=0, 花费=0, **{'7天总销售额': 0})]), 'ads', h)
    assert confirm(c, new, h).status_code == 200
    old_now = c.get(f"/api/v1/report-imports/{old['id']}", headers=h).json()
    assert old_now['counts']['conflict'] == 1 and confirm(c, old_now, h).status_code == 409
    groups = c.get('/api/v1/ad-records/summary?granularity=period', headers=h).json()['groups']
    assert groups[0]['ctr'] == '0.009091' and groups[0]['cpc'] == '0.500000'
    assert c.get('/api/v1/ad-records?granularity=period&start_date=2026-06-15', headers=h).json()['total'] == 0
    p, _ = preview(system, ads_file([ad()], formula=True), 'ads', h)
    assert p['error_count'] == 1 and confirm(c, p, h).status_code == 409


def test_permission_revocation_and_warehouse_role(system):
    from app.models import User
    c = system['client']
    operator = login(c, 'operator')
    p, _ = preview(system, sales_file([sale()]), headers=operator)
    with system['app'].state.database.session() as db:
        user = db.get(User, system['ids']['operator'])
        user.stores = []
        db.commit()
    assert confirm(c, p, operator).status_code == 404
    assert c.get(f"/api/v1/report-imports/{p['id']}/rows", headers=operator).status_code == 404
    with system['app'].state.database.session() as db:
        user = db.get(User, system['ids']['operator']); user.role = 'warehouse'; db.commit()
    assert c.get('/api/v1/sales-records', headers=operator).status_code == 403
    assert c.get('/api/v1/ad-records/summary?granularity=period', headers=operator).status_code == 403


def test_newer_identical_ad_confirmation_blocks_old_changed_preview(system):
    c = system['client']
    original, h = preview(system, ads_file([ad(花费=3)]), 'ads')
    assert confirm(c, original, h).status_code == 200
    old, _ = preview(system, ads_file([ad(花费=5)]), 'ads', h)
    newer, _ = preview(system, ads_file([ad(花费=3)]), 'ads', h)
    assert confirm(c, newer, h).json()['result']['skipped'] == 1
    assert confirm(c, old, h).status_code == 409
    assert c.get('/api/v1/ad-records/summary?granularity=period', headers=h).json()['groups'][0]['spend'] == '3.0000'
