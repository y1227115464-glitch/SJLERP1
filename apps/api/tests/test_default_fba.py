from uuid import uuid4

import pytest

from conftest import login
from test_supply import balance, fixtures, post, purchase, receive


def test_defaults_to_fba_and_receives_without_warehouse_selection(system):
    client, headers, product, supplier, source, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier, 10)
    body = {'request_id': str(uuid4()), 'store_id': system['ids']['a'],
            'purchase_order_id': order['id'], 'lines': [{'product_id': product['id'], 'quantity': 10}]}
    record = post(client, '/shipments', headers, body)
    assert record['destination_warehouse_id'] == target['id']
    assert post(client, '/shipments', headers, body)['id'] == record['id']
    post(client, f"/shipments/{record['id']}/dispatch", headers, {}, 200)
    receive(client, headers, record, 10)
    adjustment = {'request_id': str(uuid4()), 'store_id': system['ids']['a'],
                  'product_id': product['id'], 'quantity': -2, 'reason': '盘点'}
    post(client, '/inventory/adjustments', headers, adjustment)
    post(client, '/inventory/adjustments', headers, adjustment)
    assert balance(client, target)['quantity'] == 8
    assert balance(client, source)['quantity'] == 0
    same_warehouse = {**body, 'request_id': str(uuid4()), 'purchase_order_id': None,
                      'source_warehouse_id': target['id']}
    assert client.post('/api/v1/shipments', headers=headers, json=same_warehouse).status_code == 422


def test_empty_installation_creates_one_fba_and_keeps_store_scope(system):
    client = system['client']
    headers = login(client)
    product = post(client, '/products', headers, {'internal_sku': 'FBA-DEFAULT', 'name': '测试'})
    body = {'request_id': str(uuid4()), 'store_id': system['ids']['a'],
            'product_id': product['id'], 'quantity': 5, 'reason': '期初', 'kind': 'opening'}
    post(client, '/inventory/adjustments', headers, body)
    warehouses = client.get('/api/v1/warehouses').json()['items']
    assert len(warehouses) == 1
    assert warehouses[0]['kind'] == 'fba'
    assert warehouses[0]['name'] == 'FBA仓库'
    post(client, '/inventory/adjustments', headers, {**body, 'request_id': str(uuid4()),
                                                  'store_id': system['ids']['b']})
    assert client.get('/api/v1/warehouses').json()['total'] == 1
    headers = login(client, 'operator')
    rows = client.get('/api/v1/inventory').json()['items']
    assert len(rows) == 1 and rows[0]['store_id'] == system['ids']['a']


def test_new_warehouse_defaults_to_fba(system):
    client = system['client']
    warehouse = post(client, '/warehouses', login(client), {'code': 'NEW', 'name': '新仓库'})
    assert warehouse['kind'] == 'fba'


def test_fba_scope_matches_balances_movements_and_transit(system):
    client, headers, product, supplier, source, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier, 20)
    for warehouse, quantity in [(source, 3), (target, 5)]:
        post(client, '/inventory/adjustments', headers, {'request_id': str(uuid4()),
             'store_id': system['ids']['a'], 'warehouse_id': warehouse['id'],
             'product_id': product['id'], 'quantity': quantity, 'reason': '期初', 'kind': 'opening'})
        record = post(client, '/shipments', headers, {'request_id': str(uuid4()),
                      'store_id': system['ids']['a'], 'purchase_order_id': order['id'],
                      'destination_warehouse_id': warehouse['id'],
                      'lines': [{'product_id': product['id'], 'quantity': quantity}]})
        post(client, f"/shipments/{record['id']}/dispatch", headers, {}, 200)
    for path in ['/inventory', '/inventory/movements']:
        response = client.get('/api/v1' + path, params={'warehouse_kind': 'fba'}).json()
        assert response['total'] == 1
        assert response['items'][0]['warehouse_id'] == target['id']
    summary = client.get('/api/v1/inventory/summary', params={'warehouse_kind': 'fba'}).json()
    assert summary == {'quantity': 5, 'reserved': 0, 'available': 5, 'in_transit': 5}
    assert client.get('/api/v1/inventory/summary').json()['quantity'] == 8


def test_inactive_fba_is_not_selected_and_failed_post_rolls_back_creation(system):
    client, headers, product, _, _, target = fixtures(system)
    client.patch(f"/api/v1/warehouses/{target['id']}", headers=headers, json={'is_active': False})
    body = {'request_id': str(uuid4()), 'store_id': system['ids']['a'],
            'product_id': product['id'], 'quantity': -1, 'reason': '无库存扣减'}
    assert client.post('/api/v1/inventory/adjustments', headers=headers, json=body).status_code == 409
    assert client.get('/api/v1/warehouses').json()['total'] == 2
    post(client, '/inventory/adjustments', headers, {**body, 'quantity': 5})
    row = client.get('/api/v1/inventory').json()['items'][0]
    assert row['warehouse_kind'] == 'fba' and row['warehouse_id'] != target['id']


def test_concurrent_first_use_creates_one_default_fba(system):
    if not system['settings'].database_url.startswith('postgresql'):
        pytest.skip('PostgreSQL concurrency test')
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi.testclient import TestClient

    client = system['client']
    headers = login(client)
    product = post(client, '/products', headers, {'internal_sku': 'CONCURRENT-FBA', 'name': '并发测试'})
    barrier = Barrier(2)
    def submit(store):
        with TestClient(system['app'], cookies=dict(client.cookies)) as other:
            barrier.wait(timeout=10)
            return other.post('/api/v1/inventory/adjustments', headers=headers, json={
                'request_id': str(uuid4()), 'store_id': store, 'product_id': product['id'],
                'quantity': 5, 'reason': '期初', 'kind': 'opening'}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(submit, [system['ids']['a'], system['ids']['b']])) == [201, 201]
    assert client.get('/api/v1/warehouses').json()['total'] == 1
    assert client.get('/api/v1/inventory/summary').json()['quantity'] == 10
