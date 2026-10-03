import { useState } from 'react';
import { Alert, Button, Col, Form, Input, Modal, Row, Select, Table } from 'antd';
import type { FormInstance } from 'antd';
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons';
import { ErrorNotice, usePagedList } from './common';
import { queryPath, useDebouncedValue } from './CatalogShared';
import { QuantityInput, RemoteSelect, required } from './SupplyShared';
import { cartonText } from './packing';
import type { Shipment } from './supply-types';

export interface ShipmentDraftLine {
  purchase_line_id?: string | null; supplier_stock_id?: string | null; product_id: string;
  quantity: number; units_per_carton?: number | null; source_label?: string; available_quantity?: number;
}
export interface PurchaseSource {
  id: string; product_id: string; internal_sku: string; product_name: string; product_name_zh?: string;
  purchase_number: string; supplier_name: string; units_per_carton: number | null; available_quantity: number;
}
interface StockSource {
  id: string; purchase_line_id: string; product_id: string; internal_sku: string; product_name: string;
  purchase_number: string; supplier_name: string; remaining_quantity: number; units_per_carton: number | null;
}
export const stockSourceLabel = (stock: { supplier_name: string; purchase_number: string; id: string }) =>
  `供应商库存 · ${stock.supplier_name} · ${stock.purchase_number} · 批次 ${stock.id.slice(0, 8)}`;

function StockPicker({ storeId, selected, onAdd, onClose }: {
  storeId: string; selected: string[]; onAdd: (line: ShipmentDraftLine) => void; onClose: () => void;
}) {
  const [search, setSearch] = useState('');
  const q = useDebouncedValue(search);
  const resource = usePagedList<StockSource>(queryPath('/supplier-stock', { store_id: storeId, q }));
  return <Modal open title="从供应商库存添加 SKU" width={920} footer={null} onCancel={onClose}>
    <Alert className="page-notice" type="info" title="选择 SKU 对应的库存批次，默认填入该批次全部可用余量。发货数量不能超过余量，保存后扣减所选批次；移除或减少时退回原批次。" />
    <Input allowClear placeholder="搜索 SKU、商品、供应商或采购单" value={search} onChange={event => setSearch(event.target.value)} style={{ marginBottom: 16 }} />
    <ErrorNotice error={resource.error} retry={resource.reload} />
    <Table<StockSource> rowKey="id" size="small" loading={resource.loading} dataSource={resource.data?.items ?? []} pagination={resource.pagination} columns={[
      { title: '商品 / SKU', render: (_, stock) => <>{stock.internal_sku}<div className="cell-secondary">{stock.product_name}</div></> },
      { title: '数量来源', render: (_, stock) => stockSourceLabel(stock) },
      { title: '可用数量', dataIndex: 'remaining_quantity' },
      { title: '操作', render: (_, stock) => <Button disabled={selected.includes(stock.id)} onClick={() => {
        onAdd({ supplier_stock_id: stock.id, purchase_line_id: stock.purchase_line_id, product_id: stock.product_id,
          quantity: stock.remaining_quantity, units_per_carton: stock.units_per_carton, available_quantity: stock.remaining_quantity,
          source_label: `${stock.internal_sku} · ${stock.product_name}｜${stockSourceLabel(stock)}` }); onClose();
      }}>{selected.includes(stock.id) ? '已添加' : '添加'}</Button> },
    ]} />
  </Modal>;
}

