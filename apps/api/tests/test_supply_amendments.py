from uuid import uuid4

import pytest

from conftest import login
from test_supply import balance, fixtures, post, purchase, receive, shipment


def amend(client, kind, record, lines, *, status=200, body=None):
    payload = body or {'request_id': str(uuid4()), 'expected_version': record.get('lines_version', '0' * 64),
                       'lines': lines, 'reason': '更正商品数量'}
    response = client.patch(f"/api/v1/{kind}/{record['id']}/lines", headers=login(client), json=payload)
    assert response.status_code == status, response.text
    return response.json(), payload


def test_submitted_purchase_can_change_quantities_and_add_products(system):
    client, headers, product, supplier, _, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier, 20)
    second = post(client, '/products', headers, {'internal_sku': 'ADD', 'name': '追加商品', 'units_per_carton': 1})
    inbound = shipment(system, client, headers, product, target, 8, order=order)
    original_id = order['lines'][0]['id']
    changed, body = amend(client, 'purchase-orders', order, [
        {'product_id': product['id'], 'quantity': 12},
        {'product_id': second['id'], 'quantity': 5, 'unit_price': '2.5000'}])
    assert changed['lines'][0]['id'] == original_id
    assert changed['lines'][0]['unit_price'] == '3.1234'
    assert changed['total_amount'] == '49.9808'
    replay, _ = amend(client, 'purchase-orders', order, [], body=body)
    assert len(replay['lines']) == 2
    amend(client, 'purchase-orders', changed, [
        {'product_id': product['id'], 'quantity': 7}, {'product_id': second['id'], 'quantity': 5}], status=409)
    amend(client, 'purchase-orders', order, body['lines'], status=409)
    headers = login(client)
    post(client, f"/shipments/{inbound['id']}/dispatch", headers, {}, 200)
    receive(client, headers, inbound, 8)
    assert balance(client, target)['quantity'] == 8


def test_supplier_shipment_can_change_products_and_reallocate(system):
    client, headers, product, supplier, _, target = fixtures(system)
    second = post(client, '/products', headers, {'internal_sku': 'OTHER', 'name': '替换商品', 'units_per_carton': 2})
    order = purchase(system, client, headers, product, supplier, 20)
    order, _ = amend(client, 'purchase-orders', order, [
        {'product_id': product['id'], 'quantity': 20}, {'product_id': second['id'], 'quantity': 12, 'unit_price': '1'}])
    headers = login(client)
    record = shipment(system, client, headers, product, target, 10, order=order)
    changed, body = amend(client, 'shipments', record, [
        {'product_id': second['id'], 'quantity': 8, 'units_per_carton': 2}])
    assert changed['lines'][0]['product_id'] == second['id']
    assert '更正商品数量' in changed['events'][-1]['notes']
    replay, _ = amend(client, 'shipments', record, [], body=body)
    assert replay['lines'][0]['id'] == changed['lines'][0]['id']
    detail = client.get(f"/api/v1/purchase-orders/{order['id']}").json()
    assert [line['unallocated_quantity'] for line in detail['lines']] == [20, 4]
    amend(client, 'shipments', changed, [{'product_id': second['id'], 'quantity': 14, 'units_per_carton': 2}], status=409)
    amend(client, 'shipments', changed, [{'product_id': second['id'], 'quantity': 7, 'units_per_carton': 2}], status=422)
    headers = login(client)
    post(client, f"/shipments/{record['id']}/dispatch", headers, {}, 200)
    dispatched = client.get(f"/api/v1/shipments/{record['id']}").json()
    changed, _ = amend(client, 'shipments', dispatched, [{'product_id': second['id'], 'quantity': 10, 'units_per_carton': 2}])
    headers = login(client)
    receive(client, headers, changed, 4)
    partial = client.get(f"/api/v1/shipments/{record['id']}").json()
    amend(client, 'shipments', partial, [{'product_id': product['id'], 'quantity': 5, 'units_per_carton': 1}], status=409)
    amend(client, 'shipments', partial, [{'product_id': second['id'], 'quantity': 2, 'units_per_carton': 2}], status=409)
    completed, _ = amend(client, 'shipments', partial, [{'product_id': second['id'], 'quantity': 4, 'units_per_carton': 2}])
    assert completed['status'] == 'received' and completed['received_at']
    assert balance(client, target)['quantity'] == 4
    assert client.get('/api/v1/inventory/summary').json()['in_transit'] == 0


