import { useState } from 'react';
import { Button, Form, Input, Table, Tooltip } from 'antd';
import type { FormInstance } from 'antd';
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons';
import { QuantityInput } from './SupplyShared';
import { cartonText } from './packing';
import { groupShipmentRows } from './shipment-grid';
import { StockPicker } from './ShipmentStockPicker';
import type { PurchaseSource, ShipmentDraftLine } from './ShipmentSourceRows';
import type { Shipment } from './supply-types';

type Group = ReturnType<typeof groupShipmentRows>[number];
export function SupplierShipmentGrid({ form, storeId, purchaseLines, purchaseOrders, loading, shipment }: {
  form: FormInstance; storeId?: string; purchaseLines: PurchaseSource[]; purchaseOrders: { id: string; number: string }[];
  loading: boolean; shipment?: Shipment;
}) {
  const [picking, setPicking] = useState(false);
  const watched: ShipmentDraftLine[] | undefined = Form.useWatch('lines', { form, preserve: true });
  const rows: ShipmentDraftLine[] = watched || form.getFieldValue('lines') || [];
  const groups = groupShipmentRows(rows);
  const original = (index: number) => shipment?.lines.find(line => rows[index]?.supplier_stock_id
    ? line.supplier_stock_id === rows[index].supplier_stock_id
    : !line.supplier_stock_id && line.purchase_line_id === rows[index]?.purchase_line_id);
  const source = (index: number) => purchaseLines.find(line => line.id === rows[index]?.purchase_line_id);
  const sourceNumber = (index: number) => source(index)?.purchase_number || original(index)?.purchase_number;
  const sourceLabel = (index: number) => rows[index]?.supplier_stock_id ? `批次 ${rows[index].supplier_stock_id!.slice(0, 8)}` : sourceNumber(index);
  const available = (index: number) => rows[index]?.supplier_stock_id ? rows[index].available_quantity : source(index)?.available_quantity;
  const product = (group: Group) => {
    const index = group.indices[0];
    const purchase = source(index); const saved = original(index);
    if (purchase || saved) return { sku: purchase?.internal_sku || saved?.internal_sku, name: purchase?.product_name_zh || purchase?.product_name || saved?.product_name };
    const [sku, ...name] = (rows[index]?.source_label?.split('｜')[0] || '').split(' · ');
    return { sku, name: name.join(' · ') };
  };
  return <Form.List name="lines" rules={[{ validator: async (_, lines: ShipmentDraftLine[]) => {
    if (!lines?.some(line => line.quantity > 0)) throw new Error('至少填写一个来源的发货数量');
  } }]}>{(fields, { add, remove }, { errors }) => {
    const quantityCell = (index: number, batchLabel = false) => {
      const field = fields[index]; if (!field) return null;
      const received = original(index)?.received_quantity || 0;
      return <div key={field.key} className="shipment-source-cell">
        <Form.Item name={[field.name, 'quantity']} dependencies={[[ 'lines', field.name, 'units_per_carton' ]]}
          rules={[{ required: true, message: '请填写数量' }, { validator: async (_, value) => {
            if (value == null) return;
            const current: ShipmentDraftLine = form.getFieldValue(['lines', field.name]);
            const limit = current.supplier_stock_id ? current.available_quantity : purchaseLines.find(line => line.id === current.purchase_line_id)?.available_quantity;
            if (value < received) throw new Error(`不能少于已收 ${received} 件`);
            if (limit !== undefined && value > limit) throw new Error(`${current.supplier_stock_id ? '供应商库存' : '采购'}余量不足，最多 ${limit} 件`);
            if (value > 0 && !current.units_per_carton) throw new Error('请填写箱规');
            if (current.units_per_carton && value % current.units_per_carton !== 0) throw new Error(`须为 ${current.units_per_carton} 的整数倍`);
          } }]}><QuantityInput min={received} /></Form.Item>
        <div className="shipment-source-caption">{available(index) !== undefined ? `最多 ${available(index)}` : '余量加载中'}{received > 0 ? ` · 已收 ${received}` : ''}</div>
        {batchLabel && <Tooltip title={rows[index].source_label?.split('｜')[1]}><div className="shipment-source-caption">{sourceLabel(index)}</div></Tooltip>}
      </div>;
    };
    const packingCell = (group: Group) => {
      const sizes = new Set(group.indices.map(index => rows[index].units_per_carton || null));
      const mixed = sizes.size > 1;
      return group.indices.map((index, position) => {
        const field = fields[index]; if (!field) return null;
        return <div key={field.key} hidden={!mixed && position > 0}>
          {mixed && <div className="shipment-source-caption" title={sourceLabel(index) || undefined}>{rows[index].supplier_stock_id ? sourceLabel(index) : `采购单 ${purchaseOrders.findIndex(order => order.number === sourceNumber(index)) + 1}`}</div>}
          <Form.Item name={[field.name, 'units_per_carton']} rules={[{ validator: async (_, value) => {
            if (form.getFieldValue(['lines', field.name, 'quantity']) > 0 && !value) throw new Error('请填箱规');
          } }]}><QuantityInput onChange={value => {
            if (!mixed) group.indices.filter(other => other !== index).forEach(other => form.setFieldValue(['lines', other, 'units_per_carton'], value));
          }} /></Form.Item>
        </div>;
      });
    };
    return <>
      {fields.map(field => <div key={field.key} hidden>
        <Form.Item name={[field.name, 'supplier_stock_id']}><Input /></Form.Item>
        <Form.Item name={[field.name, 'purchase_line_id']}><Input /></Form.Item>
        <Form.Item name={[field.name, 'product_id']}><Input /></Form.Item>
      </div>)}
      <Table<Group> className="shipment-source-grid" rowKey="productId" size="small" pagination={false} dataSource={groups}
        tableLayout="fixed" scroll={{ x: 560 + purchaseOrders.length * 104 }} columns={[
          { title: '商品 / SKU', fixed: 'left', render: (_, group) => { const info = product(group); return <><strong>{info.sku}</strong><div className="cell-secondary">{info.name}</div></>; } },
          { title: <>箱规<div className="shipment-source-caption">件/箱</div></>, width: 84, render: (_, group) => packingCell(group) },
          { title: '本批数量（件）', children: [
            { title: '共计', width: 96, render: (_, group) => <><strong className="shipment-total">{group.total}</strong><div className="shipment-source-caption">{new Set(group.indices.map(index => rows[index].units_per_carton)).size === 1 ? cartonText(group.total, rows[group.indices[0]].units_per_carton) : '按来源箱规'}</div></> },
            ...purchaseOrders.map((order, index) => ({ title: <Tooltip title={order.number}><div>采购单 {index + 1}<div className="shipment-order-number">{order.number}</div></div></Tooltip>, key: order.id, width: 104,
              render: (_: unknown, group: Group) => {
                const indices = group.indices.filter(i => !rows[i].supplier_stock_id && sourceNumber(i) === order.number);
                return indices.length ? indices.map(i => quantityCell(i)) : <span className="shipment-source-caption">—</span>;
              } })),
            { title: '供应商库存', width: 112, render: (_, group) => {
              const indices = group.indices.filter(index => rows[index].supplier_stock_id);
              return indices.length ? <>{indices.length > 1 && <div className="shipment-source-caption">共 {group.stockTotal} 件</div>}{indices.map(index => quantityCell(index, true))}</> : <span className="shipment-source-caption">—</span>;
            } },
          ] },
          { title: '', width: 48, render: (_, group) => <Button type="text" aria-label="移除 SKU" disabled={group.indices.some(index => (original(index)?.received_quantity || 0) > 0)} icon={<MinusCircleOutlined />} onClick={() => remove(group.indices)} /> },
        ]} />
      <Form.ErrorList errors={errors} />
      <p className="catalog-field-help">共计自动汇总各来源数量。填 0 可取消该来源；供应商库存按批次扣减，悬停批次可查看原采购单。只要保留该批库存数量，货件就会保留其采购来源用于追溯。</p>
      <Button block type="dashed" icon={<PlusOutlined />} disabled={!storeId || fields.length >= 1000 || loading} onClick={() => setPicking(true)}>从供应商库存添加 SKU</Button>
      {picking && storeId && <StockPicker key={storeId} storeId={storeId} selected={rows.flatMap(row => row.supplier_stock_id ? [row.supplier_stock_id] : [])} onAdd={line => {
        const sameProduct = rows.filter(row => row.product_id === line.product_id);
        const sizes = new Set(sameProduct.map(row => row.units_per_carton));
        add({ ...line, units_per_carton: sameProduct.length && sizes.size === 1 ? sameProduct[0].units_per_carton : line.units_per_carton });
      }} onClose={() => setPicking(false)} />}
    </>;
  }}</Form.List>;
}
