import assert from 'node:assert/strict';
import test from 'node:test';
import { SALES_UTC_OFFSET_MINUTES, salesReportTime } from '../src/sales-report-time.ts';
import { reportDateRange } from '../src/report-date-ranges.ts';

test('PDT 显示全年固定减七小时，跨日跨年均正确', () => {
  assert.equal(salesReportTime('2026-09-19T06:59:59+00:00'), '2026-09-18 23:59:59');
  assert.equal(salesReportTime('2026-09-19T07:00:00Z'), '2026-09-19 00:00:00');
  assert.equal(salesReportTime('2026-01-01T06:00:00Z'), '2025-12-31 23:00:00');
  assert.equal(salesReportTime('2026-01-15T07:00:00Z'), '2026-01-15 00:00:00');
  assert.equal(salesReportTime('2026-11-01T09:30:00Z'), '2026-11-01 02:30:00');
  assert.equal(salesReportTime(null), '—');
});

test('销售快捷日期使用 PDT 的今天，不使用电脑时区或冬令时', () => {
  for (const [instant, day] of [
    ['2026-09-19T06:59:59Z', '2026-09-18'], ['2026-09-19T07:00:00Z', '2026-09-19'],
    ['2026-01-15T07:30:00Z', '2026-01-15'], ['2026-01-01T06:30:00Z', '2025-12-31'],
  ]) {
    assert.deepEqual(reportDateRange('today', new Date(instant), true, SALES_UTC_OFFSET_MINUTES), { start: day, end: day });
  }
  const now = new Date('2026-09-01T06:00:00Z');
  assert.deepEqual(reportDateRange('thisMonth', now, true, SALES_UTC_OFFSET_MINUTES), { start: '2026-08-01', end: '2026-08-31' });
  assert.deepEqual(reportDateRange('last3', now, false, SALES_UTC_OFFSET_MINUTES), { start: '2026-08-28', end: '2026-08-30' });
});
