from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import User
from conftest import login


def post(client, path, headers, body, status=201):
    if path.startswith('/shipments/') and path.endswith(('/dispatch', '/cancel')) and not body:
        body = {'request_id': str(uuid4())}
    response = client.post('/api/v1' + path, headers=headers, json=body)
    assert response.status_code == status, response.text
    return response.json()


def fixtures(system):
    client = system['client']
    headers = login(client)
    product = post(client, '/products', headers, {'internal_sku': 'SUPPLY-TEST', 'name': '供应链测试商品', 'units_per_carton': 1})
    supplier = post(client, '/suppliers', headers, {'code': 'SUPPLY', 'name': '供应链测试供应商'})
    source = post(client, '/warehouses', headers, {'code': 'CN', 'name': '国内测试仓', 'kind': 'domestic'})
    target = post(client, '/warehouses', headers, {'code': 'FBA', 'name': 'FBA测试仓', 'kind': 'fba'})
    return client, headers, product, supplier, source, target


def purchase(system, client, headers, product, supplier, quantity=100):
    body = {'request_id': str(uuid4()), 'store_id': system['ids']['a'], 'supplier_id': supplier['id'],
            'order_date': '2026-09-08', 'expected_date': '2026-09-20', 'currency': 'CNY',
            'lines': [{'product_id': product['id'], 'quantity': quantity, 'unit_price': '3.1234'}]}
    order = post(client, '/purchase-orders', headers, body)
    assert post(client, '/purchase-orders', headers, body)['id'] == order['id']
    return post(client, f"/purchase-orders/{order['id']}/confirm", headers, {}, 200)


def shipment(system, client, headers, product, target, quantity, *, order=None, source=None):
    body = {'request_id': str(uuid4()), 'store_id': system['ids']['a'], 'destination_warehouse_id': target['id'],
            'lines': [{'product_id': product['id'], 'quantity': quantity}], 'expected_date': '2026-09-25'}
    if order:
        body['purchase_order_id'] = order['id']
    else:
        body['source_warehouse_id'] = source['id']
    result = post(client, '/shipments', headers, body)
    assert post(client, '/shipments', headers, body)['id'] == result['id']
    return result


def receive(client, headers, record, quantity, token=None):
    return post(client, f"/shipments/{record['id']}/receive", headers, {
        'request_id': token or str(uuid4()), 'notes': '验收入库',
        'lines': [{'line_id': record['lines'][0]['id'], 'quantity': quantity}]}, 200)


def balance(client, warehouse):
    rows = client.get('/api/v1/inventory', params={'warehouse_id': warehouse['id']}).json()['items']
    return rows[0] if rows else {'quantity': 0, 'reserved': 0, 'available': 0}


def test_purchase_validation_money_edit_and_scope(system):
    client, headers, product, supplier, source, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier)
    assert Decimal(order['total_amount']) == Decimal('312.3400')
    assert client.patch(f"/api/v1/purchase-orders/{order['id']}", headers=headers,
                        json={'notes': '不得修改已提交采购'}).status_code == 409
    bad = {'request_id': str(uuid4()), 'store_id': system['ids']['a'], 'supplier_id': supplier['id'],
           'order_date': '2026-09-08', 'lines': [{'product_id': product['id'], 'quantity': 1.5, 'unit_price': '1'}]}
    assert client.post('/api/v1/purchase-orders', headers=headers, json=bad).status_code == 422
    bad['lines'] = [{'product_id': product['id'], 'quantity': 2, 'unit_price': '1'}] * 2
    assert client.post('/api/v1/purchase-orders', headers=headers, json=bad).status_code == 422
    login(client, 'finance')
    assert client.get('/api/v1/purchase-orders').json()['total'] == 0
    assert client.get(f"/api/v1/purchase-orders/{order['id']}").status_code == 404
    with system['app'].state.database.session() as db:
        user = db.get(User, system['ids']['operator'])
        user.role = 'warehouse'
        db.commit()
    headers = login(client, 'operator')
    visible = client.get(f"/api/v1/purchase-orders/{order['id']}").json()
    assert 'total_amount' not in visible and 'unit_price' not in visible['lines'][0]
    assert client.post(f"/api/v1/purchase-orders/{order['id']}/cancel", headers=headers, json={}).status_code == 403


