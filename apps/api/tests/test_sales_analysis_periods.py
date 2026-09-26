from datetime import date
from decimal import Decimal

import pytest

from conftest import login
from test_ad_daily import daily
from test_brand_ads import brand, brand_file, configure
from test_report_parsers import sale
from test_reports import preview, confirm
from test_sales_analysis import analysis, cost, imported
from app.reports.analysis_periods import period_start, period_end


def periods(system, headers, **params):
    response = system['client'].get('/api/v1/sales-analysis/periods', headers=headers, params={
        'store_id': system['ids']['a'], 'sku': 'SKU-A', 'start_date': '2025-09-25',
        'end_date': '2025-09-29', **params})
    assert response.status_code == 200, response.text
    return response.json()


def test_daily_pdt_cost_versions_empty_days_ads_and_scope(system):
    c = system['client']
    h = imported(system, [sale(**{'purchase-date': '2025-09-26T06:59:59Z'}),
        sale(**{'amazon-order-id': 'NEXT', 'purchase-date': '2025-09-26T07:00:00Z'}),
        sale(**{'amazon-order-id': 'UTC-NEXT', 'purchase-date': '2025-09-27T06:59:59Z'}),
        sale(**{'amazon-order-id': 'CANCEL', 'order-status': 'Cancelled'}),
        sale(**{'amazon-order-id': 'PENDING', 'order-status': 'Pending', 'item-status': 'Unshipped'})])
    imported(system, [sale()], h=h, store=system['ids']['b'])
    imported(system, [daily(日期='2025-09-25', 花费=1), daily(日期='2025-09-26', 花费=2),
        daily(日期='2025-09-27', 花费=3), daily(日期='2025-09-28', 广告SKU='OTHER', 花费=4)], 'ads', h)
    cost(c, h, product_cost='1', inbound_fee='0', fba_fee='2')
    cost(c, h, effective_from='2025-09-27', product_cost='3', inbound_fee='0', fba_fee='4')
    rows = periods(system, h)['items']
    assert [r['period_start'] for r in rows] == [f'2025-09-{day}' for day in range(25, 30)]
    assert [r['quantity'] for r in rows] == [2, 4, 0, 0, 0]
    assert [r['product_cost'] for r in rows] == ['2.00', '8.00', '0.00', '0.00', '0.00']
    assert rows[1]['fba_fee'] == '12.00' and rows[1]['cost_versions'] == 2
    assert [r['ad_spend'] for r in rows] == ['1.00', '2.00', '3.00', '0.00', None]
    assert rows[2]['actual_profit'] == '-3.00' and rows[2]['actual_profit_rate'] == '0.000000'
    assert rows[4]['actual_profit'] is None
    total = analysis(c, h, store_id=system['ids']['a'], start_date='2025-09-25', end_date='2025-09-29')['items'][0]
    assert sum(Decimal(r['sales']) for r in rows) == Decimal(total['sales'])
    assert periods(system, h, order_scope='non_cancelled')['items'][1]['quantity'] == 6
    assert periods(system, h, start_date='2025-09-26', end_date='2025-09-26')['items'][0]['quantity'] == 4


@pytest.mark.parametrize(('granularity', 'ranges'), [
    ('week', [('2025-12-28', '2025-12-28'), ('2025-12-29', '2026-01-04'), ('2026-01-05', '2026-01-05')]),
    ('month', [('2025-12-28', '2025-12-31'), ('2026-01-01', '2026-01-05')]),
    ('year', [('2025-12-28', '2025-12-31'), ('2026-01-01', '2026-01-05')]),
])
def test_calendar_buckets_clip_range_and_recalculate_margin(system, granularity, ranges):
    c = system['client']
    h = imported(system, [sale(**{'amazon-order-id': str(i), 'purchase-date': f'{day}T07:00:00Z',
        'last-updated-date': f'{day}T08:00:00Z', 'item-price': amount})
        for i, (day, amount) in enumerate([('2025-12-28', '10'), ('2026-01-02', '100'), ('2026-01-06', '1000')])])
    cost(c, h, product_cost='0', inbound_fee='0', fba_fee='0')
    imported(system, [daily(日期='2025-12-28', 花费=10), daily(日期='2026-01-02', 花费=0)], 'ads', h)
    params = dict(start_date='2025-12-28', end_date='2026-01-05', granularity=granularity)
    rows = periods(system, h, **params)['items']
    assert [(r['period_start'], r['period_end']) for r in rows] == ranges
    assert sum(Decimal(r['sales']) for r in rows) == Decimal('110.00')
    assert rows[0]['actual_profit_rate'] == '-0.150000'
    assert rows[1]['actual_profit_rate'] == '0.850000'
    page = periods(system, h, **params, limit=1, offset=1)
    assert page['total'] == len(rows) and page['items'] == [rows[1]]


