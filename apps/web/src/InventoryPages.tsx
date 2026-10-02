import { useState } from 'react';
import { Alert, Button, Card, Col, Form, Input, InputNumber, Modal, Row, Select, Statistic, Table, Tabs, Tag } from 'antd';
import { PlusOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import { api, errorText } from './api';
import { dateTime, EmptyState, ErrorNotice, PageHeading, usePagedList, useResource } from './common';
import { queryPath, useDebouncedValue } from './CatalogShared';
import { movementKinds, options, RemoteSelect, requestId, required, StoreField, storeParam } from './SupplyShared';
import type { InventoryBalance, Movement, StockSummary } from './supply-types';
import type { Store, User } from './types';

export function InventoryPage({ user, stores, selectedStore }: { user: User; stores: Store[]; selectedStore: string }) {
  const [q, setQ] = useState(''); const query = useDebouncedValue(q); const [editing, setEditing] = useState<InventoryBalance | null | undefined>();
  const [tab, setTab] = useState('balances'); const [version, setVersion] = useState(0);
  const scope = { store_id: storeParam(selectedStore), warehouse_kind: 'fba' };
  const resource = usePagedList<InventoryBalance>(queryPath('/inventory', { ...scope, q: query }));
  const summary = useResource<StockSummary>(queryPath('/inventory/summary', scope));
  const refresh = () => { resource.reload(); summary.reload(); setVersion(value => value + 1); };
  return <>
    <PageHeading eyebrow="INVENTORY CONTROL" title="FBA库存管理" description="统一按 FBA仓库核对各店铺商品的实物、占用、可用与在途数量，每次变动保留单据流水。" extra={user.permissions.includes('inventory.adjust') && <Button type="primary" icon={<PlusOutlined />} onClick={() => setEditing(null)}>期初 / 库存调整</Button>} />
    <ErrorNotice error={summary.error} retry={summary.reload} />
    <Row gutter={[16, 16]} className="supply-summary">{[
      ['仓内实物', summary.data?.quantity], ['计划占用', summary.data?.reserved], ['当前可用', summary.data?.available], ['运输在途', summary.data?.in_transit],
    ].map(([title, value]) => <Col xs={12} xl={6} key={title}><Card><Statistic title={title} value={value ?? '—'} suffix="件" loading={summary.loading} /></Card></Col>)}</Row>
    <Alert className="page-notice" type="info" showIcon title="数量口径" description="摘要、库存余额和库存流水统一统计 FBA仓库；在途仅计算发往 FBA仓库且已发出未接收的数量。FBA仓库库存为人工接收的账面记录，实时可售库存需后续导入亚马逊快照核对。" />
    <Tabs activeKey={tab} onChange={setTab} items={[
      { key: 'balances', label: '库存余额', children: <><ErrorNotice error={resource.error} retry={resource.reload} /><Card className="section-card" title="FBA仓库商品库存" extra={<Button icon={<ReloadOutlined />} onClick={refresh}>刷新</Button>}>
        <div className="catalog-filter-bar"><Input className="catalog-search" prefix={<SearchOutlined />} placeholder="搜索商品名称或内部 SKU" value={q} onChange={event => setQ(event.target.value)} allowClear /></div>
        <Table<InventoryBalance> rowKey="id" dataSource={resource.data?.items ?? []} loading={resource.loading} pagination={resource.pagination} scroll={{ x: 950 }} locale={{ emptyText: <EmptyState text="暂无库存记录。可登记期初数量，或从采购货件接收入库。" /> }} columns={[
          { title: '商品 / SKU', width: 270, render: (_, item) => <>{item.product_name}<small className="cell-secondary">{item.internal_sku}</small></> },
          { title: '店铺', dataIndex: 'store_name', width: 160 },
          ...(user.permissions.includes('inventory.adjust') ? [{ title: '操作', width: 80, render: (_: unknown, item: InventoryBalance) => <Button type="link" onClick={() => setEditing(item)}>调整</Button> }] : []),
          { title: '实物', dataIndex: 'quantity', width: 90 }, { title: '占用', dataIndex: 'reserved', width: 90 }, { title: '可用', dataIndex: 'available', width: 100, render: value => <strong className={value === 0 ? 'supply-zero' : ''}>{value}</strong> }, { title: '最后变动', dataIndex: 'updated_at', width: 170, render: dateTime },
        ]} />
      </Card></> },
      { key: 'movements', label: '库存流水', children: tab === 'movements' ? <MovementList key={version} selectedStore={selectedStore} /> : null },
    ]} />
    {editing !== undefined && <AdjustmentEditor balance={editing} stores={stores} selectedStore={selectedStore} onClose={() => setEditing(undefined)} onSaved={() => { setEditing(undefined); refresh(); }} />}
  </>;
}

function MovementList({ selectedStore }: { selectedStore: string }) {
  const [kind, setKind] = useState<string>();
  const resource = usePagedList<Movement>(queryPath('/inventory/movements', { store_id: storeParam(selectedStore), kind, warehouse_kind: 'fba' }));
  return <><ErrorNotice error={resource.error} retry={resource.reload} /><Card className="section-card" title="已过账流水" extra={<Button icon={<ReloadOutlined />} onClick={resource.reload}>刷新</Button>}>
    <div className="catalog-filter-bar"><Select allowClear placeholder="全部变动类型" style={{ width: 200 }} value={kind} onChange={setKind} options={options(movementKinds)} /><span className="cell-secondary">已过账流水保留历史，差异通过新的调整记录处理。</span></div>
    <Table<Movement> rowKey="id" loading={resource.loading} dataSource={resource.data?.items ?? []} pagination={resource.pagination} scroll={{ x: 1320 }} columns={[
      { title: '时间 / 操作人', width: 180, render: (_, item) => <>{dateTime(item.created_at)}<small className="cell-secondary">{item.actor_name}</small></> },
      { title: '商品 / SKU', width: 230, render: (_, item) => <>{item.product_name}<small className="cell-secondary">{item.internal_sku}</small></> },
      { title: '店铺', dataIndex: 'store_name', width: 160 },
      { title: '类型', dataIndex: 'kind', width: 130, render: value => <Tag>{movementKinds[value]}</Tag> },
      { title: '实物变动', dataIndex: 'quantity', width: 100, render: value => value > 0 ? `+${value}` : value },
      { title: '占用变动', dataIndex: 'reserved_delta', width: 100, render: value => value > 0 ? `+${value}` : value },
      { title: '变动后实物 / 占用', width: 140, render: (_, item) => `${item.balance_after} / ${item.reserved_after}` },
      { title: '来源 / 原因', width: 280, render: (_, item) => <>{item.reference_number || '手工登记'}<small className="cell-secondary catalog-prewrap">{item.reason}</small></> },
    ]} locale={{ emptyText: <EmptyState text="暂无库存变动。入库、发货、占用及调整会自动产生流水。" /> }} />
  </Card></>;
}

function AdjustmentEditor({ balance, stores, selectedStore, onClose, onSaved }: { balance: InventoryBalance | null; stores: Store[]; selectedStore: string; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm(); const [token] = useState(requestId); const [saving, setSaving] = useState(false); const [error, setError] = useState('');
  return <Modal open title="FBA仓库 期初 / 库存调整" onCancel={saving ? undefined : onClose} closable={!saving} mask={{ closable: false }} onOk={() => form.submit()} confirmLoading={saving} okText="确认过账">
    <Alert type="info" showIcon className="page-notice" title="填入实际变动量" description="增加填正数，减少填负数；期初仅可登记一次。已保存流水不能编辑，请写明盘点或调整原因。" /><ErrorNotice error={error} />
    <Form form={form} layout="vertical" initialValues={{ store_id: balance?.store_id || storeParam(selectedStore), warehouse_id: balance?.warehouse_id, product_id: balance?.product_id, kind: balance ? 'adjustment' : 'opening', quantity: 1 }} onFinish={async values => {
      setSaving(true); setError(''); try { await api('/inventory/adjustments', { method: 'POST', body: { ...values, request_id: token } }); onSaved(); }
      catch (cause) { setError(errorText(cause)); } finally { setSaving(false); }
    }}><StoreField stores={stores} fixed={!!balance} /><Form.Item name="warehouse_id" hidden><Input /></Form.Item><Form.Item name="product_id" label="商品 / SKU" rules={required}><RemoteSelect path="/products?is_active=true" disabled={!!balance} initialLabel={balance ? `${balance.internal_sku} · ${balance.product_name}` : undefined} /></Form.Item><Row gutter={16}><Col span={12}><Form.Item name="kind" label="类型" rules={required}><Select options={[{ value: 'opening', label: '期初库存' }, { value: 'adjustment', label: '库存调整' }]} /></Form.Item></Col><Col span={12}><Form.Item name="quantity" label="变动数量" rules={[...required, { validator: async (_, value) => { if (!value) throw new Error('数量不能为零'); } }]}><InputNumber precision={0} min={-1000000000} max={1000000000} style={{ width: '100%' }} /></Form.Item></Col></Row><Form.Item name="reason" label="原因 / 盘点依据" rules={required}><Input.TextArea rows={3} maxLength={2000} /></Form.Item></Form>
  </Modal>;
}
