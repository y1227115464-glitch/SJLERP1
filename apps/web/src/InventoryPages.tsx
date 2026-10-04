import { useEffect, useState } from 'react';
import { Alert, Button, Card, Col, Form, Input, InputNumber, Modal, Row, Select, Statistic, Table, Tabs, Tag } from 'antd';
import { PlusOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import { api, errorText } from './api';
import { dateTime, EmptyState, ErrorNotice, PageHeading, usePagedList, useResource } from './common';
import { queryPath, useDebouncedValue } from './CatalogShared';
import { movementKinds, options, RemoteSelect, requestId, required, StoreField, storeParam } from './SupplyShared';
import type { InventoryBalance, Movement, StockSummary } from './supply-types';
import type { ListResult, Store, User } from './types';
import { adjustmentQuantity, productBelongsToStore } from './inventory-adjustment';
import type { Product } from './catalog-types';

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
          { title: '商品 / SKU', width: 270, render: (_, item) => <><strong>{item.internal_sku}</strong><small className="cell-secondary">{item.product_name}</small></> },
          { title: '店铺', dataIndex: 'store_name', width: 160 },
          ...(user.permissions.includes('inventory.adjust') ? [{ title: '操作', width: 80, render: (_: unknown, item: InventoryBalance) => <Button type="link" onClick={() => setEditing(item)}>调整</Button> }] : []),
          { title: '实物', dataIndex: 'quantity', width: 90 }, { title: '占用', dataIndex: 'reserved', width: 90 }, { title: '可用', dataIndex: 'available', width: 100, render: value => <strong className={value === 0 ? 'supply-zero' : ''}>{value}</strong> }, { title: '最后变动', dataIndex: 'updated_at', width: 170, render: dateTime },
        ]} />
      </Card></> },
      { key: 'movements', label: '库存流水', children: tab === 'movements' ? <MovementList key={`${selectedStore}:${version}`} selectedStore={selectedStore} /> : null },
    ]} />
    {editing !== undefined && <AdjustmentEditor balance={editing} stores={stores} selectedStore={selectedStore} onClose={() => setEditing(undefined)} onSaved={() => { setEditing(undefined); refresh(); }} />}
  </>;
}

function MovementList({ selectedStore }: { selectedStore: string }) {
  const [kind, setKind] = useState<string>();
  const [productId, setProductId] = useState<string>();
  const resource = usePagedList<Movement>(queryPath('/inventory/movements', { store_id: storeParam(selectedStore), product_id: productId, kind, warehouse_kind: 'fba' }));
  return <><ErrorNotice error={resource.error} retry={resource.reload} /><Card className="section-card" title="已过账流水" extra={<Button icon={<ReloadOutlined />} onClick={resource.reload}>刷新</Button>}>
    <div className="catalog-filter-bar"><InventorySkuFilter selectedStore={selectedStore} value={productId} onChange={setProductId} /><Select allowClear placeholder="全部变动类型" style={{ width: 200 }} value={kind} onChange={setKind} options={options(movementKinds)} /><span className="cell-secondary">已过账流水保留历史，差异通过新的调整记录处理。</span></div>
    <Table<Movement> rowKey="id" loading={resource.loading} dataSource={resource.data?.items ?? []} pagination={resource.pagination} scroll={{ x: 1480 }} columns={[
      { title: '时间 / 操作人', width: 180, render: (_, item) => <>{dateTime(item.created_at)}<small className="cell-secondary">{item.actor_name}</small></> },
      { title: '商品 / SKU', width: 230, render: (_, item) => <><strong>{item.internal_sku}</strong><small className="cell-secondary">{item.product_name}</small></> },
      { title: '店铺', dataIndex: 'store_name', width: 160 },
      { title: '类型', dataIndex: 'kind', width: 130, render: value => <Tag>{movementKinds[value]}</Tag> },
      { title: '实物变动', dataIndex: 'quantity', width: 100, render: value => value > 0 ? `+${value}` : value },
      { title: '消耗状态', width: 130, render: (_, item) => item.fifo ? <Tag color={item.fifo.is_current ? 'processing' : item.fifo.remaining_quantity ? 'default' : 'success'}>{item.fifo.is_current ? '当前消耗' : item.fifo.remaining_quantity ? '待消耗' : '已耗尽'}</Tag> : '—' },
      { title: '占用变动', dataIndex: 'reserved_delta', width: 100, render: value => value > 0 ? `+${value}` : value },
      { title: '变动后实物 / 占用', width: 140, render: (_, item) => `${item.balance_after} / ${item.reserved_after}` },
      { title: '来源 / 原因', width: 280, render: (_, item) => <>{item.reference_number || '手工登记'}<small className="cell-secondary" title={item.id}>流水 {item.id.slice(0, 8)}</small><small className="cell-secondary catalog-prewrap">{item.reason}</small></> },
    ]} locale={{ emptyText: <EmptyState text={productId || kind ? '当前筛选条件下暂无库存流水，请更换 SKU 或变动类型。' : '暂无库存变动。入库、发货、占用及调整会自动产生流水。'} /> }} />
  </Card></>;
}

