from uuid import uuid4

from conftest import login
from test_supply import fixtures, post, purchase, shipment, receive
from test_purchase_transfer import current, transfer_body


def body(order, quantity, **extra):
    return {'request_id': str(uuid4()), 'expected_version': order['lines_version'],
            'reason': '已付款余货暂存供应商', 'payment_status': 'paid',
            'lines': [{'product_id': order['lines'][0]['product_id'], 'quantity': quantity}], **extra}


def stock_list(client, params=None):
    response = client.get('/api/v1/supplier-stock', params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_partial_ship_hold_release_receive_keeps_financials(system):
    client, headers, product, supplier, source, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier, 100)
    post(client, f"/purchase-orders/{order['id']}/finance", headers,
         {'request_id': str(uuid4()), 'payment_status': 'paid', 'invoice_status': 'received', 'notes': '已付全款'}, 200)
    first = shipment(system, client, headers, product, target, 60, order=order)
    post(client, f"/shipments/{first['id']}/dispatch", headers, {}, 200)
    payload = body(current(client, order), 40)
    for _ in range(2):
        result = post(client, f"/purchase-orders/{order['id']}/supplier-stock", headers, payload)
        assert result['total_amount'] == '312.3400'
        assert result['payment_status'] == 'paid' and result['invoice_status'] == 'received'
    stock = stock_list(client)['items'][0]
    assert stock_list(client)['total'] == 1
    assert stock['remaining_quantity'] == 40
    assert current(client, order)['lines'][0]['unallocated_quantity'] == 0
    assert stock_list(client, {'q': supplier['name']})['total'] == 1
    assert stock_list(client, {'supplier_id': 'missing'})['total'] == 0
    summary = client.get('/api/v1/supplier-stock/summary').json()
    assert summary['items'] == [{'id': supplier['id'], 'supplier_name': supplier['name'], 'quantity': 40, 'batches': 1}]
    receive(client, headers, first, 60)
    assert current(client, order)['status'] == 'closed'
    release_body = {'request_id': str(uuid4()), 'quantity': 15, 'reason': '安排第二批发货'}
    for _ in range(2):
        result = post(client, f"/supplier-stock/{stock['id']}/release", headers, release_body, 200)
        assert result['remaining_quantity'] == 25
    reopened = current(client, order)
    assert reopened['status'] == 'partially_received'
    assert reopened['lines'][0]['unallocated_quantity'] == 15
    second = shipment(system, client, headers, product, target, 15, order=order)
    post(client, f"/shipments/{second['id']}/dispatch", headers, {}, 200)
    receive(client, headers, second, 15)
    assert current(client, order)['status'] == 'closed'
    payment = {'request_id': str(uuid4()), 'payment_status': 'partial', 'reason': '核实部分款项'}
    for _ in range(2):
        post(client, f"/supplier-stock/{stock['id']}/payment", headers, payment, 200)
    events = client.get(f"/api/v1/supplier-stock/{stock['id']}/events").json()
    assert events['total'] == 3
    assert {row['quantity'] for row in events['items']} == {40, -15, 0}
    assert current(client, order)['payment_status'] == 'paid'
    assert current(client, order)['total_amount'] == '312.3400'
    post(client, f"/supplier-stock/{stock['id']}/release", headers,
         {'request_id': str(uuid4()), 'quantity': 25, 'reason': '余货全部发出'}, 200)
    assert stock_list(client)['total'] == 0
    assert stock_list(client, {'include_empty': True})['total'] == 1
    assert client.get('/api/v1/supplier-stock/summary').json()['total'] == 0


