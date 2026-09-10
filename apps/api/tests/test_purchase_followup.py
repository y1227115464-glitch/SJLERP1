from uuid import uuid4

from conftest import login
from test_supply import fixtures, post, purchase, shipment, receive, balance


def test_purchase_product_intersection_and_scope(system):
    client, headers, product, supplier, _, _ = fixtures(system)
    other = post(client, '/products', headers, {'internal_sku': 'NO-SUPPLY', 'name': '无供应商品'})
    params = {'store_id': system['ids']['a'], 'supplier_id': supplier['id'], 'is_active': True}
    def candidates():
        response = client.get('/api/v1/products', params=params)
        assert response.status_code == 200
        return response.json()
    assert [x['id'] for x in candidates()['items']] == [product['id']]
    post(client, '/supplier-quotes', headers, {'supplier_id': supplier['id'], 'label': '重复关联',
        'product_ids': [product['id']], 'tiers': [{'min_quantity': 1, 'unit_price': '1'}]})
    assert candidates()['total'] == 1
    body = {'request_id': str(uuid4()), 'store_id': system['ids']['a'], 'supplier_id': supplier['id'],
        'order_date': '2026-09-10', 'lines': [{'product_id': other['id'], 'quantity': 1, 'unit_price': '1'}]}
    assert client.post('/api/v1/purchase-orders', headers=headers, json=body).status_code == 422
    client.put(f"/api/v1/products/{product['id']}/stores/{system['ids']['a']}", headers=headers, json={'is_active': False})
    assert candidates()['total'] == 0
    body['lines'][0]['product_id'] = product['id']
    assert client.post('/api/v1/purchase-orders', headers=headers, json=body).status_code == 422
    headers = login(client, 'operator')
    assert client.get('/api/v1/products', params={**params, 'store_id': system['ids']['b']}).status_code == 404
    assert client.put(f"/api/v1/products/{product['id']}/stores/{system['ids']['b']}", headers=headers, json={'is_active': True}).status_code == 404


def test_finance_followup_after_receipt_idempotency_and_permissions(system):
    client, headers, product, supplier, _, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier, 2)
    assert order['payment_status'] == 'unpaid' and order['invoice_status'] == 'pending'
    record = shipment(system, client, headers, product, target, 2, order=order)
    post(client, f"/shipments/{record['id']}/dispatch", headers, {}, 200)
    receive(client, headers, record, 2)
    body = {'request_id': str(uuid4()), 'payment_status': 'paid', 'invoice_status': 'partial', 'notes': '已付款，待补尾票'}
    path = f"/purchase-orders/{order['id']}/finance"
    result = post(client, path, headers, body, 200)
    assert result['status'] == 'received' and result['payment_status'] == 'paid'
    post(client, path, headers, body, 200)
    detail = client.get(f"/api/v1/purchase-orders/{order['id']}").json()
    assert len(detail['finance_history']) == 1 and detail['finance_notes'] == body['notes']
    assert client.get('/api/v1/purchase-orders?payment_status=paid&invoice_status=partial').json()['total'] == 1
    assert client.post('/api/v1'+path, headers=headers, json={**body, 'payment_status': 'bad'}).status_code == 422
    headers = login(client, 'finance')
    assert client.post('/api/v1'+path, headers=headers, json={**body, 'request_id': str(uuid4())}).status_code == 404
    headers = login(client, 'operator')
    assert client.post('/api/v1'+path, headers=headers, json=body).status_code == 403


def merge_body(*records):
    return {'request_id': str(uuid4()), 'shipment_ids': [x['id'] for x in records],
        'expected_versions': {x['id']: x['lines_version'] for x in records}}


def test_supplier_merge_preserves_allocation_and_receipts(system):
    client, headers, product, supplier, _, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier, 20)
    a = shipment(system, client, headers, product, target, 3, order=order)
    b = shipment(system, client, headers, product, target, 5, order=order)
    body = merge_body(a, b)
    merged = post(client, '/shipments/merge', headers, body, 200)
    assert merged['id'] == a['id'] and merged['lines'][0]['quantity'] == 8
    assert post(client, '/shipments/merge', headers, body, 200)['id'] == a['id']
    old = client.get(f"/api/v1/shipments/{b['id']}").json()
    assert old['status'] == 'cancelled' and old['merged_into_id'] == a['id']
    current = client.get(f"/api/v1/purchase-orders/{order['id']}").json()
    assert current['lines'][0]['allocated_quantity'] == 8
    post(client, f"/shipments/{merged['id']}/dispatch", headers, {}, 200)
    receive(client, headers, merged, 8)
    assert balance(client, target)['quantity'] == 8
    assert client.get(f"/api/v1/purchase-orders/{order['id']}").json()['lines'][0]['received_quantity'] == 8


def test_warehouse_merge_keeps_reservations_and_cancel_releases_once(system):
    client, headers, product, _, source, target = fixtures(system)
    post(client, '/inventory/adjustments', headers, {'request_id': str(uuid4()), 'store_id': system['ids']['a'],
        'warehouse_id': source['id'], 'product_id': product['id'], 'quantity': 20, 'reason': '期初', 'kind': 'opening'})
    a = shipment(system, client, headers, product, target, 3, source=source)
    b = shipment(system, client, headers, product, target, 5, source=source)
    merged = post(client, '/shipments/merge', headers, merge_body(a, b), 200)
    assert balance(client, source)['reserved'] == 8
    post(client, f"/shipments/{merged['id']}/cancel", headers, {}, 200)
    assert balance(client, source)['reserved'] == 0 and balance(client, source)['quantity'] == 20


