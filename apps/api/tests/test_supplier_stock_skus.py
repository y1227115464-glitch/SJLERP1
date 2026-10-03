from uuid import uuid4

from conftest import login
from test_supply import fixtures, post, purchase, allow_purchase
from test_supplier_stock import body, stock_list


def skus(client, **params):
    response = client.get('/api/v1/supplier-stock/skus', params=params)
    assert response.status_code == 200, response.text
    return response.json()


def hold(client, headers, order, quantity):
    post(client, f"/purchase-orders/{order['id']}/supplier-stock", headers, body(order, quantity))
    return next(row for row in stock_list(client)['items'] if row['purchase_order_id'] == order['id'])


def test_sku_aggregates_batches_suppliers_and_current_balances_before_paging(system):
    client, headers, product, supplier, source, target = fixtures(system)
    other = post(client, '/suppliers', headers, {'code': 'OTHER', 'name': '另一供应商'})
    allow_purchase(system, client, headers, product, other)
    second = post(client, '/products', headers, {'internal_sku': 'ZZ-SECOND', 'name': '第二商品', 'units_per_carton': 1})
    allow_purchase(system, client, headers, second, supplier)
    first_order = purchase(system, client, headers, product, supplier, 100)
    first = hold(client, headers, first_order, 40)
    hold(client, headers, purchase(system, client, headers, product, supplier, 100), 30)
    hold(client, headers, purchase(system, client, headers, product, other, 100), 20)
    empty = hold(client, headers, purchase(system, client, headers, product, other, 100), 5)
    hold(client, headers, purchase(system, client, headers, second, supplier, 100), 7)
    for stock, quantity in [(first, 15), (empty, 5)]:
        post(client, f"/supplier-stock/{stock['id']}/release", headers,
             {'request_id': str(uuid4()), 'quantity': quantity, 'reason': '安排发货'}, 200)
    result = skus(client, limit=1)
    assert result['total'] == 2
    assert result['items'] == [{'id': product['id'], 'internal_sku': product['internal_sku'], 'product_name': product['name'],
                               'quantity': 75, 'batches': 3, 'suppliers': 2}]
    assert skus(client, limit=1, offset=1)['items'][0]['quantity'] == 7
    assert skus(client, supplier_id=other['id'])['items'][0]['quantity'] == 20
    assert skus(client, supplier_id=supplier['id'], q=product['internal_sku'])['items'][0]['quantity'] == 55
    assert skus(client, q=other['name'])['items'][0]['quantity'] == 20
    assert skus(client, q=first_order['number'])['items'][0]['quantity'] == 25
    assert skus(client, q='missing')['total'] == 0
    assert client.patch(f"/api/v1/products/{product['id']}", headers=headers, json={'name_zh': '中文标签纸'}).status_code == 200
    assert skus(client, q='中文标签纸')['items'][0]['quantity'] == 75
    assert skus(client, q='中文标签纸')['items'][0]['product_name'] == '中文标签纸'
    batches = stock_list(client, {'product_id': product['id']})
    assert batches['total'] == 3
    assert sum(row['remaining_quantity'] for row in batches['items']) == 75
    assert stock_list(client, {'product_id': product['id'], 'include_empty': True})['total'] == 4
    assert stock_list(client, {'product_id': second['id']})['total'] == 1
    assert stock_list(client, {'product_id': product['id'], 'supplier_id': other['id']})['total'] == 1


def test_sku_store_scope_is_applied_before_aggregation(system):
    client, headers, product, supplier, source, target = fixtures(system)
    hold(client, headers, purchase(system, client, headers, product, supplier, 100), 20)
    # Move brand ownership while retaining historical stock in the first store.
    assert client.patch(f"/api/v1/stores/{system['ids']['a']}", headers=headers,
                        json={'brand': '原店铺品牌'}).status_code == 200
    assert client.patch(f"/api/v1/stores/{system['ids']['b']}", headers=headers,
                        json={'brand': '供应链测试品牌'}).status_code == 200
    second_store = post(client, '/purchase-orders', headers, {'request_id': str(uuid4()),
        'store_id': system['ids']['b'], 'supplier_id': supplier['id'], 'order_date': '2026-10-03',
        'already_ordered': True, 'lines': [{'product_id': product['id'], 'quantity': 100, 'unit_price': '2'}]})
    hold(client, headers, second_store, 9)
    assert skus(client)['items'][0]['quantity'] == 29
    assert skus(client, store_id=system['ids']['a'])['items'][0]['quantity'] == 20
    login(client, 'finance')
    assert skus(client)['items'][0]['quantity'] == 9
    assert skus(client, store_id=system['ids']['a'])['total'] == 0
    assert stock_list(client, {'product_id': product['id']})['total'] == 1
    login(client, 'operator')
    assert client.get('/api/v1/supplier-stock/skus').status_code == 403
