import { useState } from 'react';
import { App as AntApp, Button, Card, Col, Descriptions, Drawer, Form, Input, InputNumber, Modal, Progress, Row, Select, Space, Switch, Table, Timeline } from 'antd';
import { MinusCircleOutlined, PlusOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api, errorText } from './api';
import { dateTime, EmptyState, ErrorNotice, PageHeading, usePagedList, useResource } from './common';
import { queryPath, useDebouncedValue } from './CatalogShared';
import { displayMoney, options, purchaseStatuses, QuantityInput, RemoteSelect, requestId, required, StatusTag, StoreField, storeParam } from './SupplyShared';
import { ProductQuickEditor } from './ProductQuickEditor';
import { cartonText, totalWeight } from './packing';
import { PurchaseLinesEditor } from './PurchaseLinesEditor';
import { ShipmentEditor } from './ShipmentForms';
import { SourceTasks, useLinkedDetail } from './TaskShared';
import type { PurchaseOrder } from './supply-types';
import type { Store, User } from './types';

interface Props { user: User; stores: Store[]; selectedStore: string }
export function PurchasesPage({ user, stores, selectedStore }: Props) {
  const [q, setQ] = useState('');
  const [status, setStatus] = useState<string>();
  const query = useDebouncedValue(q);
  const resource = usePagedList<PurchaseOrder>(queryPath('/purchase-orders', { store_id: storeParam(selectedStore), q: query, status }));
  const [editing, setEditing] = useState<PurchaseOrder | null | undefined>();
  const [detail, setDetail] = useLinkedDetail();
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
        { title: '采购 / 预计发货', width: 170, render: (_, item) => <>{item.order_date}<small className="cell-secondary">发货 {item.planned_ship_date || '未定日期'}</small></> },
        ...(user.permissions.includes('costs.view') ? [{ title: '采购金额', width: 170, render: (_: unknown, item: PurchaseOrder) => displayMoney(item.total_amount, item.currency) }] : []),
        { title: '到货进度', width: 170, render: (_, item) => { const received = item.lines.reduce((sum, line) => sum + line.received_quantity, 0); const quantity = item.lines.reduce((sum, line) => sum + line.quantity, 0); return <><Progress percent={Math.round(received / quantity * 100)} size="small" /><small>{received} / {quantity} 件</small></>; } },
        { title: '状态', width: 170, render: (_, item) => <StatusTag status={item.status} labels={purchaseStatuses} overdue={item.overdue} /> },
        { title: '操作', width: 90, render: (_, item) => <Button type="link" onClick={() => setDetail(item.id)}>详情</Button> },
      ]} />
    </Card>
    {detail && <PurchaseDetails key={`${detail}:${version}`} id={detail} user={user} onClose={() => setDetail(null)} onEdit={setEditing} onPlan={setPlanning} onChanged={refresh} />}
    {editing !== undefined && <PurchaseEditor user={user} order={editing} stores={stores} selectedStore={selectedStore} onClose={() => setEditing(undefined)} onSaved={() => { setEditing(undefined); refresh(); }} />}
    {planning && <ShipmentEditor user={user} stores={stores} selectedStore={selectedStore} purchase={planning} onClose={() => setPlanning(null)} onSaved={() => { setPlanning(null); refresh(); }} />}
  </>;
}

