from uuid import uuid4

from conftest import login
from test_supply import allow_purchase, fixtures, purchase, shipment, post, receive


def transfer_body(order, quantity):
    return {'request_id': str(uuid4()), 'expected_version': order['lines_version'],
            'order_date': '2026-10-03', 'planned_ship_date': '2026-10-15',
            'lines': [{'product_id': order['lines'][0]['product_id'], 'quantity': quantity}]}


def current(client, order):
    response = client.get(f"/api/v1/purchase-orders/{order['id']}")
    assert response.status_code == 200, response.text
    return response.json()


def test_transfer_partial_remainder_preserves_shipments_prices_and_retries(system):
    client, headers, product, supplier, source, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier, 100)
    first = shipment(system, client, headers, product, target, 60, order=order)
    post(client, f"/shipments/{first['id']}/dispatch", headers, {}, 200)
    receive(client, headers, first, 20)
    order = current(client, order)
    assert order['lines'][0]['unallocated_quantity'] == 40
    body = transfer_body(order, 30)
    new = post(client, f"/purchase-orders/{order['id']}/transfer", headers, body)
    assert post(client, f"/purchase-orders/{order['id']}/transfer", headers, body)['id'] == new['id']
    assert new['source_purchase_order_id'] == order['id']
    assert new['source_purchase_number'] == order['number']
    assert new['store_id'] == order['store_id'] and new['supplier_id'] == order['supplier_id']
    assert new['lines'][0]['unit_price'] == order['lines'][0]['unit_price']
    assert new['status'] == 'ordered' and new['planned_ship_date'] == '2026-10-15'
    old = current(client, order)
    assert old['lines'][0]['quantity'] == 100
    assert old['lines'][0]['received_quantity'] == 20
    assert old['lines'][0]['allocated_quantity'] == 40
    assert old['lines'][0]['transferred_quantity'] == 30
    assert old['lines'][0]['unallocated_quantity'] == 10
    assert old['total_amount'] == '218.6380' and new['total_amount'] == '93.7020'
    assert old['transfer_orders'] == [{'id': new['id'], 'number': new['number']}]
    receive(client, headers, first, 40)
    shipment(system, client, headers, product, target, 30, order=new)
    assert current(client, new)['lines'][0]['unallocated_quantity'] == 0
    assert current(client, order)['lines'][0]['unallocated_quantity'] == 10


def test_full_transfer_closes_original_and_prevents_reuse(system):
    client, headers, product, supplier, source, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier, 10)
    new = post(client, f"/purchase-orders/{order['id']}/transfer", headers, transfer_body(order, 10))
    old = current(client, order)
    assert old['status'] == 'closed' and old['total_amount'] == '0.0000'
    assert old['lines'][0]['cancelled_quantity'] == 0
    assert old['lines'][0]['unallocated_quantity'] == 0
    ids = {row['id'] for row in client.get('/api/v1/purchase-orders?shippable=true').json()['items']}
    assert old['id'] not in ids and new['id'] in ids
    response = client.post(f"/api/v1/purchase-orders/{old['id']}/transfer", headers=headers, json=transfer_body(old, 1))
    assert response.status_code == 409


def test_transfer_rechecks_allocations_and_rolls_back_invalid_lines(system):
    client, headers, product, supplier, source, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier, 10)
    pending = shipment(system, client, headers, product, target, 6, order=order)
    path = f"/api/v1/purchase-orders/{order['id']}/transfer"
    assert client.post(path, headers=headers, json=transfer_body(order, 5)).status_code == 409
    body = transfer_body(order, 2)
    body['lines'].append({'product_id': 'not-in-purchase', 'quantity': 1})
    assert client.post(path, headers=headers, json=body).status_code == 409
    assert current(client, order)['lines'][0]['transferred_quantity'] == 0
    assert client.get('/api/v1/purchase-orders').json()['total'] == 1
    new = post(client, f"/purchase-orders/{order['id']}/transfer", headers, transfer_body(order, 4))
    # Neither a new shipment nor an amended shipment can reuse transferred stock.
    excessive = {'request_id': str(uuid4()), 'store_id': order['store_id'], 'purchase_order_id': order['id'],
                 'lines': [{'product_id': product['id'], 'quantity': 1}]}
    assert client.post('/api/v1/shipments', headers=headers, json=excessive).status_code == 409
    change = {'request_id': str(uuid4()), 'expected_version': pending['lines_version'],
              'lines': [{'product_id': product['id'], 'quantity': 7}]}
    assert client.patch(f"/api/v1/shipments/{pending['id']}/lines", headers=headers, json=change).status_code == 409
    # Cancelling remaining quantities must not cancel the transferred quantity again.
    post(client, f"/shipments/{pending['id']}/cancel", headers, {}, 200)
    cancelled = post(client, f"/purchase-orders/{order['id']}/cancel", headers, {}, 200)
    assert cancelled['lines'][0]['cancelled_quantity'] == 6
    assert cancelled['lines'][0]['transferred_quantity'] == 4
    assert current(client, new)['lines'][0]['unallocated_quantity'] == 4


