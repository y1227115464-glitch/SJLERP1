import { useState } from 'react';
import { Alert, App, AutoComplete, Button, Card, Form, Input, InputNumber, Modal, Select, Space, Switch, Table, Tag } from 'antd';
import { api, errorText } from './api';
import { ErrorNotice, usePagedList, useResource } from './common';
import { queryPath, useDebouncedValue } from './CatalogShared';
import type { Store, User } from './types';

type Allocation = { sku: string; percentage: string | number };
type Campaign = { store_id: string; store_name: string; campaign: string; revision: number; allocations: Allocation[]; is_deleted?: boolean };

export function BrandAdAllocations({ selectedStore, user, onChanged }: { selectedStore: string; user: User; onChanged?: () => void }) {
  const [q, setQ] = useState('');
  const [editing, setEditing] = useState<Campaign>();
  const [showDeleted, setShowDeleted] = useState(false);
  const [deleting, setDeleting] = useState<Campaign>();
  const [deletingBusy, setDeletingBusy] = useState(false);
  const [deleteError, setDeleteError] = useState('');
  const { message } = App.useApp();
  const term = useDebouncedValue(q);
  const list = usePagedList<Campaign>(queryPath('/brand-ad-campaigns', { store_id: selectedStore === 'all' ? undefined : selectedStore, q: term, show_deleted: showDeleted }));
  const canEdit = user.permissions.includes('reports.import');
  const remove = async () => {
    if (!deleting) return;
    setDeletingBusy(true); setDeleteError('');
    try {
      await api('/brand-ad-campaigns', { method: 'DELETE', body: { store_id: deleting.store_id, campaign: deleting.campaign, revision: deleting.revision } });
      message.success('已删除活动分摊，可通过“显示已删除”恢复');
      setDeleting(undefined);
      if (!showDeleted && list.data?.items.length === 1 && list.pagination.current > 1) list.pagination.onChange(list.pagination.current - 1);
      list.reload(); onChanged?.();
    } catch (cause) { setDeleteError(errorText(cause)); list.reload(); } finally { setDeletingBusy(false); }
  };
  return <>
    <Alert showIcon type="info" title="按店铺和广告活动名称维护商品分摊" description="导入品牌广告后，活动自动出现在这里。每个活动的 SKU 分担比例须合计 100%；保存后应用于该活动所有已导入及后续日报。活动名称须与报表一致，改名后需为新名称配置。" />
    <Card className="section-card" title="品牌广告商品分摊" extra={canEdit && <Button type="primary" onClick={() => setEditing({ store_id: selectedStore === 'all' ? '' : selectedStore, store_name: '', campaign: '', revision: 0, allocations: [] })}>新增活动分摊</Button>}>
      <Space wrap style={{ marginBottom: 16 }}><Input aria-label="搜索品牌广告活动" placeholder="搜索广告活动名称" value={q} onChange={e => setQ(e.target.value)} allowClear /><Button onClick={list.reload}>刷新</Button><Space><Switch aria-label="显示已删除" checked={showDeleted} onChange={setShowDeleted} />显示已删除</Space></Space>
      <ErrorNotice error={list.error} retry={list.reload} />
      <Table<Campaign> rowKey={row => JSON.stringify([row.store_id, row.campaign])} dataSource={list.data?.items ?? []} loading={list.loading} pagination={list.pagination} columns={[
        { title: '店铺', dataIndex: 'store_name' }, { title: '广告活动名称', dataIndex: 'campaign' },
        { title: '商品 / 分担比例', render: (_, row) => <>{row.is_deleted && <Tag>已删除，分摊已停用</Tag>}{row.allocations.length ? row.allocations.map(item => <div key={item.sku}>{item.sku} · {Number(item.percentage)}%</div>) : !row.is_deleted && <Tag color="warning">待配置分摊</Tag>}</> },
        { title: '操作', render: (_, row) => canEdit ? <Space wrap><Button onClick={() => setEditing(row)}>{row.is_deleted ? '恢复并维护' : '维护商品与比例'}</Button>{!row.is_deleted && <Button danger onClick={() => { setDeleteError(''); setDeleting(row); }}>删除分摊</Button>}</Space> : '只读' },
      ]} />
    </Card>
    {editing && <AllocationEditor key={JSON.stringify([editing.store_id, editing.campaign])} campaign={editing} onClose={() => setEditing(undefined)} onSaved={() => { setEditing(undefined); list.reload(); onChanged?.(); }} />}
    {deleting && <Modal open title="删除活动分摊" okText="删除分摊" cancelText="取消" okButtonProps={{ danger: true }} confirmLoading={deletingBusy}
      closable={!deletingBusy} maskClosable={!deletingBusy} cancelButtonProps={{ disabled: deletingBusy }} onCancel={() => setDeleting(undefined)} onOk={remove}>
      <p>删除「{deleting.store_name}」的「{deleting.campaign}」分摊记录？</p>
      <p>原始广告报表和花费会保留。该活动停止向商品分摊，相关利润会提示待分摊。可通过“显示已删除”恢复。</p>
      <ErrorNotice error={deleteError} />
    </Modal>}
  </>;
}

