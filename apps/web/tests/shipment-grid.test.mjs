import test from 'node:test';
import assert from 'node:assert/strict';
import { groupShipmentRows, allocatedShipmentRows, editableShipmentPurchaseIds } from '../src/shipment-grid.ts';

test('重新打开混合发货时，库存追溯采购单不恢复为采购余量选项', () => {
  const shipment = {
    purchase_orders: [{ id: 'a', number: 'PO-A' }, { id: 'b', number: 'PO-B' }, { id: 'c', number: 'PO-C' }],
    lines: [
      { purchase_number: 'PO-A', supplier_stock_id: null },
      { purchase_number: 'PO-A', supplier_stock_id: 'stock-a' },
      { purchase_number: 'PO-B', supplier_stock_id: 'stock-b', received_quantity: 5 },
    ],
  };
  assert.deepEqual(editableShipmentPurchaseIds(shipment), ['a', 'c']);
  assert.equal(shipment.lines.length, 3);
  assert.deepEqual(editableShipmentPurchaseIds({ ...shipment, lines: shipment.lines.filter(line => line.supplier_stock_id) }), ['c']);
  assert.deepEqual(editableShipmentPurchaseIds({ purchase_orders: [], lines: [] }), []);
});

test('同一 SKU 跨采购单和多个库存批次合并，保留来源索引并分别汇总', () => {
  const rows = [
    {product_id:'a',purchase_line_id:'po-1',quantity:20},
    {product_id:'b',purchase_line_id:'po-2',quantity:5},
    {product_id:'a',purchase_line_id:'po-3',quantity:30},
    {product_id:'a',purchase_line_id:'po-1',supplier_stock_id:'stock-1',quantity:10},
    {product_id:'a',purchase_line_id:'po-3',supplier_stock_id:'stock-2',quantity:40},
  ];
  assert.deepEqual(groupShipmentRows(rows), [
    {productId:'a',indices:[0,2,3,4],total:100,stockTotal:50},
    {productId:'b',indices:[1],total:5,stockTotal:0},
  ]);
  rows[2].quantity=0;
  assert.equal(groupShipmentRows(rows)[0].total,70);
  assert.deepEqual(allocatedShipmentRows(rows).map(row => row.purchase_line_id), ['po-1','po-2','po-1','po-3']);
  assert.equal(allocatedShipmentRows(rows)[2].supplier_stock_id,'stock-1');
});

test('暂时清空数量和取消来源不产生 NaN 或虚构数量', () => {
  const rows=[{product_id:'a',quantity:null},{product_id:'a',quantity:0,supplier_stock_id:'stock-1'}];
  assert.deepEqual(groupShipmentRows(rows),[{productId:'a',indices:[0,1],total:0,stockTotal:0}]);
  assert.deepEqual(allocatedShipmentRows(rows),[]);
});
