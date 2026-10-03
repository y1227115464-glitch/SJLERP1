from uuid import uuid4

from conftest import login
from test_supply import fixtures, post, purchase
from test_supplier_stock import body, stock_list
from test_purchase_transfer import current


def prepare(system, quantity=20, held=20):
    client, headers, product, supplier, source, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier, quantity)
    post(client, f"/purchase-orders/{order['id']}/supplier-stock", headers, body(order, held))
    stock = stock_list(client)['items'][0]
    return client, headers, product, order, stock


def item(product, stock, quantity):
    return {'product_id': product['id'], 'supplier_stock_id': stock['id'], 'quantity': quantity}


def create(client, headers, order, lines, **extra):
    payload = {'request_id': str(uuid4()), 'store_id': order['store_id'], 'lines': lines, **extra}
    record = post(client, '/shipments', headers, payload)
    assert post(client, '/shipments', headers, payload)['id'] == record['id']
    return record


def amend(client, headers, record, lines, status=200, **extra):
    payload = {'request_id': str(uuid4()), 'expected_version': record['lines_version'], 'lines': lines, **extra}
    response = client.patch(f"/api/v1/shipments/{record['id']}/lines", headers=headers, json=payload)
    assert response.status_code == status, response.text
    if status == 200:
        assert client.patch(f"/api/v1/shipments/{record['id']}/lines", headers=headers, json=payload).status_code == 200
    return response.json()


def test_stock_only_closed_order_amend_cancel_and_retry(system):
    client, headers, product, order, stock = prepare(system)
    assert current(client, order)['status'] == 'closed'
    record = create(client, headers, order, [item(product, stock, 12)])
    line = record['lines'][0]
    assert line['supplier_stock_id'] == stock['id']
    assert line['purchase_line_id'] == stock['purchase_line_id']
    assert line['supplier_stock_remaining_quantity'] == 8
    assert current(client, order)['lines'][0]['unallocated_quantity'] == 0
    assert current(client, order)['status'] == 'ordered'
    record = amend(client, headers, record, [item(product, stock, 6)])
    assert stock_list(client)['items'][0]['remaining_quantity'] == 14
    record = amend(client, headers, record, [item(product, stock, 20)])
    assert stock_list(client)['total'] == 0
    assert record['lines'][0]['supplier_stock_remaining_quantity'] == 0
    post(client, f"/shipments/{record['id']}/cancel", headers, {}, 200)
    assert stock_list(client)['items'][0]['remaining_quantity'] == 20
    assert current(client, order)['status'] == 'closed'
    assert current(client, order)['lines'][0]['unallocated_quantity'] == 0


def test_mixed_sources_multiple_batches_receive_and_preserve_floor(system):
    client, headers, product, order, first = prepare(system, 50, 20)
    post(client, f"/purchase-orders/{order['id']}/supplier-stock", headers, body(current(client, order), 10))
    second = next(stock for stock in stock_list(client)['items'] if stock['id'] != first['id'])
    normal = {'product_id': product['id'], 'purchase_line_id': first['purchase_line_id'], 'quantity': 20}
    lines = [normal, item(product, first, 20), item(product, second, 10)]
    record = create(client, headers, order, lines, purchase_order_ids=[order['id']])
    assert len(record['lines']) == 3
    assert current(client, order)['lines'][0]['unallocated_quantity'] == 0
    amend(client, headers, record, [{**normal, 'quantity': 21}, *lines[1:]], 409)
    record = post(client, f"/shipments/{record['id']}/dispatch", headers, {}, 200)
    stock_line = next(line for line in record['lines'] if line['supplier_stock_id'] == first['id'])
    record = post(client, f"/shipments/{record['id']}/receive", headers,
                  {'request_id': str(uuid4()), 'lines': [{'line_id': stock_line['id'], 'quantity': 5}]}, 200)
    amend(client, headers, record, [normal, item(product, first, 4), lines[2]], 409)
    record = amend(client, headers, record, [normal, item(product, first, 5), lines[2]])
    assert stock_list(client)['items'][0]['remaining_quantity'] == 15
    record = post(client, f"/shipments/{record['id']}/receive", headers,
                  {'request_id': str(uuid4()), 'lines': [{'line_id': line['id'], 'quantity': line['quantity'] - line['received_quantity']}
                             for line in record['lines'] if line['quantity'] > line['received_quantity']]}, 200)
    assert record['status'] == 'received'
    fresh = current(client, order)
    assert fresh['lines'][0]['received_quantity'] == 35
    assert fresh['lines'][0]['supplier_stock_quantity'] == 15
    assert fresh['status'] == 'closed'


