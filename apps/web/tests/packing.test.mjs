import test from 'node:test';
import assert from 'node:assert/strict';
import { cartonText, totalWeight } from '../src/packing.ts';

test('purchase shows complete cartons and loose pieces without rounding quantity', () => {
  assert.equal(cartonText(25, 12), '2 箱 + 1 件');
  assert.equal(cartonText(24, 12), '2 箱');
  assert.equal(cartonText(1, 12), '0 箱 + 1 件');
  assert.equal(cartonText(25, null), '箱规未维护');
});

test('weight calculation retains four decimal places for small and large valid inputs', () => {
  assert.equal(totalWeight(25, '0.2500'), '6.2500 kg');
  assert.equal(totalWeight(3, '0.0001'), '0.0003 kg');
  assert.equal(totalWeight(1000000000, '99999999999999.9999'), '99999999999999999900000.0000 kg');
  assert.equal(totalWeight(25, null), '重量未维护');
});
