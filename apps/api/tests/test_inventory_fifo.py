from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select

from app.supply.fifo import allocate
from app.supply.models import InventoryMovement
from conftest import login
from test_report_parsers import sale, sales_file
from test_reports import confirm, preview
from test_report_deletion import remove
from test_sales_analysis import imported
from test_supply import fixtures, post


def movement(identifier, quantity, day, warehouse='fba', hour=12):
    return SimpleNamespace(id=identifier, quantity=quantity, warehouse_id=warehouse, reference_number='IN-' + identifier,
                           created_at=datetime(2025, 9, day, hour, tzinfo=timezone.utc))


def test_fifo_cross_lots_days_and_exact_exhaustion():
    result = allocate([movement('b', 5, 26), movement('a', 3, 25), movement('c', 7, 27)],
                      [('2025-09-25', 2), ('2025-09-26', 6)])
    assert result['consumed_quantity'] == 8
    assert result['remaining_quantity'] == 7
    assert result['current_lot']['movement_id'] == 'c'
    assert result['daily'][1]['allocations'] == [
        {key: result['lots'][i][key] for key in ['movement_id', 'reference_number', 'created_at']} | {'quantity': quantity}
        for i, quantity in [(0, 1), (1, 5)]]
    assert [lot['is_current'] for lot in result['lots']] == [False, False, True]
    assert allocate([movement('a', 3, 25)], [('2025-09-25', 3)])['current_lot'] is None


def test_shortage_never_uses_future_receipts_and_prior_orders_are_visible():
    result = allocate([movement('a', 3, 25), movement('b', 10, 27)],
                      [('2025-09-24', 20), ('2025-09-25', 5), ('2025-09-26', 2), ('2025-09-27', 1)])
    assert result['ignored_order_quantity'] == 20
    assert result['order_quantity'] == 8
    assert result['shortage_quantity'] == 4
    assert result['remaining_quantity'] == 9
    assert result['current_lot']['movement_id'] == 'b'
    assert result['daily'][1]['allocations'] == []
    empty = allocate([], [('2025-09-24', 2)])
    assert empty['shortage_quantity'] == 2 and empty['current_lot'] is None


def test_adjustments_reservations_and_warehouse_outbound_do_not_double_consume():
    result = allocate([movement('a', 5, 25, 'one'), movement('b', 10, 25, 'two'),
                       movement('reserve', 0, 25, 'one'), movement('out', -4, 26, 'two'),
                       movement('correction', 2, 27, 'one')], [('2025-09-26', 7)])
    assert [lot['remaining_quantity'] for lot in result['lots']] == [0, 4, 2]
    assert result['other_consumed_quantity'] == 4
    assert result['consumed_quantity'] == 7
    assert result['current_lot']['movement_id'] == 'b'
    conflict = allocate([movement('a', 5, 25), movement('out', -3, 27)], [('2025-09-26', 4)])
    assert conflict['other_shortage_quantity'] == 2
    assert conflict['remaining_quantity'] == 0


def test_daily_pdt_boundary_and_deterministic_same_time_order():
    # 06:00 UTC is still the previous PDT day. Same timestamps use movement ID.
    result = allocate([movement('b', 3, 26, hour=6), movement('a', 2, 26, hour=6)], [('2025-09-25', 3)])
    assert result['start_date'] == '2025-09-25'
    assert [lot['movement_id'] for lot in result['lots']] == ['a', 'b']
    assert result['current_lot']['movement_id'] == 'b'
    assert result['remaining_quantity'] == 2


def setup_stock(system):
    c, h, product, _, domestic, fba = fixtures(system)
    for warehouse, quantity, day in [(fba, 3, 25), (fba, 10, 26), (domestic, 100, 25)]:
        saved = post(c, '/inventory/adjustments', h, {'request_id': str(uuid4()), 'store_id': system['ids']['a'],
            'warehouse_id': warehouse['id'], 'product_id': product['id'], 'quantity': quantity, 'reason': 'FIFO 测试'})
        with system['app'].state.database.session() as db:
            record = db.scalar(select(InventoryMovement).where(InventoryMovement.reference_id == saved['id']))
            record.created_at = datetime(2025, 9, day, 12, tzinfo=timezone.utc)
            db.commit()
    return c, h, product, fba


