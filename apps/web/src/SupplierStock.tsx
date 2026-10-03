import { useEffect, useState } from 'react';
import { Alert, Button, Card, Checkbox, Drawer, Form, Input, Modal, Select, Space, Table, Tabs } from 'antd';
import { api, errorText } from './api';
import { dateTime, EmptyState, ErrorNotice, usePagedList, useResource } from './common';
import { queryPath, useDebouncedValue } from './CatalogShared';
import { displayMoney, options, QuantityInput, requestId, required, storeParam } from './SupplyShared';
import type { PurchaseOrder } from './supply-types';
import type { User } from './types';

const payments: Record<string, string> = { unknown: '待核实', unpaid: '未付款', partial: '部分付款', paid: '已付款' };
const kinds: Record<string, string> = { transfer: '采购转入', release: '转回采购待发货', payment: '更新付款情况', shipment: '发货分配 / 退回' };
interface Stock {
  id: string; store_id: string; store_name: string; supplier_id: string; supplier_name: string;
  purchase_order_id: string; purchase_number: string; product_name: string; internal_sku: string;
  quantity: number; remaining_quantity: number; payment_status: string; reason: string; created_at: string;
  unit_price?: string; currency?: string;
}
interface Summary { id: string; supplier_name: string; quantity: number; batches: number }
interface SkuStock { id: string; internal_sku: string; product_name: string; quantity: number; batches: number; suppliers: number }
interface Event { id: string; kind: string; quantity: number; balance_after: number; reason: string; payment_status: string; actor_name: string; created_at: string }

export function SupplierStockPanel({ user, selectedStore, version, onChanged, onPurchase }: { user: User; selectedStore: string; version: number; onChanged: () => void; onPurchase: (id: string) => void }) {
  const [supplier, setSupplier] = useState<Summary>();
  const [view, setView] = useState('skus');
  const [q, setQ] = useState('');
  const [includeEmpty, setIncludeEmpty] = useState(false);
  const [selectedSku, setSelectedSku] = useState<SkuStock>();
  const [action, setAction] = useState<{ stock: Stock; kind: 'release' | 'payment' }>();
  const [history, setHistory] = useState<Stock>();
  const query = useDebouncedValue(q);
  const summary = usePagedList<Summary>(queryPath('/supplier-stock/summary', { store_id: storeParam(selectedStore) }));
  const skus = usePagedList<SkuStock>(queryPath('/supplier-stock/skus', { store_id: storeParam(selectedStore), supplier_id: supplier?.id, q: query }));
  const resource = usePagedList<Stock>(queryPath('/supplier-stock', { store_id: storeParam(selectedStore), supplier_id: supplier?.id, q: query, include_empty: includeEmpty, product_id: selectedSku?.id }));
  useEffect(() => { summary.reload(); skus.reload(); resource.reload(); }, [version, summary.reload, skus.reload, resource.reload]);
  const refresh = onChanged;
  return <>
    <Alert className="page-notice" type="info" showIcon title="供应商代存库存" description="从采购单将未分配发货的余量转入，按供应商、店铺和采购批次管理。原采购金额和付款记录保留；需要发货时可在新建或修改发货弹窗中直接选择库存批次，也可先转回采购待发货。" />
    <ErrorNotice error={summary.error || skus.error || resource.error} retry={() => { summary.reload(); skus.reload(); resource.reload(); }} />
    <Card title="各供应商现存库存" className="section-card" extra={<Button onClick={refresh}>刷新库存</Button>}>
      <Table<Summary> rowKey="id" loading={summary.loading} dataSource={summary.data?.items ?? []} pagination={summary.pagination} size="small" columns={[
        { title: '供应商', dataIndex: 'supplier_name' }, { title: '现存数量（件）', dataIndex: 'quantity' }, { title: '有库存批次', dataIndex: 'batches' },
        { title: '操作', render: (_, row) => <Button type="link" onClick={() => { setSupplier(row); setSelectedSku(undefined); }}>查看库存明细</Button> },
      ]} locale={{ emptyText: <EmptyState text="暂无供应商库存。请在采购单中选择「转入供应商库存」。" /> }} />
    </Card>
    <Space wrap style={{ marginBlock: 16 }}><Input allowClear placeholder="搜索供应商、SKU、商品或采购单号" value={q} onChange={event => { setQ(event.target.value); setSelectedSku(undefined); }} style={{ width: 340 }} />{supplier && <Button onClick={() => { setSupplier(undefined); setSelectedSku(undefined); }}>全部供应商</Button>}</Space>
    <Card title={supplier?.supplier_name || '全部供应商'} className="section-card">
      <Tabs activeKey={view} onChange={setView} items={[{ key: 'skus', label: 'SKU 库存' }, { key: 'batches', label: '库存批次' }]} />
      {view === 'skus' && <>
      <p className="catalog-field-help">按当前店铺、供应商和搜索条件，将同一 SKU 的现存数量合并汇总；已转完的批次不计入。点击「查看批次」可切换到对应的库存批次。</p>
      <Table<SkuStock> rowKey="id" dataSource={skus.data?.items ?? []} loading={skus.loading} pagination={skus.pagination} scroll={{ x: 760 }} locale={{ emptyText: <EmptyState text="当前条件下暂无 SKU 库存。" /> }} columns={[
        { title: 'SKU / 商品', width: 280, render: (_, row) => <>{row.internal_sku}<small className="cell-secondary">{row.product_name}</small></> },
        { title: '现存数量（件）', dataIndex: 'quantity', width: 150 },
        { title: '供应商数', dataIndex: 'suppliers', width: 100 },
        { title: '有库存批次', dataIndex: 'batches', width: 120 },
        { title: '操作', width: 110, render: (_, row) => <Button type="link" onClick={() => { setSelectedSku(row); setView('batches'); }}>查看批次</Button> },
      ]} />
      </>}
      {view === 'batches' && <>
      <Space wrap style={{ marginBottom: 16 }}><Checkbox checked={includeEmpty} onChange={event => setIncludeEmpty(event.target.checked)}>包含已转完批次</Checkbox>{selectedSku && <><span>当前 SKU：{selectedSku.internal_sku}</span><Button onClick={() => setSelectedSku(undefined)}>全部 SKU 批次</Button></>}</Space>
      <Table<Stock> rowKey="id" dataSource={resource.data?.items ?? []} loading={resource.loading} pagination={resource.pagination} scroll={{ x: 1250 }} columns={[
        { title: '供应商 / 店铺', width: 180, render: (_, row) => <>{row.supplier_name}<small className="cell-secondary">{row.store_name}</small></> },
        { title: '商品 / SKU', width: 200, render: (_, row) => <>{row.internal_sku}<small className="cell-secondary">{row.product_name}</small></> },
        { title: '来源采购单 / 转入时间', width: 250, render: (_, row) => <><Button type="link" onClick={() => onPurchase(row.purchase_order_id)}>{row.purchase_number}</Button><small className="cell-secondary">{dateTime(row.created_at)}</small></> },
        { title: '转入 / 现存', width: 110, render: (_, row) => `${row.quantity} / ${row.remaining_quantity} 件` },
        { title: '本批付款情况', width: 130, render: (_, row) => payments[row.payment_status] },
        ...(user.permissions.includes('costs.view') ? [{ title: '原采购单价', width: 130, render: (_: unknown, row: Stock) => displayMoney(row.unit_price, row.currency) }] : []),
        { title: '留存原因', dataIndex: 'reason', width: 180 },
        { title: '操作', width: 180, render: (_, row) => <Space direction="vertical" size={0}>
          {user.permissions.includes('purchases.manage') && <><Button type="link" disabled={!row.remaining_quantity} onClick={() => setAction({ stock: row, kind: 'release' })}>转回采购待发货</Button><Button type="link" onClick={() => setAction({ stock: row, kind: 'payment' })}>更新付款情况</Button></>}
          <Button type="link" onClick={() => setHistory(row)}>库存流水</Button>
        </Space> },
      ]} />
      </>}
    </Card>
    {action && <StockAction stock={action.stock} kind={action.kind} onClose={() => setAction(undefined)} onSaved={() => { setAction(undefined); refresh(); }} />}
    {history && <StockHistory stock={history} onClose={() => setHistory(undefined)} />}
  </>;
}

