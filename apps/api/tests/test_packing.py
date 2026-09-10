from decimal import Decimal
from uuid import uuid4

from test_supply import fixtures, purchase, post


def test_product_packing_purchase_and_shipment_snapshot(system):
    client, headers, product, supplier, source, target = fixtures(system)
    path = f"/api/v1/products/{product['id']}"
    response = client.patch(path, headers=headers, json={'name_zh': '中文商品', 'units_per_carton': 12, 'unit_weight_kg': '0.2500'})
    assert response.status_code == 200, response.text
    assert response.json()['units_per_carton'] == 12
    order = purchase(system, client, headers, product, supplier, 49)
    line = order['lines'][0]
    assert line['product_name_zh'] == '中文商品'
    assert line['units_per_carton'] == 12
    assert Decimal(line['total_weight_kg']) == Decimal('12.25')
    body = {'request_id': str(uuid4()), 'store_id': system['ids']['a'], 'purchase_order_id': order['id'],
            'destination_warehouse_id': target['id'], 'lines': [{'product_id': product['id'], 'quantity': 25}]}
    assert client.post('/api/v1/shipments', headers=headers, json=body).status_code == 422
    body['lines'][0]['quantity'] = 24
    shipped = post(client, '/shipments', headers, body)
    assert shipped['lines'][0]['units_per_carton'] == 12
    assert shipped['lines'][0]['carton_count'] == 2
    assert client.patch(path, headers=headers, json={'units_per_carton': 5, 'unit_weight_kg': '0.5'}).status_code == 200
    assert post(client, '/shipments', headers, body)['id'] == shipped['id']
    assert client.get(f"/api/v1/shipments/{shipped['id']}").json()['lines'][0]['units_per_carton'] == 12
    assert Decimal(client.get(f"/api/v1/purchase-orders/{order['id']}").json()['lines'][0]['total_weight_kg']) == Decimal('24.5')
    body['request_id'] = str(uuid4()); body['lines'][0]['quantity'] = 25
    assert post(client, '/shipments', headers, body)['lines'][0]['units_per_carton'] == 5
    edit_path = f"/api/v1/shipments/{shipped['id']}/lines/{shipped['lines'][0]['id']}"
    assert client.patch(edit_path, headers=headers, json={'units_per_carton': 5}).status_code == 422
    response = client.patch(edit_path, headers=headers, json={'units_per_carton': 8})
    assert response.status_code == 200, response.text
    assert response.json()['lines'][0]['carton_count'] == 3
    assert client.get(path).json()['units_per_carton'] == 5
    post(client, f"/shipments/{shipped['id']}/dispatch", headers, {}, 200)
    assert client.patch(edit_path, headers=headers, json={'units_per_carton': 12}).status_code == 409


def test_packing_validation_and_missing_defaults(system):
    client, headers, product, supplier, source, target = fixtures(system)
    path = f"/api/v1/products/{product['id']}"
    for value in [0, -1, 1.5, True, 1000000001]:
        assert client.patch(path, headers=headers, json={'units_per_carton': value}).status_code == 422
    for value in ['0', '-1', '0.12345', 'NaN', 'Infinity']:
        assert client.patch(path, headers=headers, json={'unit_weight_kg': value}).status_code == 422
    assert client.patch(path, headers=headers, json={'units_per_carton': None}).status_code == 200
    order = purchase(system, client, headers, product, supplier, 13)
    body = {'request_id': str(uuid4()), 'store_id': system['ids']['a'], 'purchase_order_id': order['id'],
            'destination_warehouse_id': target['id'], 'lines': [{'product_id': product['id'], 'quantity': 12}]}
    assert client.post('/api/v1/shipments', headers=headers, json=body).status_code == 422
    body['lines'][0]['units_per_carton'] = 6
    result = post(client, '/shipments', headers, body)
    assert result['lines'][0]['units_per_carton'] == 6
    assert client.get(path).json()['units_per_carton'] is None


