from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from app.models import Store, User
from conftest import login
from test_brand_ads import brand, brand_file
from test_report_parsers import sale, sales_file, ad, ads_file
from test_reports import confirm, preview
from test_sales_analysis import analysis, imported, cost


def deletion(c, batch, h):
    response = c.get(f"/api/v1/report-imports/{batch['id']}/deletion-preview", headers=h)
    assert response.status_code == 200, response.text
    return response.json()


def remove(c, batch, h, impact=None):
    impact = impact or deletion(c, batch, h)
    return c.request('DELETE', f"/api/v1/report-imports/{batch['id']}", headers=h,
                     json={'verification_token': impact['verification_token']})


@pytest.mark.parametrize('content,kind,endpoint', [
    (lambda: sales_file([sale()]), 'sales', 'sales-records'),
    (lambda: brand_file([brand()]), 'ads', 'ad-records'),
    (lambda: ads_file([ad()]), 'ads', 'ad-records?granularity=period'),
])
def test_deleting_batch_removes_facts_archives_source_and_allows_reupload(system, content, kind, endpoint):
    c = system['client']
    p, h = preview(system, content(), kind)
    assert confirm(c, p, h).status_code == 200
    assert deletion(c, p, h)['affected_rows'] == 1
    result = remove(c, p, h)
    assert result.status_code == 200 and result.json()['deletion_result']['deleted_rows'] == 1
    assert remove(c, p, h).json() == result.json()
    assert c.get(f'/api/v1/{endpoint}', headers=h).json()['total'] == 0
    assert c.get('/api/v1/report-imports', headers=h).json()['total'] == 0
    assert c.get('/api/v1/report-imports?show_deleted=true', headers=h).json()['total'] == 1
    detail = c.get(f"/api/v1/report-imports/{p['id']}", headers=h).json()
    assert detail['deleted_at'] and not detail['can_confirm'] and 'verification_token' not in detail
    assert c.get(f"/api/v1/report-imports/{p['id']}/rows", headers=h).json()['total'] == 1
    assert confirm(c, p, h).status_code == 409
    again, _ = preview(system, content(), kind, h)
    assert again['counts']['create'] == 1
    assert confirm(c, again, h).status_code == 200
    assert c.get(f'/api/v1/{endpoint}', headers=h).json()['total'] == 1


def test_brand_batch_deletion_clears_unallocated_warning_and_recalculates_profit(system):
    c = system['client']
    h = imported(system, [sale()])
    cost(c, h)
    before = analysis(c, h)
    p, _ = preview(system, brand_file([brand()]), 'ads', h)
    assert confirm(c, p, h).status_code == 200
    assert analysis(c, h)['excluded']['unallocated_brand_campaigns']
    assert remove(c, p, h).status_code == 200
    after = analysis(c, h)
    assert not after['excluded']['unallocated_brand_campaigns']
    assert after['totals'] == before['totals']
    assert c.get('/api/v1/ad-records/summary', headers=h).json()['groups'] == []


def test_delete_only_current_provenance_and_reject_stale_impact(system):
    c = system['client']
    first, h = preview(system, sales_file([sale(), sale(sku='SKU-B')]))
    assert confirm(c, first, h).status_code == 200
    stale = deletion(c, first, h)
    same, _ = preview(system, sales_file([sale()]), headers=h)
    assert confirm(c, same, h).status_code == 200
    assert deletion(c, same, h)['affected_rows'] == 0
    assert remove(c, same, h).status_code == 200
    assert c.get('/api/v1/sales-records', headers=h).json()['total'] == 2
    newer, _ = preview(system, sales_file([sale(quantity='3', **{'last-updated-date': '2025-09-28T00:00:00Z'})]), headers=h)
    assert confirm(c, newer, h).status_code == 200
    assert remove(c, first, h, stale).status_code == 409
    assert deletion(c, first, h)['affected_rows'] == 1
    assert remove(c, first, h).status_code == 200
    remaining = c.get('/api/v1/sales-records', headers=h).json()
    assert remaining['total'] == 1 and remaining['items'][0]['quantity'] == 3
    assert remove(c, newer, h).status_code == 200
    assert c.get('/api/v1/sales-records/summary', headers=h).json()['groups'] == []


def test_pending_error_batches_delete_without_touching_existing_data(system):
    c = system['client']
    first, h = preview(system, sales_file([sale()]))
    assert confirm(c, first, h).status_code == 200
    for rows in [[sale()], [sale(quantity='1.5')]]:
        p, _ = preview(system, sales_file(rows), headers=h)
        assert deletion(c, p, h)['affected_rows'] == 0
        assert remove(c, p, h).status_code == 200
        assert confirm(c, p, h).status_code == 409
        assert c.get(f"/api/v1/report-imports/{p['id']}/rows", headers=h).json()['total'] == 1
    assert c.get('/api/v1/sales-records', headers=h).json()['total'] == 1


def test_confirm_after_delete_preview_requires_new_deletion_preview(system):
    c = system['client']
    p, h = preview(system, sales_file([sale()]))
    impact = deletion(c, p, h)
    assert confirm(c, p, h).status_code == 200
    assert remove(c, p, h, impact).status_code == 409
    assert c.get('/api/v1/sales-records', headers=h).json()['total'] == 1
    assert remove(c, p, h).status_code == 200


def test_deletion_scope_permissions_and_inactive_store(system):
    c = system['client']
    p, h = preview(system, sales_file([sale()]))
    assert confirm(c, p, h).status_code == 200
    impact = deletion(c, p, h)
    other = login(c, 'finance')
    assert c.get(f"/api/v1/report-imports/{p['id']}/deletion-preview", headers=other).status_code == 404
    assert remove(c, p, other, impact).status_code == 404
    op = login(c, 'operator')
    with system['app'].state.database.session() as db:
        db.get(User, system['ids']['operator']).role = 'warehouse'
        db.commit()
    assert remove(c, p, op, impact).status_code == 403
    h = login(c)
    with system['app'].state.database.session() as db:
        db.get(Store, system['ids']['a']).is_active = False
        db.commit()
    assert remove(c, p, h, impact).status_code == 409
    assert c.get('/api/v1/sales-records', headers=h).json()['total'] == 1


def test_postgres_concurrent_confirmation_and_deletion(system):
    if system['app'].state.database.engine.dialect.name != 'postgresql':
        pytest.skip('PostgreSQL store locking concurrency')
    c = system['client']
    p, h = preview(system, sales_file([sale()]))
    impact = deletion(c, p, h)
    barrier = Barrier(2)
    def run(action):
        with TestClient(system['app']) as separate:
            separate.cookies.update(c.cookies)
            barrier.wait()
            return (confirm(separate, p, h) if action == 'confirm' else remove(separate, p, h, impact)).status_code
    with ThreadPoolExecutor(2) as pool:
        statuses = list(pool.map(run, ['confirm', 'delete']))
    assert sorted(statuses) == [200, 409]
    batch = c.get(f"/api/v1/report-imports/{p['id']}", headers=h).json()
    assert c.get('/api/v1/sales-records', headers=h).json()['total'] == (0 if batch['deleted_at'] else 1)
