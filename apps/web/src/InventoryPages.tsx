import { useState } from 'react';
import { Alert, Button, Card, Col, Form, Input, InputNumber, Modal, Row, Select, Statistic, Switch, Table, Tabs, Tag } from 'antd';
import { PlusOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import { api, errorText } from './api';
import { ActiveTag, dateTime, EmptyState, ErrorNotice, PageHeading, usePagedList, useResource } from './common';
import { queryPath, useDebouncedValue } from './CatalogShared';
import { activeWarehousesPath, movementKinds, options, RemoteSelect, requestId, required, StoreField, storeParam, warehouseKinds } from './SupplyShared';
import type { InventoryBalance, Movement, StockSummary, Warehouse } from './supply-types';
import type { Store, User } from './types';

export function InventoryPage({ user, stores, selectedStore }: { user: User; stores: Store[]; selectedStore: string }) {
  const [q, setQ] = useState(''); const query = useDebouncedValue(q); const [warehouse, setWarehouse] = useState<string>(); const [editing, setEditing] = useState(false);
  const [tab, setTab] = useState('balances'); const [version, setVersion] = useState(0);
  const scope = { store_id: storeParam(selectedStore), warehouse_id: warehouse };
  const resource = usePagedList<InventoryBalance>(queryPath('/inventory', { ...scope, q: query }));
  const summary = useResource<StockSummary>(queryPath('/inventory/summary', { store_id: storeParam(selectedStore) }));
  const refresh = () => { resource.reload(); summary.reload(); setVersion(value => value + 1); };
  return <>
    <PageHeading eyebrow="INVENTORY CONTROL" title="库存管理" description="按店铺、仓库和商品核对实物、占用、可用与在途数量，每次变动保留单据流水。" extra={user.permissions.includes('inventory.adjust') && <Button type="primary" icon={<PlusOutlined />} onClick={() => setEditing(true)}>期初 / 库存调整</Button>} />
    <ErrorNotice error={summary.error} retry={summary.reload} />
    <Row gutter={[16, 16]} className="supply-summary">{[
      ['仓内实物', summary.data?.quantity], ['计划占用', summary.data?.reserved], ['当前可用', summary.data?.available], ['运输在途', summary.data?.in_transit],
    ].map(([title, value]) => <Col xs={12} xl={6} key={title}><Card><Statistic title={title} value={value ?? '—'} suffix="件" loading={summary.loading} /></Card></Col>)}</Row>
    <Alert className="page-notice" type="info" showIcon title="数量口径" description="摘要汇总当前店铺范围的全部仓库；在途仅计算已发出未接收数量。FBA 仓为人工接收的账面记录，实时可售库存需后续导入亚马逊快照核对。" />
    <Tabs activeKey={tab} onChange={setTab} items={[
      { key: 'balances', label: '库存余额', children: <><ErrorNotice error={resource.error} retry={resource.reload} /><Card className="section-card" title="仓库商品库存" extra={<Button icon={<ReloadOutlined />} onClick={refresh}>刷新</Button>}>
        <div className="catalog-filter-bar"><Input className="catalog-search" prefix={<SearchOutlined />} placeholder="搜索商品名称或内部 SKU" value={q} onChange={event => setQ(event.target.value)} allowClear /><div style={{ width: 260 }}><RemoteSelect path="/warehouses" value={warehouse} onChange={setWarehouse} placeholder="筛选仓库" /></div>{warehouse && <Button onClick={() => setWarehouse(undefined)}>全部仓库</Button>}</div>
        <Table<InventoryBalance> rowKey="id" dataSource={resource.data?.items ?? []} loading={resource.loading} pagination={resource.pagination} scroll={{ x: 1150 }} locale={{ emptyText: <EmptyState text="暂无库存记录。可登记期初数量，或从采购货件接收入库。" /> }} columns={[
          { title: '商品 / SKU', width: 270, render: (_, item) => <>{item.product_name}<small className="cell-secondary">{item.internal_sku}</small></> },
          { title: '店铺', dataIndex: 'store_name', width: 160 }, { title: '仓库', width: 200, render: (_, item) => <>{item.warehouse_name}<small className="cell-secondary">{warehouseKinds[item.warehouse_kind]}</small></> },
          { title: '实物', dataIndex: 'quantity', width: 90 }, { title: '占用', dataIndex: 'reserved', width: 90 }, { title: '可用', dataIndex: 'available', width: 100, render: value => <strong className={value === 0 ? 'supply-zero' : ''}>{value}</strong> }, { title: '最后变动', dataIndex: 'updated_at', width: 170, render: dateTime },
        ]} />
      </Card></> },
      { key: 'movements', label: '库存流水', children: tab === 'movements' ? <MovementList key={version} selectedStore={selectedStore} /> : null },
      { key: 'warehouses', label: '仓库档案', children: tab === 'warehouses' ? <WarehouseList user={user} /> : null },
    ]} />
    {editing && <AdjustmentEditor stores={stores} selectedStore={selectedStore} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); refresh(); }} />}
  </>;
}