function SkuInput({ storeId, value, onChange }: { storeId: string; value?: string; onChange?: (value: string) => void }) {
  const [search, setSearch] = useState('');
  const term = useDebouncedValue(search);
  const options = useResource<{ items: { sku: string; name: string }[] }>(storeId ? queryPath('/brand-ad-campaigns/products', { store_id: storeId, q: term }) : null);
  return <AutoComplete aria-label="分担商品 SKU" value={value} onChange={onChange} onSearch={setSearch} disabled={!storeId}
    placeholder="选择商品，或输入订单中的 Seller SKU" showSearch={{ filterOption: false }} options={options.data?.items.map(item => ({ value: item.sku, label: `${item.sku}${item.name ? ` · ${item.name}` : ''}` }))} />;
}

function AllocationEditor({ campaign, onClose, onSaved }: { campaign: Campaign; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const { message } = App.useApp();
  const stores = useResource<{ items: Store[] }>('/stores?limit=200');
  const storeId = Form.useWatch('store_id', form) || campaign.store_id;
  const allocations: Allocation[] = Form.useWatch('allocations', form) || [];
  const total = allocations.reduce((sum, item) => sum + Math.round(Number(item?.percentage || 0) * 10000), 0) / 10000;
  const save = async (values: Campaign) => {
    setBusy(true); setError('');
    try {
      await api('/brand-ad-campaigns', { method: 'PUT', body: { store_id: values.store_id, campaign: values.campaign, allocations: values.allocations, revision: campaign.revision } });
      message.success('已保存商品分摊，利润分析将按新比例计算'); onSaved();
    } catch (cause) { setError(errorText(cause)); } finally { setBusy(false); }
  };
  return <Modal open width={780} title={campaign.is_deleted ? '恢复品牌广告商品分摊' : '维护品牌广告商品分摊'} onCancel={onClose} closable={!busy} maskClosable={!busy} footer={null}>
    <ErrorNotice error={error || stores.error} />
    <Form form={form} layout="vertical" initialValues={{ ...campaign, allocations: campaign.allocations.length ? campaign.allocations : [{ sku: '', percentage: 100 }] }} onFinish={save} disabled={busy}>
      <Form.Item name="store_id" label="店铺" rules={[{ required: true }]}><Select disabled={!!campaign.campaign || busy} options={stores.data?.items.filter(store => store.is_active).map(store => ({ value: store.id, label: store.name }))} /></Form.Item>
      <Form.Item name="campaign" label="广告活动名称" rules={[{ required: true, whitespace: true, max: 500 }]}><Input disabled={!!campaign.campaign || busy} /></Form.Item>
      <p className="table-subtext">商品按 Seller SKU 关联利润分析。内部商品编号与订单 SKU 不同时，请填写订单 SKU；CMBQ 尺寸别名会自动归并。</p>
      <Form.List name="allocations">{(fields, { add, remove }) => <>
        {fields.map(field => <div key={field.key} style={{ display: 'flex', gap: 12, alignItems: 'start' }}>
          <Form.Item name={[field.name, 'sku']} label="商品 SKU" style={{ flex: 1 }} rules={[{ required: true, whitespace: true, max: 120 }]}><SkuInput storeId={storeId} /></Form.Item>
          <Form.Item name={[field.name, 'percentage']} label="分担比例（%）" rules={[{ required: true }]}><InputNumber min={0.0001} max={100} precision={4} style={{ width: 140 }} /></Form.Item>
          <Button danger style={{ marginTop: 30 }} disabled={fields.length === 1} onClick={() => remove(field.name)}>移除</Button>
        </div>)}
        <Button onClick={() => add({ sku: '', percentage: null })} disabled={fields.length >= 200}>添加商品</Button>
      </>}</Form.List>
      <p style={{ color: total === 100 ? undefined : '#cf1322' }}>比例合计：{total}%（须为 100%）</p>
      <Space><Button onClick={onClose}>取消</Button><Button type="primary" htmlType="submit" loading={busy} disabled={total !== 100}>{campaign.is_deleted ? '恢复并保存' : '保存分摊'}</Button></Space>
    </Form>
  </Modal>;
}