function InventorySkuFilter({ selectedStore, value, onChange }: { selectedStore: string; value?: string; onChange: (value?: string) => void }) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [selection, setSelection] = useState<{ value: string; label: string; name: string }>();
  const q = useDebouncedValue(search);
  const resource = useResource<ListResult<InventoryBalance>>(open ? queryPath('/inventory', {
    store_id: storeParam(selectedStore), warehouse_kind: 'fba', q, limit: '200',
  }) : null);
  const choices = [...new Map((resource.data?.items ?? []).map(item => [item.product_id, {
    value: item.product_id, label: item.internal_sku, name: item.product_name,
  }])).values()];
  if (value && selection?.value === value && !choices.some(item => item.value === value)) choices.unshift(selection);
  return <Select aria-label="按 SKU 筛选库存流水" allowClear className="catalog-search" placeholder="搜索并选择 SKU（全部 SKU）"
    value={value} loading={resource.loading} options={choices} onOpenChange={setOpen}
    showSearch={{ filterOption: false, onSearch: setSearch }}
    optionRender={option => <><strong>{option.data.label}</strong><small className="cell-secondary">{option.data.name}</small></>}
    onChange={id => { setSelection(choices.find(item => item.value === id)); setSearch(''); onChange(id); }}
    notFoundContent={resource.error ? <Alert type="error" title={resource.error} /> : resource.loading ? '加载中…' : '没有匹配的 FBA 库存 SKU'}
    popupRender={menu => <>{menu}{(resource.data?.total ?? 0) > 200 && <div className="cell-secondary" style={{ padding: 8 }}>仅显示前 200 条库存对应的 SKU，请输入更完整的 SKU 缩小范围。</div>}</>} />;
}