function MovementList({ selectedStore }: { selectedStore: string }) {
  const [kind, setKind] = useState<string>();
  const resource = usePagedList<Movement>(queryPath('/inventory/movements', { store_id: storeParam(selectedStore), kind }));
  return <><ErrorNotice error={resource.error} retry={resource.reload} /><Card className="section-card" title="已过账流水" extra={<Button icon={<ReloadOutlined />} onClick={resource.reload}>刷新</Button>}>
    <div className="catalog-filter-bar"><Select allowClear placeholder="全部变动类型" style={{ width: 200 }} value={kind} onChange={setKind} options={options(movementKinds)} /><span className="cell-secondary">已过账流水保留历史，差异通过新的调整记录处理。</span></div>
    <Table<Movement> rowKey="id" loading={resource.loading} dataSource={resource.data?.items ?? []} pagination={resource.pagination} scroll={{ x: 1450 }} columns={[
      { title: '时间 / 操作人', width: 180, render: (_, item) => <>{dateTime(item.created_at)}<small className="cell-secondary">{item.actor_name}</small></> },
      { title: '商品 / SKU', width: 230, render: (_, item) => <>{item.product_name}<small className="cell-secondary">{item.internal_sku}</small></> },
      { title: '店铺 / 仓库', width: 180, render: (_, item) => <>{item.store_name}<small className="cell-secondary">{item.warehouse_name}</small></> },
      { title: '类型', dataIndex: 'kind', width: 130, render: value => <Tag>{movementKinds[value]}</Tag> },
      { title: '实物变动', dataIndex: 'quantity', width: 100, render: value => value > 0 ? `+${value}` : value },
      { title: '占用变动', dataIndex: 'reserved_delta', width: 100, render: value => value > 0 ? `+${value}` : value },
      { title: '变动后实物 / 占用', width: 140, render: (_, item) => `${item.balance_after} / ${item.reserved_after}` },
      { title: '来源 / 原因', width: 280, render: (_, item) => <>{item.reference_number || '手工登记'}<small className="cell-secondary catalog-prewrap">{item.reason}</small></> },
    ]} locale={{ emptyText: <EmptyState text="暂无库存变动。入库、发货、占用及调整会自动产生流水。" /> }} />
  </Card></>;
}

function WarehouseList({ user }: { user: User }) {
  const resource = usePagedList<Warehouse>('/warehouses'); const [editing, setEditing] = useState<Warehouse | null | undefined>();
  const canManage = user.permissions.includes('warehouses.manage');
  return <><ErrorNotice error={resource.error} retry={resource.reload} /><Card className="section-card" title="公司共享仓库档案" extra={canManage && <Button icon={<PlusOutlined />} onClick={() => setEditing(null)}>新增仓库</Button>}>
    <Table<Warehouse> rowKey="id" dataSource={resource.data?.items ?? []} loading={resource.loading} pagination={resource.pagination} scroll={{ x: 850 }} columns={[
      { title: '仓库编码', dataIndex: 'code' }, { title: '仓库名称', dataIndex: 'name' }, { title: '仓库类型', dataIndex: 'kind', render: value => warehouseKinds[value] }, { title: '地址', dataIndex: 'address' },
      { title: '状态', dataIndex: 'is_active', render: value => <ActiveTag active={value} /> }, { title: '操作', render: (_, item) => canManage && <Button type="link" onClick={() => setEditing(item)}>编辑</Button> },
    ]} locale={{ emptyText: <EmptyState text="请按实际业务建立国内仓、海外仓或 FBA 目的仓。" /> }} />
  </Card>{editing !== undefined && <WarehouseEditor warehouse={editing} onClose={() => setEditing(undefined)} onSaved={() => { setEditing(undefined); resource.reload(); }} />}</>;
}