function StockHistory({ stock, onClose }: { stock: Stock; onClose: () => void }) {
  const resource = usePagedList<Event>(`/supplier-stock/${stock.id}/events`);
  return <Drawer open title={`${stock.internal_sku} · 库存流水`} size={850} onClose={onClose}>
    <p>{stock.supplier_name} · {stock.purchase_number}</p><ErrorNotice error={resource.error} retry={resource.reload} />
    <Table<Event> rowKey="id" loading={resource.loading} dataSource={resource.data?.items ?? []} pagination={resource.pagination} columns={[
      { title: '时间 / 操作人', render: (_, row) => <>{dateTime(row.created_at)}<small className="cell-secondary">{row.actor_name}</small></> },
      { title: '操作', render: (_, row) => kinds[row.kind] }, { title: '变动', render: (_, row) => row.quantity > 0 ? `+${row.quantity}` : row.quantity },
      { title: '余量', dataIndex: 'balance_after' }, { title: '付款情况', render: (_, row) => payments[row.payment_status] }, { title: '原因', dataIndex: 'reason' },
    ]} />
  </Drawer>;
}

function StockAction({ stock, kind, onClose, onSaved }: { stock: Stock; kind: 'release' | 'payment'; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm(); const [token] = useState(requestId); const [saving, setSaving] = useState(false); const [error, setError] = useState('');
  return <Modal open title={kind === 'release' ? '转回原采购单待发货' : '更新本批库存付款情况'} onCancel={saving ? undefined : onClose} closable={!saving} mask={{ closable: false }} onOk={() => form.submit()} confirmLoading={saving}>
    <p>{stock.internal_sku} · {stock.supplier_name} · 当前库存 {stock.remaining_quantity} 件</p>
    <ErrorNotice error={error} /><Form form={form} layout="vertical" initialValues={kind === 'release' ? { quantity: stock.remaining_quantity } : { payment_status: stock.payment_status }} onFinish={async values => {
      setSaving(true); setError('');
      try { await api(`/supplier-stock/${stock.id}/${kind}`, { method: 'POST', body: { request_id: token, ...values } }); onSaved(); }
      catch (cause) { setError(errorText(cause)); } finally { setSaving(false); }
    }}>
      {kind === 'release' ? <><Alert showIcon type="info" title="转回后到原采购单安排发货" description="可转回部分数量；此操作增加原单可安排发货余量，不表示货物已经发出，也不产生新的采购金额。" /><Form.Item name="quantity" label="转回数量" rules={[...required, { type: 'integer', min: 1, max: stock.remaining_quantity }]}><QuantityInput max={stock.remaining_quantity} /></Form.Item></> : <Form.Item name="payment_status" label="本批库存付款情况" rules={required} extra="独立记录这批库存的付款情况，不修改整张采购单的财务跟进。"><Select options={options(payments)} /></Form.Item>}
      <Form.Item name="reason" label="操作原因 / 备注" rules={[{ required: true, whitespace: true }]}><Input.TextArea rows={3} maxLength={1000} /></Form.Item>
    </Form>
  </Modal>;
}

export function SupplierStockTransfer({ id, onClose, onSaved }: { id: string; onClose: () => void; onSaved: () => void }) {
  const resource = useResource<PurchaseOrder>(`/purchase-orders/${id}`);
  if (!resource.data) return <Modal open title="转入供应商库存" footer={null} onCancel={onClose}>{resource.loading ? <p>读取最新采购余量…</p> : <ErrorNotice error={resource.error} retry={resource.reload} />}</Modal>;
  return <TransferForm order={resource.data} onClose={onClose} onSaved={onSaved} />;
}

function TransferForm({ order, onClose, onSaved }: { order: PurchaseOrder; onClose: () => void; onSaved: () => void }) {
  const remaining = order.lines.filter(line => (line.unallocated_quantity ?? 0) > 0);
  const [quantities, setQuantities] = useState<Record<string, number>>(Object.fromEntries(remaining.map(line => [line.product_id, line.unallocated_quantity ?? 0])));
  const [form] = Form.useForm(); const [token] = useState(requestId); const [saving, setSaving] = useState(false); const [error, setError] = useState('');
  const eligible = ['ordered', 'partially_received'].includes(order.status) && remaining.length > 0;
  return <Modal open title="采购余量转入供应商库存" width={850} onCancel={saving ? undefined : onClose} closable={!saving} mask={{ closable: false }} onOk={() => form.submit()} confirmLoading={saving} okText="确认转入库存" okButtonProps={{ disabled: !eligible }}>
    <Alert className="page-notice" type={eligible ? 'info' : 'warning'} showIcon title={`${order.supplier_name} · ${order.number}`} description={eligible ? '按商品填写转入数量，填 0 表示本次不转。数量仅限未分配发货的余量；原采购金额、已付款和发票记录保留。付款情况不同的库存请分次转入。' : '当前没有可转入的采购余量。'} />
    <ErrorNotice error={error} />
    <Table rowKey="id" dataSource={remaining} pagination={false} columns={[
      { title: '商品 / SKU', render: (_, line) => <>{line.internal_sku}<small className="cell-secondary">{line.product_name_zh || line.product_name}</small></> },
      { title: '可转余量', dataIndex: 'unallocated_quantity' },
      { title: '本次转入', render: (_, line) => <QuantityInput min={0} max={line.unallocated_quantity} value={quantities[line.product_id]} onChange={value => setQuantities(previous => ({ ...previous, [line.product_id]: Number(value ?? 0) }))} /> },
    ]} />
    <Form form={form} layout="vertical" initialValues={{ payment_status: 'unknown' }} onFinish={async values => {
      const lines = remaining.map(line => ({ product_id: line.product_id, quantity: quantities[line.product_id] })).filter(line => line.quantity !== 0);
      if (!lines.length || lines.some(line => !Number.isInteger(line.quantity) || line.quantity < 0 || line.quantity > (remaining.find(item => item.product_id === line.product_id)?.unallocated_quantity ?? 0))) { setError('请至少填写一件商品，且转入数量不能超过可转余量。'); return; }
      setSaving(true); setError('');
      try { await api(`/purchase-orders/${order.id}/supplier-stock`, { method: 'POST', body: { request_id: token, expected_version: order.lines_version, ...values, lines } }); onSaved(); }
      catch (cause) { setError(errorText(cause)); } finally { setSaving(false); }
    }}>
      <Form.Item name="payment_status" label="本次转入库存的付款情况" rules={required} extra="整单付款情况仅供参考，请核实这批余货是否已付款。"><Select options={options(payments)} /></Form.Item>
      <Form.Item name="reason" label="留存原因 / 备注" rules={[{ required: true, whitespace: true }]}><Input.TextArea rows={3} maxLength={1000} placeholder="例如：已支付货款，本次只发部分，剩余暂存供应商。" /></Form.Item>
    </Form>
  </Modal>;
}
