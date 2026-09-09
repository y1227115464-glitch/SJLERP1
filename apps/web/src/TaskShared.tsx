import { useEffect, useState } from 'react';
import { App as AntApp, Alert, Button, Card, Col, Descriptions, Drawer, Form, Input, Modal, Row, Select, Space, Switch, Table, Tag, Timeline } from 'antd';
import { api, errorText } from './api';
import { dateTime, EmptyState, ErrorNotice, usePagedList, useResource } from './common';
import { queryPath } from './CatalogShared';
import { RemoteSelect, requestId, required } from './SupplyShared';
import type { Store, User } from './types';
import type { Task, TaskSource, TaskStatus } from './task-types';
import { ApplyTaskRules } from './TaskRules';

export const taskLabels: Record<string, string> = { pending: '待处理', overdue: '已逾期', today: '今天', future: '未来', unscheduled: '未定日期', completed: '已完成', cancelled: '已取消' };
export const kindLabels: Record<string, string> = { manual: '手动待办', daily: '每日提醒', weekly: '每周提醒', purchase_order: '下单提醒', production: '生产进度', dispatch: '发货提醒' };
export function taskDate(task: Task) { return task.due_date ? `${task.due_date} ${task.due_time || '全天'} · ${task.timezone}` : '未定日期'; }
export function sourceHref(task: Task) {
  const page = { purchase: 'purchases', shipment: 'shipments', imports: 'imports', sales: 'sales', inventory: 'inventory' }[task.source_kind || ''];
  if (!page) return undefined;
  return `#${page}?${new URLSearchParams({ ...(task.source_id ? { id: task.source_id } : {}), ...(task.store_id ? { store: task.store_id } : {}) })}`;
}
export function useReminderRefresh(reload: () => void) {
  useEffect(() => { const refresh = () => { if (!document.hidden) reload(); }; const timer = window.setInterval(refresh, 30000); window.addEventListener('focus', refresh); return () => { window.clearInterval(timer); window.removeEventListener('focus', refresh); }; }, [reload]);
}
export function useLinkedDetail() {
  const read = () => new URLSearchParams(location.hash.split('?')[1] || '').get('id');
  const [id, setId] = useState<string | null>(read);
  useEffect(() => { const update = () => setId(read()); window.addEventListener('hashchange', update); return () => window.removeEventListener('hashchange', update); }, []);
  return [id, setId] as const;
}

