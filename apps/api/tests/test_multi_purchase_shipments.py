from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.tasks.scheduler import tick
from test_supply import allow_purchase, balance, fixtures, post, purchase, shipment


def create_multi(system, client, headers, orders, **extra):
    body = {'request_id': str(uuid4()), 'store_id': system['ids']['a'],
            'purchase_order_ids': [order['id'] for order in orders], **extra}
    result = post(client, '/shipments', headers, body)
    assert post(client, '/shipments', headers, body)['id'] == result['id']
    return result


def order_detail(client, order):
    return client.get(f"/api/v1/purchase-orders/{order['id']}").json()


def test_defaults_all_products_preserve_sources_and_receive_same_sku(system):
    client, headers, product, supplier, _, target = fixtures(system)
    second = post(client, '/products', headers, {'internal_sku': 'MULTI-SECOND', 'name': '第二商品', 'units_per_carton': 1})
    allow_purchase(system, client, headers, second, supplier)
    first = post(client, '/purchase-orders', headers, {'request_id': str(uuid4()), 'store_id': system['ids']['a'],
        'supplier_id': supplier['id'], 'order_date': '2026-09-08', 'already_ordered': True,
        'lines': [{'product_id': product['id'], 'quantity': 20, 'unit_price': '1'},
                  {'product_id': second['id'], 'quantity': 7, 'unit_price': '1'}]})
    other = purchase(system, client, headers, product, supplier, 30)
    shipment(system, client, headers, product, target, 5, order=first)
    record = create_multi(system, client, headers, [first, other], destination_warehouse_id=target['id'])
    assert set(record['purchase_order_ids']) == {first['id'], other['id']}
    assert len(record['lines']) == 3
    quantities = {line['purchase_line_id']: line['quantity'] for line in record['lines']}
    assert quantities == {first['lines'][0]['id']: 15, first['lines'][1]['id']: 7, other['lines'][0]['id']: 30}
    for order in [first, other]:
        assert all(line['unallocated_quantity'] == 0 for line in order_detail(client, order)['lines'])
        listed = client.get('/api/v1/shipments', params={'purchase_order_id': order['id']}).json()['items']
        assert record['id'] in {item['id'] for item in listed}
    assert client.get('/api/v1/purchase-orders?shippable=true').json()['total'] == 0
    post(client, f"/shipments/{record['id']}/dispatch", headers, {}, 200)
    same_sku = [line for line in record['lines'] if line['product_id'] == product['id']]
    body = {'request_id': str(uuid4()), 'lines': [{'line_id': line['id'], 'quantity': line['quantity']} for line in same_sku]}
    result = post(client, f"/shipments/{record['id']}/receive", headers, body, 200)
    assert result['status'] == 'partially_received'
    post(client, f"/shipments/{record['id']}/receive", headers, body, 200)
    stocks = client.get('/api/v1/inventory', params={'warehouse_id': target['id']}).json()['items']
    assert next(row for row in stocks if row['product_id'] == product['id'])['quantity'] == 45
    assert order_detail(client, first)['lines'][0]['received_quantity'] == 15
    assert order_detail(client, other)['status'] == 'received'


def test_amend_allocation_floors_and_cancel_release_each_order(system):
    client, headers, product, supplier, _, _ = fixtures(system)
    orders = [purchase(system, client, headers, product, supplier, qty) for qty in [20, 30]]
    record = create_multi(system, client, headers, orders)
    def amend(rows, status=200):
        response = client.patch(f"/api/v1/shipments/{record['id']}/lines", headers=headers,
            json={'request_id': str(uuid4()), 'expected_version': record['lines_version'], 'lines': rows})
        assert response.status_code == status, response.text
        return response.json()
    rows = [{'purchase_line_id': order['lines'][0]['id'], 'product_id': product['id'], 'quantity': 10} for order in orders]
    amend([{**rows[0], 'quantity': 21}, rows[1]], 409)
    record = amend(rows)
    assert [order_detail(client, order)['lines'][0]['unallocated_quantity'] for order in orders] == [10, 20]
    post(client, f"/shipments/{record['id']}/cancel", headers, {}, 200)
    assert [order_detail(client, order)['lines'][0]['unallocated_quantity'] for order in orders] == [20, 30]
    record = create_multi(system, client, headers, orders)
    record = post(client, f"/shipments/{record['id']}/dispatch", headers, {}, 200)
    record = post(client, f"/shipments/{record['id']}/receive", headers,
                  {'request_id': str(uuid4()), 'lines': [{'line_id': record['lines'][0]['id'], 'quantity': 5}]}, 200)
    received = next(line for line in record['lines'] if line['received_quantity'])
    amend([row for row in rows if row['purchase_line_id'] != received['purchase_line_id']], 409)
    amend([{**row, 'quantity': 4 if row['purchase_line_id'] == received['purchase_line_id'] else 10} for row in rows], 409)