function PurchaseDetails({ id, user, onClose, onEdit, onPlan, onChanged }: { id: string; user: User; onClose: () => void; onEdit: (order: PurchaseOrder) => void; onPlan: (order: PurchaseOrder) => void; onChanged: () => void }) {
  const resource = useResource<PurchaseOrder>(`/purchase-orders/${id}`);
  const order = resource.data;
  const { modal, message } = AntApp.useApp();
  const [error, setError] = useState('');
  const [productId, setProductId] = useState<string>();
  const [editingLines, setEditingLines] = useState(false);
  const [followup, setFollowup] = useState<'schedule' | 'production'>();
  const perform = (action: 'confirm' | 'cancel') => modal.confirm({ title: action === 'confirm' ? '登记已向供应商下单？' : '取消尚未分配的采购余量？', content: action === 'confirm' ? '用于记录已完成的下单操作，不会自动向供应商发送订单。登记后可以安排分批发货，也可调整商品数量或追加商品，原商品单价保留。' : '仅取消未分配给货件的余量，已到货、待发及在途数量均保留。', onOk: async () => {
    try { await api(`/purchase-orders/${id}/${action}`, { method: 'POST', body: {} }); message.success('采购单已更新'); onChanged(); }
    catch (cause) { setError(errorText(cause)); throw cause; }
  } });
  return <Drawer open onClose={onClose} title="采购单详情" size={1040} loading={resource.loading}>
    <ErrorNotice error={resource.error || error} retry={resource.reload} />{order && <>
      <div className="supply-detail-heading"><div><h2>{order.number}</h2><StatusTag status={order.status} labels={purchaseStatuses} overdue={order.overdue} /></div><Space wrap>
        {user.permissions.includes('purchases.manage') && order.status === 'draft' && <><Button onClick={() => onEdit(order)}>编辑草稿</Button><Button type="primary" onClick={() => perform('confirm')}>登记已下单</Button></>}
        {user.permissions.includes('purchases.manage') && ['ordered', 'partially_received', 'received'].includes(order.status) && <Button onClick={() => setEditingLines(true)}>编辑商品及数量</Button>}
        {user.permissions.includes('shipments.manage') && ['ordered', 'partially_received'].includes(order.status) && <Button type="primary" onClick={() => onPlan(order)}>安排供应商发货</Button>}
        {user.permissions.includes('purchases.manage') && !['received', 'closed', 'cancelled'].includes(order.status) && <Button danger onClick={() => perform('cancel')}>取消未分配余量</Button>}
      </Space></div>
      {user.permissions.includes('purchases.manage') && !['received', 'closed', 'cancelled'].includes(order.status) && <Space style={{ marginBottom: 16 }}><Button onClick={() => setFollowup('schedule')}>调整预计发货日</Button><Button onClick={() => setFollowup('production')}>记录生产确认</Button></Space>}
      <Descriptions bordered column={2} size="small" items={[
        { key: 'store', label: '所属店铺', children: order.store_name }, { key: 'supplier', label: '供应商', children: order.supplier_name },
        { key: 'planned', label: '预计发货', children: order.planned_ship_date || '未定日期' }, { key: 'ordered', label: '登记下单时间', children: dateTime(order.ordered_at) },
        { key: 'date', label: '采购日期', children: order.order_date }, { key: 'expected', label: '预计到货', children: order.expected_date || '—' },
        ...(order.total_amount !== undefined ? [{ key: 'amount', label: '采购金额', children: displayMoney(order.total_amount, order.currency) }, { key: 'terms', label: '付款约定', children: order.payment_terms || '—' }] : []),
        { key: 'notes', label: '备注', children: order.notes || '—', span: 2 }, { key: 'created', label: '创建时间', children: dateTime(order.created_at), span: 2 },
      ]} />
      <h3 className="catalog-section-title">商品及交付情况</h3>
      <Table rowKey="id" dataSource={order.lines} pagination={false} scroll={{ x: 1150 }} columns={[
        { title: 'SKU / 中文商品名', render: (_, line) => <>{line.internal_sku}<small className="cell-secondary">{line.product_name_zh || line.product_name}</small>{user.permissions.includes('products.manage') && <Button type="link" size="small" onClick={() => setProductId(line.product_id)}>编辑商品信息</Button>}</> },
        { title: '箱规 / 箱数', render: (_, line) => <>{cartonText(line.quantity, line.units_per_carton)}<small className="cell-secondary">{line.units_per_carton ? `${line.units_per_carton} 件/箱` : '未维护'}</small></> },
        { title: '总重量（kg）', render: (_, line) => <>{line.total_weight_kg ?? '未维护'}<small className="cell-secondary">{line.unit_weight_kg ? `${line.unit_weight_kg} kg/件` : '单重未维护'}</small></> },
        { title: '采购量', dataIndex: 'quantity' }, ...(order.total_amount !== undefined ? [{ title: '单价', dataIndex: 'unit_price' }] : []),
        { title: '已到货', dataIndex: 'received_quantity' }, { title: '待发 / 在途', dataIndex: 'allocated_quantity' },
        { title: '可安排发货', dataIndex: 'unallocated_quantity' }, { title: '已取消', dataIndex: 'cancelled_quantity' },
      ]} />
      {!!order.production_history?.length && <><h3 className="catalog-section-title">生产确认记录（最近 50 条）</h3><Timeline items={order.production_history.map((entry, index) => ({ key: index, content: <><p className="catalog-prewrap">{entry.notes}</p><small>{entry.actor_name} · {dateTime(entry.created_at)}</small></> }))} /></>}
      {editingLines && <PurchaseLinesEditor order={order} onClose={() => setEditingLines(false)} onSaved={onChanged} />}
      <SourceTasks source={{ kind: 'purchase', id, number: order.number, store_id: order.store_id }} user={user} />
      {productId && <ProductQuickEditor id={productId} onClose={() => setProductId(undefined)} onSaved={() => { setProductId(undefined); onChanged(); }} />}
      {followup && <PurchaseFollowup kind={followup} order={order} onClose={() => setFollowup(undefined)} onSaved={onChanged} />}
    </>}
  </Drawer>;
}