def test_purchase_shipping_receipts_reservations_and_ledger(system):
    client, headers, product, supplier, source, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier)
    inbound = shipment(system, client, headers, product, source, 60, order=order)
    post(client, f"/shipments/{inbound['id']}/dispatch", headers, {}, 200)
    token = str(uuid4())
    receive(client, headers, inbound, 40, token)
    receive(client, headers, inbound, 40, token)
    assert balance(client, source)['quantity'] == 40
    current = client.get(f"/api/v1/purchase-orders/{order['id']}").json()
    assert current['lines'][0]['received_quantity'] == 40
    outbound = shipment(system, client, headers, product, target, 25, source=source)
    assert balance(client, source)['available'] == 15
    assert balance(client, source)['reserved'] == 25
    post(client, f"/shipments/{outbound['id']}/dispatch", headers, {}, 200)
    assert client.post(f"/api/v1/shipments/{outbound['id']}/dispatch", headers=headers, json={'request_id': str(uuid4())}).status_code == 409
    receive(client, headers, outbound, 20)
    assert balance(client, source)['quantity'] == 15
    assert balance(client, source)['reserved'] == 0
    assert balance(client, target)['quantity'] == 20
    summary = client.get('/api/v1/inventory/summary').json()
    assert summary['in_transit'] == 25  # supplier 20 + outbound 5
    movements = client.get('/api/v1/inventory/movements').json()
    assert movements['total'] == 4
    assert {row['kind'] for row in movements['items']} == {'receipt', 'reserve', 'dispatch'}
    assert client.post(f"/api/v1/shipments/{outbound['id']}/receive", headers=headers, json={
        'request_id': str(uuid4()), 'lines': [{'line_id': outbound['lines'][0]['id'], 'quantity': 6}]}).status_code == 409
    assert balance(client, target)['quantity'] == 20
    receive(client, headers, outbound, 5)
    assert client.get(f"/api/v1/shipments/{outbound['id']}").json()['status'] == 'received'


def test_allocations_cancellation_and_negative_inventory(system):
    client, headers, product, supplier, source, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier, 10)
    inbound = shipment(system, client, headers, product, source, 8, order=order)
    excessive = {'request_id': str(uuid4()), 'store_id': system['ids']['a'], 'purchase_order_id': order['id'],
                 'destination_warehouse_id': source['id'], 'lines': [{'product_id': product['id'], 'quantity': 3}]}
    assert client.post('/api/v1/shipments', headers=headers, json=excessive).status_code == 409
    cancelled = post(client, f"/purchase-orders/{order['id']}/cancel", headers, {}, 200)
    assert cancelled['lines'][0]['cancelled_quantity'] == 2
    assert cancelled['status'] == 'ordered'
    post(client, f"/shipments/{inbound['id']}/cancel", headers, {}, 200)
    inbound = shipment(system, client, headers, product, source, 4, order=order)
    post(client, f"/shipments/{inbound['id']}/dispatch", headers, {}, 200)
    receive(client, headers, inbound, 4)
    closed = post(client, f"/purchase-orders/{order['id']}/cancel", headers, {}, 200)
    assert closed['status'] == 'closed'
    assert closed['lines'][0]['cancelled_quantity'] == 6
    outbound = shipment(system, client, headers, product, target, 3, source=source)
    adjustment = {'request_id': str(uuid4()), 'store_id': system['ids']['a'], 'warehouse_id': source['id'],
                  'product_id': product['id'], 'quantity': -2, 'reason': '盘点差异', 'kind': 'adjustment'}
    assert client.post('/api/v1/inventory/adjustments', headers=headers, json=adjustment).status_code == 409
    post(client, f"/shipments/{outbound['id']}/cancel", headers, {}, 200)
    assert balance(client, source)['available'] == 4
    post(client, '/inventory/adjustments', headers, adjustment)
    post(client, '/inventory/adjustments', headers, adjustment)
    assert balance(client, source)['quantity'] == 2
    adjustment['quantity'] = 2
    assert client.post('/api/v1/inventory/adjustments', headers=headers, json=adjustment).status_code == 409