def test_invalid_sources_do_not_allocate(system):
    client, headers, product, supplier, source, _ = fixtures(system)
    orders = [purchase(system, client, headers, product, supplier) for _ in range(2)]
    base = {'request_id': str(uuid4()), 'store_id': system['ids']['a'], 'purchase_order_ids': [o['id'] for o in orders]}
    line = {'product_id': product['id'], 'purchase_line_id': orders[0]['lines'][0]['id'], 'quantity': 5}
    cases = [({'source_warehouse_id': source['id']}, 422),
             ({'purchase_order_ids': [orders[0]['id']] * 2}, 422),
             ({'store_id': system['ids']['b']}, 409),
             ({'lines': [{'product_id': product['id'], 'quantity': 5}]}, 409),
             ({'lines': [{**line, 'purchase_line_id': str(uuid4())}]}, 409),
             ({'lines': [line, line]}, 422),
             ({'lines': []}, 422)]
    for extra, status in cases:
        response = client.post('/api/v1/shipments', headers=headers, json={**base, **extra})
        assert response.status_code == status, response.text
    assert all(order_detail(client, o)['lines'][0]['unallocated_quantity'] == 100 for o in orders)


def test_merge_different_orders_and_dispatch_reminders(system):
    client, headers, product, supplier, _, target = fixtures(system)
    post(client, '/task-rules/templates', headers, {'request_id': str(uuid4()), 'templates': ['dispatch']})
    orders = [purchase(system, client, headers, product, supplier, qty) for qty in [20, 30]]
    for order, day in zip(orders, ['2026-10-15', '2026-10-20']):
        post(client, f"/purchase-orders/{order['id']}/schedule", headers,
             {'request_id': str(uuid4()), 'planned_ship_date': day}, 200)
    records = [shipment(system, client, headers, product, target, qty, order=o) for o, qty in zip(orders, [20, 30])]
    merged = post(client, '/shipments/merge', headers, {'request_id': str(uuid4()),
        'shipment_ids': [r['id'] for r in records], 'expected_versions': {r['id']: r['lines_version'] for r in records}}, 200)
    assert len(merged['lines']) == 2 and len(merged['purchase_order_ids']) == 2
    factory = system['app'].state.database.session
    tick(factory)
    tasks = client.get('/api/v1/tasks', params={'group': 'all', 'source_id': merged['id'], 'source_kind': 'shipment'}).json()['items']
    assert tasks and all(t['due_date'] == '2026-10-15' for t in tasks)
    post(client, f"/shipments/{merged['id']}/dispatch", headers, {}, 200)
    tick(factory)
    for order in orders:
        tasks = client.get('/api/v1/tasks', params={'group': 'all', 'source_id': order['id'], 'source_kind': 'purchase'}).json()['items']
        assert tasks and all(t['status'] == 'completed' for t in tasks)
    post(client, f"/shipments/{merged['id']}/receive", headers, {'request_id': str(uuid4()),
        'lines': [{'line_id': line['id'], 'quantity': line['quantity']} for line in merged['lines']]}, 200)
    assert balance(client, target)['quantity'] == 50
    assert all(order_detail(client, o)['status'] == 'received' for o in orders)


def test_migration_backfills_existing_shipments(system):
    client, headers, product, supplier, _, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier)
    record = shipment(system, client, headers, product, target, 10, order=order)
    config = Config(str(Path(__file__).parents[1] / 'alembic.ini'))
    command.downgrade(config, 'a32b87d19c04')
    command.upgrade(config, 'head')
    restored = client.get(f"/api/v1/shipments/{record['id']}").json()
    assert restored['purchase_order_ids'] == [order['id']]
    assert restored['lines'] == record['lines']
    checks = inspect(system['app'].state.database.engine).get_check_constraints('shipment_lines')
    assert any('received_quantity <= quantity' in check['sqltext'] for check in checks)
    assert order_detail(client, order)['lines'][0]['unallocated_quantity'] == 90


def test_concurrent_multi_order_allocation_locks_all_parents(system):
    import pytest
    if not system['settings'].database_url.startswith('postgresql'):
        pytest.skip('PostgreSQL concurrency test')
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi.testclient import TestClient
    client, headers, product, supplier, _, _ = fixtures(system)
    orders = [purchase(system, client, headers, product, supplier, 20) for _ in range(2)]
    barrier = Barrier(2)
    def create(ids):
        with TestClient(system['app'], cookies=dict(client.cookies)) as other:
            barrier.wait(timeout=10)
            result = other.post('/api/v1/shipments', headers=headers, json={
                'request_id': str(uuid4()), 'store_id': system['ids']['a'], 'purchase_order_ids': ids})
            return result.status_code
    ids = [order['id'] for order in orders]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, [ids, ids[::-1]]))
    assert sorted(results) == [201, 409]
    assert all(order_detail(client, order)['lines'][0]['unallocated_quantity'] == 0 for order in orders)
