from uuid import uuid4

import pytest

from app.tasks.scheduler import tick
from test_supply import fixtures, post, purchase, shipment, balance
from test_multi_purchase_shipments import order_detail


def change(client, headers, record, orders, quantities=None, status=200, body=None):
    body = body or {'request_id': str(uuid4()), 'expected_version': record['lines_version'],
        'purchase_order_ids': [order['id'] for order in orders],
        'lines': [{'product_id': line['product_id'], 'purchase_line_id': line['id'],
                   'quantity': (quantities or {}).get(line['id'], 10), 'units_per_carton': 1}
                  for order in orders for line in order['lines']]}
    result = client.patch(f"/api/v1/shipments/{record['id']}/lines", headers=headers, json=body)
    assert result.status_code == status, result.text
    return result.json(), body


def test_add_remove_sources_reallocate_and_reconcile_tasks(system):
    client, headers, product, supplier, _, target = fixtures(system)
    post(client, '/task-rules/templates', headers, {'request_id': str(uuid4()), 'templates': ['dispatch']})
    a, b = [purchase(system, client, headers, product, supplier, 20) for _ in range(2)]
    for order, day in [(a, '2026-10-20'), (b, '2026-10-15')]:
        post(client, f"/purchase-orders/{order['id']}/schedule", headers,
             {'request_id': str(uuid4()), 'planned_ship_date': day}, 200)
    record = shipment(system, client, headers, product, target, 20, order=a)
    factory = system['app'].state.database.session
    tick(factory)
    def tasks(kind, identifier):
        return client.get('/api/v1/tasks', params={'group': 'all', 'source_kind': kind, 'source_id': identifier}).json()['items']
    assert tasks('purchase', a['id'])[0]['suppressed']
    original_id = record['lines'][0]['id']
    record, body = change(client, headers, record, [a, b], {a['lines'][0]['id']: 20})
    assert record['lines'][0]['id'] == original_id
    assert len(record['purchase_order_ids']) == 2
    assert [order_detail(client, order)['lines'][0]['unallocated_quantity'] for order in [a, b]] == [0, 10]
    replay, _ = change(client, headers, record, [], body=body)
    assert replay['lines_version'] == record['lines_version']
    tick(factory)
    assert tasks('shipment', record['id'])[0]['due_date'] == '2026-10-15'
    previous = record
    record, _ = change(client, headers, record, [b])
    assert record['purchase_order_ids'] == [b['id']] and record['purchase_order_id'] == b['id']
    assert order_detail(client, a)['lines'][0]['unallocated_quantity'] == 20
    assert client.get('/api/v1/shipments', params={'purchase_order_id': a['id']}).json()['total'] == 0
    change(client, headers, previous, [a, b], status=409)
    tick(factory)
    assert not tasks('purchase', a['id'])[0]['suppressed']
    record = post(client, f"/shipments/{record['id']}/dispatch", headers, {}, 200)
    record = post(client, f"/shipments/{record['id']}/receive", headers, {'request_id': str(uuid4()),
        'lines': [{'line_id': record['lines'][0]['id'], 'quantity': 10}]}, 200)
    assert balance(client, target)['quantity'] == 10
    assert order_detail(client, b)['lines'][0]['received_quantity'] == 10
    assert order_detail(client, a)['lines'][0]['received_quantity'] == 0


def test_received_source_cannot_be_removed_but_new_orders_can_be_added(system):
    client, headers, product, supplier, _, target = fixtures(system)
    a, b = [purchase(system, client, headers, product, supplier, 20) for _ in range(2)]
    record = shipment(system, client, headers, product, target, 10, order=a)
    post(client, f"/shipments/{record['id']}/dispatch", headers, {}, 200)
    record = post(client, f"/shipments/{record['id']}/receive", headers,
        {'request_id': str(uuid4()), 'lines': [{'line_id': record['lines'][0]['id'], 'quantity': 4}]}, 200)
    result, _ = change(client, headers, record, [b], status=409)
    assert result['error']['code'] == 'received_purchase_locked'
    record, _ = change(client, headers, record, [a, b])
    original = next(line for line in record['lines'] if line['purchase_line_id'] == a['lines'][0]['id'])
    assert original['received_quantity'] == 4
    assert balance(client, target)['quantity'] == 4
    assert order_detail(client, a)['lines'][0]['received_quantity'] == 4
    assert order_detail(client, b)['lines'][0]['received_quantity'] == 0