def test_stock_protected_from_transfer_cancel_amend_and_allocations(system):
    client, headers, product, supplier, source, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier, 20)
    pending = shipment(system, client, headers, product, target, 6, order=order)
    path = f"/api/v1/purchase-orders/{order['id']}/supplier-stock"
    assert client.post(path, headers=headers, json=body(order, 15)).status_code == 409
    assert stock_list(client)['total'] == 0
    post(client, f"/purchase-orders/{order['id']}/supplier-stock", headers, body(order, 10))
    assert client.post(path, headers=headers, json=body(order, 1)).status_code == 409
    fresh = current(client, order)
    assert fresh['lines'][0]['unallocated_quantity'] == 4
    assert client.post(f"/api/v1/purchase-orders/{order['id']}/transfer", headers=headers, json=transfer_body(fresh, 5)).status_code == 409
    assert client.patch(f"/api/v1/purchase-orders/{order['id']}/lines", headers=headers, json={
        'request_id': str(uuid4()), 'expected_version': fresh['lines_version'],
        'lines': [{'product_id': product['id'], 'quantity': 15}]}).status_code == 409
    assert client.patch(f"/api/v1/shipments/{pending['id']}/lines", headers=headers, json={
        'request_id': str(uuid4()), 'expected_version': pending['lines_version'],
        'lines': [{'product_id': product['id'], 'quantity': 11}]}).status_code == 409
    assert client.post('/api/v1/shipments', headers=headers, json={
        'request_id': str(uuid4()), 'store_id': order['store_id'], 'purchase_order_id': order['id'],
        'lines': [{'product_id': product['id'], 'quantity': 5}]}).status_code == 409
    cancelled = post(client, f"/purchase-orders/{order['id']}/cancel", headers, {}, 200)
    assert cancelled['lines'][0]['cancelled_quantity'] == 4
    assert cancelled['lines'][0]['supplier_stock_quantity'] == 10


def test_stock_validation_scope_and_atomicity(system):
    client, headers, product, supplier, source, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier, 10)
    path = f"/api/v1/purchase-orders/{order['id']}/supplier-stock"
    payload = body(order, 2)
    for quantity in [0, -1, 1.5]:
        invalid = body(order, quantity)
        assert client.post(path, headers=headers, json=invalid).status_code == 422
    duplicate = body(order, 2); duplicate['lines'] *= 2
    assert client.post(path, headers=headers, json=duplicate).status_code == 422
    invalid = body(order, 2); invalid['lines'].append({'product_id': 'missing', 'quantity': 1})
    assert client.post(path, headers=headers, json=invalid).status_code == 409
    assert stock_list(client)['total'] == 0
    assert current(client, order)['lines'][0]['supplier_stock_quantity'] == 0
    post(client, f"/purchase-orders/{order['id']}/supplier-stock", headers, payload)
    payload['payment_status'] = 'unpaid'
    assert client.post(path, headers=headers, json=payload).status_code == 409
    stock = stock_list(client)['items'][0]
    release_path = f"/api/v1/supplier-stock/{stock['id']}/release"
    release = {'request_id': str(uuid4()), 'quantity': 3, 'reason': '发货'}
    assert client.post(release_path, headers=headers, json=release).status_code == 409
    finance = login(client, 'finance')
    assert stock_list(client)['total'] == 0
    assert client.get('/api/v1/supplier-stock/summary').json()['total'] == 0
    assert client.get(f"/api/v1/supplier-stock/{stock['id']}/events").status_code == 404
    assert client.post(release_path, headers=finance, json=release).status_code == 404
    operator = login(client, 'operator')
    assert client.get('/api/v1/supplier-stock').status_code == 403
    assert client.post(release_path, headers=operator, json=release).status_code == 403
    from app.models import User
    with system['app'].state.database.session() as db:
        db.get(User, system['ids']['operator']).role = 'warehouse'
        db.commit()
    rows = stock_list(client)['items']
    assert len(rows) == 1 and 'unit_price' not in rows[0]


def test_postgres_concurrent_stock_transfers_and_releases(system):
    import pytest
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi.testclient import TestClient
    if system['app'].state.database.engine.dialect.name != 'postgresql':
        pytest.skip('Requires PostgreSQL row locks')
    client, headers, product, supplier, source, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier, 10)
    def concurrent(path, payloads):
        barrier = Barrier(2)
        def submit(payload):
            with TestClient(system['app'], cookies=dict(client.cookies)) as other:
                barrier.wait(timeout=10)
                response = other.post(path, headers=headers, json=payload)
                return response.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            return sorted(pool.map(submit, payloads))
    path = f"/api/v1/purchase-orders/{order['id']}/supplier-stock"
    payload = body(order, 10)
    assert concurrent(path, [payload, payload]) == [201, 201]
    stock = stock_list(client)['items'][0]
    releases = [{'request_id': str(uuid4()), 'quantity': 7, 'reason': '发货'} for _ in range(2)]
    assert concurrent(f"/api/v1/supplier-stock/{stock['id']}/release", releases) == [200, 409]
    assert stock_list(client)['items'][0]['remaining_quantity'] == 3
    assert current(client, order)['lines'][0]['unallocated_quantity'] == 7

