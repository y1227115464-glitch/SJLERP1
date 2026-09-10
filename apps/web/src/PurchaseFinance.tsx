import { useState } from 'react';
import { Button, Descriptions, Form, Input, Modal, Select, Timeline } from 'antd';
import { api, errorText } from './api';
import { dateTime, ErrorNotice } from './common';
import { options, requestId, required } from './SupplyShared';
import type { PurchaseOrder } from './supply-types';
import type { User } from './types';

export const paymentStatuses: Record<string, string> = { unpaid: '未付款', partial: '部分付款', paid: '已付清' };
export const invoiceStatuses: Record<string, string> = { pending: '未收票', partial: '部分收票', received: '已收齐', not_required: '无需发票' };

export function PurchaseFinance({ order, user, onSaved }: { order: PurchaseOrder; user: User; onSaved: () => void }) {
  const [editing, setEditing] = useState(false);
  return <>
    <h3 className="catalog-section-title">付款与发票跟进 {user.permissions.includes('purchases.manage') && <Button type="link" onClick={() => setEditing(true)}>更新跟进</Button>}</h3>
    <Descriptions bordered size="small" column={2} items={[
      { key: 'payment', label: '付款状态', children: paymentStatuses[order.payment_status] },
      { key: 'invoice', label: '发票状态', children: invoiceStatuses[order.invoice_status] },
      ...(order.finance_notes !== undefined ? [
        { key: 'notes', label: '跟进备注', children: <span className="catalog-prewrap">{order.finance_notes || '—'}</span>, span: 2 },
        { key: 'time', label: '最后跟进', children: order.finance_updated_at ? dateTime(order.finance_updated_at) : '尚未跟进，请核实付款与收票情况', span: 2 },
      ] : []),
    ]} />
    {!!order.finance_history?.length && <Timeline style={{ marginTop: 20 }} items={order.finance_history.map(entry => ({ key: entry.id, content: <><strong>{paymentStatuses[entry.payment_status]} · {invoiceStatuses[entry.invoice_status]}</strong><p className="catalog-prewrap">{entry.notes || '未填写备注'}</p><small>{entry.actor_name} · {dateTime(entry.created_at)}</small></> }))} />}
    {editing && <FinanceEditor order={order} onClose={() => setEditing(false)} onSaved={onSaved} />}
  </>;
}

function FinanceEditor({ order, onClose, onSaved }: { order: PurchaseOrder; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm();
  const [token] = useState(requestId);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  return <Modal open title="更新付款与发票跟进" onCancel={saving ? undefined : onClose} closable={!saving} mask={{ closable: false }} onOk={() => form.submit()} confirmLoading={saving} okText="保存跟进">
    <ErrorNotice error={error} />
    <Form form={form} layout="vertical" initialValues={{ payment_status: order.payment_status, invoice_status: order.invoice_status, notes: order.finance_notes || '' }} onFinish={async values => {
      setSaving(true); setError('');
      try { await api(`/purchase-orders/${order.id}/finance`, { method: 'POST', body: { ...values, request_id: token } }); onSaved(); onClose(); }
      catch (cause) { setError(errorText(cause)); } finally { setSaving(false); }
    }}>
      <Form.Item name="payment_status" label="付款状态" rules={required}><Select options={options(paymentStatuses)} /></Form.Item>
      <Form.Item name="invoice_status" label="发票状态" rules={required}><Select options={options(invoiceStatuses)} /></Form.Item>
      <Form.Item name="notes" label="跟进备注"><Input.TextArea maxLength={2000} rows={4} placeholder="例如：已付定金，尾款及剩余发票预计下周处理" /></Form.Item>
    </Form>
  </Modal>;
}
