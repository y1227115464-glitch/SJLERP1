import assert from 'node:assert/strict';
import test from 'node:test';
import { reportDateRange } from '../src/report-date-ranges.ts';

test('九个快捷区间包含今天，当前周期截止今天', () => {
  const now = new Date(2026, 8, 8, 0, 30);
  const expected = {
    last7: ['2026-09-02', '2026-09-08'], last3: ['2026-09-06', '2026-09-08'], today: ['2026-09-08', '2026-09-08'],
    last30: ['2026-08-10', '2026-09-08'], thisWeek: ['2026-09-07', '2026-09-08'], lastWeek: ['2026-08-31', '2026-09-06'],
    thisMonth: ['2026-09-01', '2026-09-08'], lastMonth: ['2026-08-01', '2026-08-31'], thisYear: ['2026-01-01', '2026-09-08'],
  };
  for (const [preset, [start, end]] of Object.entries(expected)) {
    assert.deepEqual(reportDateRange(preset, now), { start, end }, preset);
  }
  assert.equal(now.getDate(), 8, '不修改传入日期');
});

test('周日属于本周，周一和上周可以跨年', () => {
  assert.deepEqual(reportDateRange('thisWeek', new Date(2026, 8, 6)), { start: '2026-08-31', end: '2026-09-06' });
  assert.deepEqual(reportDateRange('thisWeek', new Date(2026, 0, 5)), { start: '2026-01-05', end: '2026-01-05' });
  assert.deepEqual(reportDateRange('lastWeek', new Date(2026, 0, 5)), { start: '2025-12-29', end: '2026-01-04' });
});

test('上月跨年、闰年二月与月末日期正确', () => {
  assert.deepEqual(reportDateRange('lastMonth', new Date(2026, 0, 1)), { start: '2025-12-01', end: '2025-12-31' });
  assert.deepEqual(reportDateRange('lastMonth', new Date(2024, 2, 31)), { start: '2024-02-01', end: '2024-02-29' });
  assert.deepEqual(reportDateRange('lastMonth', new Date(2025, 2, 31)), { start: '2025-02-01', end: '2025-02-28' });
  assert.deepEqual(reportDateRange('thisYear', new Date(2026, 0, 1)), { start: '2026-01-01', end: '2026-01-01' });
});

test('按本地日历计算最近天数，跨年与夏令时不偏移一天', () => {
  assert.deepEqual(reportDateRange('last7', new Date(2026, 0, 2, 0, 30)), { start: '2025-12-27', end: '2026-01-02' });
  assert.deepEqual(reportDateRange('last3', new Date(2026, 2, 9, 0, 30)), { start: '2026-03-07', end: '2026-03-09' });
  assert.deepEqual(reportDateRange('last3', new Date(2026, 10, 2, 23, 30)), { start: '2026-10-31', end: '2026-11-02' });
  assert.deepEqual(reportDateRange('today', new Date(2026, 8, 8, 23, 30)), { start: '2026-09-08', end: '2026-09-08' });
});

test('取消含当天时最近 N 天截至昨天，固定周期和今天不受影响', () => {
  const now = new Date(2026, 8, 8);
  assert.deepEqual(reportDateRange('last3', now, false), { start: '2026-09-05', end: '2026-09-07' });
  assert.deepEqual(reportDateRange('last7', now, false), { start: '2026-09-01', end: '2026-09-07' });
  assert.deepEqual(reportDateRange('last30', now, false), { start: '2026-08-09', end: '2026-09-07' });
  assert.deepEqual(reportDateRange('last3', new Date(2026, 0, 1), false), { start: '2025-12-29', end: '2025-12-31' });
  for (const preset of ['today', 'thisWeek', 'lastWeek', 'thisMonth', 'lastMonth', 'thisYear']) {
    assert.deepEqual(reportDateRange(preset, now, false), reportDateRange(preset, now, true), preset);
  }
});