def test_transfer_rejects_stale_duplicate_and_unauthorized_requests(system):
    client, headers, product, supplier, source, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier, 10)
    path = f"/api/v1/purchase-orders/{order['id']}/transfer"
    body = transfer_body(order, 3)
    body['lines'] *= 2
    assert client.post(path, headers=headers, json=body).status_code == 422
    body = transfer_body(order, 3)
    assert client.post(path, headers=headers, json=body).status_code == 201
    assert client.post(path, headers=headers, json=transfer_body(order, 1)).status_code == 409
    body['lines'][0]['quantity'] = 2
    assert client.post(path, headers=headers, json=body).status_code == 409
    finance = login(client, 'finance')
    assert client.post(path, headers=finance, json=transfer_body(order, 1)).status_code == 404
    operator = login(client, 'operator')
    assert client.post(path, headers=operator, json=transfer_body(order, 1)).status_code == 403


def test_selected_products_transfer_and_unselected_products_stay(system):
    client, headers, product, supplier, source, target = fixtures(system)
    second = post(client, '/products', headers, {'internal_sku': 'TRANSFER-SECOND', 'name': '第二商品', 'units_per_carton': 1})
    allow_purchase(system, client, headers, second, supplier)
    order = purchase(system, client, headers, product, supplier, 10)
    response = client.patch(f"/api/v1/purchase-orders/{order['id']}/lines", headers=headers, json={
        'request_id': str(uuid4()), 'expected_version': order['lines_version'],
        'lines': [{'product_id': product['id'], 'quantity': 10}, {'product_id': second['id'], 'quantity': 20, 'unit_price': '2'}]})
    assert response.status_code == 200, response.text
    order = current(client, order)
    body = transfer_body(order, 5)
    body['lines'] = [{'product_id': second['id'], 'quantity': 7}]
    new = post(client, f"/purchase-orders/{order['id']}/transfer", headers, body)
    assert [(line['product_id'], line['quantity']) for line in new['lines']] == [(second['id'], 7)]
    old = current(client, order)
    assert [line['unallocated_quantity'] for line in old['lines']] == [10, 13]
    # Transferred quantities remain protected when the original PO is amended.
    response = client.patch(f"/api/v1/purchase-orders/{order['id']}/lines", headers=headers, json={
        'request_id': str(uuid4()), 'expected_version': old['lines_version'],
        'lines': [{'product_id': product['id'], 'quantity': 10}, {'product_id': second['id'], 'quantity': 6}]})
    assert response.status_code == 409
    all_remaining = transfer_body(old, 1)
    all_remaining['lines'] = [{'product_id': line['product_id'], 'quantity': line['unallocated_quantity']} for line in old['lines']]
    last = post(client, f"/purchase-orders/{order['id']}/transfer", headers, all_remaining)
    assert [line['quantity'] for line in last['lines']] == [10, 13]
    assert current(client, order)['status'] == 'closed'


def test_postgres_concurrent_transfers_and_shipping_do_not_duplicate_remainder(system):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    import pytest
    from fastapi.testclient import TestClient

    if system['app'].state.database.engine.dialect.name != 'postgresql':
        pytest.skip('Requires PostgreSQL row locks')
    client, headers, product, supplier, source, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier, 10)
    path = f"/api/v1/purchase-orders/{order['id']}/transfer"
    for identical in [True, False]:
        barrier = Barrier(2)
        body = transfer_body(current(client, order), 4)
        bodies = [body, body if identical else {**body, 'request_id': str(uuid4())}]
        def submit(payload):
            with TestClient(system['app'], cookies=dict(client.cookies)) as other:
                barrier.wait(timeout=10)
                response = other.post(path, headers=headers, json=payload)
                return response.status_code, response.json()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, bodies))
        assert sorted(status for status, _ in results) == ([201, 201] if identical else [201, 409]), results
        if identical:
            assert results[0][1]['id'] == results[1][1]['id']
    assert current(client, order)['lines'][0]['transferred_quantity'] == 8
    order = current(client, order)
    barrier = Barrier(2)
    actions = [(path, transfer_body(order, 2)), ('/api/v1/shipments', {
        'request_id': str(uuid4()), 'store_id': order['store_id'], 'purchase_order_id': order['id'],
        'lines': [{'product_id': product['id'], 'quantity': 2}]})]
    def act(action):
        with TestClient(system['app'], cookies=dict(client.cookies)) as other:
            barrier.wait(timeout=10)
            return other.post(action[0], headers=headers, json=action[1]).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(act, actions)) == [201, 409]
    assert current(client, order)['lines'][0]['unallocated_quantity'] == 0
