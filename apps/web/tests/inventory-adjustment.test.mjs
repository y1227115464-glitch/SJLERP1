import test from 'node:test';
import assert from 'node:assert/strict';
import { adjustmentQuantity, productBelongsToStore } from '../src/inventory-adjustment.ts';

test('SKU 通过品牌归属店铺，无需独立售卖绑定；切换到其他品牌后不匹配', () => {
  const product = { brand: 'Risepekt', is_active: true };
  assert.equal(productBelongsToStore(product, 'Risepekt'), true);
  assert.equal(productBelongsToStore(product, 'Wmiwulien'), false);
  assert.equal(productBelongsToStore({ brand: 'Wmiwulien', is_active: true }, 'Wmiwulien'), true);
  assert.equal(productBelongsToStore({ ...product, is_active: false }, 'Risepekt'), false);
});

test('未配置品牌或尚未读取商品时不能匹配店铺', () => {
  for (const brand of ['', '   ', undefined]) {
    assert.equal(productBelongsToStore({ brand: '', is_active: true }, brand), false);
  }
  assert.equal(productBelongsToStore(null, 'Risepekt'), false);
  assert.equal(productBelongsToStore(undefined, 'Risepekt'), false);
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
