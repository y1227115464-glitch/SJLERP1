import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { Alert, App as AntApp, Avatar, Badge, Button, DatePicker, Divider, Dropdown, Form, Input, Layout, Menu, Select, Tag, Tooltip } from 'antd';
import { ApartmentOutlined, ArrowRightOutlined, BellOutlined, CalendarOutlined, CheckCircleOutlined, ContainerOutlined, DollarOutlined, CloudUploadOutlined, DashboardOutlined, FileProtectOutlined, FolderOpenOutlined, ImportOutlined, LockOutlined, LogoutOutlined, MenuFoldOutlined, MenuUnfoldOutlined, QuestionCircleOutlined, SafetyCertificateOutlined, SettingOutlined, ShopOutlined, TeamOutlined, ThunderboltOutlined, UserOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api, errorText, setCsrfToken } from './api';
import { fetchAll, LoadingScreen, roleLabels } from './common';
import type { Store, User } from './types';
const WorkspacePage = lazy(() => import('./WorkspacePage').then(module => ({ default: module.WorkspacePage })));
const StoresPage = lazy(() => import('./ManagementPages').then(module => ({ default: module.StoresPage })));
const UsersPage = lazy(() => import('./ManagementPages').then(module => ({ default: module.UsersPage })));
const AttachmentsPage = lazy(() => import('./SystemPages').then(module => ({ default: module.AttachmentsPage })));
const AuditPage = lazy(() => import('./SystemPages').then(module => ({ default: module.AuditPage })));
const JobsPage = lazy(() => import('./SystemPages').then(module => ({ default: module.JobsPage })));
const NotificationsPage = lazy(() => import('./SystemPages').then(module => ({ default: module.NotificationsPage })));
const ProductsPage = lazy(() => import('./ProductPages').then(module => ({ default: module.ProductsPage })));
const SuppliersPage = lazy(() => import('./SupplierPages').then(module => ({ default: module.SuppliersPage })));
const QuotesPage = lazy(() => import('./QuotePages').then(module => ({ default: module.QuotesPage })));
const PurchasesPage = lazy(() => import('./PurchasePages').then(module => ({ default: module.PurchasesPage })));
const ShipmentsPage = lazy(() => import('./ShipmentPages').then(module => ({ default: module.ShipmentsPage })));
const InventoryPage = lazy(() => import('./InventoryPages').then(module => ({ default: module.InventoryPage })));

