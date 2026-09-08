import { lazy, Suspense, useState } from 'react';
import { Alert, App as AntApp, Button, Card, Col, Descriptions, Drawer, Form, Input, Modal, Row, Select, Space, Spin, Switch, Table, Tabs, Tag } from 'antd';
import { EditOutlined, PlusOutlined, ReloadOutlined, SearchOutlined, TeamOutlined } from '@ant-design/icons';
import { api, errorText } from './api';
import { ActiveTag, dateTime, EmptyState, ErrorNotice, PageHeading, usePagedList, useResource } from './common';
import { canViewQuotes, queryPath, SharedCatalogNotice, useDebouncedValue } from './CatalogShared';
import type { Supplier } from './catalog-types';
import type { User } from './types';
const QuoteCollection = lazy(() => import('./QuotePages').then(module => ({ default: module.QuoteCollection })));

export function SuppliersPage({ user }: { user: User }) {
  const canManage = user.permissions.includes('suppliers.manage');
  const [query, setQuery] = useState('');
  const [active, setActive] = useState<string>();
  const q = useDebouncedValue(query);
  const resource = usePagedList<Supplier>(queryPath('/suppliers', { q, is_active: active }));
  const [editing, setEditing] = useState<Supplier | null | undefined>(undefined);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [detailVersion, setDetailVersion] = useState(0);
  return <>
    <PageHeading eyebrow="SUPPLIER DIRECTORY" title="供应商管理" description="统一维护供货方档案、联系方式和付款约定，按权限查看关联采购报价。" extra={canManage && <Button type="primary" icon={<PlusOutlined />} onClick={() => setEditing(null)}>新增供应商</Button>} />
    <SharedCatalogNotice /><ErrorNotice error={resource.error} retry={resource.reload} />
    <Card className="section-card" title="供应商档案" extra={<Button icon={<ReloadOutlined />} loading={resource.loading} onClick={resource.reload}>刷新</Button>}>
      <div className="catalog-filter-bar"><Input allowClear prefix={<SearchOutlined />} aria-label="搜索供应商" placeholder="搜索供应商名称、编码或联系人" value={query} onChange={event => setQuery(event.target.value)} className="catalog-search" /><Select aria-label="筛选供应商启停状态" allowClear value={active} onChange={setActive} placeholder="全部状态" options={[{ value: 'true', label: '启用中' }, { value: 'false', label: '已停用' }]} style={{ minWidth: 145 }} /></div>
      <Table<Supplier> rowKey="id" dataSource={resource.data?.items ?? []} loading={resource.loading} pagination={resource.pagination} scroll={{ x: 1050 }} locale={{ emptyText: <EmptyState text={q || active ? '没有匹配的供应商，请调整筛选条件。' : '暂无供应商档案，可先建立供应商，再维护供货报价。'} /> }} columns={[
        { title: '供应商 / 编码', dataIndex: 'name', width: 240, render: (value: string, supplier) => <div className="table-name"><span className="store-avatar"><TeamOutlined /></span><div><button className="catalog-title-link" onClick={() => setDetailId(supplier.id)}>{value}</button><small>{supplier.code}</small></div></div> },
        { title: '联系人', dataIndex: 'contact_name', width: 130, render: (value: string) => value || '未填写' },
        { title: '联系方式', dataIndex: 'phone', width: 210, render: (value: string, supplier) => <div className="catalog-wrap">{value || '电话未填写'}<small className="cell-secondary">{supplier.email || '邮箱未填写'}</small></div> },
        { title: '付款约定', dataIndex: 'payment_terms', width: 220, render: (value: string) => <span className="catalog-wrap">{value || '未提供'}</span> },
        { title: '状态', dataIndex: 'is_active', width: 110, render: (value: boolean) => <ActiveTag active={value} /> },
        { title: '操作', key: 'actions', width: 155, render: (_: unknown, supplier) => <Space size={0}><Button type="link" onClick={() => setDetailId(supplier.id)}>详情</Button>{canManage && <Button type="link" onClick={() => setEditing(supplier)}>编辑</Button>}</Space> },
      ]} />
    </Card>
    {detailId && <SupplierDetails key={`${detailId}:${detailVersion}`} id={detailId} user={user} onClose={() => setDetailId(null)} onEdit={setEditing} />}
    {editing !== undefined && <SupplierEditor supplier={editing} onClose={() => setEditing(undefined)} onSaved={() => { setEditing(undefined); resource.reload(); setDetailVersion(version => version + 1); }} />}
  </>;
}

