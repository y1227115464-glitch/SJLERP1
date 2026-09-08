import { useState } from 'react';
import { App as AntApp, Button, Card, Col, Descriptions, Drawer, Form, Input, InputNumber, Modal, Progress, Row, Select, Space, Table } from 'antd';
import { MinusCircleOutlined, PlusOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api, errorText } from './api';
import { dateTime, EmptyState, ErrorNotice, PageHeading, usePagedList, useResource } from './common';
import { queryPath, useDebouncedValue } from './CatalogShared';
import { displayMoney, options, purchaseStatuses, QuantityInput, RemoteSelect, requestId, required, StatusTag, StoreField, storeParam } from './SupplyShared';
import { ShipmentEditor } from './ShipmentForms';
import type { PurchaseOrder } from './supply-types';
import type { Store, User } from './types';

interface Props { user: User; stores: Store[]; selectedStore: string }
export function PurchasesPage({ user, stores, selectedStore }: Props) {
  const [q, setQ] = useState('');
  const [status, setStatus] = useState<string>();
  const query = useDebouncedValue(q);
  const resource = usePagedList<PurchaseOrder>(queryPath('/purchase-orders', { store_id: storeParam(selectedStore), q: query, status }));
  const [editing, setEditing] = useState<PurchaseOrder | null | undefined>();
  const [detail, setDetail] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [planning, setPlanning] = useState<PurchaseOrder | null>(null);
  const canManage = user.permissions.includes('purchases.manage');
  const refresh = () => { resource.reload(); setVersion(value => value + 1); };
  return <>
    <PageHeading eyebrow="PURCHASE ORDERS" title="采购记录" description="从下单到分批到货，记录每张采购单的商品、数量、交期和履约情况。" extra={canManage && <Button type="primary" icon={<PlusOutlined />} onClick={() => setEditing(null)}>新增采购单</Button>} />
    <ErrorNotice error={resource.error} retry={resource.reload} />
    <Card className="section-card" title="采购单" extra={<Button icon={<ReloadOutlined />} onClick={resource.reload}>刷新</Button>}>
      <div className="catalog-filter-bar"><Input className="catalog-search" prefix={<SearchOutlined />} placeholder="搜索采购单号" value={q} onChange={event => setQ(event.target.value)} allowClear /><Select placeholder="全部状态" value={status} onChange={setStatus} allowClear options={options(purchaseStatuses)} style={{ width: 170 }} /></div>
      <Table<PurchaseOrder> rowKey="id" dataSource={resource.data?.items ?? []} loading={resource.loading} pagination={resource.pagination} scroll={{ x: 1100 }} locale={{ emptyText: <EmptyState text="暂无采购记录。先维护商品和供应商，再建立采购单。" /> }} columns={[
        { title: '采购单 / 店铺', width: 250, render: (_, item) => <><button className="catalog-title-link" onClick={() => setDetail(item.id)}>{item.number}</button><small className="cell-secondary">{item.store_name}</small></> },
        { title: '供应商', dataIndex: 'supplier_name', width: 170 },
        { title: '采购 / 预计到货', width: 170, render: (_, item) => <>{item.order_date}<small className="cell-secondary">预计 {item.expected_date || '未设置'}</small></> },
        ...(user.permissions.includes('costs.view') ? [{ title: '采购金额', width: 170, render: (_: unknown, item: PurchaseOrder) => displayMoney(item.total_amount, item.currency) }] : []),
        { title: '到货进度', width: 170, render: (_, item) => { const received = item.lines.reduce((sum, line) => sum + line.received_quantity, 0); const quantity = item.lines.reduce((sum, line) => sum + line.quantity, 0); return <><Progress percent={Math.round(received / quantity * 100)} size="small" /><small>{received} / {quantity} 件</small></>; } },
        { title: '状态', width: 170, render: (_, item) => <StatusTag status={item.status} labels={purchaseStatuses} overdue={item.overdue} /> },
        { title: '操作', width: 90, render: (_, item) => <Button type="link" onClick={() => setDetail(item.id)}>详情</Button> },
      ]} />
    </Card>
    {detail && <PurchaseDetails key={`${detail}:${version}`} id={detail} user={user} onClose={() => setDetail(null)} onEdit={setEditing} onPlan={setPlanning} onChanged={refresh} />}
    {editing !== undefined && <PurchaseEditor order={editing} stores={stores} selectedStore={selectedStore} onClose={() => setEditing(undefined)} onSaved={() => { setEditing(undefined); refresh(); }} />}
    {planning && <ShipmentEditor user={user} stores={stores} selectedStore={selectedStore} purchase={planning} onClose={() => setPlanning(null)} onSaved={() => { setPlanning(null); refresh(); }} />}
  </>;
}

