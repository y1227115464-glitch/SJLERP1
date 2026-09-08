from test_report_parsers import AD_HEADERS, ad, ads_file
from test_reports import preview, confirm

DAILY_HEADERS = ['日期', *AD_HEADERS[2:]]


def daily(**changes):
    return {key: value for key, value in ad(**changes).items() if key not in ('开始日期', '结束日期')} | {'日期': changes.get('日期', '2026-06-01')}


def daily_file(rows):
    return ads_file(rows, headers=DAILY_HEADERS)


def test_daily_parser_date_identity_and_last_row_wins():
    from app.reports.parsers import parse_report
    source = [daily(), daily(广告ASIN='B999999999', 货币='CAD', 花费=8), daily(日期='2026-06-02')]
    result = parse_report('ads', daily_file(source))
    assert not result['errors'] and result['duplicate_count'] == 1
    assert len(result['rows']) == 2
    assert result['rows'][0]['row'] == 3
    assert result['rows'][0]['data']['spend'] == '8.0000'
    assert result['rows'][0]['data']['report_date'] == '2026-06-01'
    assert result['rows'][0]['data']['start_date'] == result['rows'][0]['data']['end_date']
    one_day = parse_report('ads', ads_file([ad(结束日期='2026-06-01')]))
    assert one_day['rows'][0]['key'] == parse_report('ads', daily_file([daily()]))['rows'][0]['key']
    assert parse_report('ads', daily_file([daily(日期='2026-02-30')]))['errors']
    conflict = ads_file([ad(日期='2026-06-02')], headers=['日期', *AD_HEADERS])
    assert parse_report('ads', conflict)['errors']


def test_daily_import_overwrites_attributes_and_keeps_other_keys(system):
    c = system['client']
    rows = [daily(), daily(日期='2026-06-02'), daily(广告SKU='SKU-B'), daily(广告活动名称='第二活动'), daily(广告组名称='第二组')]
    first, h = preview(system, daily_file(rows), 'ads')
    assert confirm(c, first, h).json()['result']['created'] == 5
    new, _ = preview(system, daily_file([daily(广告ASIN='B999999999', 广告组合名称='新组合', 货币='CAD', **{'国家/地区': '加拿大'}, 零售商='其他', 花费=8)]), 'ads', h)
    assert new['counts'] == {'create': 0, 'update': 1, 'skip': 0, 'conflict': 0}
    assert confirm(c, new, h).json()['result']['updated'] == 1
    result = c.get('/api/v1/ad-records', headers=h).json()
    assert result['total'] == 5
    changed = [r for r in result['items'] if r['currency'] == 'CAD'][0]
    assert changed['spend'] == '8.0000' and changed['asin'] == 'B999999999'
    assert changed['import_id'] == new['id'] and changed['source_row'] == 2
    assert c.get('/api/v1/ad-records?start_date=2026-06-02&end_date=2026-06-02', headers=h).json()['total'] == 1
    again, _ = preview(system, daily_file([daily(广告ASIN='B999999999', 广告组合名称='新组合', 货币='CAD', **{'国家/地区': '加拿大'}, 零售商='其他', 花费=8)]), 'ads', h)
    assert confirm(c, again, h).json()['result']['skipped'] == 1
    other, _ = preview(system, daily_file([daily()]), 'ads', h, store=system['ids']['b'])
    assert confirm(c, other, h).json()['result']['created'] == 1


def test_daily_and_legacy_period_are_separate_and_old_preview_reuploads(system):
    from app.reports.models import ReportImport
    c = system['client']
    period, h = preview(system, ads_file([ad(花费=30)]), 'ads')
    assert confirm(c, period, h).status_code == 200
    day, _ = preview(system, daily_file([daily(花费=2)]), 'ads', h)
    assert confirm(c, day, h).status_code == 200
    assert c.get('/api/v1/ad-records', headers=h).json()['total'] == 1
    assert c.get('/api/v1/ad-records/summary', headers=h).json()['groups'][0]['spend'] == '2.0000'
    assert c.get('/api/v1/ad-records/summary?granularity=period', headers=h).json()['groups'][0]['spend'] == '30.0000'
    pending, _ = preview(system, daily_file([daily(花费=9)]), 'ads', h)
    with system['app'].state.database.session() as db:
        db.get(ReportImport, pending['id']).parser_version = 'amazon-v1'
        db.commit()
    detail = c.get(f"/api/v1/report-imports/{pending['id']}", headers=h).json()
    assert detail['counts']['conflict'] == 1
    assert confirm(c, detail, h).status_code == 409