function AdjustmentEditor({ balance, stores, selectedStore, onClose, onSaved }: { balance: InventoryBalance | null; stores: Store[]; selectedStore: string; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm();
  const [token] = useState(requestId);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [sign, setSign] = useState<1 | -1>(1);
  const [productLabel, setProductLabel] = useState<string>();
  const storeId = Form.useWatch('store_id', form);
  const productId = Form.useWatch('product_id', form);
  const kind = Form.useWatch('kind', form) ?? 'adjustment';
  const storeBrand = stores.find(store => store.id === storeId)?.brand;
  const selectedProduct = useResource<Pick<Product, 'brand' | 'is_active'>>(!balance && productId ? `/products/${productId}` : null);
  const productMatchesStore = productBelongsToStore(selectedProduct.data, storeBrand);
  const checkingProduct = !balance && !!productId && (selectedProduct.loading || !!selectedProduct.error || !productMatchesStore);
  const productPath = storeBrand?.trim() ? queryPath('/products', { is_active: true, brand: storeBrand }) : null;

  useEffect(() => {
    if (!balance && productId && (!storeBrand?.trim() || (selectedProduct.data && !productMatchesStore))) {
      form.setFieldValue('product_id', undefined);
      setProductLabel(undefined);
    }
  }, [balance, form, productId, storeBrand, selectedProduct.data, productMatchesStore]);

  return <Modal open title="FBA仓库 期初 / 库存调整" onCancel={saving ? undefined : onClose} closable={!saving} mask={{ closable: false }} onOk={() => form.submit()} confirmLoading={saving} okButtonProps={{ disabled: checkingProduct }} okText="确认过账">
    <ErrorNotice error={error} />
    <ErrorNotice error={selectedProduct.error} retry={selectedProduct.reload} />
    {!balance && storeId && !storeBrand?.trim() && <Alert className="page-notice" type="warning" showIcon title="当前店铺尚未关联品牌，请先在店铺管理中设置品牌。" />}
    <Form form={form} layout="vertical" disabled={saving} initialValues={{ store_id: balance?.store_id || storeParam(selectedStore), warehouse_id: balance?.warehouse_id, product_id: balance?.product_id, kind: 'adjustment', quantity: 1 }} onValuesChange={changes => {
      if (changes.kind === 'opening') setSign(1);
    }} onFinish={async values => {
      if (checkingProduct) return;
      setSaving(true); setError('');
      try {
        await api('/inventory/adjustments', { method: 'POST', body: { ...values, quantity: adjustmentQuantity(values.quantity, sign, values.kind), request_id: token } });
        onSaved();
      } catch (cause) { setError(errorText(cause)); } finally { setSaving(false); }
    }}>
      <StoreField stores={stores} fixed={!!balance} />
      <Form.Item name="warehouse_id" hidden><Input /></Form.Item>
      <Form.Item name="product_id" label="商品 / SKU" rules={required} getValueProps={value => ({ value: checkingProduct ? undefined : value })}>
        <RemoteSelect key={storeId || 'no-store'} path={productPath} disabled={!!balance || saving || checkingProduct} placeholder={!storeId ? '请先选择店铺' : !storeBrand?.trim() ? '请先设置店铺品牌' : '输入名称或 SKU 搜索并选择'}
          initialLabel={balance ? `${balance.internal_sku} · ${balance.product_name}` : productLabel}
          onRecord={record => setProductLabel(`${record.internal_sku} · ${record.name_zh || record.name}`)} />
      </Form.Item>
      <Row gutter={16}>
        <Col span={12}><Form.Item name="kind" label="类型" rules={required} extra={kind === 'opening' ? <div style={{ marginTop: 8 }}>每个sku期初库存只能登记一次</div> : undefined}><Select options={[{ value: 'opening', label: '期初库存' }, { value: 'adjustment', label: '库存调整' }]} /></Form.Item></Col>
        <Col span={12}><Form.Item name="quantity" label="变动数量" rules={[...required, { validator: async (_, value) => { adjustmentQuantity(value, sign, kind); } }]}>
          <InputNumber precision={0} min={1} max={1000000000} style={{ width: '100%' }} styles={{ prefix: { pointerEvents: 'auto' } }}
            prefix={<Button type="text" size="small" htmlType="button" disabled={saving || kind === 'opening'} aria-label={sign === 1 ? '当前增加，点击切换为减少' : '当前减少，点击切换为增加'} title={kind === 'opening' ? '期初库存仅支持增加' : '点击切换增加或减少'} onMouseDown={event => event.stopPropagation()} onClick={() => setSign(current => current === 1 ? -1 : 1)}>{sign === 1 ? '+' : '−'}</Button>} />
        </Form.Item></Col>
      </Row>
      <Form.Item name="reason" label="原因 / 盘点依据" rules={required}><Input.TextArea rows={3} maxLength={2000} /></Form.Item>
    </Form>
  </Modal>;
}
