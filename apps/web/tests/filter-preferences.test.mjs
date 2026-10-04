import assert from 'node:assert/strict';
import test from 'node:test';
import { readSelectedStore, saveSelectedStore, readSalesDates, saveSalesDates } from '../src/filter-preferences.ts';

test('店铺全局保存，销售分析恢复具体日期、快捷区间和全部日期', () => {
  const values = new Map();
  globalThis.localStorage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
  try {
    assert.equal(readSelectedStore(), null);
    assert.equal(readSalesDates(), null);
    saveSelectedStore('store-a');
    const range = { start: '2026-09-01', end: '2026-09-30', preset: 'lastMonth' };
    saveSalesDates(range);
    assert.equal(readSelectedStore(), 'store-a');
    assert.deepEqual(readSalesDates(), range);
    saveSelectedStore('store-b');
    assert.deepEqual(readSalesDates(), range);
    saveSalesDates({ start: '', end: '' });
    assert.deepEqual(readSalesDates(), { start: '', end: '' });
    for (const invalid of ['{', 'null', '{"start":"2026-02-30","end":"2026-03-01"}', '{"start":"2026-10-04","end":"2026-10-01"}']) {
      values.set('sjlerp:sales-analysis:dates', invalid);
      assert.equal(readSalesDates(), null);
    }
  } finally { delete globalThis.localStorage; }
});

test('浏览器禁止本地存储时仍可正常使用筛选', () => {
  globalThis.localStorage = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } };
  try {
    assert.equal(readSelectedStore(), null);
    assert.equal(readSalesDates(), null);
    assert.doesNotThrow(() => saveSelectedStore('all'));
    assert.doesNotThrow(() => saveSalesDates({ start: '', end: '' }));
  } finally { delete globalThis.localStorage; }
});