def test_merge_rejects_invalid_route_status_and_stale_version(system):
    client, headers, product, supplier, source, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier, 30)
    a = shipment(system, client, headers, product, target, 3, order=order)
    b = shipment(system, client, headers, product, source, 5, order=order)
    post(client, '/shipments/merge', headers, merge_body(a, b), 409)
    c = shipment(system, client, headers, product, target, 5, order=order)
    bad = merge_body(a, c); bad['expected_versions'][a['id']] = '0' * 64
    post(client, '/shipments/merge', headers, bad, 409)
    post(client, '/shipments/merge', headers, merge_body(a, a), 422)
    post(client, f"/shipments/{c['id']}/dispatch", headers, {}, 200)
    post(client, '/shipments/merge', headers, merge_body(a, c), 409)
    assert client.get(f"/api/v1/shipments/{a['id']}").json()['lines'][0]['quantity'] == 3


def test_merge_store_source_packing_and_logistics_boundaries(system):
    client, headers, product, supplier, source, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier, 30)
    other_order = purchase(system, client, headers, product, supplier, 30)
    a = shipment(system, client, headers, product, target, 6, order=order)
    other = shipment(system, client, headers, product, target, 6, order=other_order)
    post(client, '/shipments/merge', headers, merge_body(a, other), 409)
    b = shipment(system, client, headers, product, target, 6, order=order)
    from app.supply.models import Shipment, ShipmentLine
    with system['app'].state.database.session() as db:
        db.get(ShipmentLine, b['lines'][0]['id']).units_per_carton = 2
        db.commit()
    b = client.get(f"/api/v1/shipments/{b['id']}").json()
    assert post(client, '/shipments/merge', headers, merge_body(a, b), 409)['error']['code'] == 'merge_packing_mismatch'
    with system['app'].state.database.session() as db:
        db.get(ShipmentLine, b['lines'][0]['id']).units_per_carton = 1
        db.get(Shipment, b['id']).store_id = system['ids']['b']
        db.commit()
    post(client, '/shipments/merge', headers, merge_body(a, b), 409)
    warehouse_headers = login(client, 'operator')
    assert client.post('/api/v1/shipments/merge', headers=warehouse_headers, json=merge_body(a, b)).status_code == 403
    from app.models import User
    with system['app'].state.database.session() as db:
        db.get(User, system['ids']['operator']).role = 'warehouse'
        db.commit()
    warehouse_headers = login(client, 'operator')
    post(client, '/shipments/merge', warehouse_headers, merge_body(a, b), 404)
    headers = login(client)
    with system['app'].state.database.session() as db:
        db.get(Shipment, b['id']).store_id = system['ids']['a']
        db.commit()
    for record, tracking in [(a, 'A'), (b, 'B')]:
        response = client.patch(f"/api/v1/shipments/{record['id']}", headers=headers, json={'tracking_number': tracking})
        assert response.status_code == 200
    b = client.get(f"/api/v1/shipments/{b['id']}").json()
    assert post(client, '/shipments/merge', headers, merge_body(a, b), 409)['error']['code'] == 'merge_logistics_conflict'


def test_postgres_concurrent_merge_dispatch_and_replay(system):
    import pytest
    if system['app'].state.database.engine.dialect.name != 'postgresql':
        pytest.skip('Requires PostgreSQL row locks')
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi.testclient import TestClient
    client, headers, product, _, source, target = fixtures(system)
    post(client, '/inventory/adjustments', headers, {'request_id': str(uuid4()), 'store_id': system['ids']['a'],
        'warehouse_id': source['id'], 'product_id': product['id'], 'quantity': 30, 'reason': '并发期初', 'kind': 'opening'})
    a = shipment(system, client, headers, product, target, 3, source=source)
    b = shipment(system, client, headers, product, target, 5, source=source)
    body = merge_body(a, b)
    def concurrent(requests):
        barrier = Barrier(2)
        def send(item):
            with TestClient(system['app'], cookies=dict(client.cookies)) as other:
                barrier.wait(timeout=10)
                response = other.post('/api/v1'+item[0], headers=headers, json=item[1])
                return response.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(send, requests))
    assert concurrent([('/shipments/merge', body)] * 2) == [200, 200]
    assert balance(client, source)['reserved'] == 8
    c = shipment(system, client, headers, product, target, 4, source=source)
    d = shipment(system, client, headers, product, target, 6, source=source)
    results = concurrent([('/shipments/merge', merge_body(c, d)),
        (f"/shipments/{d['id']}/dispatch", {'request_id': str(uuid4())})])
    assert sorted(results) == [200, 409]
    stock = balance(client, source)
    if results[0] == 200:
        assert (stock['quantity'], stock['reserved']) == (30, 18)
    else:
        assert (stock['quantity'], stock['reserved']) == (24, 12)


def test_draft_confirm_rechecks_current_assortment(system):
    client, headers, product, supplier, _, _ = fixtures(system)
    draft = post(client, '/purchase-orders', headers, {'request_id': str(uuid4()), 'store_id': system['ids']['a'],
        'supplier_id': supplier['id'], 'order_date': '2026-09-10',
        'lines': [{'product_id': product['id'], 'quantity': 1, 'unit_price': '1'}]})
    client.put(f"/api/v1/products/{product['id']}/stores/{system['ids']['a']}", headers=headers, json={'is_active': False})
    post(client, f"/purchase-orders/{draft['id']}/confirm", headers, {}, 422)
    assert client.get(f"/api/v1/purchase-orders/{draft['id']}").json()['status'] == 'draft'
