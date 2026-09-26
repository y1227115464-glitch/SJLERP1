import assert from 'node:assert/strict';
import test from 'node:test';
import { salesCurrencySummary } from '../src/sales-currency-summary.ts';

test('合并同币种不同状态，保留原币种并将 USD 排在首位', () => {
  const groups = [
    { currency: 'CAD', rows: 1, quantity: 1, net_amount: '77.5100', missing_amount_rows: 0 },
    { currency: 'USD', order_status: 'Shipped', rows: 10, quantity: 12, net_amount: '154468.6200', missing_amount_rows: 0 },
    { currency: 'USD', order_status: 'Pending', rows: 2, quantity: 3, net_amount: '25.3300', missing_amount_rows: 0 },
    { currency: 'CAD', rows: 22, quantity: 25, net_amount: '458.5600', missing_amount_rows: 0 },
  ];
  const before = structuredClone(groups);
  assert.deepEqual(salesCurrencySummary(groups), [
    { currency: 'USD', rows: 12, quantity: 15, net_amount: '154,493.95', missing_amount_rows: 0 },
    { currency: 'CAD', rows: 23, quantity: 26, net_amount: '536.07', missing_amount_rows: 0 },
  ]);
  assert.deepEqual(groups, before);
});

test('区分零金额、全部缺失和部分缺失，未知币种放在末尾', () => {
  assert.deepEqual(salesCurrencySummary([
    { currency: null, rows: 2, quantity: 0, net_amount: null, missing_amount_rows: 2 },
    { currency: 'USD', rows: 1, quantity: 1, net_amount: '0.0000', missing_amount_rows: 0 },
    { currency: 'USD', rows: 1, quantity: 2, net_amount: null, missing_amount_rows: 1 },
  ]), [
    { currency: 'USD', rows: 2, quantity: 3, net_amount: '0.00', missing_amount_rows: 1 },
    { currency: null, rows: 2, quantity: 0, net_amount: null, missing_amount_rows: 2 },
  ]);
});

test('先按四位精度相加再舍入，支持负数和大金额', () => {
  const sum = (...values) => salesCurrencySummary(values.map(net_amount => ({ currency: 'USD', rows: 1, quantity: 1, net_amount, missing_amount_rows: 0 })))[0].net_amount;
  assert.equal(sum('0.0040', '0.0040'), '0.01');
  assert.equal(sum('-1.0050'), '-1.01');
  assert.equal(sum('-0.0040'), '0.00');
  assert.equal(sum('9999999999999999.9999', '0.0001'), '10,000,000,000,000,000.00');
  assert.equal(sum('1.0000', '-1.0000'), '0.00');
});

test('空结果不生成虚构汇总', () => {
  assert.deepEqual(salesCurrencySummary([]), []);
});