interface PurchaseValues { store_id: string; supplier_id: string; order_date: string; expected_date?: string; planned_ship_date?: string; already_ordered?: boolean; currency: string; payment_terms?: string; notes?: string; lines: { product_id: string; quantity: number; unit_price: string; internal_sku?: string; product_name?: string; product_name_zh?: string; units_per_carton?: number | null; unit_weight_kg?: string | null }[] }
function PurchaseEditor({ user, order, stores, selectedStore, onClose, onSaved }: { user: User; order: PurchaseOrder | null; stores: Store[]; selectedStore: string; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm<PurchaseValues>();
  const [editingProduct, setEditingProduct] = useState<string>();
  const rows = Form.useWatch('lines', { form, preserve: true }) || [];
  const updateProduct = (product: { id: string; name?: string; name_zh?: string; internal_sku?: string; units_per_carton?: number | null; unit_weight_kg?: string | null }) => {
    form.setFieldsValue({ lines: form.getFieldValue('lines').map((line: PurchaseValues['lines'][number]) => line?.product_id === product.id ? { ...line, product_name: product.name, product_name_zh: product.name_zh, internal_sku: product.internal_sku, units_per_carton: product.units_per_carton, unit_weight_kg: product.unit_weight_kg } : line) });
  };
  const [token] = useState(requestId);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const save = async (input: PurchaseValues) => {
    setSaving(true); setError('');
    const body = { ...input, expected_date: input.expected_date || null, planned_ship_date: input.planned_ship_date || null, notes: input.notes || '', payment_terms: input.payment_terms || '', lines: input.lines.map(line => ({ product_id: line.product_id, quantity: line.quantity, unit_price: String(line.unit_price) })) };
    try { if (order) { const { store_id: _store, ...changes } = body; await api(`/purchase-orders/${order.id}`, { method: 'PATCH', body: changes }); }
      else await api('/purchase-orders', { method: 'POST', body: { ...body, request_id: token } }); onSaved(); }
    catch (cause) { setError(errorText(cause)); } finally { setSaving(false); }
  };
  return <Modal open title={order ? '编辑采购草稿' : '新增采购单'} width={1000} onCancel={saving ? undefined : onClose} closable={!saving} mask={{ closable: false }} onOk={() => form.submit()} confirmLoading={saving} okText={order ? "保存草稿" : "保存采购单"}>
    <ErrorNotice error={error} />
    <Form form={form} layout="vertical" onFinish={save} initialValues={order ? { ...order, expected_date: order.expected_date || '', planned_ship_date: order.planned_ship_date || '', lines: order.lines } : { store_id: storeParam(selectedStore), order_date: dayjs().format('YYYY-MM-DD'), currency: 'CNY', lines: [{ quantity: 1, unit_price: '0' }] }}>
      <Row gutter={16}><Col span={12}><StoreField stores={stores} fixed={!!order} /></Col><Col span={12}><Form.Item name="supplier_id" label="供应商" rules={required}><RemoteSelect path="/suppliers?is_active=true" initialLabel={order?.supplier_name} /></Form.Item></Col></Row>
      <Row gutter={16}><Col span={8}><Form.Item name="order_date" label="采购日期" rules={required}><Input type="date" /></Form.Item></Col><Col span={8}><Form.Item name="expected_date" label="预计到货"><Input type="date" /></Form.Item></Col><Col span={8}><Form.Item name="currency" label="币种" rules={required}><Select options={['CNY', 'USD', 'EUR', 'GBP'].map(value => ({ value, label: value }))} /></Form.Item></Col></Row>
      {!order && <Form.Item name="already_ordered" label="已向供应商下单" valuePropName="checked" extra="补录已下单采购时开启；仅登记事实，不发送订单。"><Switch /></Form.Item>}
      <Form.Item name="planned_ship_date" label="预计发货日" extra="用于生产确认和发货提醒；可以留空，确定后再补充。"><Input type="date" /></Form.Item>
      <Form.List name="lines" rules={[{ validator: async (_, lines) => { if (!lines?.length) throw new Error('至少添加一行商品'); if (lines.length > 100) throw new Error('最多 100 行'); } }]}>{(fields, { add, remove }, { errors }) => <>
        {fields.map(field => <div key={field.key}><Row gutter={12} key={field.key} align="middle"><Col span={12}><Form.Item name={[field.name, 'product_id']} label="商品 / SKU" rules={required}><RemoteSelect path="/products?is_active=true" selectedLabel={[rows[field.name]?.internal_sku, rows[field.name]?.product_name_zh || rows[field.name]?.product_name].filter(Boolean).join(' · ')} onRecord={updateProduct} /></Form.Item></Col><Col span={5}><Form.Item name={[field.name, 'quantity']} label="采购数量" rules={required}><QuantityInput /></Form.Item></Col><Col span={5}><Form.Item name={[field.name, 'unit_price']} label="单价" rules={required}><InputNumber stringMode min="0" max="99999999999999.9999" precision={4} style={{ width: '100%' }} /></Form.Item></Col><Col span={2}><Button aria-label="移除商品行" type="text" icon={<MinusCircleOutlined />} onClick={() => remove(field.name)} /></Col></Row><Space wrap style={{ marginBottom: 16 }}><span>{cartonText(rows[field.name]?.quantity || 0, rows[field.name]?.units_per_carton)}</span><span>总重量：{totalWeight(rows[field.name]?.quantity || 0, rows[field.name]?.unit_weight_kg)}</span>{user.permissions.includes('products.manage') && rows[field.name]?.product_id && <Button type="link" onClick={() => setEditingProduct(rows[field.name].product_id)}>编辑商品信息</Button>}</Space></div>)}
        <Form.ErrorList errors={errors} /><Button block type="dashed" icon={<PlusOutlined />} disabled={fields.length >= 100} onClick={() => add({ quantity: 1, unit_price: '0' })}>添加商品</Button>
      </>}</Form.List>
      <Form.Item name="payment_terms" label="付款约定" style={{ marginTop: 20 }}><Input maxLength={2000} /></Form.Item><Form.Item name="notes" label="采购备注"><Input.TextArea rows={2} maxLength={5000} /></Form.Item>
    </Form>
    {editingProduct && <ProductQuickEditor id={editingProduct} onClose={() => setEditingProduct(undefined)} onSaved={product => { updateProduct(product); setEditingProduct(undefined); }} />}
  </Modal>;
}


function PurchaseFollowup({ kind, order, onClose, onSaved }: { kind: 'schedule' | 'production'; order: PurchaseOrder; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm(); const [saving, setSaving] = useState(false); const [error, setError] = useState(''); const [token] = useState(requestId);
  return <Modal open title={kind === 'schedule' ? '调整预计发货日' : '记录生产进度确认'} onCancel={saving ? undefined : onClose} onOk={() => form.submit()} confirmLoading={saving} okText="保存记录"><ErrorNotice error={error} /><Form form={form} layout="vertical" initialValues={{ planned_ship_date: order.planned_ship_date || '' }} onFinish={async values => {
    setSaving(true); try { await api(`/purchase-orders/${order.id}/${kind}`, { method: 'POST', body: { request_id: token, ...(kind === 'schedule' ? { planned_ship_date: values.planned_ship_date || null } : { notes: values.notes }) } }); onSaved(); } catch (cause) { setError(errorText(cause)); } finally { setSaving(false); }
  }}>{kind === 'schedule' ? <Form.Item name="planned_ship_date" label="预计发货日" extra="跟随单据的待办会改期，手动调整过的待办会保留安排并显示提示。"><Input type="date" /></Form.Item> : <Form.Item name="notes" label="已确认的生产进度" rules={required} extra="记录后，对应未完成的生产确认提醒会自动完成。"><Input.TextArea rows={4} maxLength={2000} placeholder="例如：供应商确认周四可提供 50 件，其余下周补齐。" /></Form.Item>}</Form></Modal>;
}
