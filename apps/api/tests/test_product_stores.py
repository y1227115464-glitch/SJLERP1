from sqlalchemy import select

from app.models import Product, Store
from app.product_scope import ProductStore
from conftest import login
from test_supply import fixtures


def test_brand_ownership_is_read_only_and_ignores_legacy_switches(system):
    client, headers, product, supplier, _, _ = fixtures(system)
    a, b = system['ids']['a'], system['ids']['b']
    with system['app'].state.database.session() as db:
        db.add_all([ProductStore(store_id=a, product_id=product['id'], is_active=False),
                    ProductStore(store_id=b, product_id=product['id'], is_active=True)])
        db.commit()
    path = f"/api/v1/products/{product['id']}/stores"
    result = client.get(path)
    assert result.status_code == 200
    assert result.json() == {'brand': '供应链测试品牌', 'items': [
        {'store_id': a, 'store_name': '测试甲店', 'store_active': True}]}
    for store_id in (a, b):
        for active in (False, True):
            result = client.put(f'{path}/{store_id}', headers=headers, json={'is_active': active})
            assert result.status_code == 409
            assert result.json()['error']['code'] == 'store_ownership_read_only'
    with system['app'].state.database.session() as db:
        rows = db.scalars(select(ProductStore)).all()
        assert {row.store_id: row.is_active for row in rows} == {a: False, b: True}
    params = {'store_id': a, 'supplier_id': supplier['id'], 'is_active': True}
    assert client.get('/api/v1/products', params=params).json()['total'] == 1
    assert client.get('/api/v1/products', params={**params, 'store_id': b}).json()['total'] == 0
    login(client, 'operator')
    assert client.get(path).json()['items'][0]['store_id'] == a
    login(client, 'finance')
    assert client.get(path).json()['items'] == []


def test_missing_unmatched_and_duplicate_brand_do_not_assign_a_store(system):
    client, headers, product, _, _, _ = fixtures(system)
    path = f"/api/v1/products/{product['id']}/stores"
    for brand in ('', '无对应店铺品牌'):
        assert client.patch(f"/api/v1/products/{product['id']}", headers=headers, json={'brand': brand}).status_code == 200
        assert client.get(path).json() == {'brand': brand, 'items': []}
        assert client.get('/api/v1/products', params={'store_id': system['ids']['b']}).json()['total'] == 0
    with system['app'].state.database.session() as db:
        db.get(Product, product['id']).brand = '供应链测试品牌'
        db.get(Store, system['ids']['b']).brand = '供应链测试品牌'
        db.commit()
    assert client.get(path).status_code == 409
    for store in ('a', 'b'):
        assert client.get('/api/v1/products', params={'store_id': system['ids'][store]}).json()['total'] == 0
    # A duplicate outside the user's scope must not create a false unique match.
    login(client, 'operator')
    assert client.get(path).status_code == 409


def test_inactive_store_still_displays_ownership_and_brand_changes_refresh_it(system):
    client, headers, product, _, _, _ = fixtures(system)
    path = f"/api/v1/products/{product['id']}/stores"
    assert client.patch(f"/api/v1/stores/{system['ids']['a']}", headers=headers,
                        json={'is_active': False}).status_code == 200
    assert client.get(path).json()['items'] == [
        {'store_id': system['ids']['a'], 'store_name': '测试甲店', 'store_active': False}]
    assert client.patch(f"/api/v1/stores/{system['ids']['a']}", headers=headers,
                        json={'brand': '新品牌'}).status_code == 200
    assert client.get(path).json()['items'] == []
    assert client.patch(f"/api/v1/products/{product['id']}", headers=headers,
                        json={'brand': '新品牌'}).status_code == 200
    assert client.get(path).json()['items'][0]['store_id'] == system['ids']['a']
    assert client.get('/api/v1/products/not-a-product/stores').status_code == 404