export function ShipmentSourceRows({ form, supplier, storeId, purchaseLines, loading, shipment, warehouseLabel }: {
  form: FormInstance; supplier: boolean; storeId?: string; purchaseLines: PurchaseSource[]; loading: boolean;
  shipment?: Shipment; warehouseLabel?: string;
}) {
  const [picking, setPicking] = useState(false);
  const rows: ShipmentDraftLine[] = Form.useWatch('lines', { form, preserve: true }) || [];
  return <Form.List name="lines" rules={[{ validator: async (_, lines) => { if (!lines?.length) throw new Error('至少添加一行商品'); } }]}>{(fields, { add, remove }, { errors }) => <>
    {fields.map(field => {
      const row = rows[field.name];
      const stock = !!row?.supplier_stock_id;
      const original = shipment?.lines.find(line => stock ? line.supplier_stock_id === row.supplier_stock_id :
        !line.supplier_stock_id && (supplier ? line.purchase_line_id === row?.purchase_line_id : line.product_id === row?.product_id));
      const received = original?.received_quantity || 0;
      const source = purchaseLines.find(line => line.id === row?.purchase_line_id);
      const available = stock ? row.available_quantity : supplier ? source?.available_quantity : undefined;
      const description = stock ? row.source_label?.split('｜')[1] : supplier ? (source ? `采购余量 · ${source.supplier_name} · ${source.purchase_number}` : '请选择来源采购商品') : `仓库库存 · ${warehouseLabel || '请先选择发货仓库'}`;
      return <Row key={field.key} gutter={12} align="top">
        <Form.Item hidden name={[field.name, 'supplier_stock_id']}><Input /></Form.Item>
        {supplier && <Form.Item hidden name={[field.name, 'product_id']} rules={required}><Input /></Form.Item>}
        {stock && <Form.Item hidden name={[field.name, 'purchase_line_id']} rules={required}><Input /></Form.Item>}
        <Col span={11}><Form.Item label="商品 / SKU · 数量来源" extra={<>{description}{available !== undefined && <div>本单最多可发 {available} 件；本行发货 {row?.quantity || 0} 件</div>}</>}>
          {stock ? <Input value={row.source_label?.split('｜')[0]} readOnly /> : <Form.Item noStyle name={[field.name, supplier ? 'purchase_line_id' : 'product_id']} rules={required}>
            {supplier ? <Select showSearch optionFilterProp="label" disabled={received > 0 || loading} loading={loading}
              placeholder="从采购余量选择商品" options={purchaseLines.map(line => ({ value: line.id,
                disabled: rows.some((other, index) => index !== field.name && !other.supplier_stock_id && other.purchase_line_id === line.id),
                label: `${line.purchase_number} · ${line.internal_sku} · ${line.product_name_zh || line.product_name}` }))}
              onChange={id => { const line = purchaseLines.find(line => line.id === id); form.setFieldValue(['lines', field.name, 'product_id'], line?.product_id); form.setFieldValue(['lines', field.name, 'units_per_carton'], shipment?.lines.find(original => !original.supplier_stock_id && original.purchase_line_id === id)?.units_per_carton ?? line?.units_per_carton); }} /> :
              <RemoteSelect path="/products?is_active=true" disabled={received > 0} selectedLabel={original ? `${original.internal_sku} · ${original.product_name}` : undefined} onRecord={product => form.setFieldValue(['lines', field.name, 'units_per_carton'], product.units_per_carton)} />}
          </Form.Item>}
        </Form.Item></Col>
        <Col span={5}><Form.Item name={[field.name, 'units_per_carton']} label="本单箱规（件/箱）" rules={required}><QuantityInput /></Form.Item></Col>
        <Col span={6}><Form.Item name={[field.name, 'quantity']} label="本批数量（件）" dependencies={[[ 'lines', field.name, 'units_per_carton' ], ['lines', field.name, 'purchase_line_id']]}
          extra={<>{shipment && <>已接收 {received} 件；</>}{cartonText(row?.quantity || 0, row?.units_per_carton)}</>}
          rules={[...required, { validator: async (_, value) => {
            const current: ShipmentDraftLine = form.getFieldValue(['lines', field.name]);
            const currentAvailable = current?.supplier_stock_id ? current.available_quantity : supplier
              ? purchaseLines.find(line => line.id === current?.purchase_line_id)?.available_quantity : undefined;
            const size = form.getFieldValue(['lines', field.name, 'units_per_carton']);
            if (value < received) throw new Error(`不能少于已接收的 ${received} 件`);
            if (currentAvailable !== undefined && value > currentAvailable) throw new Error(current?.supplier_stock_id
              ? `发货数量超过供应商库存批次余量，本单最多可发 ${currentAvailable} 件`
              : `超过该采购来源可发数量 ${currentAvailable} 件`);
            if (size && value % size !== 0) throw new Error(`数量须为 ${size} 的整数倍`);
          } }]}><QuantityInput min={Math.max(1, received)} /></Form.Item></Col>
        <Col span={2}><Button aria-label="移除发货商品行" type="text" disabled={received > 0} icon={<MinusCircleOutlined />} onClick={() => remove(field.name)} /></Col>
      </Row>;
    })}
    <Form.ErrorList errors={errors} />
    <Button block type="dashed" icon={<PlusOutlined />} disabled={fields.length >= 1000 || loading || (supplier && !storeId)}
      onClick={() => supplier ? setPicking(true) : add({ quantity: 1 })}>{supplier ? '从供应商库存添加 SKU' : '添加发货商品'}</Button>
    {picking && storeId && <StockPicker key={storeId} storeId={storeId} selected={rows.flatMap(row => row.supplier_stock_id ? [row.supplier_stock_id] : [])} onAdd={add} onClose={() => setPicking(false)} />}
  </>}</Form.List>;
}
