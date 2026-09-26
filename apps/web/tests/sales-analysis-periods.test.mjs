import assert from 'node:assert/strict';
import test from 'node:test';
import { defaultSalesGranularity } from '../src/sales-analysis-periods.ts';

test('SKU 明细按包含起止日的天数选择默认粒度', () => {
  for (const [days, expected] of [[1, 'day'], [14, 'day'], [15, 'week'], [30, 'week'], [31, 'month'], [180, 'month'], [181, 'year']]) {
    const start = '2024-12-25';
    const end = new Date(Date.parse(`${start}T00:00:00Z`) + (days - 1) * 86400000).toISOString().slice(0, 10);
    assert.equal(defaultSalesGranularity(start, end), expected, `${days} days`);
  }
  assert.equal(defaultSalesGranularity('2024-02-16', '2024-03-01'), 'week');
  assert.equal(defaultSalesGranularity('', ''), 'year');
  assert.equal(defaultSalesGranularity('2025-01-01', ''), 'year');
});
