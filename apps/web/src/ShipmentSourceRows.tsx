import { Button, Col, Form, Row } from 'antd';
import type { FormInstance } from 'antd';
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons';
import { QuantityInput, RemoteSelect, required } from './SupplyShared';
import { cartonText } from './packing';
import { SupplierShipmentGrid } from './SupplierShipmentGrid';
import type { Shipment } from './supply-types';
export { stockSourceLabel } from './ShipmentStockPicker';

export interface ShipmentDraftLine {
  purchase_line_id?: string | null; supplier_stock_id?: string | null; product_id: string;
  quantity: number; units_per_carton?: number | null; source_label?: string; available_quantity?: number;
}
export interface PurchaseSource {
  id: string; product_id: string; internal_sku: string; product_name: string; product_name_zh?: string;
  purchase_number: string; supplier_name: string; units_per_carton: number | null; available_quantity: number;
}
export function ShipmentSourceRows({ form, supplier, storeId, purchaseLines, loading, shipment, warehouseLabel, purchaseOrders = [] }: {
  form: FormInstance; supplier: boolean; storeId?: string; purchaseLines: PurchaseSource[]; loading: boolean;
  shipment?: Shipment; warehouseLabel?: string; purchaseOrders?: { id: string; number: string }[];
}) {
  const rows: ShipmentDraftLine[] = Form.useWatch('lines', { form, preserve: true }) || [];
  if (supplier) return <SupplierShipmentGrid form={form} storeId={storeId} purchaseLines={purchaseLines} purchaseOrders={purchaseOrders} loading={loading} shipment={shipment} />;
  return <Form.List name="lines" rules={[{ validator: async (_, lines) => { if (!lines?.length) throw new Error('至少添加一行商品'); } }]}>{(fields, { add, remove }, { errors }) => <>
    {fields.map(field => {
      const row = rows[field.name];
      const original = shipment?.lines.find(line => line.product_id === row?.product_id);
      const received = original?.received_quantity || 0;
      return <Row key={field.key} gutter={12} align="top">
        <Col span={14}><Form.Item label="商品 / SKU" extra={`仓库库存 · ${warehouseLabel || '请先选择发货仓库'}`}>
          <Form.Item noStyle name={[field.name, 'product_id']} rules={required}>
            <RemoteSelect path="/products?is_active=true" disabled={received > 0} selectedLabel={original ? `${original.internal_sku} · ${original.product_name}` : undefined} onRecord={product => form.setFieldValue(['lines', field.name, 'units_per_carton'], product.units_per_carton)} />
          </Form.Item>
        </Form.Item></Col>
        <Col span={4}><Form.Item name={[field.name, 'units_per_carton']} label="箱规（件/箱）" rules={required}><QuantityInput /></Form.Item></Col>
        <Col span={4}><Form.Item name={[field.name, 'quantity']} label="本批数量（件）" dependencies={[[ 'lines', field.name, 'units_per_carton' ]]}
          extra={<>{shipment && <>已接收 {received} 件；</>}{cartonText(row?.quantity || 0, row?.units_per_carton)}</>}
          rules={[...required, { validator: async (_, value) => {
            const size = form.getFieldValue(['lines', field.name, 'units_per_carton']);
            if (value < received) throw new Error(`不能少于已接收的 ${received} 件`);
            if (size && value % size !== 0) throw new Error(`数量须为 ${size} 的整数倍`);
          } }]}><QuantityInput min={Math.max(1, received)} /></Form.Item></Col>
        <Col span={2}><Button aria-label="移除发货商品行" type="text" disabled={received > 0} icon={<MinusCircleOutlined />} onClick={() => remove(field.name)} /></Col>
      </Row>;
    })}
    <Form.ErrorList errors={errors} />
    <Button block type="dashed" icon={<PlusOutlined />} disabled={fields.length >= 1000 || loading} onClick={() => add({ quantity: 1 })}>添加发货商品</Button>
  </>}</Form.List>;
}