def test_warehouse_shipment_amendments_correct_reservations_and_dispatch(system):
    client, headers, product, _, source, target = fixtures(system)
    post(client, '/inventory/adjustments', headers, {'request_id': str(uuid4()), 'store_id': system['ids']['a'],
         'warehouse_id': source['id'], 'product_id': product['id'], 'quantity': 20, 'kind': 'opening', 'reason': '期初'})
    record = shipment(system, client, headers, product, target, 10, source=source)
    changed, _ = amend(client, 'shipments', record, [{'product_id': product['id'], 'quantity': 12, 'units_per_carton': 1}])
    assert balance(client, source)['reserved'] == 12
    amend(client, 'shipments', changed, [{'product_id': product['id'], 'quantity': 21, 'units_per_carton': 1}], status=409)
    assert balance(client, source)['reserved'] == 12
    headers = login(client)
    post(client, f"/shipments/{record['id']}/dispatch", headers, {}, 200)
    dispatched = client.get(f"/api/v1/shipments/{record['id']}").json()
    changed, body = amend(client, 'shipments', dispatched, [{'product_id': product['id'], 'quantity': 7, 'units_per_carton': 1}])
    amend(client, 'shipments', dispatched, [], body=body)
    assert balance(client, source)['quantity'] == 13
    assert balance(client, source)['reserved'] == 0
    assert client.get('/api/v1/inventory/summary').json()['in_transit'] == 7


def test_purchase_received_and_cancelled_floors_and_invalid_edits(system):
    client, headers, product, supplier, _, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier, 10)
    record = shipment(system, client, headers, product, target, 4, order=order)
    order = post(client, f"/purchase-orders/{order['id']}/cancel", headers, {}, 200)
    assert order['lines'][0]['cancelled_quantity'] == 6
    amend(client, 'purchase-orders', order, [{'product_id': product['id'], 'quantity': 9}], status=409)
    amend(client, 'purchase-orders', order, [{'product_id': product['id'], 'quantity': 12, 'unit_price': '9'}], status=422)
    amend(client, 'purchase-orders', order, [{'product_id': product['id'], 'quantity': 12}] * 2, status=422)
    second = post(client, '/products', login(client), {'internal_sku': 'NEW', 'name': '新增'})
    amend(client, 'purchase-orders', order, [{'product_id': second['id'], 'quantity': 1, 'unit_price': '1'}], status=409)
    amend(client, 'purchase-orders', order, [{'product_id': product['id'], 'quantity': 12},
          {'product_id': second['id'], 'quantity': 1}], status=422)
    assert client.get(f"/api/v1/purchase-orders/{order['id']}").json()['lines'][0]['quantity'] == 10
    post(client, f"/shipments/{record['id']}/cancel", login(client), {}, 200)
    amend(client, 'shipments', record, [{'product_id': product['id'], 'quantity': 4, 'units_per_carton': 1}], status=409)


def test_receipts_change_version_and_completed_shipments_lock(system):
    client, headers, product, supplier, _, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier, 10)
    record = shipment(system, client, headers, product, target, 10, order=order)
    post(client, f"/shipments/{record['id']}/dispatch", headers, {}, 200)
    receive(client, headers, record, 3)
    old_partial = client.get(f"/api/v1/shipments/{record['id']}").json()
    receive(client, headers, record, 2)
    amend(client, 'shipments', old_partial, [{'product_id': product['id'], 'quantity': 8, 'units_per_carton': 1}], status=409)
    current = client.get(f"/api/v1/shipments/{record['id']}").json()
    assert current['lines_version'] != old_partial['lines_version']
    receive(client, login(client), current, 5)
    completed = client.get(f"/api/v1/shipments/{record['id']}").json()
    amend(client, 'shipments', completed, [{'product_id': product['id'], 'quantity': 12, 'units_per_carton': 1}], status=409)
    order = client.get(f"/api/v1/purchase-orders/{order['id']}").json()
    assert order['status'] == 'received'
    changed, _ = amend(client, 'purchase-orders', order, [{'product_id': product['id'], 'quantity': 12}])
    assert changed['status'] == 'partially_received'
    assert changed['lines'][0]['received_quantity'] == 10
    assert balance(client, target)['quantity'] == 10