type Page = 'workspace' | 'stores' | 'users' | 'jobs' | 'notifications' | 'attachments' | 'audit' | 'products' | 'suppliers' | 'quotes' | 'purchases' | 'shipments' | 'inventory';
const pageTitles: Record<Page, string> = { workspace: '经营工作台', stores: '店铺管理', users: '账号与权限', jobs: '后台任务', notifications: '站内通知', attachments: '附件中心', audit: '操作日志', products: '商品管理', suppliers: '供应商管理', quotes: '采购报价', purchases: '采购记录', shipments: '发货进度', inventory: '库存管理' };
const pagePermissions: Record<Page, string> = { workspace: 'workspace.view', stores: 'stores.view', users: 'users.manage', jobs: 'jobs.view', notifications: 'notifications.view', attachments: 'files.view', audit: 'audit.view', products: 'products.view', suppliers: 'suppliers.view', quotes: 'quotes.view', purchases: 'purchases.view', shipments: 'shipments.view', inventory: 'inventory.view' };
function initialPage(): Page { const hash = location.hash.slice(1); return hash in pageTitles ? hash as Page : 'workspace'; }

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [booting, setBooting] = useState(true);
  const [authError, setAuthError] = useState('');
  const storeRequest = useRef(0);
  const [stores, setStores] = useState<Store[]>([]);
  const [storeError, setStoreError] = useState('');
  const [selectedStore, setSelectedStore] = useState<string>('all');
  const [collapsed, setCollapsed] = useState(false);
  const [page, setPage] = useState<Page>(initialPage);
  const [unread, setUnread] = useState(0);
  const [range, setRange] = useState<[dayjs.Dayjs, dayjs.Dayjs]>([dayjs().startOf('month'), dayjs()]);
  const { message, modal } = AntApp.useApp();
  const can = useCallback((permission: string) => !!user?.permissions.includes(permission), [user]);
  const navigate = (next: Page) => { setPage(next); location.hash = next; };
  useEffect(() => {
    const update = () => setPage(initialPage());
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);
  useEffect(() => {
    const expire = () => { storeRequest.current += 1; setUser(null); setStores([]); setUnread(0); setAuthError('登录已过期或账号权限已变更，请重新登录。'); };
    window.addEventListener('sjlerp:unauthorized', expire);
    api<{ user: User; csrf_token: string }>('/auth/me')
      .then(result => { setUser(result.user); setCsrfToken(result.csrf_token); setAuthError(''); })
      .catch(error => { if (error.status !== 401) setAuthError(errorText(error)); else setAuthError(''); })
      .finally(() => setBooting(false));
    return () => window.removeEventListener('sjlerp:unauthorized', expire);
  }, []);
  const refreshStores = useCallback(async () => {
    if (!user) return;
    const requestId = ++storeRequest.current;
    try {
      const data = await fetchAll<Store>('/stores');
      if (requestId !== storeRequest.current) return;
      setStores(data); setStoreError('');
      setSelectedStore(current => current === 'all' || data.some(store => store.id === current) ? current : 'all');
    } catch (error) { if (requestId === storeRequest.current) setStoreError(errorText(error)); }
  }, [user]);
  useEffect(() => { void refreshStores(); }, [refreshStores]);
  useEffect(() => { document.title = `${user ? pageTitles[page] : '登录'} · 书剑录 ERP`; }, [page, user]);
  if (booting) return <LoadingScreen />;
  if (!user) return <LoginPage error={authError} onLogin={(next, csrf) => { storeRequest.current += 1; setUser(next); setCsrfToken(csrf); setAuthError(''); setUnread(0); setStoreError(''); }} />;
  const logout = () => modal.confirm({ title: '退出当前账号？', content: '退出后需重新登录才能访问工作空间。', okText: '退出登录', cancelText: '取消',
    onOk: async () => { try { await api('/auth/logout', { method: 'POST' }); storeRequest.current += 1; setUser(null); setCsrfToken(''); setStores([]); setUnread(0); } catch (error) { message.error(errorText(error)); throw error; } } });
  const items = [
    { type: 'group' as const, label: '工作空间', children: [
      can('workspace.view') && { key: 'workspace', icon: <DashboardOutlined />, label: '经营工作台' },
      can('notifications.view') && { key: 'notifications', icon: <BellOutlined />, label: <span className="nav-with-count">站内通知{unread > 0 && <span className="nav-count">{unread}</span>}</span> },
    ].filter(Boolean) },
    { type: 'group' as const, label: '业务管理', children: [
      can('stores.view') && { key: 'stores', icon: <ShopOutlined />, label: '店铺管理' },
      can('products.view') && { key: 'products', icon: <ApartmentOutlined />, label: '商品管理' },
      can('suppliers.view') && { key: 'suppliers', icon: <ContainerOutlined />, label: '供应商管理' },
      can('quotes.view') && can('costs.view') && { key: 'quotes', icon: <DollarOutlined />, label: '采购报价' },
      can('purchases.view') && { key: 'purchases', icon: <FileProtectOutlined />, label: '采购记录' },
      can('shipments.view') && { key: 'shipments', icon: <ContainerOutlined />, label: '发货进度' },
      can('inventory.view') && { key: 'inventory', icon: <ApartmentOutlined />, label: '库存管理' },
      { key: 'imports-planned', icon: <ImportOutlined />, label: <span className="planned-nav">数据导入中心<span>筹建</span></span>, disabled: true },
      { key: 'finance-planned', icon: <FileProtectOutlined />, label: <span className="planned-nav">销售与财务<span>筹建</span></span>, disabled: true },
    ].filter(Boolean) },
    { type: 'group' as const, label: '协同与设置', children: [
      can('files.view') && { key: 'attachments', icon: <FolderOpenOutlined />, label: '附件中心' },
      can('jobs.view') && { key: 'jobs', icon: <ThunderboltOutlined />, label: '后台任务' },
      can('users.manage') && { key: 'users', icon: <TeamOutlined />, label: '账号与权限' },
      can('audit.view') && { key: 'audit', icon: <SafetyCertificateOutlined />, label: '操作日志' },
    ].filter(Boolean) },
  ];
  const sharedCatalog = ['products', 'suppliers', 'quotes'].includes(page);
  return <Layout className="app-layout">
    <Layout.Sider width={228} collapsedWidth={76} collapsed={collapsed} breakpoint="lg" onBreakpoint={setCollapsed} className="sidebar">
      <a className="brand" href="#workspace" aria-label="书剑录 ERP 首页"><span className="brand-mark">书</span>{!collapsed && <span className="brand-title">书剑录<span>SHUJIANLU ERP</span></span>}</a>
      {!collapsed && <div className="workspace-chip"><span className="small-dot" />美国站 · 多店铺工作空间</div>}
      <Menu theme="dark" mode="inline" selectedKeys={[page]} items={items as Parameters<typeof Menu>[0]['items']} onClick={({ key }) => navigate(key as Page)} />
      <div className="sidebar-footer">{!collapsed && <><div><span className="status-dot" /> 内部工作空间</div><p>美国站 · FBA</p></>}<Button type="text" className="collapse-button" aria-label={collapsed ? '展开导航' : '收起导航'} onClick={() => setCollapsed(!collapsed)} icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />} /></div>
    </Layout.Sider>
    <Layout className="main-layout">
      <Layout.Header className="topbar"><div className="breadcrumb">工作空间<span>/</span><strong>{pageTitles[page]}</strong></div><div className="topbar-actions">
        <Tag className="version-tag" bordered={false}>美国站 US</Tag>
        {can('notifications.view') && <Tooltip title="站内通知"><Badge count={unread} size="small"><Button aria-label="打开站内通知" type="text" icon={<BellOutlined />} onClick={() => navigate('notifications')} /></Badge></Tooltip>}
        <Divider type="vertical" />
        <Dropdown trigger={['click']} menu={{ items: [{ key: 'identity', label: <div>{user.email}<br /><small>{roleLabels[user.role]}</small></div>, disabled: true }, { type: 'divider' }, { key: 'logout', label: '退出登录', icon: <LogoutOutlined />, onClick: logout }] }}><Button type="text" className="user-button"><Avatar size={30} style={{ background: '#e8edf3', color: '#315b88' }}>{user.display_name.slice(0, 1)}</Avatar><span>{user.display_name}</span></Button></Dropdown>
      </div></Layout.Header>
      {sharedCatalog ? <div className="scope-bar catalog-scope-bar"><ApartmentOutlined /><strong>公司共享档案</strong><span>当前页面不受店铺或经营日期筛选影响</span><Tag bordered={false}>按角色授权访问</Tag></div> : <div className="scope-bar"><div className="scope-field"><ShopOutlined /><span className="filter-label">店铺</span><Select aria-label="选择店铺" value={selectedStore} onChange={setSelectedStore} style={{ minWidth: 190 }} variant="borderless" options={[{ value: 'all', label: user.role === 'admin' ? '全部店铺' : '我的全部店铺' }, ...stores.map(store => ({ value: store.id, label: `${store.name}${store.is_active ? '' : '（停用）'}` }))]} /></div><div className="scope-divider" /><div className="scope-field date-filter"><CalendarOutlined /><DatePicker.RangePicker aria-label="统计日期范围" value={range} onChange={value => { if (value?.[0] && value[1]) setRange([value[0], value[1]]); }} allowClear={false} variant="borderless" format="YYYY-MM-DD" /></div><Tooltip title="经营报表上线后使用此期间；当前账号、店铺和系统记录不按经营日期过滤。"><span className="scope-note"><QuestionCircleOutlined /> 经营期间待报表接入后生效</span></Tooltip></div>}
      <Layout.Content className="content">
        {storeError && <Alert type="error" showIcon title="店铺列表加载失败" description={storeError} action={<Button onClick={() => void refreshStores()}>重试</Button>} style={{ marginBottom: 20 }} />}
        {(!can(pagePermissions[page]) || (page === 'quotes' && !can('costs.view'))) ? <Alert type="warning" showIcon title="暂无访问权限" description="当前账号无法查看此页面。如需调整，请联系公司管理员。" /> : <Suspense fallback={<div className="page-loading">页面加载中…</div>}>
          {page === 'workspace' && <WorkspacePage user={user} stores={stores} selectedStore={selectedStore} onNavigate={navigate} onUnread={setUnread} />}
          {page === 'stores' && <StoresPage user={user} stores={stores} selectedStore={selectedStore} refreshStores={refreshStores} />}
          {page === 'users' && <UsersPage user={user} stores={stores} />}
          {page === 'jobs' && <JobsPage user={user} stores={stores} selectedStore={selectedStore} />}
          {page === 'notifications' && <NotificationsPage onUnread={setUnread} />}
          {page === 'attachments' && <AttachmentsPage user={user} stores={stores} selectedStore={selectedStore} />}
          {page === 'audit' && <AuditPage selectedStore={selectedStore} />}
          {page === 'products' && <ProductsPage user={user} />}
          {page === 'suppliers' && <SuppliersPage user={user} />}
          {page === 'quotes' && <QuotesPage user={user} />}
          {page === 'purchases' && <PurchasesPage key={selectedStore} user={user} stores={stores} selectedStore={selectedStore} />}
          {page === 'shipments' && <ShipmentsPage key={selectedStore} user={user} stores={stores} selectedStore={selectedStore} />}
          {page === 'inventory' && <InventoryPage key={selectedStore} user={user} stores={stores} selectedStore={selectedStore} />}
        </Suspense>}
        <footer className="page-footer"><span>书剑录 ERP</span><span>美国站 · FBA 经营与供应链管理</span></footer>
      </Layout.Content>
    </Layout>
  </Layout>;
}