def test_source_validation_rolls_back_and_version_covers_empty_source_changes(system):
    from app.supply.models import PurchaseOrder
    client, headers, product, supplier, source, target = fixtures(system)
    a, b = [purchase(system, client, headers, product, supplier, 20) for _ in range(2)]
    record = shipment(system, client, headers, product, target, 10, order=a)
    change(client, headers, record, [b], {b['lines'][0]['id']: 21}, status=409)
    change(client, headers, record, [b, b], status=422)
    change(client, headers, record, [], status=422)
    with system['app'].state.database.session() as db:
        db.get(PurchaseOrder, b['id']).store_id = system['ids']['b']
        db.commit()
    change(client, headers, record, [b], status=409)
    with system['app'].state.database.session() as db:
        row = db.get(PurchaseOrder, b['id'])
        row.store_id, row.status = system['ids']['a'], 'draft'
        db.commit()
    change(client, headers, record, [b], status=409)
    with system['app'].state.database.session() as db:
        db.get(PurchaseOrder, b['id']).status = 'ordered'
        db.commit()
    assert order_detail(client, a)['lines'][0]['unallocated_quantity'] == 10
    assert order_detail(client, b)['lines'][0]['unallocated_quantity'] == 20
    body = {'request_id': str(uuid4()), 'expected_version': record['lines_version'],
            'purchase_order_ids': [a['id'], b['id']],
            'lines': [{'product_id': product['id'], 'purchase_line_id': a['lines'][0]['id'], 'quantity': 10}]}
    updated, _ = change(client, headers, record, [], body=body)
    assert updated['lines_version'] != record['lines_version']
    change(client, headers, record, [a], status=409)
    post(client, '/inventory/adjustments', headers, {'request_id': str(uuid4()), 'store_id': system['ids']['a'],
         'warehouse_id': source['id'], 'product_id': product['id'], 'quantity': 20, 'kind': 'opening', 'reason': '测试'})
    warehouse = shipment(system, client, headers, product, target, 10, source=source)
    change(client, headers, warehouse, [a], status=422)
    assert balance(client, source)['reserved'] == 10


def test_concurrent_new_source_allocation_is_serialized(system):
    if not system['settings'].database_url.startswith('postgresql'):
        pytest.skip('PostgreSQL concurrency test')
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi.testclient import TestClient
    client, headers, product, supplier, _, target = fixtures(system)
    a, b = [purchase(system, client, headers, product, supplier, 20) for _ in range(2)]
    record = shipment(system, client, headers, product, target, 10, order=a)
    barrier = Barrier(2)
    def submit(edit):
        with TestClient(system['app'], cookies=dict(client.cookies)) as other:
            body = {'request_id': str(uuid4()), 'lines': [{'product_id': product['id'], 'purchase_line_id': b['lines'][0]['id'], 'quantity': 20}],
                    'purchase_order_ids': [b['id']]}
            if edit:
                body['expected_version'] = record['lines_version']
            else:
                body.update(store_id=system['ids']['a'], destination_warehouse_id=target['id'])
            barrier.wait(timeout=10)
            result = other.request('PATCH' if edit else 'POST', f"/api/v1/shipments/{record['id']}/lines" if edit else '/api/v1/shipments', headers=headers, json=body)
            return result.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, [True, False]))
    assert sorted(results) in [[200, 409], [201, 409]]
    assert order_detail(client, b)['lines'][0]['unallocated_quantity'] == 0
    assert order_detail(client, a)['lines'][0]['unallocated_quantity'] in [10, 20]