def test_amendment_permissions_scope_and_long_audit_summary(system):
    from sqlalchemy import select
    from app.models import AuditLog, User
    from app.tasks.models import SourceEvent
    client, headers, product, supplier, _, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier, 20)
    record = shipment(system, client, headers, product, target, 10, order=order)
    purchase_body = {'request_id': str(uuid4()), 'expected_version': order['lines_version'],
                     'lines': [{'product_id': product['id'], 'quantity': 22}], 'reason': '更正' * 500}
    shipment_body = {'request_id': str(uuid4()), 'expected_version': record['lines_version'],
                     'lines': [{'product_id': product['id'], 'quantity': 12, 'units_per_carton': 1}]}
    for kind, row, body in [('purchase-orders', order, purchase_body), ('shipments', record, shipment_body)]:
        response = client.patch(f"/api/v1/{kind}/{row['id']}/lines", headers=login(client, 'operator'), json=body)
        assert response.status_code == 403
    assert client.patch(f"/api/v1/purchase-orders/{order['id']}/lines", headers=login(client, 'finance'), json=purchase_body).status_code == 404
    with system['app'].state.database.session() as db:
        db.get(User, system['ids']['finance']).role = 'warehouse'
        db.commit()
    assert client.patch(f"/api/v1/shipments/{record['id']}/lines", headers=login(client, 'finance'), json=shipment_body).status_code == 404
    amend(client, 'purchase-orders', order, [], body=purchase_body)
    with system['app'].state.database.session() as db:
        audit = db.scalar(select(AuditLog).where(AuditLog.action == 'purchases.lines.update'))
        assert len(audit.summary) <= 500 and '3.1234' not in audit.summary
        events = db.scalars(select(SourceEvent).where(SourceEvent.source_id == order['id'])).all()
        changes = [item.data for item in events if 'line_changes' in item.data]
        assert len(changes) == 1 and changes[0]['reason'] == '更正' * 500


def test_concurrent_amendments_and_receipt_remain_consistent(system):
    if not system['settings'].database_url.startswith('postgresql'):
        pytest.skip('PostgreSQL concurrency test')
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi.testclient import TestClient

    client, headers, product, supplier, _, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier, 20)
    record = shipment(system, client, headers, product, target, 10, order=order)
    post(client, f"/shipments/{record['id']}/dispatch", headers, {}, 200)
    record = client.get(f"/api/v1/shipments/{record['id']}").json()

    def concurrent(requests):
        barrier = Barrier(2)
        def submit(request):
            method, path, body = request
            with TestClient(system['app'], cookies=dict(client.cookies)) as other:
                barrier.wait(timeout=10)
                response = other.request(method, '/api/v1' + path, headers=headers, json=body)
                return response.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(submit, requests))

    body = {'request_id': str(uuid4()), 'expected_version': record['lines_version'],
            'lines': [{'product_id': product['id'], 'quantity': 6, 'units_per_carton': 1}]}
    receipt = {'request_id': str(uuid4()), 'lines': [{'line_id': record['lines'][0]['id'], 'quantity': 8}]}
    results = concurrent([('PATCH', f"/shipments/{record['id']}/lines", body),
                          ('POST', f"/shipments/{record['id']}/receive", receipt)])
    assert sorted(results) == [200, 409]
    current = client.get(f"/api/v1/shipments/{record['id']}").json()
    assert current['lines'][0]['quantity'] >= current['lines'][0]['received_quantity']
    body = {**body, 'request_id': str(uuid4()), 'expected_version': current['lines_version'],
            'lines': [{'product_id': product['id'], 'quantity': 12, 'units_per_carton': 1}]}
    request = ('PATCH', f"/shipments/{record['id']}/lines", body)
    assert concurrent([request, request]) == [200, 200]
    current = client.get(f"/api/v1/shipments/{record['id']}").json()
    assert current['lines'][0]['quantity'] == 12
    body = {**body, 'request_id': str(uuid4()), 'expected_version': current['lines_version']}
    results = concurrent([('PATCH', f"/shipments/{record['id']}/lines", {**body, 'lines': [{'product_id': product['id'], 'quantity': 13, 'units_per_carton': 1}]}),
                          ('PATCH', f"/shipments/{record['id']}/lines", {**body, 'request_id': str(uuid4()), 'lines': [{'product_id': product['id'], 'quantity': 14, 'units_per_carton': 1}]})])
    assert sorted(results) == [200, 409]