def test_overallocation_mismatch_scope_and_failure_rollback(system):
    client, headers, product, order, stock = prepare(system)
    payload = {'request_id': str(uuid4()), 'store_id': order['store_id'], 'lines': [item(product, stock, 21)]}
    assert client.post('/api/v1/shipments', headers=headers, json=payload).status_code == 409
    payload['lines'] = [item(product, stock, 10), {'product_id': product['id'], 'purchase_line_id': stock['purchase_line_id'], 'quantity': 1}]
    assert client.post('/api/v1/shipments', headers=headers, json=payload).status_code == 409
    assert stock_list(client)['items'][0]['remaining_quantity'] == 20
    payload['lines'] = [{**item(product, stock, 10), 'purchase_line_id': 'wrong'}]
    assert client.post('/api/v1/shipments', headers=headers, json=payload).status_code == 422
    payload['lines'] = [item(product, stock, 10)]
    payload['store_id'] = system['ids']['b']
    assert client.post('/api/v1/shipments', headers=headers, json=payload).status_code == 409
    finance = login(client, 'finance')
    assert client.post('/api/v1/shipments', headers=finance, json=payload).status_code in (403, 404)


def test_add_remove_new_stock_source_and_merge(system):
    client, headers, product, order, stock = prepare(system)
    # Stock-only plans can be combined without returning their allocations.
    first = create(client, headers, order, [item(product, stock, 5)])
    second = create(client, headers, order, [item(product, stock, 5)])
    merged = post(client, '/shipments/merge', headers, {'request_id': str(uuid4()), 'shipment_ids': [first['id'], second['id']],
        'expected_versions': {first['id']: first['lines_version'], second['id']: second['lines_version']}}, 200)
    assert merged['lines'][0]['quantity'] == 10
    assert merged['lines'][0]['supplier_stock_id'] == stock['id']
    assert stock_list(client)['items'][0]['remaining_quantity'] == 10
    post(client, f"/shipments/{merged['id']}/cancel", headers, {}, 200)
    assert stock_list(client)['items'][0]['remaining_quantity'] == 20


def test_amend_add_stock_from_closed_order_then_remove(system):
    client, headers, product, order, stock = prepare(system)
    supplier = {'id': stock['supplier_id']}
    other = purchase(system, client, headers, product, supplier, 10)
    normal = {'product_id': product['id'], 'purchase_line_id': other['lines'][0]['id'], 'quantity': 10}
    record = create(client, headers, other, [normal], purchase_order_ids=[other['id']])
    record = amend(client, headers, record, [normal, item(product, stock, 10)])
    assert set(record['purchase_order_ids']) == {order['id'], other['id']}
    record = amend(client, headers, record, [normal], purchase_order_ids=[other['id']])
    assert record['purchase_order_ids'] == [other['id']]
    assert stock_list(client)['items'][0]['remaining_quantity'] == 20


def test_edit_purchase_selection_excludes_stock_provenance_without_losing_stock(system):
    client, headers, product, order, stock = prepare(system)
    other = purchase(system, client, headers, product, {'id': stock['supplier_id']}, 10)
    normal = {'product_id': product['id'], 'purchase_line_id': other['lines'][0]['id'], 'quantity': 10}
    lines = [normal, item(product, stock, 10)]
    record = create(client, headers, other, lines, purchase_order_ids=[other['id']])
    original_lines = record['lines']
    for _ in range(2):
        record = amend(client, headers, record, lines, purchase_order_ids=[other['id']])
        record = client.get(f"/api/v1/shipments/{record['id']}").json()
        assert set(record['purchase_order_ids']) == {order['id'], other['id']}
        assert record['lines'] == original_lines
        assert stock_list(client)['items'][0]['remaining_quantity'] == 10
    # Removing only the direct allocation leaves a valid stock-only shipment.
    record = amend(client, headers, record, [item(product, stock, 10)], purchase_order_ids=[])
    assert record['purchase_order_ids'] == [order['id']]
    assert current(client, other)['lines'][0]['unallocated_quantity'] == 10
    record = post(client, f"/shipments/{record['id']}/dispatch", headers, {}, 200)
    record = post(client, f"/shipments/{record['id']}/receive", headers,
                  {'request_id': str(uuid4()), 'lines': [{'line_id': record['lines'][0]['id'], 'quantity': 5}]}, 200)
    record = amend(client, headers, record, [item(product, stock, 10)], purchase_order_ids=[])
    assert record['lines'][0]['received_quantity'] == 5
    assert record['purchase_order_ids'] == [order['id']]


def test_concurrent_stock_shipments_do_not_overallocate(system):
    import pytest
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi.testclient import TestClient
    if system['app'].state.database.engine.dialect.name != 'postgresql':
        pytest.skip('Requires PostgreSQL row locks')
    client, headers, product, order, stock = prepare(system)
    barrier = Barrier(2)
    def submit(_):
        with TestClient(system['app'], cookies=dict(client.cookies)) as other:
            barrier.wait(timeout=10)
            response = other.post('/api/v1/shipments', headers=headers, json={
                'request_id': str(uuid4()), 'store_id': order['store_id'], 'lines': [item(product, stock, 15)]})
            return response.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, range(2))) == [201, 409]
    assert stock_list(client)['items'][0]['remaining_quantity'] == 5
    assert current(client, order)['lines'][0]['unallocated_quantity'] == 0
