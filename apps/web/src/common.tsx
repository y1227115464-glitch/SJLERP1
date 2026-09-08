import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Alert, Button, Empty, Spin, Tag } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api, errorText } from './api';
import type { ListResult } from './types';

export function useResource<T>(path: string | null) {
  const [snapshot, setSnapshot] = useState<{ path: string | null; data: T | null; loading: boolean; error: string }>({ path: null, data: null, loading: true, error: '' });
  const [version, setVersion] = useState(0);
  const reload = useCallback(() => setVersion(value => value + 1), []);
  useEffect(() => {
    let active = true;
    if (!path) { setSnapshot({ path, data: null, loading: false, error: '' }); return; }
    setSnapshot(previous => ({ path, data: previous.path === path ? previous.data : null, loading: true, error: '' }));
    api<T>(path).then(data => { if (active) setSnapshot({ path, data, loading: false, error: '' }); })
      .catch(cause => { if (active) setSnapshot({ path, data: null, loading: false, error: errorText(cause) }); });
    return () => { active = false; };
  }, [path, version]);
  // Bind visible data to its source path so a store switch never renders the previous store's data.
  const current = snapshot.path === path ? snapshot : { data: null, loading: !!path, error: '' };
  return { data: current.data, loading: current.loading, error: current.error, reload };
}
export function usePagedList<T>(path: string) {
  const [cursor, setCursor] = useState({ path, page: 1 });
  useEffect(() => { setCursor({ path, page: 1 }); }, [path]);
  const page = cursor.path === path ? cursor.page : 1;
  const pageSize = 20;
  const resource = useResource<ListResult<T>>(`${path}${path.includes('?') ? '&' : '?'}limit=${pageSize}&offset=${(page - 1) * pageSize}`);
  return { ...resource, pagination: { current: page, pageSize, total: resource.data?.total ?? 0,
    onChange: (next: number) => setCursor({ path, page: next }), showSizeChanger: false, showTotal: (total: number) => `共 ${total} 条` } };
}
export async function fetchAll<T>(path: string): Promise<T[]> {
  const items: T[] = [];
  let total = 1;
  while (items.length < total) {
    const result = await api<ListResult<T>>(`${path}?limit=200&offset=${items.length}`);
    items.push(...result.items);
    total = result.total;
    if (!result.items.length) break;
  }
  return items;
}
export function PageHeading({ eyebrow, title, description, extra }: { eyebrow: string; title: string; description: string; extra?: ReactNode }) {
  return <div className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div><div className="heading-actions">{extra}</div></div>;
}
export function ErrorNotice({ error, retry }: { error: string; retry?: () => void }) {
  if (!error) return null;
  return <Alert className="error-notice" type="error" showIcon title="暂时无法完成请求" description={error}
    action={retry ? <Button size="small" icon={<ReloadOutlined />} onClick={retry}>重试</Button> : undefined} />;
}
export function EmptyState({ text }: { text: string }) { return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={text} />; }
export function LoadingScreen() { return <div className="loading-screen"><Spin size="large" /><p>正在连接书剑录工作空间…</p></div>; }
export const dateTime = (value?: string | null) => value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '—';
export const roleLabels: Record<string, string> = { admin: '公司管理员', manager: '店铺主管', operator: '运营', finance: '财务', warehouse: '仓库' };
export function ActiveTag({ active }: { active: boolean }) { return <Tag bordered={false} color={active ? 'success' : 'default'}>{active ? '启用中' : '已停用'}</Tag>; }

export const permissionLabels: Record<string, string> = {
  'reports.view': '查看销售与广告导入数据', 'reports.import': '导入销售与广告报告',
  'workspace.view': '查看工作台', 'stores.view': '查看店铺', 'stores.manage': '管理店铺',
  'stores.export': '导出店铺', 'users.manage': '管理账号', 'audit.view': '查看操作日志',
  'jobs.view': '查看后台任务', 'jobs.run': '运行与重试任务', 'files.view': '查看与下载附件',
  'files.upload': '上传附件', 'notifications.view': '查看个人通知', 'approvals.view': '查看审批',
  'costs.view': '查看成本', 'finance.view': '查看财务数据',
  'products.view': '查看商品', 'products.manage': '管理与导入商品',
  'suppliers.view': '查看供应商', 'suppliers.manage': '管理供应商',
  'quotes.view': '查看采购报价', 'quotes.manage': '管理采购报价',
  'purchases.view': '查看采购记录', 'purchases.manage': '维护与提交采购单',
  'shipments.view': '查看发货进度', 'shipments.manage': '维护货件与收发货',
  'inventory.view': '查看库存与流水', 'inventory.adjust': '登记期初和库存调整', 'warehouses.manage': '管理仓库档案',
};
export const actionLabels: Record<string, string> = {
  'reports.preview': '预览亚马逊报表', 'reports.confirm': '确认亚马逊报表导入',
  'auth.login': '登录', 'auth.logout': '退出', 'stores.export': '导出店铺', 'stores.create': '新增店铺',
  'stores.update': '更新店铺', 'users.create': '新增账号', 'users.update': '更新账号权限',
  'users.bootstrap': '初始化管理员', 'jobs.create': '提交任务', 'jobs.retry': '重试任务',
  'products.create': '新增商品', 'products.update': '更新商品', 'products.import_preview': '预览商品导入',
  'products.import_confirm': '确认商品导入', 'suppliers.create': '新增供应商', 'suppliers.update': '更新供应商',
  'quotes.create': '新增采购报价', 'quotes.update': '更新采购报价',
  'purchases.create': '新增采购单', 'purchases.update': '修改采购草稿', 'purchases.confirm': '提交采购单', 'purchases.cancel': '取消采购余量',
  'shipments.create': '建立发货计划', 'shipments.update': '维护物流资料', 'shipments.dispatch': '确认发货', 'shipments.cancel': '取消发货计划', 'shipments.event': '跟进物流进度', 'shipments.receive': '登记接收入库',
  'inventory.adjust': '调整库存', 'warehouses.create': '新增仓库', 'warehouses.update': '更新仓库档案',
  'jobs.succeeded': '任务完成', 'jobs.failed': '任务失败', 'files.upload': '上传附件', 'files.download': '下载附件',
};
export const resourceLabels: Record<string, string> = { report_import: '亚马逊报表导入', user: '账号', store: '店铺', job: '后台任务', attachment: '附件', approval: '审批', product: '商品', supplier: '供应商', supplier_quote: '采购报价', product_import: '商品导入', purchase_order: '采购单', shipment: '货件', inventory: '库存', warehouse: '仓库' };