interface EditorValues { title: string; notes: string; store_id?: string; assignee_id?: string; due_date?: string; due_time?: string; timezone: string; follow_source: boolean; notify: boolean }
export function TaskEditor({ task, source, user, stores, selectedStore, onClose, onSaved }: { task?: Task; source?: TaskSource; user: User; stores: Store[]; selectedStore?: string; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm<EditorValues>(); const [token] = useState(requestId); const [saving, setSaving] = useState(false); const [error, setError] = useState('');
  const watchedStore = Form.useWatch('store_id', form); const following = Form.useWatch('follow_source', form);
  const save = async (values: EditorValues) => {
    setSaving(true); setError('');
    const common = { title: values.title, notes: values.notes || '', due_date: values.due_date || null, due_time: values.due_time || null, timezone: values.timezone, notify: values.notify, assignee_id: values.assignee_id || user.id };
    try {
      if (task) await api(`/tasks/${task.id}`, { method: 'PATCH', body: { ...common, version: task.version, follow_source: values.follow_source || false } });
      else await api('/tasks', { method: 'POST', body: { ...common, request_id: token, store_id: source?.store_id || values.store_id || null, source_kind: source?.kind, source_id: source?.id } });
      onSaved();
    } catch (cause) { setError(errorText(cause)); } finally { setSaving(false); }
  };
  return <Modal open title={task ? '调整待办' : source ? `添加关联待办 · ${source.number}` : '新建待办'} width={660} onCancel={saving ? undefined : onClose} mask={{ closable: false }} onOk={() => form.submit()} confirmLoading={saving} okText="保存待办">
    <ErrorNotice error={error} /><Form form={form} layout="vertical" onFinish={save} initialValues={task ? { ...task, due_date: task.due_date || '', due_time: task.due_time || '' } : { store_id: source?.store_id || (selectedStore !== 'all' ? selectedStore : undefined), assignee_id: user.id, timezone: 'Asia/Shanghai', notify: true, follow_source: false }}>
      <Form.Item name="title" label="要做什么" rules={required}><Input maxLength={200} autoFocus placeholder="例如：向供应商确认本周可发数量" /></Form.Item>
      {!task && !source && <Form.Item name="store_id" label="所属店铺"><Select showSearch optionFilterProp="label" allowClear placeholder="个人待办（不指定店铺）" options={stores.map(store => ({ value: store.id, label: store.name }))} onChange={() => form.setFieldValue('assignee_id', user.id)} /></Form.Item>}
      {user.permissions.includes('tasks.assign') && <Form.Item name="assignee_id" label="负责人" rules={required}><RemoteSelect path={queryPath('/tasks/assignees', { store_id: source?.store_id || task?.store_id || watchedStore })} initialLabel={task?.assignee_name || user.display_name} /></Form.Item>}
      {task && ['production', 'dispatch'].includes(task.action_kind) && <Form.Item name="follow_source" label="日期跟随单据预计发货日" valuePropName="checked" extra="关闭后可单独改期；单据改期只会提示，不会覆盖你的安排。"><Switch /></Form.Item>}
      <Row gutter={16}><Col span={12}><Form.Item name="due_date" label="安排日期"><Input type="date" disabled={following} /></Form.Item></Col><Col span={12}><Form.Item name="due_time" label="提醒时间" extra="留空表示全天；全天待办到次日才算逾期。"><Input type="time" /></Form.Item></Col></Row>
      <Form.Item name="timezone" label="时区" rules={required}><Select showSearch options={['Asia/Shanghai', 'America/Los_Angeles', 'America/New_York', 'Europe/London', 'UTC', ...(task ? [task.timezone] : [])].filter((value, i, all) => all.indexOf(value) === i).map(value => ({ value, label: value }))} /></Form.Item>
      <Form.Item name="notify" label="到时生成站内通知" valuePropName="checked" extra="待办始终显示在工作台；站内通知适用于设置了具体时间的待办。"><Switch /></Form.Item>
      <Form.Item name="notes" label="备注"><Input.TextArea rows={3} maxLength={5000} /></Form.Item>
    </Form>
  </Modal>;
}

export function TaskTable({ path, user, stores, onChanged, compact = false }: { path: string; user: User; stores: Store[]; onChanged?: () => void; compact?: boolean }) {
  const list = usePagedList<Task>(path); const [editing, setEditing] = useState<Task>(); const [detail, setDetail] = useState<string>(); const [busy, setBusy] = useState<string>(); const [error, setError] = useState(''); const { message } = AntApp.useApp();
  const refresh = () => { list.reload(); onChanged?.(); }; useReminderRefresh(list.reload);
  const status = async (task: Task, value: TaskStatus) => {
    setBusy(task.id); setError('');
    try { await api(`/tasks/${task.id}/status`, { method: 'POST', body: { request_id: requestId(), version: task.version, status: value } }); message.success(value === 'completed' ? '待办已完成' : value === 'cancelled' ? '待办已取消' : '待办已恢复'); refresh(); }
    catch (cause) { setError(errorText(cause)); list.reload(); } finally { setBusy(undefined); }
  };
  return <><ErrorNotice error={list.error || error} retry={list.reload} /><Table<Task> rowKey="id" size={compact ? 'small' : 'middle'} dataSource={list.data?.items || []} loading={list.loading} pagination={list.pagination} scroll={{ x: compact ? 770 : 1000 }} locale={{ emptyText: <EmptyState text="当前没有待办。可以手动添加，或启用提醒规则。" /> }} columns={[
    { title: '待办事项', width: 320, render: (_, task) => <><button className="catalog-title-link" onClick={() => setDetail(task.id)}>{task.title}</button><small className="cell-secondary">{kindLabels[task.action_kind]}{task.source_number && ` · ${task.source_number}`}</small>{task.source_changed_at && <Tag color="orange">单据已改期，保留本次安排</Tag>}{task.suppressed && <Tag>已由分批货件提醒覆盖</Tag>}</> },
    { title: '安排', width: 250, render: (_, task) => <>{taskDate(task)}<small className="cell-secondary">{task.follow_source ? '跟随预计发货日' : '单次安排'}</small></> },
    { title: '状态', width: 95, render: (_, task) => <Tag color={task.category === 'overdue' ? 'error' : task.status === 'completed' ? 'success' : 'default'}>{taskLabels[task.category]}</Tag> },
    ...(!compact ? [{ title: '负责人 / 店铺', width: 180, render: (_: unknown, task: Task) => <>{task.assignee_name}<small className="cell-secondary">{task.store_name || '个人待办'}</small></> }] : []),
    { title: '操作', width: 215, render: (_, task) => <Space size={0} wrap>{task.status === 'pending' ? <><Button type="link" disabled={!!busy} loading={busy === task.id} onClick={() => status(task, 'completed')}>完成</Button><Button type="link" onClick={() => setEditing(task)}>调整</Button><Button type="link" disabled={!!busy} onClick={() => status(task, 'cancelled')}>取消</Button></> : <Button type="link" disabled={!!busy} onClick={() => status(task, 'pending')}>恢复</Button>}{sourceHref(task) && <Button type="link" href={sourceHref(task)}>{task.source_id ? '打开单据' : '打开页面'}</Button>}</Space> },
  ]} />{editing && <TaskEditor task={editing} user={user} stores={stores} onClose={() => setEditing(undefined)} onSaved={() => { setEditing(undefined); refresh(); }} />}{detail && <TaskDetails id={detail} onClose={() => setDetail(undefined)} />}</>;
}
function TaskDetails({ id, onClose }: { id: string; onClose: () => void }) {
  const data = useResource<Task>(`/tasks/${id}`); const task = data.data;
  const actions: Record<string, string> = { created: '创建待办', updated: '调整待办', status: '状态变更', source_reschedule: '跟随单据改期', source_changed: '单据日期有变化', coverage: '更新分批货件覆盖情况' };
  return <Drawer open title="待办记录" size={640} onClose={onClose} loading={data.loading}><ErrorNotice error={data.error} retry={data.reload} />{task && <><h2>{task.title}</h2><Descriptions column={1} items={[{ key: 'date', label: '安排', children: taskDate(task) }, { key: 'owner', label: '负责人', children: task.assignee_name }, { key: 'source', label: '来源', children: task.source_number || kindLabels[task.action_kind] }, { key: 'note', label: '备注', children: <span className="catalog-prewrap">{task.notes || '—'}</span> }, { key: 'reason', label: '结束说明', children: task.completion_reason || '—' }]} /><h3>最近 100 条变更</h3><Timeline items={task.history?.map(entry => ({ key: entry.id, content: <><strong>{actions[entry.action] || '更新待办'}</strong><p>{String(entry.data.reason || '')}{entry.data.after && entry.action === 'status' ? taskLabels[String(entry.data.after)] : ''}{entry.action === 'source_reschedule' ? `${entry.data.before} → ${entry.data.after}` : ''}</p><small>{dateTime(entry.created_at)}</small></> }))} /></>}</Drawer>;
}
export function SourceTasks({ source, user }: { source: TaskSource; user: User }) {
  const [creating, setCreating] = useState(false); const [rules, setRules] = useState(false); const [version, setVersion] = useState(0);
  if (!user.permissions.includes('tasks.view')) return null;
  return <Card className="section-card task-source-card" title="关联待办" extra={<Space><Button onClick={() => setRules(true)}>添加规则提醒</Button><Button onClick={() => setCreating(true)}>添加待办</Button></Space>}><Alert type="info" showIcon title="待办用于提醒，可随时完成、调整或取消；单据操作不受待办状态限制。" style={{ marginBottom: 16 }} /><TaskTable key={version} compact path={queryPath('/tasks', { source_kind: source.kind, source_id: source.id, group: 'all', mine: false })} user={user} stores={[]} />{creating && <TaskEditor source={source} user={user} stores={[]} onClose={() => setCreating(false)} onSaved={() => { setCreating(false); setVersion(v => v + 1); }} />}{rules && <ApplyTaskRules source={source} onClose={() => setRules(false)} onSaved={() => { setRules(false); setVersion(v => v + 1); }} />}</Card>;
}
