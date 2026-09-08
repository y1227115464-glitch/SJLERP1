import pytest

from conftest import login
from test_ad_daily import daily, daily_file
from test_report_parsers import ad, ads_file, sale, sales_file
from test_reports import preview, confirm


@pytest.mark.parametrize('kind', ['sales', 'ads'])
def test_sku_suggestions_are_unique_match_literals_and_search_exactly(system, kind):
    c = system['client']
    rows = ([sale(sku='SKU-A'), sale(sku='SKU-AB'), sale(sku='SKU_%'),
             sale(sku='SKU-A', **{'amazon-order-id': '222-1234567-1234567'})] if kind == 'sales' else
            [daily(广告SKU='SKU-A'), daily(广告SKU='SKU-AB'), daily(广告SKU='SKU_%'), daily(广告SKU='SKU-A', 广告组名称='另一组')])
    batch, h = preview(system, (sales_file if kind == 'sales' else daily_file)(rows), kind)
    assert confirm(c, batch, h).status_code == 200
    route = '/api/v1/sales-records' if kind == 'sales' else '/api/v1/ad-records'
    result = c.get(route + '/suggestions', headers=h).json()
    assert result == {'items': ['SKU-A', 'SKU-AB', 'SKU_%'], 'has_more': False}
    assert c.get(route + '/suggestions', headers=h, params={'q': 'sku-a'}).json()['items'] == ['SKU-A', 'SKU-AB']
    assert c.get(route + '/suggestions', headers=h, params={'q': '%'}).json()['items'] == ['SKU_%']
    assert c.get(route + '/suggestions', headers=h, params={'q': 'missing'}).json()['items'] == []
    assert c.get(route + '/suggestions', headers=h, params={'limit': 1}).json() == {'items': ['SKU-A'], 'has_more': True}
    assert c.get(route + '/suggestions', headers=h, params={'limit': 101}).status_code == 422
    assert c.get(route + '/suggestions', headers=h, params={'q': 'a' * 201}).status_code == 422
    exact = c.get(route, headers=h, params={'sku': 'SKU-A'}).json()
    assert exact['total'] == 2 and {row['sku'] for row in exact['items']} == {'SKU-A'}
    assert sum(group['rows'] for group in c.get(route + '/summary', headers=h, params={'sku': 'SKU-A'}).json()['groups']) == 2
    assert c.get(route, headers=h, params={'q': 'SKU-A'}).json()['total'] == 3


def test_suggestions_follow_store_dates_status_granularity_and_permissions(system):
    from app.models import User
    c = system['client']
    batch, h = preview(system, sales_file([sale(sku='SHIPPED'), sale(sku='PENDING', **{'order-status': 'Pending'})]))
    assert confirm(c, batch, h).status_code == 200
    batch, _ = preview(system, daily_file([daily(广告SKU='DAILY')]), 'ads', h)
    assert confirm(c, batch, h).status_code == 200
    batch, _ = preview(system, ads_file([ad(广告SKU='PERIOD')]), 'ads', h)
    assert confirm(c, batch, h).status_code == 200
    batch, _ = preview(system, sales_file([sale(sku='OTHER_STORE')]), headers=h, store=system['ids']['b'])
    assert confirm(c, batch, h).status_code == 200
    h = login(c, 'operator')
    sales = '/api/v1/sales-records/suggestions'
    ads = '/api/v1/ad-records/suggestions'
    assert c.get(sales, headers=h).json()['items'] == ['PENDING', 'SHIPPED']
    assert c.get(sales, headers=h, params={'status': 'Pending'}).json()['items'] == ['PENDING']
    assert c.get(sales, headers=h, params={'start_date': '2025-09-27'}).json()['items'] == []
    assert c.get(sales, headers=h, params={'store_id': system['ids']['b']}).json()['items'] == []
    assert c.get(ads, headers=h).json()['items'] == ['DAILY']
    assert c.get(ads, headers=h, params={'granularity': 'period'}).json()['items'] == ['PERIOD']
    assert c.get(ads, headers=h, params={'start_date': '2026-06-02'}).json()['items'] == []
    assert c.get(ads, headers=h, params={'start_date': '2026-06-02', 'end_date': '2026-06-01'}).status_code == 422
    with system['app'].state.database.session() as db:
        db.get(User, system['ids']['operator']).role = 'warehouse'
        db.commit()
    assert c.get(sales, headers=h).status_code == 403
    assert c.get(ads, headers=h).status_code == 403
