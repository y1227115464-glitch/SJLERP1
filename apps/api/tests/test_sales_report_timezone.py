from datetime import date, timedelta

import pytest

from test_report_parsers import sale
from test_sales_analysis import analysis, imported
from test_ad_daily import daily


@pytest.mark.parametrize('day', ['2026-09-18', '2026-01-15', '2026-03-08', '2026-11-01', '2026-12-31'])
def test_fixed_pdt_boundaries_consistent_across_orders_summary_analysis_and_suggestions(system, day):
    c = system['client']
    tomorrow = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    timestamps = [f'{day}T06:59:59+00:00', f'{day}T07:00:00+00:00',
                  f'{tomorrow}T06:59:59+00:00', f'{tomorrow}T07:00:00+00:00']
    rows = [sale(**{'amazon-order-id': f'ORDER-{i}', 'sku': f'SKU-{i}', 'quantity': '1',
                    'purchase-date': stamp, 'last-updated-date': stamp, 'item-price': '10'}) for i, stamp in enumerate(timestamps)]
    h = imported(system, rows)
    params = {'start_date': day, 'end_date': day}
    result = c.get('/api/v1/sales-records', headers=h, params=params).json()
    assert result['total'] == 2
    assert {row['sku'] for row in result['items']} == {'SKU-1', 'SKU-2'}
    # The stored/exported source timestamp stays UTC; only calendar filtering changes.
    assert {row['purchase_date'] for row in result['items']} == set(timestamps[1:3])
    summary = c.get('/api/v1/sales-records/summary', headers=h, params=params).json()['groups']
    assert summary[0]['quantity'] == 2 and summary[0]['net_amount'] == '20.0000'
    result = analysis(c, h, **params)
    assert result['totals']['quantity'] == 2 and result['totals']['sales'] == '20.00'
    for endpoint in ['sales-records/suggestions', 'sales-analysis/suggestions']:
        assert c.get('/api/v1/' + endpoint, headers=h, params=params).json()['items'] == ['SKU-1', 'SKU-2']
    assert c.get('/api/v1/sales-records', headers=h, params={'start_date': day}).json()['total'] == 3
    assert c.get('/api/v1/sales-records', headers=h, params={'end_date': day}).json()['total'] == 3
    assert c.get('/api/v1/sales-records', headers=h).json()['total'] == 4


def test_multi_day_fixed_pdt_range_keeps_ad_report_dates(system):
    c = system['client']
    h = imported(system, [sale(**{'purchase-date': '2026-09-20T06:59:59Z', 'last-updated-date': '2026-09-20T07:00:00Z'})])
    imported(system, [daily(日期='2026-09-19', 花费=3), daily(日期='2026-09-20', 花费=8)], 'ads', h)
    result = analysis(c, h, start_date='2026-09-18', end_date='2026-09-19')
    assert result['totals']['quantity'] == 2 and result['totals']['ad_spend'] == '3.00'
    assert c.get('/api/v1/sales-records?start_date=2026-09-19&end_date=2026-09-18', headers=h).status_code == 422
    assert c.get('/api/v1/sales-records?end_date=9999-12-31', headers=h).status_code == 422
