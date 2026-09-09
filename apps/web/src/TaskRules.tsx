import { useState } from 'react';
import { Alert, Button, Checkbox, Col, Form, Input, InputNumber, Modal, Row, Select, Space, Switch, Table, Tag } from 'antd';
import { api, errorText } from './api';
import { ErrorNotice, usePagedList } from './common';
import { requestId, required } from './SupplyShared';
import { kindLabels } from './TaskShared';
import type { Store, User } from './types';
import type { TaskRule, TaskSource } from './task-types';

const weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'].map((label, value) => ({ value, label }));
function allowedKinds(user: User) { return ['daily', 'weekly', ...(user.permissions.includes('purchases.view') ? ['purchase_order', 'production'] : []), ...(user.permissions.includes('shipments.view') ? ['dispatch'] : [])]; }
function timing(rule: TaskRule) {
  const time = rule.due_time || '全天';
  if (rule.kind === 'production' || rule.kind === 'dispatch') return `预计发货${rule.offset_days === 0 ? '当天' : rule.offset_days < 0 ? `前 ${-rule.offset_days} 天` : `后 ${rule.offset_days} 天`} · ${time}`;
  return `${rule.kind === 'purchase_order' ? '创建采购单后首个 ' : ''}${rule.weekdays.map(d => weekdays[d].label).join('、')} · ${time}`;
}
export function TaskRules({ user, stores, selectedStore }: { user: User; stores: Store[]; selectedStore: string }) {
  const rules = usePagedList<TaskRule>('/task-rules'); const [editing, setEditing] = useState<TaskRule | null | undefined>(); const [templates, setTemplates] = useState(false); const [error, setError] = useState(''); const [busy, setBusy] = useState<string>();
  const toggle = async (rule: TaskRule, enabled: boolean) => { setBusy(rule.id); try { await api(`/task-rules/${rule.id}`, { method: 'PATCH', body: { version: rule.version, enabled } }); rules.reload(); } catch (cause) { setError(errorText(cause)); rules.reload(); } finally { setBusy(undefined); } };
  return <><Alert type="info" showIcon title="规则只生成待办。暂停规则后停止新增，已生成待办保留；修改规则默认从后续待办生效。" /><div className="catalog-filter-bar"><Space><Button type="primary" onClick={() => setTemplates(true)}>添加推荐提醒</Button><Button onClick={() => setEditing(null)}>自定义规则</Button></Space></div><ErrorNotice error={rules.error || error} retry={rules.reload} />
    <Table<TaskRule> rowKey="id" dataSource={rules.data?.items || []} loading={rules.loading} pagination={rules.pagination} scroll={{ x: 900 }} locale={{ emptyText: '尚未启用提醒。添加推荐提醒后，可逐条修改或暂停。' }} columns={[
      { title: '规则', width: 200, render: (_, rule) => <>{rule.title}<small className="cell-secondary">{kindLabels[rule.kind]}</small></> },
      { title: '触发安排', width: 350, render: (_, rule) => <>{timing(rule)}<small className="cell-secondary">{rule.timezone}{['daily', 'weekly'].includes(rule.kind) ? ' · 提前展示未来 7 天' : ' · 适用于新建单据'}</small></> },
      { title: '适用范围', width: 190, render: (_, rule) => rule.store_name || (['daily', 'weekly'].includes(rule.kind) ? '个人待办' : '我新建的所有授权店铺单据') },
      { title: '启用', width: 85, render: (_, rule) => <Switch checked={rule.enabled} loading={busy === rule.id} onChange={enabled => toggle(rule, enabled)} aria-label={`${rule.title}启用状态`} /> },
      { title: '操作', width: 85, render: (_, rule) => <Button type="link" onClick={() => setEditing(rule)}>编辑</Button> },
    ]} />{editing !== undefined && <RuleEditor rule={editing} user={user} stores={stores} selectedStore={selectedStore} onClose={() => setEditing(undefined)} onSaved={() => { setEditing(undefined); rules.reload(); }} />}{templates && <Templates user={user} stores={stores} selectedStore={selectedStore} onClose={() => setTemplates(false)} onSaved={() => { setTemplates(false); rules.reload(); }} />}</>;
}
function RuleEditor({ rule, user, stores, selectedStore, onClose, onSaved }: { rule: TaskRule | null; user: User; stores: Store[]; selectedStore: string; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm(); const kind = Form.useWatch('kind', form); const [token] = useState(requestId); const [saving, setSaving] = useState(false); const [error, setError] = useState('');
  const save = async (input: TaskRule) => { setSaving(true); setError(''); const { title, kind, weekdays, due_time, timezone, offset_days, enabled, notify } = input; const body = { title, weekdays: weekdays || [0], due_time: due_time || null, timezone, offset_days: offset_days || 0, enabled, notify };
    try { if (rule) await api(`/task-rules/${rule.id}`, { method: 'PATCH', body: { ...body, version: rule.version } }); else await api('/task-rules', { method: 'POST', body: { ...body, kind, store_id: input.store_id || null, request_id: token } }); onSaved(); } catch (cause) { setError(errorText(cause)); } finally { setSaving(false); } };
  return <Modal open title={rule ? '编辑提醒规则' : '添加提醒规则'} width={670} onCancel={saving ? undefined : onClose} mask={{ closable: false }} onOk={() => form.submit()} confirmLoading={saving} okText="保存规则"><ErrorNotice error={error} /><Form layout="vertical" form={form} onFinish={save} initialValues={rule || { title: '', kind: 'daily', weekdays: [0, 1, 2, 3, 4, 5, 6], timezone: 'Asia/Shanghai', enabled: true, notify: true, offset_days: 0, store_id: selectedStore !== 'all' ? selectedStore : undefined }}>
    <Form.Item name="title" label="待办标题" rules={required}><Input maxLength={200} /></Form.Item><Form.Item name="kind" label="触发方式" rules={required}><Select disabled={!!rule} options={allowedKinds(user).map(value => ({ value, label: kindLabels[value] }))} onChange={value => form.setFieldsValue({ weekdays: value === 'purchase_order' ? [0] : value === 'weekly' ? [4] : [0, 1, 2, 3, 4, 5, 6], offset_days: value === 'production' ? -2 : 0 })} /></Form.Item>
    <Form.Item name="store_id" label="适用店铺" extra="不指定店铺：周期事项为个人待办；单据规则适用于自己新建的授权店铺单据。"><Select disabled={!!rule} allowClear showSearch optionFilterProp="label" placeholder="不指定店铺" options={stores.map(s => ({ value: s.id, label: s.name }))} /></Form.Item>
    {['daily', 'weekly'].includes(kind) && <Form.Item name="weekdays" label="重复日期" rules={required}><Checkbox.Group options={weekdays} /></Form.Item>}
    {kind === 'purchase_order' && <Form.Item name="weekdays" label="创建后首个指定星期（单次）" rules={[{ validator: async (_, value) => { if (value?.length !== 1) throw new Error('请选择一个星期'); } }]}><Select mode="multiple" maxCount={1} options={weekdays} /></Form.Item>}
    {['production', 'dispatch'].includes(kind) && <Form.Item name="offset_days" label="相对预计发货日的天数" extra="负数表示提前，0 表示当天；没有预计发货日时生成未定日期待办。"><InputNumber min={-365} max={365} precision={0} /></Form.Item>}
    <Row gutter={16}><Col span={12}><Form.Item name="due_time" label="具体时间（留空为全天）"><Input type="time" /></Form.Item></Col><Col span={12}><Form.Item name="timezone" label="时区" rules={required}><Input maxLength={64} placeholder="Asia/Shanghai" /></Form.Item></Col></Row>
    <Space size={32}><Form.Item name="enabled" label="启用规则" valuePropName="checked"><Switch /></Form.Item><Form.Item name="notify" label="具体时间到时通知" valuePropName="checked"><Switch /></Form.Item></Space>
  </Form></Modal>;
}
function Templates({ user, stores, selectedStore, onClose, onSaved }: { user: User; stores: Store[]; selectedStore: string; onClose: () => void; onSaved: () => void }) {
  const options = [{ value: 'daily_data', label: '每天 15:00 · 下载经营数据', kind: 'daily' }, { value: 'weekly_analysis', label: '每周五全天 · 分析销售数据与库存情况', kind: 'weekly' }, { value: 'purchase_order', label: '创建采购单后首个周一 09:00 · 下单提醒', kind: 'purchase_order' }, { value: 'production', label: '预计发货前两天 · 确认生产进度', kind: 'production' }, { value: 'dispatch', label: '预计发货当天 · 发货提醒', kind: 'dispatch' }].filter(option => allowedKinds(user).includes(option.kind) && (!['daily_data', 'weekly_analysis'].includes(option.value) || user.permissions.includes('reports.view')));
  const [selected, setSelected] = useState(options.map(o => o.value)); const [store, setStore] = useState<string | undefined>(selectedStore === 'all' ? undefined : selectedStore); const [token] = useState(requestId); const [saving, setSaving] = useState(false); const [error, setError] = useState('');
  const save = async () => { setSaving(true); try { await api('/task-rules/templates', { method: 'POST', body: { request_id: token, store_id: store || null, templates: selected } }); onSaved(); } catch (cause) { setError(errorText(cause)); } finally { setSaving(false); } };
  return <Modal open title="添加推荐提醒" width={670} onCancel={saving ? undefined : onClose} onOk={save} okText="启用所选提醒" confirmLoading={saving} okButtonProps={{ disabled: !selected.length }}><ErrorNotice error={error} /><p>选择适合自己的提醒。已有同范围模板保留原设置，历史单据可在详情中单独添加提醒。</p><Select value={store} onChange={setStore} allowClear showSearch optionFilterProp="label" placeholder="个人事项 / 所有授权店铺的新单据" style={{ width: '100%', marginBottom: 20 }} options={stores.map(s => ({ value: s.id, label: s.name }))} /><Checkbox.Group value={selected} onChange={values => setSelected(values as string[])}><Space orientation="vertical" size={16}>{options.map(option => <Checkbox key={option.value} value={option.value}>{option.label}</Checkbox>)}</Space></Checkbox.Group></Modal>;
}
export function ApplyTaskRules({ source, onClose, onSaved }: { source: TaskSource; onClose: () => void; onSaved: () => void }) {
  const rules = usePagedList<TaskRule>('/task-rules'); const [selected, setSelected] = useState<React.Key[]>([]); const [saving, setSaving] = useState(false); const [error, setError] = useState(''); const [token] = useState(requestId);
  const allowed = (rule: TaskRule) => rule.enabled && (!rule.store_id || rule.store_id === source.store_id) && (source.kind === 'shipment' ? rule.kind === 'dispatch' : ['purchase_order', 'production', 'dispatch'].includes(rule.kind));
  const save = async () => { setSaving(true); try { await api('/tasks/apply-rules', { method: 'POST', body: { request_id: token, source_kind: source.kind, source_id: source.id, rule_ids: selected } }); onSaved(); } catch (cause) { setError(errorText(cause)); } finally { setSaving(false); } };
  return <Modal open title={`为 ${source.number} 添加提醒`} width={730} onCancel={saving ? undefined : onClose} onOk={save} confirmLoading={saving} okButtonProps={{ disabled: !selected.length }} okText="添加所选提醒"><Alert showIcon type="info" title="已完成的业务不会生成多余提醒；已存在的同规则待办保留，不会重建。" /><ErrorNotice error={rules.error || error} retry={rules.reload} /><Table<TaskRule> rowKey="id" dataSource={rules.data?.items || []} pagination={rules.pagination} loading={rules.loading} rowSelection={{ selectedRowKeys: selected, preserveSelectedRowKeys: true, onChange: setSelected, getCheckboxProps: rule => ({ disabled: !allowed(rule) }) }} columns={[{ title: '规则', dataIndex: 'title' }, { title: '安排', render: (_, rule) => timing(rule) }, { title: '适用', render: (_, rule) => <Tag>{allowed(rule) ? '可添加' : '不适用 / 已暂停'}</Tag> }]} /></Modal>;
}