def test_daily_newer_identical_upload_blocks_older_changed_preview(system):
    c = system['client']
    original, h = preview(system, daily_file([daily(花费=3)]), 'ads')
    assert confirm(c, original, h).status_code == 200
    old, _ = preview(system, daily_file([daily(花费=8)]), 'ads', h)
    newer, _ = preview(system, daily_file([daily(花费=3)]), 'ads', h)
    assert confirm(c, newer, h).json()['result']['skipped'] == 1
    refreshed = c.get(f"/api/v1/report-imports/{old['id']}", headers=h).json()
    assert refreshed['counts']['conflict'] == 1 and confirm(c, refreshed, h).status_code == 409
    assert c.get('/api/v1/ad-records/summary', headers=h).json()['groups'][0]['spend'] == '3.0000'


def test_postgres_daily_concurrent_different_users_and_asins(system):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    import pytest
    from fastapi.testclient import TestClient
    from conftest import login
    if system['app'].state.database.engine.dialect.name != 'postgresql':
        pytest.skip('PostgreSQL daily identity store locking')
    c = system['client']
    first, h1 = preview(system, daily_file([daily()]), 'ads')
    cookie1 = dict(c.cookies)
    c.cookies.clear()  # A second browser login must not revoke the first browser's session.
    h2 = login(c, 'operator')
    second, _ = preview(system, daily_file([daily(广告ASIN='B999999999', 花费=8)]), 'ads', h2)
    cookie2 = dict(c.cookies)
    gate = Barrier(2)
    def run(args):
        batch, headers, cookies = args
        with TestClient(system['app']) as client:
            client.cookies.update(cookies)
            gate.wait()
            return confirm(client, batch, headers).status_code
    with ThreadPoolExecutor(2) as pool:
        statuses = list(pool.map(run, [(first, h1, cookie1), (second, h2, cookie2)]))
    assert sorted(statuses) == [200, 409]
    refreshed = c.get(f"/api/v1/report-imports/{second['id']}", headers=h2).json()
    if refreshed['result'] is None:
        assert confirm(c, refreshed, h2).status_code == 200
    assert c.get('/api/v1/ad-records', headers=h2).json()['total'] == 1
    assert c.get('/api/v1/ad-records/summary', headers=h2).json()['groups'][0]['spend'] == '8.0000'


def test_daily_migration_deduplicates_existing_days_and_keeps_periods(system):
    from datetime import date, datetime, timezone
    from pathlib import Path
    from uuid import uuid4
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import MetaData, Table, insert, select
    from app.reports.parsers import ad_row, ad_keys, fingerprint
    config = Config(str(Path(__file__).parents[1] / 'alembic.ini'))
    command.downgrade(config, 'de1aefc77089')
    engine = system['app'].state.database.engine
    imported = datetime.now(timezone.utc)
    batch_id = str(uuid4())
    with engine.begin() as db:
        batches = Table('report_imports', MetaData(), autoload_with=db)
        records = Table('ad_records', MetaData(), autoload_with=db)
        source_rows, values = [], []
        for i, raw in enumerate([ad(结束日期='2026-06-01'), ad(结束日期='2026-06-01', 广告ASIN='B999999999', 花费=8), ad()]):
            _, _, data = ad_row(raw)
            data.pop('report_date', None)
            key, identity = ad_keys(data)
            source_rows.append({'row': i + 2, 'key': key, 'identity': identity, 'hash': fingerprint(data), 'data': data})
            fields = ['campaign', 'ad_group', 'sku', 'asin', 'country', 'currency', 'impressions', 'clicks', 'spend', 'attributed_sales', 'orders', 'units']
            values.append({**{field: data[field] for field in fields}, 'id': str(uuid4()), 'store_id': system['ids']['a'],
                'natural_key': key, 'identity_key': identity, 'value_hash': fingerprint(data), 'data': data,
                'import_id': batch_id, 'source_row': i + 2, 'latest_report_at': imported,
                'start_date': date.fromisoformat(data['start_date']), 'end_date': date.fromisoformat(data['end_date'])})
        db.execute(insert(batches), {'id': batch_id, 'store_id': system['ids']['a'], 'owner_id': system['ids']['admin'],
            'kind': 'ads', 'filename': 'legacy.xlsx', 'file_hash': 'a' * 64, 'storage_key': str(uuid4()), 'parser_version': 'amazon-v1',
            'parsed_rows': source_rows, 'errors': [], 'duplicate_count': 0, 'source_total': 3, 'row_count': 3, 'error_count': 0,
            'result': {'created': 3, 'updated': 0, 'skipped': 0, 'file_duplicates': 0}, 'created_at': imported, 'confirmed_at': imported})
        db.execute(insert(records), values)
    command.upgrade(config, 'head')
    with engine.connect() as db:
        records = Table('ad_records', MetaData(), autoload_with=db)
        rows = db.execute(select(records)).mappings().all()
        assert len(rows) == 2
        day = [row for row in rows if row['report_date']][0]
        assert day['asin'] == 'B999999999' and day['source_row'] == 3
        assert day['data']['spend'] == '8.0000'
        assert day['natural_key'] == ad_keys(day['data'])[0]
        assert day['value_hash'] == fingerprint(day['data'])
        assert db.scalar(select(batches.c.row_count)) == 3