function PurchaseDetails({ id, user, onClose, onEdit, onPlan, onChanged }: { id: string; user: User; onClose: () => void; onEdit: (order: PurchaseOrder) => void; onPlan: (order: PurchaseOrder) => void; onChanged: () => void }) {
  const resource = useResource<PurchaseOrder>(`/purchase-orders/${id}`);
  const order = resource.data;
  const { modal, message } = AntApp.useApp();
  const [error, setError] = useState('');
  const perform = (action: 'confirm' | 'cancel') => modal.confirm({ title: action === 'confirm' ? '提交此采购单？' : '取消尚未分配的采购余量？', content: action === 'confirm' ? '提交后商品、数量和金额将锁定，可以安排分批发货。' : '仅取消未分配给货件的余量，已到货、待发及在途数量均保留。', onOk: async () => {
    try { await api(`/purchase-orders/${id}/${action}`, { method: 'POST', body: {} }); message.success('采购单已更新'); onChanged(); }
    catch (cause) { setError(errorText(cause)); throw cause; }
  } });
  return <Drawer open onClose={onClose} title="采购单详情" size={1040} loading={resource.loading}>
    <ErrorNotice error={resource.error || error} retry={resource.reload} />{order && <>
      <div className="supply-detail-heading"><div><h2>{order.number}</h2><StatusTag status={order.status} labels={purchaseStatuses} overdue={order.overdue} /></div><Space wrap>
        {user.permissions.includes('purchases.manage') && order.status === 'draft' && <><Button onClick={() => onEdit(order)}>编辑草稿</Button><Button type="primary" onClick={() => perform('confirm')}>提交采购单</Button></>}
        {user.permissions.includes('shipments.manage') && ['ordered', 'partially_received'].includes(order.status) && <Button type="primary" onClick={() => onPlan(order)}>安排供应商发货</Button>}
        {user.permissions.includes('purchases.manage') && !['received', 'closed', 'cancelled'].includes(order.status) && <Button danger onClick={() => perform('cancel')}>取消未分配余量</Button>}
      </Space></div>
      <Descriptions bordered column={2} size="small" items={[
        { key: 'store', label: '所属店铺', children: order.store_name }, { key: 'supplier', label: '供应商', children: order.supplier_name },
        { key: 'date', label: '采购日期', children: order.order_date }, { key: 'expected', label: '预计到货', children: order.expected_date || '—' },
        ...(order.total_amount !== undefined ? [{ key: 'amount', label: '采购金额', children: displayMoney(order.total_amount, order.currency) }, { key: 'terms', label: '付款约定', children: order.payment_terms || '—' }] : []),
        { key: 'notes', label: '备注', children: order.notes || '—', span: 2 }, { key: 'created', label: '创建时间', children: dateTime(order.created_at), span: 2 },
      ]} />
      <h3 className="catalog-section-title">商品及交付情况</h3>
      <Table rowKey="id" dataSource={order.lines} pagination={false} scroll={{ x: 850 }} columns={[
        { title: '商品', render: (_, line) => <>{line.product_name}<small className="cell-secondary">{line.internal_sku}</small></> },
        { title: '采购量', dataIndex: 'quantity' }, ...(order.total_amount !== undefined ? [{ title: '单价', dataIndex: 'unit_price' }] : []),
        { title: '已到货', dataIndex: 'received_quantity' }, { title: '待发 / 在途', dataIndex: 'allocated_quantity' },
        { title: '可安排发货', dataIndex: 'unallocated_quantity' }, { title: '已取消', dataIndex: 'cancelled_quantity' },
      ]} />
    </>}
  </Drawer>;
}

