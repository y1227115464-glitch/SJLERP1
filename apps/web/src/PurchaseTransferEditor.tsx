import { useState } from 'react';
import { Alert, Button, Col, Form, Input, Modal, Row, Select } from 'antd';
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api, errorText } from './api';
import { ErrorNotice, useResource } from './common';
import { displayMoney, QuantityInput, requestId, required } from './SupplyShared';
import type { PurchaseOrder } from './supply-types';

interface Values {
  order_date: string; expected_date?: string; planned_ship_date?: string; notes?: string;
  lines: { product_id: string; quantity: number }[];
}

export function PurchaseTransferEditor({ id, onClose, onSaved }: { id: string; onClose: () => void; onSaved: (order: PurchaseOrder) => void }) {
  const resource = useResource<PurchaseOrder>(`/purchase-orders/${id}`);
  if (!resource.data) return <Modal open title="剩余商品转入新采购单" onCancel={onClose} footer={null}>
    {resource.loading ? <p>正在读取最新采购余量…</p> : <ErrorNotice error={resource.error} retry={resource.reload} />}
  </Modal>;
  return <TransferForm order={resource.data} onClose={onClose} onSaved={onSaved} />;
}

function TransferForm({ order, onClose, onSaved }: { order: PurchaseOrder; onClose: () => void; onSaved: (order: PurchaseOrder) => void }) {
  const [form] = Form.useForm<Values>();
  const [token] = useState(requestId);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const remaining = order.lines.filter(line => (line.unallocated_quantity ?? 0) > 0);
  const eligible = ['ordered', 'partially_received'].includes(order.status) && remaining.length > 0;
  const rows: Values['lines'] = Form.useWatch('lines', form) || [];
  return <Modal open title="剩余商品转入新采购单" width={960} onCancel={saving ? undefined : onClose} closable={!saving}
    mask={{ closable: false }} onOk={() => form.submit()} confirmLoading={saving} okButtonProps={{ disabled: !eligible }} okText="确认转入并创建采购单">
    <Alert className="page-notice" type={eligible ? 'info' : 'warning'} showIcon
      title={eligible ? `来源采购单：${order.number} · ${order.store_name} · ${order.supplier_name}` : '此采购单当前没有可转出的商品余量'}
      description="默认带入全部可转余量，可移除商品、重新选择剩余商品或减少数量。保存后原单增加已转出数量，新单沿用供应商、店铺、币种及单价，保持已下单状态。已到货、已取消、已转出和已分配给货件的数量不再转入。" />
    <ErrorNotice error={error} />
    <Form form={form} layout="vertical" initialValues={{ order_date: dayjs().format('YYYY-MM-DD'), lines: remaining.map(line => ({ product_id: line.product_id, quantity: line.unallocated_quantity })) }}
      onFinish={async values => {
        setSaving(true); setError('');
        try {
          const created = await api<PurchaseOrder>(`/purchase-orders/${order.id}/transfer`, { method: 'POST', body: {
            request_id: token, expected_version: order.lines_version, ...values,
            expected_date: values.expected_date || null, planned_ship_date: values.planned_ship_date || null, notes: values.notes || '',
          } });
          onSaved(created);
        } catch (cause) { setError(errorText(cause)); } finally { setSaving(false); }
      }}>
      <Row gutter={16}>
        <Col span={8}><Form.Item name="order_date" label="新单采购日期" rules={required}><Input type="date" /></Form.Item></Col>
        <Col span={8}><Form.Item name="planned_ship_date" label="预计发货日"><Input type="date" /></Form.Item></Col>
        <Col span={8}><Form.Item name="expected_date" label="预计到货"><Input type="date" /></Form.Item></Col>
      </Row>
      <Form.List name="lines" rules={[{ validator: async (_, lines: Values['lines']) => {
        if (!lines?.length) throw new Error('至少选择一件剩余商品');
        if (new Set(lines.map(line => line?.product_id).filter(Boolean)).size !== lines.filter(line => line?.product_id).length) throw new Error('同一商品只能填写一行');
      } }]}>{(fields, { add, remove }, { errors }) => <>
        {fields.map(field => {
          const original = remaining.find(line => line.product_id === rows[field.name]?.product_id);
          return <Row key={field.key} gutter={12} align="top">
            <Col span={12}><Form.Item name={[field.name, 'product_id']} label="商品 / SKU" rules={required}>
              <Select showSearch optionFilterProp="label" placeholder="选择原采购单剩余商品" options={remaining.map(line => ({ value: line.product_id,
                label: `${line.internal_sku} · ${line.product_name_zh || line.product_name}（可转 ${line.unallocated_quantity} 件）`,
                disabled: rows.some((row, index) => index !== field.name && row?.product_id === line.product_id),
              }))} onChange={productId => form.setFieldValue(['lines', field.name, 'quantity'], remaining.find(line => line.product_id === productId)?.unallocated_quantity)} />
            </Form.Item></Col>
            <Col span={6}><Form.Item name={[field.name, 'quantity']} label="转入新单数量" dependencies={[['lines', field.name, 'product_id']]} rules={[...required, { validator: async (_, value) => {
              const line = remaining.find(item => item.product_id === form.getFieldValue(['lines', field.name, 'product_id']));
              if (!Number.isInteger(value) || value < 1) throw new Error('请输入大于 0 的整数');
              if (!line || value > (line.unallocated_quantity ?? 0)) throw new Error(`不能超过可转余量 ${line?.unallocated_quantity ?? 0} 件`);
            } }]}><QuantityInput max={original?.unallocated_quantity} /></Form.Item></Col>
            <Col span={4}><Form.Item label="原单价"><span>{displayMoney(original?.unit_price, order.currency)}</span></Form.Item></Col>
            <Col span={2}><Button aria-label="移除转入商品" type="text" icon={<MinusCircleOutlined />} onClick={() => remove(field.name)} /></Col>
          </Row>;
        })}
        <Form.ErrorList errors={errors} />
        <Button block type="dashed" icon={<PlusOutlined />} disabled={fields.length >= remaining.length || !eligible} onClick={() => add({ quantity: 1 })}>添加剩余商品</Button>
      </>}</Form.List>
      <Form.Item name="notes" label="新采购单备注" style={{ marginTop: 20 }}><Input.TextArea rows={2} maxLength={5000} /></Form.Item>
      <p className="catalog-field-help">未选商品及未转出的数量保留在原单；关闭页面不会转单。付款、发票跟进记录保留在原单，新单需重新核实登记。</p>
    </Form>
  </Modal>;
}
