import { useState } from 'react';
import { Alert, Button, Col, Form, Input, InputNumber, Modal, Row } from 'antd';
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons';
import { api, errorText } from './api';
import { ErrorNotice } from './common';
import { QuantityInput, RemoteSelect, requestId, required } from './SupplyShared';
import type { PurchaseOrder } from './supply-types';

interface Values { reason?: string; lines: { product_id: string; quantity: number; unit_price?: string }[] }

export function PurchaseLinesEditor({ order, onClose, onSaved }: { order: PurchaseOrder; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm<Values>();
  const [token] = useState(requestId);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  return <Modal open title="编辑采购商品及数量" width={900} onCancel={saving ? undefined : onClose} closable={!saving} mask={{ closable: false }} onOk={() => form.submit()} confirmLoading={saving} okText="保存修改">
    <Alert className="page-notice" type="info" showIcon title="可调整原商品数量，也可追加商品" description="原商品及单价保留；采购数量不能低于已收货、已分配给货件和已取消数量的合计。修改不会自动发送给供应商。" />
    <ErrorNotice error={error} />
    <Form form={form} layout="vertical" initialValues={{ lines: order.lines.map(line => ({ product_id: line.product_id, quantity: line.quantity })) }} onFinish={async values => {
      setSaving(true); setError('');
      try {
        await api(`/purchase-orders/${order.id}/lines`, { method: 'PATCH', body: {
          request_id: token, expected_version: order.lines_version, reason: values.reason || '',
          lines: values.lines.map(line => ({ product_id: line.product_id, quantity: line.quantity,
            ...(!order.lines.some(original => original.product_id === line.product_id) ? { unit_price: String(line.unit_price ?? '') } : {}) })),
        } });
        onSaved();
      } catch (cause) { setError(errorText(cause)); } finally { setSaving(false); }
    }}>
      <Form.List name="lines">{(fields, { add, remove }) => <>
        {fields.map(field => {
          const original = order.lines[field.name];
          const minimum = original ? Math.max(1, original.received_quantity + original.cancelled_quantity + (original.allocated_quantity || 0)) : 1;
          return <Row key={field.key} gutter={12} align="top">
            <Col span={12}><Form.Item name={[field.name, 'product_id']} label="商品 / SKU" rules={required}>
              <RemoteSelect path="/products?is_active=true" disabled={!!original} initialLabel={original ? `${original.internal_sku} · ${original.product_name_zh || original.product_name}` : undefined} />
            </Form.Item></Col>
            <Col span={5}><Form.Item name={[field.name, 'quantity']} label="采购数量" extra={original ? `至少 ${minimum} 件` : undefined} rules={required}><QuantityInput min={minimum} /></Form.Item></Col>
            <Col span={5}>{original ? <Form.Item label={`原单价（${order.currency}）`}><Input value={original.unit_price} readOnly /></Form.Item> : <Form.Item name={[field.name, 'unit_price']} label={`单价（${order.currency}）`} rules={required}><InputNumber stringMode min="0" max="99999999999999.9999" precision={4} style={{ width: '100%' }} /></Form.Item>}</Col>
            <Col span={2}>{!original && <Button aria-label="移除新增商品行" type="text" icon={<MinusCircleOutlined />} onClick={() => remove(field.name)} />}</Col>
          </Row>;
        })}
        <Button block type="dashed" icon={<PlusOutlined />} disabled={fields.length >= 100} onClick={() => add({ quantity: 1 })}>新增商品</Button>
      </>}</Form.List>
      <Form.Item name="reason" label="修改说明" style={{ marginTop: 20 }}><Input.TextArea rows={2} maxLength={1000} placeholder="可记录供应商变更、补货或录入更正原因" /></Form.Item>
    </Form>
  </Modal>;
}
