import test from 'node:test';
import assert from 'node:assert/strict';
import { adjustmentQuantity, productSoldInStore } from '../src/inventory-adjustment.ts';

test('切换到共同售卖的店铺保留 SKU，其他店铺或停用关联不匹配', () => {
  const stores = [
    { store_id: 'a', store_active: true, is_active: true },
    { store_id: 'b', store_active: true, is_active: true },
    { store_id: 'c', store_active: true, is_active: false },
    { store_id: 'd', store_active: false, is_active: true },
  ];
  assert.equal(productSoldInStore(stores, 'a'), true);
  assert.equal(productSoldInStore(stores, 'b'), true);
  for (const id of ['c', 'd', 'unrelated', undefined]) assert.equal(productSoldInStore(stores, id), false);
  assert.equal(productSoldInStore(undefined, 'a'), false);
});

test('增加和减少分别提交带符号的变动量，输入数字保持正数', () => {
  assert.equal(adjustmentQuantity(1, 1, 'opening'), 1);
  assert.equal(adjustmentQuantity(1, 1, 'adjustment'), 1);
  assert.equal(adjustmentQuantity(1, -1, 'adjustment'), -1);
  assert.equal(adjustmentQuantity(20, 1, 'adjustment'), 20);
  assert.equal(adjustmentQuantity(20, -1, 'adjustment'), -20);
  assert.equal(adjustmentQuantity(1000000000, -1, 'adjustment'), -1000000000);
  assert.throws(() => adjustmentQuantity(20, -1, 'opening'), /期初库存仅支持增加/);
});

test('拒绝零、负数、小数、空值和超出上限的数量', () => {
  for (const value of [0, -2, 0.5, 1.5, 2.5, null, undefined, NaN, Infinity, 1000000001]) {
    assert.throws(() => adjustmentQuantity(value, 1, 'adjustment'), /大于等于 1/);
    assert.throws(() => adjustmentQuantity(value, -1, 'adjustment'), /大于等于 1/);
  }
});