function WarehouseEditor({ warehouse, onClose, onSaved }: { warehouse: Warehouse | null; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm(); const [saving, setSaving] = useState(false); const [error, setError] = useState('');
  return <Modal open title={warehouse ? '编辑仓库' : '新增仓库'} onCancel={saving ? undefined : onClose} closable={!saving} mask={{ closable: false }} onOk={() => form.submit()} confirmLoading={saving}>
    <ErrorNotice error={error} /><Form form={form} layout="vertical" initialValues={warehouse || { kind: 'domestic', is_active: true }} onFinish={async values => {
      setSaving(true); setError(''); try { await api(warehouse ? `/warehouses/${warehouse.id}` : '/warehouses', { method: warehouse ? 'PATCH' : 'POST', body: { code: values.code, name: values.name, kind: values.kind, address: values.address || '', is_active: values.is_active } }); onSaved(); }
      catch (cause) { setError(errorText(cause)); } finally { setSaving(false); }
    }}><Form.Item name="code" label="仓库编码" rules={[...required, { pattern: /^[A-Za-z0-9_-]+$/, message: '使用字母、数字、下划线或连字符' }]}><Input maxLength={50} /></Form.Item><Form.Item name="name" label="仓库名称" rules={required}><Input maxLength={120} /></Form.Item><Form.Item name="kind" label="仓库类型" rules={required}><Select options={options(warehouseKinds)} /></Form.Item><Form.Item name="address" label="地址"><Input.TextArea rows={2} maxLength={1000} /></Form.Item><Form.Item name="is_active" label="启用" valuePropName="checked"><Switch /></Form.Item></Form>
  </Modal>;
}

function AdjustmentEditor({ stores, selectedStore, onClose, onSaved }: { stores: Store[]; selectedStore: string; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm(); const [token] = useState(requestId); const [saving, setSaving] = useState(false); const [error, setError] = useState('');
  return <Modal open title="期初 / 库存调整" onCancel={saving ? undefined : onClose} closable={!saving} mask={{ closable: false }} onOk={() => form.submit()} confirmLoading={saving} okText="确认过账">
    <Alert type="info" showIcon className="page-notice" title="填入实际变动量" description="增加填正数，减少填负数；期初仅可登记一次。已保存流水不能编辑，请写明盘点或调整原因。" /><ErrorNotice error={error} />
    <Form form={form} layout="vertical" initialValues={{ store_id: storeParam(selectedStore), kind: 'opening', quantity: 1 }} onFinish={async values => {
      setSaving(true); setError(''); try { await api('/inventory/adjustments', { method: 'POST', body: { ...values, request_id: token } }); onSaved(); }
      catch (cause) { setError(errorText(cause)); } finally { setSaving(false); }
    }}><StoreField stores={stores} /><Form.Item name="warehouse_id" label="仓库" rules={required}><RemoteSelect path={activeWarehousesPath} /></Form.Item><Form.Item name="product_id" label="商品 / SKU" rules={required}><RemoteSelect path="/products?is_active=true" /></Form.Item><Row gutter={16}><Col span={12}><Form.Item name="kind" label="类型" rules={required}><Select options={[{ value: 'opening', label: '期初库存' }, { value: 'adjustment', label: '库存调整' }]} /></Form.Item></Col><Col span={12}><Form.Item name="quantity" label="变动数量" rules={[...required, { validator: async (_, value) => { if (!value) throw new Error('数量不能为零'); } }]}><InputNumber precision={0} min={-1000000000} max={1000000000} style={{ width: '100%' }} /></Form.Item></Col></Row><Form.Item name="reason" label="原因 / 盘点依据" rules={required}><Input.TextArea rows={3} maxLength={2000} /></Form.Item></Form>
  </Modal>;
}