function SupplierDetails({ id, user, onClose, onEdit }: { id: string; user: User; onClose: () => void; onEdit: (supplier: Supplier) => void }) {
  const resource = useResource<Supplier>(`/suppliers/${id}`);
  const supplier = resource.data;
  const canManage = user.permissions.includes('suppliers.manage');
  const quoteAccess = canViewQuotes(user);
  return <Drawer title="供应商详情" open onClose={onClose} size={1100} extra={supplier && canManage && <Button icon={<EditOutlined />} onClick={() => onEdit(supplier)}>编辑供应商</Button>}>
    <ErrorNotice error={resource.error} retry={resource.reload} />{resource.loading && !supplier ? <div className="page-loading"><Spin /></div> : supplier && <>
      <div className="supplier-detail-heading"><span className="supplier-detail-avatar"><TeamOutlined /></span><div><Tag>{supplier.code}</Tag><h2>{supplier.name}</h2><ActiveTag active={supplier.is_active} /></div></div>
      <Tabs items={[
        { key: 'profile', label: '基础档案', children: <><Descriptions bordered size="small" column={{ xs: 1, sm: 2 }} items={[
          { key: 'name', label: '供应商名称', children: supplier.name, span: 2 }, { key: 'contact', label: '联系人', children: supplier.contact_name || '未填写' }, { key: 'phone', label: '电话', children: supplier.phone || '未填写' },
          { key: 'email', label: '邮箱', children: supplier.email || '未填写', span: 2 }, { key: 'address', label: '地址', children: <span className="catalog-prewrap">{supplier.address || '未填写'}</span>, span: 2 },
          { key: 'terms', label: '付款约定', children: <span className="catalog-prewrap">{supplier.payment_terms || '未提供'}</span>, span: 2 }, { key: 'notes', label: '备注与别名', children: <span className="catalog-prewrap">{supplier.notes || '—'}</span>, span: 2 },
          { key: 'created', label: '建立时间', children: dateTime(supplier.created_at) }, { key: 'updated', label: '更新时间', children: dateTime(supplier.updated_at) },
        ]} />{!quoteAccess && <Alert className="page-notice supplier-access-note" type="info" showIcon title="当前角色可查看供应商基础档案" description="采购报价、金额和来源原文需同时具有报价查看与成本查看权限。" />}</> },
        ...(quoteAccess ? [{ key: 'quotes', label: '关联采购报价', children: <Suspense fallback={<div className="page-loading">正在加载采购报价…</div>}><QuoteCollection user={user} supplierId={supplier.id} supplierName={supplier.name} /></Suspense> }] : []),
      ]} />
    </>}
  </Drawer>;
}

type SupplierValues = Pick<Supplier, 'code' | 'name' | 'contact_name' | 'phone' | 'email' | 'address' | 'payment_terms' | 'notes' | 'is_active'>;
function SupplierEditor({ supplier, onClose, onSaved }: { supplier: Supplier | null; onClose: () => void; onSaved: () => void }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const { message } = AntApp.useApp();
  const [form] = Form.useForm<SupplierValues>();
  const save = async (values: SupplierValues) => {
    setSaving(true); setError('');
    const body = { code: values.code.trim(), name: values.name.trim(), contact_name: values.contact_name ?? '', phone: values.phone ?? '', email: values.email ?? '', address: values.address ?? '', payment_terms: values.payment_terms ?? '', notes: values.notes ?? '', is_active: values.is_active };
    try { await api(supplier ? `/suppliers/${supplier.id}` : '/suppliers', { method: supplier ? 'PATCH' : 'POST', body }); message.success(supplier ? '供应商档案已更新' : '供应商已创建'); onSaved(); }
    catch (cause) { setError(errorText(cause)); } finally { setSaving(false); }
  };
  return <Modal title={supplier ? '编辑供应商档案' : '新增供应商档案'} open onCancel={() => { if (!saving) onClose(); }} footer={null} width={760} styles={{ body: { maxHeight: '76vh', overflowY: 'auto' } }}>
    <ErrorNotice error={error} /><Form form={form} layout="vertical" initialValues={supplier ?? { is_active: true }} onFinish={save} requiredMark="optional">
      <Row gutter={20}><Col xs={24} sm={10}><Form.Item name="code" label="供应商编码" rules={[{ required: true, whitespace: true, message: '请输入供应商编码' }, { max: 50, message: '最多 50 字符' }]}><Input maxLength={50} placeholder="公司内部唯一编码" /></Form.Item></Col><Col xs={24} sm={14}><Form.Item name="name" label="供应商名称" rules={[{ required: true, whitespace: true, message: '请输入供应商名称' }, { max: 200, message: '最多 200 字符' }]}><Input maxLength={200} /></Form.Item></Col></Row>
      <Row gutter={20}><Col xs={24} sm={12}><Form.Item name="contact_name" label="联系人" rules={[{ max: 120, message: '最多 120 字符' }]}><Input maxLength={120} /></Form.Item></Col><Col xs={24} sm={12}><Form.Item name="phone" label="电话" rules={[{ max: 80, message: '最多 80 字符' }]}><Input maxLength={80} /></Form.Item></Col></Row><Form.Item name="email" label="邮箱" rules={[{ type: 'email', message: '请输入有效的邮箱地址' }, { max: 254, message: '最多 254 字符' }]}><Input inputMode="email" maxLength={254} /></Form.Item><Form.Item name="address" label="地址" rules={[{ max: 1000, message: '最多 1000 字符' }]}><Input.TextArea rows={2} maxLength={1000} /></Form.Item><Form.Item name="payment_terms" label="付款约定" rules={[{ max: 2000, message: '最多 2000 字符' }]}><Input.TextArea rows={3} placeholder="账期、预付款比例或双方确认的付款条件" /></Form.Item><Form.Item name="notes" label="备注与别名" rules={[{ max: 10000, message: '最多 10000 字符' }]} extra="采购单价和报价原文请保存在采购报价中，便于按成本权限管理。"><Input.TextArea rows={3} /></Form.Item><Form.Item name="is_active" label="供应商状态" valuePropName="checked"><Switch checkedChildren="启用" unCheckedChildren="停用" /></Form.Item>
      <div className="form-footer"><Button disabled={saving} onClick={onClose}>取消</Button><Button type="primary" htmlType="submit" loading={saving}>保存供应商</Button></div>
    </Form>
  </Modal>;
}
