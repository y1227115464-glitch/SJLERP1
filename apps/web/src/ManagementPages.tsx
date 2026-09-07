import { useMemo, useState } from 'react';
import { Alert, App as AntApp, Button, Card, Col, Form, Input, Modal, Popconfirm, Row, Select, Space, Switch, Table, Tag, Tooltip } from 'antd';
import { DownloadOutlined, EditOutlined, KeyOutlined, PlusOutlined, ReloadOutlined, SearchOutlined, ShopOutlined } from '@ant-design/icons';
import { api, download, errorText } from './api';
import { ActiveTag, dateTime, EmptyState, ErrorNotice, PageHeading, permissionLabels, roleLabels, usePagedList, useResource } from './common';
import type { ListResult, Role, RoleKey, Store, User } from './types';

interface StoreValues { name: string; code: string; legal_entity: string; brand: string; marketplace: string; currency: string; is_active: boolean }
export function StoresPage({ user, stores, selectedStore, refreshStores }: { user: User; stores: Store[]; selectedStore: string; refreshStores: () => Promise<void> }) {
  const [query, setQuery] = useState('');
  const [editing, setEditing] = useState<Store | null | undefined>(undefined);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [exporting, setExporting] = useState(false);
  const [form] = Form.useForm<StoreValues>();
  const { message } = AntApp.useApp();
  const canManage = user.permissions.includes('stores.manage');
  const visibleStores = useMemo(() => stores.filter(store => (selectedStore === 'all' || selectedStore === store.id) && `${store.name} ${store.code} ${store.brand} ${store.legal_entity}`.toLowerCase().includes(query.toLowerCase())), [stores, selectedStore, query]);
  const edit = (store: Store | null) => { setEditing(store); setError(''); form.resetFields(); form.setFieldsValue(store ?? { marketplace: 'US', currency: 'USD', is_active: true }); };
  const save = async (values: StoreValues) => {
    setSaving(true); setError('');
    try {
      const clean = Object.fromEntries(Object.entries(values).map(([key, value]) => [key, typeof value === 'string' ? value.trim() : value]));
      await api(editing ? `/stores/${editing.id}` : '/stores', { method: editing ? 'PATCH' : 'POST', body: clean });
      message.success(editing ? '店铺资料已更新' : '店铺已创建'); setEditing(undefined); await refreshStores();
    } catch (cause) { setError(errorText(cause)); } finally { setSaving(false); }
  };
  return <><PageHeading eyebrow="STORE DIRECTORY" title="店铺管理" description="统一维护店铺档案，关联品牌、经营主体与美国站业务。" extra={<Space>{user.permissions.includes('stores.export') && <Button icon={<DownloadOutlined />} loading={exporting} onClick={async () => { setExporting(true); try { await download('/stores/export', '书剑录-授权店铺.csv'); } catch (cause) { message.error(errorText(cause)); } finally { setExporting(false); } }}>导出授权店铺</Button>}{canManage && <Button type="primary" icon={<PlusOutlined />} onClick={() => edit(null)}>新增店铺</Button>}</Space>} />
    <div className="summary-strip"><div><span>授权店铺</span><strong>{stores.length}</strong><small>家</small></div><div><span>启用中</span><strong>{stores.filter(store => store.is_active).length}</strong><small>家</small></div><p>经营数据按店铺隔离，报表导入后分别归集。</p></div>
    <Card className="section-card" title="店铺档案" extra={<Button icon={<ReloadOutlined />} onClick={() => void refreshStores()}>刷新</Button>}><div className="table-toolbar"><Input allowClear prefix={<SearchOutlined />} aria-label="搜索店铺" placeholder="搜索店铺、编码、品牌或主体" value={query} onChange={event => setQuery(event.target.value)} style={{ maxWidth: 360 }} /><span className="subtle-text">当前筛选 {visibleStores.length} 家店铺</span></div>
      <Table<Store> rowKey="id" dataSource={visibleStores} scroll={{ x: 1050 }} pagination={{ pageSize: 10, showSizeChanger: false, showTotal: total => `共 ${total} 家店铺` }} locale={{ emptyText: <EmptyState text={query ? '未找到匹配的店铺，请调整搜索条件。' : '暂无店铺档案，先添加店铺或联系管理员授权。'} /> }} columns={[
        { title: '店铺 / 编码', dataIndex: 'name', width: 230, render: (value: string, record) => <div className="table-name"><span className="store-avatar"><ShopOutlined /></span><div><strong>{value}</strong><small>{record.code}</small></div></div> },
        { title: '经营主体', dataIndex: 'legal_entity', render: (value: string) => value || '—' }, { title: '品牌', dataIndex: 'brand', render: (value: string) => value || '—' },
        { title: '站点 / 币种', dataIndex: 'marketplace', render: (value: string, record) => <div>{value === 'US' ? '美国 US' : value}<small className="cell-secondary">{record.currency}</small></div> },
        { title: '状态', dataIndex: 'is_active', render: (value: boolean) => <ActiveTag active={value} /> },
        { title: '创建时间', dataIndex: 'created_at', render: dateTime, width: 165 },
        ...(canManage ? [{ title: '操作', key: 'actions', width: 90, render: (_: unknown, record: Store) => <Button type="link" icon={<EditOutlined />} onClick={() => edit(record)}>编辑</Button> }] : []),
      ]} /></Card>
    <Modal title={editing ? '编辑店铺' : '新增店铺'} open={editing !== undefined} onCancel={() => { if (!saving) setEditing(undefined); }} footer={null} destroyOnHidden width={660}>
      <p className="modal-intro">请使用亚马逊后台一致的店铺名称。店铺编码用于内部识别。</p><ErrorNotice error={error} />
      <Form form={form} layout="vertical" onFinish={save} requiredMark="optional"><Row gutter={20}><Col span={12}><Form.Item name="name" label="店铺名称" rules={[{ required: true, whitespace: true, message: '请输入店铺名称' }, { max: 120, message: '店铺名称最多 120 字符' }]}><Input placeholder="例如：店铺后台显示名称" /></Form.Item></Col><Col span={12}><Form.Item name="code" label="内部编码" rules={[{ required: true, whitespace: true, message: '请输入唯一编码' }, { pattern: /^[a-zA-Z0-9_-]+$/, message: '请使用字母、数字、短横线或下划线' }, { max: 50, message: '编码最多 50 字符' }]}><Input placeholder="例如：STORE-US-01" /></Form.Item></Col></Row><Form.Item name="legal_entity" label="经营主体" rules={[{ max: 200, message: '经营主体最多 200 字符' }]}><Input placeholder="营业主体全称" /></Form.Item><Form.Item name="brand" label="品牌" rules={[{ max: 120, message: '品牌最多 120 字符' }]}><Input placeholder="该店铺经营品牌" /></Form.Item><Row gutter={20}><Col span={12}><Form.Item name="marketplace" label="站点" rules={[{ required: true }]}><Select options={[{ value: 'US', label: '美国站 US' }]} /></Form.Item></Col><Col span={12}><Form.Item name="currency" label="结算币种" rules={[{ required: true }]}><Select options={[{ value: 'USD', label: '美元 USD' }]} /></Form.Item></Col></Row><Form.Item name="is_active" label="店铺状态" valuePropName="checked"><Switch checkedChildren="启用" unCheckedChildren="停用" /></Form.Item><div className="form-footer"><Button onClick={() => setEditing(undefined)} disabled={saving}>取消</Button><Button type="primary" htmlType="submit" loading={saving}>保存店铺</Button></div></Form>
    </Modal>
  </>;
}