interface PurchaseValues { store_id: string; supplier_id: string; order_date: string; expected_date?: string; currency: string; payment_terms?: string; notes?: string; lines: { product_id: string; quantity: number; unit_price: string }[] }
function PurchaseEditor({ order, stores, selectedStore, onClose, onSaved }: { order: PurchaseOrder | null; stores: Store[]; selectedStore: string; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm<PurchaseValues>();
  const [token] = useState(requestId);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const save = async (input: PurchaseValues) => {
    setSaving(true); setError('');
    const body = { ...input, expected_date: input.expected_date || null, notes: input.notes || '', payment_terms: input.payment_terms || '', lines: input.lines.map(line => ({ product_id: line.product_id, quantity: line.quantity, unit_price: String(line.unit_price) })) };
    try { if (order) { const { store_id: _store, ...changes } = body; await api(`/purchase-orders/${order.id}`, { method: 'PATCH', body: changes }); }
      else await api('/purchase-orders', { method: 'POST', body: { ...body, request_id: token } }); onSaved(); }
    catch (cause) { setError(errorText(cause)); } finally { setSaving(false); }
  };
  return <Modal open title={order ? '编辑采购草稿' : '新增采购单'} width={1000} onCancel={saving ? undefined : onClose} closable={!saving} mask={{ closable: false }} onOk={() => form.submit()} confirmLoading={saving} okText="保存草稿">
    <ErrorNotice error={error} />
    <Form form={form} layout="vertical" onFinish={save} initialValues={order ? { ...order, expected_date: order.expected_date || '', lines: order.lines.map(line => ({ product_id: line.product_id, quantity: line.quantity, unit_price: line.unit_price })) } : { store_id: storeParam(selectedStore), order_date: dayjs().format('YYYY-MM-DD'), currency: 'CNY', lines: [{ quantity: 1, unit_price: '0' }] }}>
      <Row gutter={16}><Col span={12}><StoreField stores={stores} fixed={!!order} /></Col><Col span={12}><Form.Item name="supplier_id" label="供应商" rules={required}><RemoteSelect path="/suppliers?is_active=true" initialLabel={order?.supplier_name} /></Form.Item></Col></Row>
      <Row gutter={16}><Col span={8}><Form.Item name="order_date" label="采购日期" rules={required}><Input type="date" /></Form.Item></Col><Col span={8}><Form.Item name="expected_date" label="预计到货"><Input type="date" /></Form.Item></Col><Col span={8}><Form.Item name="currency" label="币种" rules={required}><Select options={['CNY', 'USD', 'EUR', 'GBP'].map(value => ({ value, label: value }))} /></Form.Item></Col></Row>
      <Form.List name="lines" rules={[{ validator: async (_, lines) => { if (!lines?.length) throw new Error('至少添加一行商品'); if (lines.length > 100) throw new Error('最多 100 行'); } }]}>{(fields, { add, remove }, { errors }) => <>
        {fields.map(field => <Row gutter={12} key={field.key} align="middle"><Col span={12}><Form.Item name={[field.name, 'product_id']} label="商品 / SKU" rules={required}><RemoteSelect path="/products?is_active=true" initialLabel={order?.lines[field.name]?.product_name} /></Form.Item></Col><Col span={5}><Form.Item name={[field.name, 'quantity']} label="采购数量" rules={required}><QuantityInput /></Form.Item></Col><Col span={5}><Form.Item name={[field.name, 'unit_price']} label="单价" rules={required}><InputNumber stringMode min="0" max="99999999999999.9999" precision={4} style={{ width: '100%' }} /></Form.Item></Col><Col span={2}><Button aria-label="移除商品行" type="text" icon={<MinusCircleOutlined />} onClick={() => remove(field.name)} /></Col></Row>)}
        <Form.ErrorList errors={errors} /><Button block type="dashed" icon={<PlusOutlined />} disabled={fields.length >= 100} onClick={() => add({ quantity: 1, unit_price: '0' })}>添加商品</Button>
      </>}</Form.List>
      <Form.Item name="payment_terms" label="付款约定" style={{ marginTop: 20 }}><Input maxLength={2000} /></Form.Item><Form.Item name="notes" label="采购备注"><Input.TextArea rows={2} maxLength={5000} /></Form.Item>
    </Form>
  </Modal>;
}