def test_legacy_packing_scope_and_partial_receipts(system):
    from conftest import login
    from app.supply.models import ShipmentLine
    from test_supply import shipment, receive
    client, headers, product, supplier, source, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier, 24)
    record = shipment(system, client, headers, product, target, 24, order=order)
    line_id = record['lines'][0]['id']
    edit_path = f"/api/v1/shipments/{record['id']}/lines/{line_id}"
    with system['app'].state.database.session() as db:
        db.get(ShipmentLine, line_id).units_per_carton = None
        db.commit()
    assert client.post(f"/api/v1/shipments/{record['id']}/dispatch", headers=headers, json={'request_id': str(uuid4())}).status_code == 422
    for value in [0, -1, 1.5, True, None]:
        assert client.patch(edit_path, headers=headers, json={'units_per_carton': value}).status_code == 422
    assert client.patch(f"/api/v1/shipments/{record['id']}/lines/missing", headers=headers, json={'units_per_carton': 12}).status_code == 404
    headers = login(client, 'finance')
    assert client.patch(edit_path, headers=headers, json={'units_per_carton': 12}).status_code == 403
    # A warehouse user may manage shipments, but only in their assigned stores.
    from app.models import User
    with system['app'].state.database.session() as db:
        user = db.get(User, system['ids']['finance']); user.role = 'warehouse'; db.commit()
    headers = login(client, 'finance')
    assert client.patch(edit_path, headers=headers, json={'units_per_carton': 12}).status_code == 404
    headers = login(client)
    assert client.patch(edit_path, headers=headers, json={'units_per_carton': 12}).status_code == 200
    post(client, f"/shipments/{record['id']}/dispatch", headers, {}, 200)
    received = receive(client, headers, record, 1)
    assert received['lines'][0]['received_quantity'] == 1
    assert received['lines'][0]['units_per_carton'] == 12
    assert client.patch(edit_path, headers=headers, json={'units_per_carton': 8}).status_code == 409


def test_warehouse_invalid_cartons_do_not_reserve_stock(system):
    from test_supply import balance
    client, headers, product, supplier, source, target = fixtures(system)
    assert client.patch(f"/api/v1/products/{product['id']}", headers=headers, json={'units_per_carton': 12}).status_code == 200
    post(client, '/inventory/adjustments', headers, {'request_id': str(uuid4()), 'store_id': system['ids']['a'],
        'warehouse_id': source['id'], 'product_id': product['id'], 'quantity': 25, 'kind': 'opening', 'reason': '包装测试'})
    body = {'request_id': str(uuid4()), 'store_id': system['ids']['a'], 'source_warehouse_id': source['id'],
        'destination_warehouse_id': target['id'], 'lines': [{'product_id': product['id'], 'quantity': 25}]}
    assert client.post('/api/v1/shipments', headers=headers, json=body).status_code == 422
    assert balance(client, source)['reserved'] == 0
    body['lines'][0]['quantity'] = 24
    result = post(client, '/shipments', headers, body)
    assert balance(client, source)['reserved'] == 24
    assert result['lines'][0]['units_per_carton'] == 12


def test_migration_preserves_existing_products_and_shipments(system):
    from alembic import command
    from alembic.config import Config
    from pathlib import Path
    from sqlalchemy import text
    from test_supply import shipment
    client, headers, product, supplier, source, target = fixtures(system)
    order = purchase(system, client, headers, product, supplier, 13)
    record = shipment(system, client, headers, product, target, 12, order=order)
    config = Config(str(Path(__file__).parents[1] / 'alembic.ini'))
    command.downgrade(config, '48b7a65dc109')
    with system['app'].state.database.engine.connect() as connection:
        assert connection.scalar(text('SELECT quantity FROM shipment_lines WHERE id=:id'), {'id': record['lines'][0]['id']}) == 12
    command.upgrade(config, 'head')
    migrated = client.get(f"/api/v1/shipments/{record['id']}").json()
    assert migrated['lines'][0]['units_per_carton'] is None
    assert migrated['lines'][0]['quantity'] == 12
    assert migrated['status'] == 'planned'
    assert client.get(f"/api/v1/products/{product['id']}").json()['units_per_carton'] is None
    assert client.get(f"/api/v1/purchase-orders/{order['id']}").json()['lines'][0]['quantity'] == 13
