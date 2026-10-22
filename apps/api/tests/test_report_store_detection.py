from sqlalchemy import select

from app.models import Product, Store
from app.reports.models import BrandAdAllocation, ReportImport
from conftest import login
from test_brand_ads import brand, brand_file
from test_report_parsers import ad, ads_file, sale, sales_file
from test_reports import confirm, preview


def catalog(system):
    with system['app'].state.database.session() as db:
        for key in ('a', 'b'):
            db.get(Store, system['ids'][key]).brand = f'brand-{key}'
            db.add(Product(internal_sku=f'SKU-{key.upper()}', name=f'Product {key}',
                           asin=f'ASIN-{key.upper()}', brand=f'brand-{key}'))
        db.commit()


def automatic(system, content, kind='sales', headers=None, filename=None):
    headers = headers or login(system['client'])
    response = system['client'].post('/api/v1/report-imports/preview', headers=headers,
        data={'kind': kind}, files={'file': (filename or ('report.txt' if kind == 'sales' else 'report.xlsx'), content)})
    assert response.status_code == 201, response.text
    return response.json(), headers


def test_catalog_detection_sales_ads_and_shared_asin(system):
    catalog(system)
    c = system['client']
    # ASIN can identify a Seller SKU that differs from the internal SKU.
    p, h = automatic(system, sales_file([sale(sku='seller-alias', asin='ASIN-A')]))
    assert p['store_id'] == system['ids']['a'] and p['store_name'] == '测试甲店'
    assert confirm(c, p, h).status_code == 200
    p, _ = automatic(system, ads_file([ad(广告SKU='SKU-B', 广告ASIN='ASIN-B')]), 'ads', h)
    assert p['store_id'] == system['ids']['b']
    assert confirm(c, p, h).status_code == 200
    with system['app'].state.database.session() as db:
        db.scalar(select(Product).where(Product.internal_sku == 'SKU-B')).asin = 'ASIN-A'
        db.commit()
    p, _ = automatic(system, sales_file([sale(sku='SKU-A', asin='ASIN-A')]), headers=h)
    assert p['store_id'] == system['ids']['a']


def test_history_and_brand_campaign_detection(system):
    c = system['client']
    historical, h = preview(system, sales_file([sale()]))
    assert confirm(c, historical, h).status_code == 200
    p, _ = automatic(system, ads_file([ad()]), 'ads', h)
    assert p['store_id'] == system['ids']['a']
    with system['app'].state.database.session() as db:
        db.add(BrandAdAllocation(store_id=system['ids']['b'], campaign='品牌活动', allocations=[]))
        db.commit()
    p, _ = automatic(system, brand_file([brand()]), 'ads', h)
    assert p['store_id'] == system['ids']['b']
    assert confirm(c, p, h).status_code == 200
    with system['app'].state.database.session() as db:
        db.scalar(select(BrandAdAllocation)).is_deleted = True
        db.commit()
    p, _ = automatic(system, brand_file([brand()]), 'ads', h)
    assert p['store_id'] == system['ids']['b']  # Confirmed history still identifies ownership.


def test_unresolved_preview_is_retained_blocked_scoped_and_deletable(system):
    c = system['client']
    h = login(c, 'operator')
    p, _ = automatic(system, sales_file([sale()]), headers=h, filename='TEST_A.txt')
    assert p['store_id'] is None and p['store_name'] is None
    assert p['counts']['create'] == 0 and p['counts']['error'] == 1
    path = f"/api/v1/report-imports/{p['id']}"
    assert c.get(path, headers=h).json()['can_confirm'] is False
    rows = c.get(path + '/rows', headers=h).json()['items']
    assert rows[0]['data']['sku'] == 'SKU-A'
    assert rows[0]['action'] == 'error' and '未找到所属店铺' in rows[0]['message']
    assert confirm(c, p, h).status_code == 409
    assert c.get('/api/v1/sales-records', headers=h).json()['total'] == 0
    for query in ('', f"?store_id={system['ids']['a']}"):
        assert c.get('/api/v1/report-imports' + query, headers=h).json()['total'] == 1
    other = login(c, 'finance')
    assert c.get(path, headers=other).status_code == 404
    assert c.get(path + '/rows', headers=other).status_code == 404
    assert c.get(path + '/deletion-preview', headers=other).status_code == 404
    assert c.get('/api/v1/report-imports', headers=other).json()['total'] == 0
    assert c.request('DELETE', path, headers=other, json={'verification_token': '0' * 64}).status_code == 404
    h = login(c, 'operator')
    token = c.get(path + '/deletion-preview', headers=h).json()['verification_token']
    removed = c.request('DELETE', path, headers=h, json={'verification_token': token})
    assert removed.status_code == 200 and removed.json()['deletion_result']['deleted_rows'] == 0
    assert c.get('/api/v1/report-imports', headers=h).json()['total'] == 0
    assert c.get('/api/v1/report-imports?show_deleted=true', headers=h).json()['total'] == 1
    assert c.get(path + '/rows', headers=h).json()['items'][0]['data']['sku'] == 'SKU-A'