function LoginPage({ error, onLogin }: { error: string; onLogin: (user: User, csrf: string) => void }) {
  const [loading, setLoading] = useState(false);
  const [loginError, setLoginError] = useState('');
  const submit = async (values: { email: string; password: string }) => {
    setLoading(true); setLoginError('');
    try { const result = await api<{ user: User; csrf_token: string }>('/auth/login', { method: 'POST', body: values }); onLogin(result.user, result.csrf_token); }
    catch (cause) { setLoginError(errorText(cause)); } finally { setLoading(false); }
  };
  return <div className="login-screen"><section className="login-story"><a className="brand" href="#"><span className="brand-mark">书</span><span className="brand-title">书剑录<span>SHUJIANLU ERP</span></span></a><div className="login-story-copy"><div className="login-eyebrow">书剑录内部管理系统</div><h1>多店铺经营<br />与供应链协同</h1><p>集中维护店铺、团队和业务资料，<br />按岗位和店铺范围访问工作空间。</p><div className="story-flow"><div><ShopOutlined /><span>店铺经营</span></div><span className="flow-line" /><div><CloudUploadOutlined /><span>数据归集</span></div><span className="flow-line" /><div><ApartmentOutlined /><span>供应链协同</span></div></div></div><div className="login-story-footer"><span className="gold-dot" /> SHUJIANLU · BUSINESS WORKSPACE</div></section>
      <section className="login-form-panel"><div className="login-card"><Tag color="blue" bordered={false}>书剑录内部工作空间</Tag><h2>欢迎回来</h2><p className="login-intro">登录账号，开始今天的工作。</p>{(loginError || error) && <Alert type="error" showIcon title={loginError || error} style={{ marginBottom: 24 }} />}
        <Form layout="vertical" onFinish={submit} requiredMark={false} size="large"><Form.Item label="邮箱" name="email" rules={[{ required: true, message: '请输入账号邮箱' }, { type: 'email', message: '请输入有效的邮箱地址' }]}><Input prefix={<UserOutlined />} placeholder="请输入账号邮箱" autoComplete="username" /></Form.Item><Form.Item label="密码" name="password" rules={[{ required: true, message: '请输入密码' }]}><Input.Password prefix={<LockOutlined />} placeholder="请输入密码" autoComplete="current-password" /></Form.Item><Button type="primary" htmlType="submit" block loading={loading} className="login-submit">登录工作空间 <ArrowRightOutlined /></Button></Form>
        <div className="login-help"><SafetyCertificateOutlined /><span>账号由公司管理员开通。忘记密码时，请联系管理员重置。</span></div><div className="login-stage"><CheckCircleOutlined /><div><strong>订单与广告维护方式</strong><p>从亚马逊导出报表后，统一导入 ERP 归集与核对。</p></div></div>
      </div><div className="login-legal"><SettingOutlined /> 书剑录 ERP · 内部工作空间</div></section></div>;
}
