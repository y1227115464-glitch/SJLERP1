import { useState } from 'react';
import { Alert, Button, Col, Form, Input, Modal, Row, Select } from 'antd';
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons';
import { api, errorText } from './api';
import { ErrorNotice, useResource } from './common';
import { QuantityInput, RemoteSelect, requestId, required } from './SupplyShared';
import { cartonText } from './packing';
import type { PurchaseOrder, Shipment } from './supply-types';

interface Values { reason?: string; lines: { product_id: string; quantity: number; units_per_carton: number | null }[] }

export function ShipmentLinesEditor({ shipment, onClose, onSaved }: { shipment: Shipment; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm<Values>();
  const [token] = useState(requestId);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const rows = Form.useWatch('lines', { form, preserve: true }) || [];
  const purchase = useResource<PurchaseOrder>(shipment.purchase_order_id ? `/purchase-orders/${shipment.purchase_order_id}` : null);
  const changeProduct = (index: number, productId: string, size?: number | null) => {
    form.setFieldValue(['lines', index, 'units_per_carton'], shipment.lines.find(line => line.product_id === productId)?.units_per_carton ?? size ?? null);
  };
  return <Modal open title="修改发货产品及数量（不建议操作）" width={960} onCancel={saving ? undefined : onClose} closable={!saving} mask={{ closable: false }} onOk={() => form.submit()} confirmLoading={saving} okText="保存修改" okButtonProps={{ danger: true, disabled: !!shipment.purchase_order_id && !purchase.data }}>
    <Alert className="page-notice" type="warning" showIcon title="不建议操作：仅在确认发货记录有误时修改" description="保存会调整采购分配、库存占用或已发出数量，并写入跟进记录。已接收的商品不能移除或替换，数量不得低于已接收数。请核对实际发货和 Amazon 货件资料。" />
    <ErrorNotice error={error || purchase.error} retry={purchase.error ? purchase.reload : undefined} />
    <Form form={form} layout="vertical" initialValues={{ lines: shipment.lines.map(line => ({ product_id: line.product_id, quantity: line.quantity, units_per_carton: line.units_per_carton })) }} onFinish={async values => {
      setSaving(true); setError('');
      try { await api(`/shipments/${shipment.id}/lines`, { method: 'PATCH', body: {
        request_id: token, expected_version: shipment.lines_version, reason: values.reason || '',
        lines: values.lines.map(line => ({ product_id: line.product_id, quantity: line.quantity, units_per_carton: line.units_per_carton })),
      } }); onSaved(); } catch (cause) { setError(errorText(cause)); } finally { setSaving(false); }
    }}>
      <Form.List name="lines" rules={[{ validator: async (_, lines) => { if (!lines?.length) throw new Error('至少保留一行商品'); } }]}>{(fields, { add, remove }, { errors }) => <>
        {fields.map(field => {
          const row = rows[field.name];
          const original = shipment.lines.find(line => line.product_id === row?.product_id);
          const received = original?.received_quantity || 0;
          return <Row key={field.key} gutter={12} align="top">
            <Col span={11}><Form.Item name={[field.name, 'product_id']} label="发货产品 / SKU" rules={required}>
              {shipment.purchase_order_id ? <Select showSearch optionFilterProp="label" disabled={received > 0 || !purchase.data} loading={purchase.loading} options={purchase.data?.lines.map(line => ({ value: line.product_id, label: `${line.internal_sku} · ${line.product_name_zh || line.product_name}` }))} onChange={id => changeProduct(field.name, id, purchase.data?.lines.find(line => line.product_id === id)?.units_per_carton)} /> : <RemoteSelect path="/products?is_active=true" disabled={received > 0} selectedLabel={original ? `${original.internal_sku} · ${original.product_name}` : undefined} onRecord={product => changeProduct(field.name, product.id, product.units_per_carton)} />}
            </Form.Item></Col>
            <Col span={5}><Form.Item name={[field.name, 'units_per_carton']} label="箱规（件/箱）" rules={required}><QuantityInput /></Form.Item></Col>
            <Col span={6}><Form.Item name={[field.name, 'quantity']} label="本批数量" dependencies={[[ 'lines', field.name, 'units_per_carton' ]]} extra={<>已接收 {received} 件；{cartonText(row?.quantity || 0, row?.units_per_carton)}</>} rules={[...required, { validator: async (_, value) => {
              const size = form.getFieldValue(['lines', field.name, 'units_per_carton']);
              if (value < received) throw new Error(`不能少于已接收的 ${received} 件`);
              if (size && value % size !== 0) throw new Error(`数量须为 ${size} 的整数倍`);
            } }]}><QuantityInput min={Math.max(1, received)} /></Form.Item></Col>
            <Col span={2}><Button aria-label="移除发货商品行" type="text" disabled={received > 0} icon={<MinusCircleOutlined />} onClick={() => remove(field.name)} /></Col>
          </Row>;
        })}
        <Form.ErrorList errors={errors} /><Button block type="dashed" icon={<PlusOutlined />} disabled={fields.length >= 100} onClick={() => add({ quantity: 1 })}>添加发货产品</Button>
      </>}</Form.List>
      <Form.Item name="reason" label="修改说明" style={{ marginTop: 20 }}><Input.TextArea rows={2} maxLength={1000} placeholder="说明实际发货与原记录的差异，供后续跟进核对" /></Form.Item>
    </Form>
  </Modal>;
}