def test_warehouse_opening_tracking_and_store_isolation(system):
    client, headers, product, supplier, source, target = fixtures(system)
    opening = {'request_id': str(uuid4()), 'store_id': system['ids']['a'], 'warehouse_id': source['id'],
               'product_id': product['id'], 'quantity': 10, 'reason': '期初盘点', 'kind': 'opening'}
    post(client, '/inventory/adjustments', headers, opening)
    opening['request_id'] = str(uuid4())
    assert client.post('/api/v1/inventory/adjustments', headers=headers, json=opening).status_code == 409
    record = shipment(system, client, headers, product, target, 3, source=source)
    post(client, f"/shipments/{record['id']}/dispatch", headers, {}, 200)
    post(client, f"/shipments/{record['id']}/events", headers, {
        'request_id': str(uuid4()), 'stage': 'customs', 'notes': '货物已到港清关'}, 200)
    detail = client.get(f"/api/v1/shipments/{record['id']}").json()
    assert detail['stage'] == 'customs'
    assert detail['events'][-1]['notes'] == '货物已到港清关'
    finance_headers = login(client, 'finance')
    for path in ['/shipments', '/inventory', '/inventory/movements']:
        assert client.get('/api/v1'+path).json()['total'] == 0
    assert client.get('/api/v1/inventory/summary').json()['quantity'] == 0
    assert client.get(f"/api/v1/shipments/{record['id']}").status_code == 404
    assert client.post(f"/api/v1/shipments/{record['id']}/dispatch", headers=finance_headers, json={}).status_code == 403
    login(client)
    assert client.patch(f"/api/v1/warehouses/{target['id']}", headers=login(client), json={'is_active': False}).status_code == 200


def test_postgres_concurrent_allocations_and_receipts(system):
    if system['app'].state.database.engine.dialect.name != 'postgresql':
        pytest.skip('Row-lock concurrency is verified with the local PostgreSQL instance')
    client, headers, product, supplier, source, target = fixtures(system)
    opening = {'request_id': str(uuid4()), 'store_id': system['ids']['a'], 'warehouse_id': source['id'],
               'product_id': product['id'], 'quantity': 10, 'reason': '并发测试期初', 'kind': 'opening'}
    post(client, '/inventory/adjustments', headers, opening)

    def concurrent(path, bodies):
        barrier = Barrier(2)
        def submit(body):
            with TestClient(system['app'], cookies=dict(client.cookies)) as other:
                barrier.wait(timeout=10)
                response = other.post('/api/v1'+path, headers=headers, json=body)
                return response.status_code, response.json()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(submit, bodies))

    body = {'store_id': system['ids']['a'], 'source_warehouse_id': source['id'], 'destination_warehouse_id': target['id'],
            'lines': [{'product_id': product['id'], 'quantity': 7}]}
    results = concurrent('/shipments', [{**body, 'request_id': str(uuid4())} for _ in range(2)])
    assert sorted(status for status, _ in results) == [201, 409], results
    record = next(result for status, result in results if status == 201)
    assert balance(client, source)['available'] == 3
    post(client, f"/shipments/{record['id']}/dispatch", headers, {}, 200)
    receipt = {'request_id': str(uuid4()), 'lines': [{'line_id': record['lines'][0]['id'], 'quantity': 4}]}
    results = concurrent(f"/shipments/{record['id']}/receive", [receipt, receipt])
    assert [status for status, _ in results] == [200, 200], results
    assert balance(client, target)['quantity'] == 4
    results = concurrent(f"/shipments/{record['id']}/receive", [
        {'request_id': str(uuid4()), 'lines': [{'line_id': record['lines'][0]['id'], 'quantity': 3}]} for _ in range(2)])
    assert sorted(status for status, _ in results) == [200, 409], results
    assert balance(client, target)['quantity'] == 7
    assert balance(client, source)['quantity'] == 3