def fifo(c, **params):
    r = c.get('/api/v1/inventory/fifo', params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_import_reimport_correction_deletion_and_movement_pagination(system):
    c, h, product, fba = setup_stock(system)
    data = sales_file([sale(sku=product['internal_sku'], quantity='5')])
    batch, _ = preview(system, data, headers=h)
    assert confirm(c, batch, h).status_code == 200
    row = fifo(c)['items'][0]
    assert (row['order_quantity'], row['consumed_quantity'], row['remaining_quantity']) == (5, 5, 8)
    again, _ = preview(system, data, headers=h)
    assert confirm(c, again, h).status_code == 200
    assert fifo(c)['items'][0] == row
    daily = c.get('/api/v1/inventory/fifo/daily', params={'store_id': system['ids']['a'], 'product_id': product['id']}).json()
    assert daily['total'] == 1
    assert [lot['quantity'] for lot in daily['items'][0]['allocations']] == [3, 2]
    page = c.get('/api/v1/inventory/movements', params={'warehouse_kind': 'fba', 'kind': 'adjustment', 'limit': 1}).json()
    assert page['total'] == 2
    assert page['items'][0]['fifo']['remaining_quantity'] == 8
    assert page['items'][0]['fifo']['is_current']
    # Query and FIFO computation never mutate the physical ledger or balance.
    assert c.get('/api/v1/inventory/summary', params={'warehouse_kind': 'fba'}).json()['quantity'] == 13
    corrected, _ = preview(system, sales_file([sale(sku=product['internal_sku'], quantity='9',
        **{'last-updated-date': '2025-09-28T00:00:00Z'})]), headers=h)
    assert confirm(c, corrected, h).status_code == 200
    assert fifo(c)['items'][0]['remaining_quantity'] == 4
    assert remove(c, corrected, h).status_code == 200
    assert fifo(c)['items'][0]['remaining_quantity'] == 13
    assert fifo(c)['items'][0]['current_lot']['quantity'] == 3


def test_status_exact_sku_store_scope_and_fba_channel(system):
    c, h, product, _ = setup_stock(system)
    rows = [sale(sku=product['internal_sku'], quantity='2', **{'amazon-order-id': 'OK'}),
            sale(sku=product['internal_sku'], quantity='3', **{'amazon-order-id': 'PARTIAL', 'order-status': 'Partially Shipped'})]
    for key, changes in [('cancel', {'order-status': 'Cancelled'}), ('item', {'item-status': 'Cancelled'}),
                         ('pending', {'order-status': 'Pending', 'item-status': 'Unshipped'}),
                         ('merchant', {'fulfillment-channel': 'Merchant'}), ('alias', {'sku': product['internal_sku'] + '-OTHER'})]:
        rows.append(sale(sku=product['internal_sku'], quantity='100', **{'amazon-order-id': key}) | changes)
    imported(system, rows, h=h)
    imported(system, [sale(sku=product['internal_sku'], quantity='100')], h=h, store=system['ids']['b'])
    assert fifo(c)['items'][0]['order_quantity'] == 5
    login(c, 'finance')
    assert fifo(c)['total'] == 0
    assert fifo(c, store_id=system['ids']['a'])['total'] == 0
    assert c.get('/api/v1/inventory/fifo/daily', params={'store_id': system['ids']['a'], 'product_id': product['id']}).status_code == 404
    login(c, 'operator')
    assert fifo(c)['items'][0]['order_quantity'] == 5
    imported(system, [sale(sku=product['internal_sku'], quantity='2', **{'amazon-order-id': 'OK',
        'order-status': 'Cancelled', 'last-updated-date': '2025-09-28T00:00:00Z'})], h=login(c))
    assert fifo(c)['items'][0]['order_quantity'] == 3