interface UserValues { email: string; display_name: string; password?: string; role: RoleKey; store_ids: string[] }
export function UsersPage({ user, stores }: { user: User; stores: Store[] }) {
  const resource = usePagedList<User>('/users');
  const roles = useResource<ListResult<Role>>('/roles');
  const [editing, setEditing] = useState<User | null | undefined>(undefined);
  const [resetting, setResetting] = useState<User | null>(null);
  const [saving, setSaving] = useState(false);
  const [acting, setActing] = useState<string | null>(null);
  const [formError, setFormError] = useState('');
  const [form] = Form.useForm<UserValues>();
  const [passwordForm] = Form.useForm<{ password: string; confirm_password: string }>();
  const role = Form.useWatch('role', form);
  const { message } = AntApp.useApp();
  const edit = (account: User | null) => { setEditing(account); setFormError(''); form.resetFields(); form.setFieldsValue(account ? { email: account.email, display_name: account.display_name, role: account.role, store_ids: account.store_ids } : { role: 'operator', store_ids: [] }); };
  const save = async (values: UserValues) => {
    setSaving(true); setFormError('');
    const payload = { display_name: values.display_name.trim(), role: values.role, store_ids: values.role === 'admin' ? [] : values.store_ids ?? [], ...(!editing ? { email: values.email.trim(), password: values.password } : {}) };
    try { await api(editing ? `/users/${editing.id}` : '/users', { method: editing ? 'PATCH' : 'POST', body: payload }); message.success(editing ? '账号已更新；权限变更后需重新登录' : '账号已创建'); setEditing(undefined); resource.reload(); if (editing?.id === user.id) window.dispatchEvent(new Event('sjlerp:unauthorized')); }
    catch (cause) { setFormError(errorText(cause)); } finally { setSaving(false); }
  };
  const toggle = async (account: User) => {
    if (account.id === user.id) return;
    setActing(account.id);
    try { await api(`/users/${account.id}`, { method: 'PATCH', body: { is_active: !account.is_active } }); message.success(account.is_active ? '账号已停用，现有会话已撤销' : '账号已启用'); resource.reload(); }
    catch (cause) { message.error(errorText(cause)); } finally { setActing(null); }
  };
  const resetPassword = async (values: { password: string }) => {
    if (!resetting) return;
    setSaving(true); setFormError('');
    try { await api(`/users/${resetting.id}`, { method: 'PATCH', body: { password: values.password } }); message.success('密码已重置，该账号需要重新登录'); if (resetting.id === user.id) window.dispatchEvent(new Event('sjlerp:unauthorized')); setResetting(null); passwordForm.resetFields(); }
    catch (cause) { setFormError(errorText(cause)); } finally { setSaving(false); }
  };
  return <><PageHeading eyebrow="TEAM & ACCESS" title="账号与权限" description="按岗位分配操作权限，并明确每个账号可访问的店铺范围。" extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => edit(null)}>新增账号</Button>} />
    <Alert className="page-notice" type="info" showIcon title="公司管理员拥有全部店铺的经营权限" description="其他角色仅可访问明确分配的店铺；未分配店铺表示没有店铺数据权限。操作权限和敏感字段权限由服务端统一执行。" />
    <ErrorNotice error={resource.error} retry={resource.reload} /><ErrorNotice error={roles.error} retry={roles.reload} />
    <Card className="section-card" title="团队账号" extra={<Button icon={<ReloadOutlined />} onClick={resource.reload}>刷新</Button>}><Table<User> rowKey="id" loading={resource.loading} dataSource={resource.data?.items ?? []} pagination={resource.pagination} scroll={{ x: 1080 }} locale={{ emptyText: <EmptyState text="暂无可管理的账号。" /> }} columns={[
      { title: '成员', dataIndex: 'display_name', width: 250, render: (value: string, record) => <div><strong>{value}</strong>{record.id === user.id && <Tag className="self-tag" bordered={false}>我</Tag>}<small className="cell-secondary">{record.email}</small></div> },
      { title: '角色', dataIndex: 'role', render: (value: RoleKey) => <Tag bordered={false} color={value === 'admin' ? 'blue' : 'default'}>{roleLabels[value]}</Tag> },
      { title: '店铺访问范围', dataIndex: 'store_ids', width: 290, render: (ids: string[], record) => record.role === 'admin' ? <span className="scope-all">全部店铺（公司管理员）</span> : ids.length ? <Space size={[0, 5]} wrap>{ids.map(id => <Tag key={id}>{stores.find(store => store.id === id)?.name ?? '店铺档案不可见'}</Tag>)}</Space> : <span className="subtle-text">未分配店铺</span> },
      { title: '状态', dataIndex: 'is_active', render: (value: boolean) => <ActiveTag active={value} /> },
      { title: '操作', key: 'actions', width: 280, render: (_: unknown, account) => <Space size={0}><Button type="link" onClick={() => edit(account)}>编辑</Button><Button type="link" onClick={() => { setResetting(account); setFormError(''); passwordForm.resetFields(); }}>重置密码</Button><Tooltip title={account.id === user.id ? '不可停用当前登录账号' : undefined}><span><Popconfirm title={account.is_active ? `停用 ${account.display_name}？` : `启用 ${account.display_name}？`} description={account.is_active ? '该账号的已有登录会话将立即撤销。' : '该账号将恢复登录能力。'} disabled={account.id === user.id} onConfirm={() => toggle(account)} okText="确认" cancelText="取消"><Button type="link" danger={account.is_active} disabled={account.id === user.id} loading={acting === account.id}>{account.is_active ? '停用' : '启用'}</Button></Popconfirm></span></Tooltip></Space> },
    ]} /></Card>
    <Modal title={editing ? '编辑账号与权限' : '新增团队账号'} open={editing !== undefined} onCancel={() => { if (!saving) setEditing(undefined); }} footer={null} destroyOnHidden width={650}><ErrorNotice error={formError} /><Form form={form} layout="vertical" onFinish={save} requiredMark="optional"><Row gutter={20}><Col span={12}><Form.Item name="display_name" label="姓名" rules={[{ required: true, whitespace: true, message: '请输入成员姓名' }, { max: 120, message: '姓名最多 120 字符' }]}><Input autoComplete="off" /></Form.Item></Col><Col span={12}><Form.Item name="email" label="账号邮箱" rules={[{ required: true, message: '请输入邮箱' }, { type: 'email', message: '请输入有效邮箱' }]}><Input disabled={!!editing} autoComplete="off" /></Form.Item></Col></Row>{!editing && <Form.Item name="password" label="初始密码" rules={[{ required: true, message: '请设置初始密码' }, { min: 12, message: '密码至少 12 位' }]} extra="至少 12 位。请通过公司认可的安全方式将初始密码交给本人。"><Input.Password autoComplete="new-password" /></Form.Item>}<Form.Item name="role" label="岗位角色" rules={[{ required: true, message: '请选择角色' }]}><Select loading={roles.loading} options={(roles.data?.items ?? []).map(item => ({ value: item.key, label: roleLabels[item.key] ?? item.label }))} /></Form.Item>{role === 'admin' ? <Alert className="page-notice" type="warning" showIcon title="公司管理员可访问所有店铺与敏感经营数据" description="此角色用于公司经营管理，也具有账号管理能力。保存后对该账号的已有会话重新认证。" /> : <Form.Item name="store_ids" label="可访问店铺" extra="可多选；留空表示没有店铺数据权限。"><Select mode="multiple" placeholder="选择负责的店铺" options={stores.map(store => ({ value: store.id, label: `${store.name}${store.is_active ? '' : '（停用）'}` }))} /></Form.Item>}
      {role && <details className="permissions-details"><summary>查看该角色的操作权限</summary><div>{(roles.data?.items.find(item => item.key === role)?.permissions ?? []).map(permission => <Tag key={permission}>{permissionLabels[permission] ?? permission}</Tag>)}</div></details>}{editing && <p className="subtle-text">修改角色、范围或密码后，已有登录会话会撤销。不能撤销最后一个有效公司管理员。</p>}<div className="form-footer"><Button onClick={() => setEditing(undefined)} disabled={saving}>取消</Button><Button type="primary" htmlType="submit" loading={saving} disabled={!roles.data}>保存账号</Button></div></Form></Modal>
    <Modal title={`重置密码 · ${resetting?.display_name ?? ''}`} open={!!resetting} onCancel={() => { if (!saving) setResetting(null); }} footer={null} destroyOnHidden><Alert className="page-notice" type="warning" showIcon title="重置后，该账号的所有现有会话会撤销" /><ErrorNotice error={formError} /><Form form={passwordForm} layout="vertical" onFinish={resetPassword}><Form.Item name="password" label="新密码" rules={[{ required: true, message: '请输入新密码' }, { min: 12, message: '密码至少 12 位' }]}><Input.Password autoComplete="new-password" /></Form.Item><Form.Item name="confirm_password" label="确认新密码" dependencies={['password']} rules={[{ required: true, message: '请再次输入新密码' }, ({ getFieldValue }) => ({ validator(_, value) { return !value || getFieldValue('password') === value ? Promise.resolve() : Promise.reject(new Error('两次输入的密码不一致')); } })]}><Input.Password autoComplete="new-password" /></Form.Item><div className="form-footer"><Button disabled={saving} onClick={() => setResetting(null)}>取消</Button><Button type="primary" htmlType="submit" loading={saving} icon={<KeyOutlined />}>重置密码</Button></div></Form></Modal>
  </>;
}