def test_mixed_unmatched_conflicting_and_ambiguous_files_are_not_assigned(system):
    catalog(system)
    h = login(system['client'])
    for rows in (
        [sale(sku='SKU-A', asin='ASIN-A'), sale(sku='SKU-B', asin='ASIN-B')],
        [sale(sku='SKU-A', asin='ASIN-B')],
        [sale(sku='SKU-A', asin='ASIN-A'), sale(sku='unknown', asin='unknown')],
    ):
        p, _ = automatic(system, sales_file(rows), headers=h)
        assert p['store_id'] is None
        assert confirm(system['client'], p, h).status_code == 409
    with system['app'].state.database.session() as db:
        db.get(Store, system['ids']['b']).brand = 'brand-a'
        db.commit()
    # Even when only one of two matching stores is authorized, do not guess.
    h = login(system['client'], 'operator')
    p, _ = automatic(system, sales_file([sale(sku='SKU-A', asin='ASIN-A')]), headers=h)
    assert p['store_id'] is None


def test_permissions_inactive_stores_empty_reports_and_aliases(system):
    catalog(system)
    c = system['client']
    h = login(c, 'operator')
    p, _ = automatic(system, sales_file([sale(sku='SKU-B', asin='ASIN-B')]), headers=h)
    assert p['store_id'] is None
    with system['app'].state.database.session() as db:
        db.get(Store, system['ids']['a']).is_active = False
        db.commit()
    p, _ = automatic(system, sales_file([sale(sku='SKU-A', asin='ASIN-A')]), headers=h)
    assert p['store_id'] is None
    empty = c.post('/api/v1/report-imports/preview', headers=h, data={'kind': 'sales'},
                   files={'file': ('empty.txt', sales_file([]))})
    assert empty.status_code == 422
    p, _ = automatic(system, sales_file([sale(quantity='invalid')]), headers=h)
    assert p['store_id'] is None and confirm(c, p, h).status_code == 409
    with system['app'].state.database.session() as db:
        db.get(Store, system['ids']['a']).is_active = True
        db.scalar(select(Product).where(Product.internal_sku == 'SKU-A')).internal_sku = 'CMBQ-L-250S'
        db.commit()
    p, _ = automatic(system, sales_file([sale(sku='CMBQ-XL-250S', asin='unknown')]), headers=h)
    assert p['store_id'] == system['ids']['a']
    with system['app'].state.database.session() as db:
        batch = db.get(ReportImport, p['id'])
        assert batch.store_id == system['ids']['a']


def test_migration_preserves_existing_imports_and_facts(system):
    from pathlib import Path
    from alembic import command
    from alembic.config import Config

    c = system['client']
    p, h = preview(system, sales_file([sale()]))
    assert confirm(c, p, h).status_code == 200
    config = Config(str(Path(__file__).parents[1] / 'alembic.ini'))
    command.downgrade(config, '12ac904bf831')
    command.upgrade(config, 'head')
    assert c.get(f"/api/v1/report-imports/{p['id']}", headers=h).json()['store_id'] == system['ids']['a']
    assert c.get('/api/v1/sales-records', headers=h).json()['total'] == 1
    missing, _ = automatic(system, sales_file([sale(sku='unknown', asin='unknown')]), headers=h)
    assert missing['store_id'] is None
