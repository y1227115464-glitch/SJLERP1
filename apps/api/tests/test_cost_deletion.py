from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import AuditLog
from conftest import login
from test_fba_fees import fee, order, catalog, remove_fee
from test_sales_analysis import analysis, cost, imported


def remove_cost(c, h, row):
    return c.request('DELETE', f"/api/v1/sales-analysis/costs/{row['id']}", headers=h,
                     json={'revision': row['revision']})


def test_delete_cost_versions_recalculates_costs_commission_and_profit(system):
    c = system['client']
    h = imported(system, [order(str(day), day=f'2025-09-{day}') for day in range(26, 29)])
    first = cost(c, h, product_cost='1', inbound_fee='0', commission_rate='.1')
    middle = cost(c, h, effective_from='2025-09-27', product_cost='2', inbound_fee='0', commission_rate='.2')
    latest = cost(c, h, effective_from='2025-09-28', product_cost='3', inbound_fee='0', commission_rate='.3')
    before = analysis(c, h)['totals']
    assert before['product_cost'] == '6.00'
    assert remove_cost(c, h, middle).status_code == 200
    after = analysis(c, h)['totals']
    assert after['product_cost'] == '5.00' and after['commission'] != before['commission']
    assert after['sales_profit'] != before['sales_profit']
    assert remove_cost(c, h, latest).status_code == 200
    assert analysis(c, h)['totals']['product_cost'] == '3.00'
    assert remove_cost(c, h, first).status_code == 200
    totals = analysis(c, h)['totals']
    assert totals['product_cost'] is None and totals['fba_fee'] is None and totals['sales_profit'] is None
    assert c.get('/api/v1/sales-analysis/costs', headers=h).json()['total'] == 0
    recreated = cost(c, h)
    assert recreated['id'] != first['id']
    assert remove_cost(c, h, first).status_code == 404
    assert analysis(c, h)['totals']['product_cost'] == '4.05'


def test_delete_cost_scope_fallback_and_independent_fba_versions(system):
    c = system['client']; h = imported(system, [order('FIRST')])
    common = cost(c, h)
    specific = cost(c, h, store_id=system['ids']['a'], product_cost='5', commission_rate='.2')
    dual = fee(c, h)
    assert analysis(c, h)['totals']['product_cost'] == '5.10'
    assert remove_cost(c, h, specific).status_code == 200
    assert analysis(c, h)['totals']['product_cost'] == '1.35'
    assert remove_cost(c, h, common).status_code == 200
    assert analysis(c, h)['totals']['product_cost'] is None
    assert analysis(c, h)['totals']['fba_fee'] == '2.00'
    assert catalog(c, h, q='SKU-A')['items'][0]['current']['id'] == dual['id']
    assert remove_fee(c, h, dual).status_code == 200
    assert catalog(c, h, q='SKU-A')['items'][0]['legacy_fee'] is None
    assert analysis(c, h)['totals']['fba_fee'] is None


def test_cost_delete_permissions_revision_csrf_and_audit(system):
    c = system['client']; h = login(c)
    common = cost(c, h)
    a = cost(c, h, store_id=system['ids']['a'])
    b = cost(c, h, store_id=system['ids']['b'])
    updated = cost(c, h, revision=common['revision'], product_cost='6')
    assert remove_cost(c, h, common).status_code == 409
    assert remove_cost(c, {}, updated).status_code == 403
    fin = login(c, 'finance')
    assert remove_cost(c, fin, updated).status_code == 403
    assert remove_cost(c, fin, a).status_code == 404
    assert remove_cost(c, fin, b).status_code == 200
    op = login(c, 'operator')
    assert remove_cost(c, op, a).status_code == 403
    h = login(c)
    assert remove_cost(c, h, updated).status_code == 200
    with system['app'].state.database.session() as db:
        logs = db.scalars(select(AuditLog).where(AuditLog.action == 'sales.cost.delete')).all()
        assert len(logs) == 2
        assert {log.resource_id for log in logs} == {b['id'], updated['id']}


def test_postgres_concurrent_cost_delete_and_edit(system):
    if system['app'].state.database.engine.dialect.name != 'postgresql':
        pytest.skip('PostgreSQL row locking')
    c = system['client']; h = login(c)
    saved = cost(c, h, store_id=system['ids']['a'])
    payload = {key: value for key, value in saved.items() if key != 'id'}
    gate = Barrier(2)
    def run(action):
        with TestClient(system['app']) as separate:
            separate.cookies.update(c.cookies)
            gate.wait()
            result = remove_cost(separate, h, saved) if action == 'delete' else separate.post(
                '/api/v1/sales-analysis/costs', headers=h, json={**payload, 'product_cost': '7'})
            return result.status_code
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(run, ['delete', 'edit'])) == [200, 409]