def test_week_margin_uses_aggregated_amounts_and_alias_currency(system):
    c = system['client']
    h = imported(system, [sale(sku='CMBQ-M-250S', currency='CAD', **{'item-price': '13.6'}),
        sale(sku='CMBQ-XL-250S', **{'amazon-order-id': 'SECOND', 'purchase-date': '2025-09-27T07:00:00Z', 'item-price': '100'})])
    cost(c, h, sku='CMBQ-L-250S', product_cost='0', inbound_fee='0', fba_fee='0')
    imported(system, [daily(日期='2025-09-26', 广告SKU='CMBQ-S-250S', 货币='CAD', 花费='13.6'),
        daily(日期='2025-09-27', 广告SKU='CMBQ-L-250S', 花费=0)], 'ads', h)
    row = periods(system, h, sku='CMBQ-L-250S', granularity='week')['items'][0]
    assert row['quantity'] == 4 and row['sales'] == '110.00' and row['ad_spend'] == '10.00'
    assert row['actual_profit_rate'] == '0.759091'
    assert periods(system, h, sku='CMBQ-L-250S', granularity='week', cad_per_usd='2.72')['items'][0]['sales'] == '105.00'


def test_brand_ads_pending_is_scoped_to_period_then_allocated(system):
    h = imported(system, [sale()])
    cost(system['client'], h)
    imported(system, [daily(日期='2025-09-26', 花费=2)], 'ads', h)
    p, _ = preview(system, brand_file([brand(日期='2025-09-27', 花费=10)]), 'ads', h)
    assert confirm(system['client'], p, h).status_code == 200
    rows = periods(system, h)['items']
    assert rows[1]['ad_spend'] == '2.00' and rows[2]['ad_spend'] is None
    assert configure(system, h).status_code == 200
    rows = periods(system, h)['items']
    assert rows[1]['ad_spend'] == '2.00' and rows[2]['ad_spend'] == '6.00'
    assert rows[2]['quantity'] == 0 and rows[2]['actual_profit'] == '-6.00'


def test_period_validation_permissions_unbounded_and_missing_cost(system):
    c = system['client']
    h = imported(system, [sale()])
    assert periods(system, h)['items'][1]['product_cost'] is None
    all_dates = c.get(
        '/api/v1/sales-analysis/periods', headers=h, params={'store_id': system['ids']['a'], 'sku': 'SKU-A', 'granularity': 'year'})
    assert all_dates.status_code == 200 and all_dates.json()['total'] == 1
    base = {'store_id': system['ids']['a'], 'sku': 'SKU-A'}
    for params in [{'granularity': 'quarter'}, {'sku': ''}, {'start_date': '2025-09-29', 'end_date': '2025-09-25'}, {'cad_per_usd': '0'}]:
        assert c.get('/api/v1/sales-analysis/periods', headers=h, params=base | params).status_code == 422
    assert c.get('/api/v1/sales-analysis/periods', headers=login(c, 'finance'), params=base).status_code == 404
    assert c.get('/api/v1/sales-analysis/periods', headers=login(c, 'operator'), params=base).status_code == 403


def test_leap_month_and_week_boundaries():
    assert period_start(date(2024, 2, 29), 'month') == date(2024, 2, 1)
    assert period_end(date(2024, 2, 1), 'month') == date(2024, 2, 29)
    assert period_start(date(2026, 1, 1), 'week') == date(2025, 12, 29)
