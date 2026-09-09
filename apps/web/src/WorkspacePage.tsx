import { useEffect, useState } from 'react';
import { Alert, Button, Card, Col, Input, Row, Select, Space, Tabs } from 'antd';
import { PlusOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import { ErrorNotice, PageHeading, useResource } from './common';
import { queryPath, useDebouncedValue } from './CatalogShared';
import { TaskEditor, TaskTable, taskLabels, useReminderRefresh } from './TaskShared';
import { TaskRules } from './TaskRules';
import type { Store, User, Workspace } from './types';

type Page = 'workspace' | 'stores' | 'users' | 'jobs' | 'notifications' | 'attachments' | 'audit' | 'products' | 'suppliers' | 'quotes' | 'imports' | 'sales' | 'inventory' | 'purchases' | 'shipments';
export function WorkspacePage({ user, stores, selectedStore, onNavigate, onUnread }: { user: User; stores: Store[]; selectedStore: string; onNavigate: (page: Page) => void; onUnread: (count: number) => void }) {
  const [tab, setTab] = useState('tasks'); const [group, setGroup] = useState('pending'); const [mine, setMine] = useState(true); const [query, setQuery] = useState(''); const q = useDebouncedValue(query); const [creating, setCreating] = useState(false); const [version, setVersion] = useState(0);
  const scope = { store_id: selectedStore === 'all' ? undefined : selectedStore, mine };
  const summary = useResource<Record<string, number>>(queryPath('/tasks/summary', scope));
  const workspace = useResource<Workspace>(queryPath('/workspace', { store_id: scope.store_id }));
  useEffect(() => { if (workspace.data) onUnread(workspace.data.unread_notifications); }, [workspace.data, onUnread]);
  useReminderRefresh(summary.reload); useReminderRefresh(workspace.reload);
  const refresh = () => { setVersion(v => v + 1); summary.reload(); workspace.reload(); };
  const shortcuts = [{ page: 'imports' as const, name: '下载与导入数据', permission: 'reports.view' }, { page: 'sales' as const, name: '分析销售', permission: 'reports.view' }, { page: 'inventory' as const, name: '查看库存', permission: 'inventory.view' }, { page: 'purchases' as const, name: '采购下单', permission: 'purchases.view' }, { page: 'shipments' as const, name: '安排发货', permission: 'shipments.view' }].filter(item => user.permissions.includes(item.permission));
  return <><PageHeading eyebrow="DAILY WORKSPACE" title="经营工作台" description={`${user.display_name}，从今天要处理的事情开始。工作可以灵活安排，提醒由你掌握。`} extra={<Space><Button icon={<ReloadOutlined />} onClick={refresh}>刷新</Button><Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>新建待办</Button></Space>} />
    <ErrorNotice error={summary.error || workspace.error} retry={refresh} /><Row gutter={[16, 16]} className="stats-row">{['overdue', 'today', 'future', 'unscheduled'].map(key => <Col xs={12} xl={6} key={key}><button className={`task-stat ${group === key && tab === 'tasks' ? 'is-selected' : ''}`} onClick={() => { setGroup(key); setTab('tasks'); }}><span>{taskLabels[key]}</span><strong>{summary.loading && !summary.data ? '…' : summary.data?.[key] ?? '—'}</strong><small>{key === 'overdue' ? '需要重新安排或处理' : key === 'today' ? '今日尚未到期的事项' : key === 'future' ? '按日期提前查看' : '确定时间后再安排'}</small></button></Col>)}</Row>
    {!!summary.data?.pending_sync && <Alert className="page-notice" showIcon type={summary.data.failed_sync ? 'warning' : 'info'} title={summary.data.failed_sync ? '部分单据待办尚未同步，系统将重试。可以先处理业务或手动添加待办。' : '单据变更正在同步到待办，稍后自动刷新。'} />}
    <Card className="section-card"><Tabs activeKey={tab} onChange={setTab} items={[{ key: 'tasks', label: '我的待办' }, { key: 'rules', label: '提醒规则' }]} />{tab === 'tasks' ? <><div className="catalog-filter-bar"><Input className="catalog-search" value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索待办或单据号" prefix={<SearchOutlined />} allowClear /><Select value={group} onChange={setGroup} style={{ width: 145 }} options={[{ value: 'pending', label: '全部待处理' }, ...Object.entries(taskLabels).filter(([key]) => key !== 'pending').map(([value, label]) => ({ value, label }))]} /><Select value={mine} onChange={setMine} style={{ width: 160 }} options={[{ value: true, label: '由我负责' }, { value: false, label: '全部可访问待办' }]} /></div><TaskTable key={`${version}:${mine}`} path={queryPath('/tasks', { ...scope, q, group })} user={user} stores={stores} onChanged={summary.reload} /></> : <TaskRules user={user} stores={stores} selectedStore={selectedStore} />}</Card>
    <Card className="section-card task-shortcuts" title="常用工作"><Space wrap>{shortcuts.map(item => <Button key={item.page} onClick={() => onNavigate(item.page)}>{item.name}</Button>)}</Space><p className="cell-secondary">单据可以独立处理。完成、改期或取消待办，只改变提醒安排。</p></Card>
    {creating && <TaskEditor user={user} stores={stores} selectedStore={selectedStore} onClose={() => setCreating(false)} onSaved={() => { setCreating(false); refresh(); }} />}</>;
}