def test_draft_edit_rollback_and_receipt_boundaries(system):
    client, headers, product, supplier, source, target = fixtures(system)
    draft = post(client, '/purchase-orders', headers, {'request_id': str(uuid4()), 'store_id': system['ids']['a'],
        'supplier_id': supplier['id'], 'order_date': '2026-09-08',
        'lines': [{'product_id': product['id'], 'quantity': 20, 'unit_price': '1.2345'}]})
    edited = client.patch(f"/api/v1/purchase-orders/{draft['id']}", headers=headers, json={
        'lines': [{'product_id': product['id'], 'quantity': 10, 'unit_price': '2.0001'}]})
    assert edited.status_code == 200, edited.text
    assert Decimal(edited.json()['total_amount']) == Decimal('20.0010')
    from datetime import datetime
    assert datetime.fromisoformat(edited.json()['created_at']).utcoffset() is not None
    assert client.get('/api/v1/purchase-orders?shippable=true').json()['total'] == 0
    assert client.patch(f"/api/v1/purchase-orders/{draft['id']}", headers=headers, json={'store_id': system['ids']['b']}).status_code == 422
    order = post(client, f"/purchase-orders/{draft['id']}/confirm", headers, {}, 200)
    assert client.get('/api/v1/purchase-orders?shippable=true').json()['total'] == 1
    inbound = shipment(system, client, headers, product, source, 10, order=order)
    assert client.get('/api/v1/purchase-orders?shippable=true').json()['total'] == 0
    payload = {'request_id': str(uuid4()), 'lines': [{'line_id': inbound['lines'][0]['id'], 'quantity': 10}]}
    assert client.post(f"/api/v1/shipments/{inbound['id']}/receive", headers=headers, json=payload).status_code == 409
    post(client, f"/shipments/{inbound['id']}/dispatch", headers, {}, 200)
    payload['lines'].append({'line_id': 'missing', 'quantity': 1})
    assert client.post(f"/api/v1/shipments/{inbound['id']}/receive", headers=headers, json=payload).status_code == 409
    assert balance(client, source)['quantity'] == 0
    assert client.get(f"/api/v1/shipments/{inbound['id']}").json()['lines'][0]['received_quantity'] == 0
    assert client.post(f"/api/v1/shipments/{inbound['id']}/cancel", headers=headers, json={'request_id': str(uuid4())}).status_code == 409
    payload['lines'].pop()
    assert client.post(f"/api/v1/shipments/{inbound['id']}/receive", headers=headers, json=payload).status_code == 200


def test_unallocated_cancel_and_dispatch_cancel_replay(system):
    client, headers, product, supplier, source, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier, 100)
    inbound = shipment(system, client, headers, product, source, 60, order=order)
    token = {'request_id': str(uuid4())}
    post(client, f"/shipments/{inbound['id']}/dispatch", headers, token, 200)
    post(client, f"/shipments/{inbound['id']}/dispatch", headers, token, 200)
    cancelled = post(client, f"/purchase-orders/{order['id']}/cancel", headers, {}, 200)
    assert cancelled['lines'][0]['cancelled_quantity'] == 40
    receive(client, headers, inbound, 60)
    assert client.get(f"/api/v1/purchase-orders/{order['id']}").json()['status'] == 'closed'
    outgoing = shipment(system, client, headers, product, target, 10, source=source)
    token = {'request_id': str(uuid4())}
    post(client, f"/shipments/{outgoing['id']}/cancel", headers, token, 200)
    post(client, f"/shipments/{outgoing['id']}/cancel", headers, token, 200)
    assert balance(client, source)['available'] == 60
