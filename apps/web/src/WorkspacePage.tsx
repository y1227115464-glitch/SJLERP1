import { useEffect } from 'react';
import { Alert, Button, Card, Col, Row, Skeleton, Table, Tag } from 'antd';
import { ArrowRightOutlined, BellOutlined, CheckCircleFilled, ClockCircleOutlined, FileTextOutlined, FolderOpenOutlined, ReloadOutlined, ShopOutlined, TeamOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { ActiveTag, dateTime, EmptyState, ErrorNotice, PageHeading, useResource } from './common';
import type { Store, User, Workspace } from './types';

type Page = 'workspace' | 'stores' | 'users' | 'jobs' | 'notifications' | 'attachments' | 'audit';
export function WorkspacePage({ user, stores, selectedStore, onNavigate, onUnread }: { user: User; stores: Store[]; selectedStore: string; onNavigate: (page: Page) => void; onUnread: (count: number) => void }) {
  const { data, loading, error, reload } = useResource<Workspace>(selectedStore === 'all' ? '/workspace' : `/workspace?store_id=${encodeURIComponent(selectedStore)}`);
  useEffect(() => { if (data) onUnread(data.unread_notifications); }, [data, onUnread]);
  const can = (permission: string) => user.permissions.includes(permission);
  const visibleStores = selectedStore === 'all' ? stores : stores.filter(store => store.id === selectedStore);
  const stats = [
    { label: '可访问店铺', value: data?.store_count, unit: '家', detail: '当前所选范围内的店铺', icon: <ShopOutlined />, tone: 'blue' },
    ...(data?.user_count != null ? [{ label: '团队账号', value: data.user_count, unit: '位', detail: '已建立的工作空间账号', icon: <TeamOutlined />, tone: 'purple' }] : []),
    { label: '待处理后台任务', value: data?.pending_jobs, unit: '项', detail: '等待执行与正在执行的任务', icon: <ThunderboltOutlined />, tone: 'gold' },
    { label: '未读通知', value: data?.unread_notifications, unit: '条', detail: '属于当前账号的站内提醒', icon: <BellOutlined />, tone: 'green' },
  ];
  return <>
    <PageHeading eyebrow="WORKSPACE OVERVIEW" title="经营工作台" description={`${user.display_name}，欢迎回来。查看工作空间状态，从这里开始今天的工作。`}
      extra={<Button icon={<ReloadOutlined />} onClick={reload} loading={loading}>刷新概览</Button>} />
    <ErrorNotice error={error} retry={reload} />
    <div className="workspace-banner"><div className="banner-icon"><ShopOutlined /></div><div><strong>工作空间使用准备</strong><p>维护店铺与团队权限，准备亚马逊原始订单、广告和库存报表。</p></div><Tag bordered={false}>手动报表维护</Tag></div>
    <Row gutter={[16, 16]} className="stats-row">{stats.map(stat => <Col xs={24} sm={12} xl={24 / stats.length} key={stat.label}><Card className="stat-card"><div className="stat-label">{stat.label}<span className={`stat-icon ${stat.tone}`}>{stat.icon}</span></div><div className="stat-value">{loading && !data ? <Skeleton.Input active size="small" /> : error ? '—' : stat.value ?? '—'}<span>{stat.unit}</span></div><div className="stat-detail">{stat.detail}</div></Card></Col>)}</Row>
    <Row gutter={[20, 20]}><Col xs={24} xl={16}><Card className="section-card" title={<div className="card-heading">经营数据<span>订单 · 广告 · 库存</span></div>} extra={<Tag bordered={false}>等待业务模块开放</Tag>}>
      <div className="data-status-grid">{[{ name: '订单与销售', icon: <FileTextOutlined />, note: '尚未接入订单报表' }, { name: '广告投放', icon: <ThunderboltOutlined />, note: '尚未接入广告报表' }, { name: 'FBA 库存', icon: <ShopOutlined />, note: '尚未接入库存快照' }].map(item => <div className="data-status-item" key={item.name}><div className="data-status-title">{item.icon}{item.name}</div><div className="no-data-value">—<span>暂无数据</span></div><div className="data-status-note"><span className="muted-dot" />{item.note}</div></div>)}</div>
      <div className="data-footnote"><ClockCircleOutlined /><span>销售额、广告花费及利润将在报表成功导入后展示，并标明覆盖日期和计算状态。</span></div>
    </Card></Col><Col xs={24} xl={8}><Card className="section-card setup-card" title="工作空间准备"><div className="setup-item"><CheckCircleFilled className="setup-done" /><div><strong>账号与登录</strong><p>当前已使用真实账号登录</p></div><Tag bordered={false} color="success">已完成</Tag></div><div className="setup-item"><span className={stores.length ? 'setup-done' : 'step-circle'}>{stores.length ? <CheckCircleFilled /> : '2'}</span><div><strong>建立店铺档案</strong><p>{stores.length ? `已可访问 ${stores.length} 家店铺` : '维护主体、品牌与站点信息'}</p></div>{can('stores.view') && <Button type="text" aria-label="前往店铺管理" icon={<ArrowRightOutlined />} onClick={() => onNavigate('stores')} />}</div><div className="setup-item"><span className="step-circle">3</span><div><strong>准备业务原始报表</strong><p>后续导入模块按实际样本适配</p></div><Tag bordered={false}>待建设</Tag></div></Card></Col>
    <Col xs={24} xl={16}><Card className="section-card stores-overview" title={<div className="card-heading">店铺概览<span>{selectedStore === 'all' ? '当前授权范围' : '当前所选店铺'}</span></div>} extra={can('stores.view') && <Button type="link" onClick={() => onNavigate('stores')}>管理店铺 <ArrowRightOutlined /></Button>}>
      <Table<Store> size="middle" dataSource={visibleStores} rowKey="id" pagination={visibleStores.length > 5 ? { pageSize: 5, showSizeChanger: false } : false} scroll={{ x: 620 }} locale={{ emptyText: <EmptyState text="还没有可访问的店铺，请创建档案或联系管理员分配权限。" /> }} columns={[
        { title: '店铺', dataIndex: 'name', render: (value: string, record) => <div className="table-name"><span className="store-avatar"><ShopOutlined /></span><div><strong>{value}</strong><small>{record.code}</small></div></div> },
        { title: '品牌 / 主体', dataIndex: 'brand', render: (value: string, record) => <div>{value || '—'}<small className="cell-secondary">{record.legal_entity || '未填写主体'}</small></div> },
        { title: '站点', dataIndex: 'marketplace', render: (value: string) => <span className="marketplace-tag">{value === 'US' ? '美国 US' : value}</span> },
        { title: '状态', dataIndex: 'is_active', render: (value: boolean) => <ActiveTag active={value} /> },
      ]} />
    </Card></Col><Col xs={24} xl={8}><Card className="section-card" title="常用操作"><div className="quick-actions">{[
      { permission: 'stores.manage', title: '维护店铺档案', desc: '连接店铺、品牌与经营主体', page: 'stores' as const, icon: <ShopOutlined /> },
      { permission: 'users.manage', title: '配置团队权限', desc: '明确角色与店铺访问范围', page: 'users' as const, icon: <TeamOutlined /> },
      { permission: 'files.view', title: '整理业务附件', desc: '按访问范围存档和下载', page: 'attachments' as const, icon: <FolderOpenOutlined /> },
      { permission: 'jobs.view', title: '检查后台运行', desc: '查看任务执行和失败原因', page: 'jobs' as const, icon: <ThunderboltOutlined /> },
    ].filter(item => can(item.permission)).map(item => <button className="quick-action" key={item.page} onClick={() => onNavigate(item.page)}><span className="quick-icon">{item.icon}</span><span><strong>{item.title}</strong><small>{item.desc}</small></span><ArrowRightOutlined /></button>)}</div></Card></Col>
    <Col span={24}><Card className="section-card" title={<div className="card-heading">最近操作<span>来自系统审计记录</span></div>} extra={can('audit.view') && <Button type="link" onClick={() => onNavigate('audit')}>查看全部 <ArrowRightOutlined /></Button>}>
      {loading && !data ? <Skeleton active paragraph={{ rows: 2 }} /> : data?.recent_activity.length ? <div className="activity-list">{data.recent_activity.slice(0, 5).map(activity => <div className="activity-item" key={activity.id}><span className="activity-dot" /><div><strong>{activity.actor_name || '系统'}</strong><span>{activity.summary}</span></div><time>{dateTime(activity.created_at)}</time></div>)}</div> : <EmptyState text="暂无操作记录，后续变更将在这里留痕。" />}
    </Card></Col></Row>
    {data && <Alert className="environment-note" type="info" showIcon title={`当前环境：${data.environment}。经营数据等待亚马逊报表导入，当前未接入销售、广告与库存。`} />}
  </>;
}
