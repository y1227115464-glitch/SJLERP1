import { useEffect, useState } from 'react';
import { Alert, Image, Tag } from 'antd';
import { ApartmentOutlined, PictureOutlined } from '@ant-design/icons';
import { fetchAll } from './common';
import { errorText } from './api';
import type { User } from './types';
import type { TaxStatus } from './catalog-types';

export const canViewQuotes = (user: User) => user.permissions.includes('quotes.view') && user.permissions.includes('costs.view');
export const canManageQuotes = (user: User) => user.permissions.includes('quotes.manage') && user.permissions.includes('costs.view');
export function queryPath(path: string, params: Record<string, string | boolean | undefined>) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => { if (value !== undefined && value !== '') query.set(key, String(value)); });
  return query.size ? `${path}?${query}` : path;
}
export function useDebouncedValue<T>(value: T, delay = 250) {
  const [settled, setSettled] = useState(value);
  useEffect(() => { const timer = setTimeout(() => setSettled(value), delay); return () => clearTimeout(timer); }, [value, delay]);
  return settled;
}
export function useCatalogOptions<T>(path: string | null, revision = 0) {
  const [snapshot, setSnapshot] = useState<{ path: string | null; data: T[]; error: string; loading: boolean }>({ path: null, data: [], error: '', loading: true });
  useEffect(() => {
    let active = true;
    if (!path) { setSnapshot({ path, data: [], error: '', loading: false }); return; }
    setSnapshot({ path, data: [], error: '', loading: true });
    fetchAll<T>(path).then(data => { if (active) setSnapshot({ path, data, error: '', loading: false }); })
      .catch(error => { if (active) setSnapshot({ path, data: [], error: errorText(error), loading: false }); });
    return () => { active = false; };
  }, [path, revision]);
  return snapshot.path === path ? snapshot : { data: [] as T[], error: '', loading: !!path };
}
export function SharedCatalogNotice({ description }: { description?: string }) {
  return <Alert className="page-notice" type="info" showIcon icon={<ApartmentOutlined />} title="公司共享基础档案" description={description ?? '所有授权成员共用这份档案，不受顶部店铺与经营日期筛选影响；品牌不代表店铺授权范围。'} />;
}
export function ReviewTag({ needsReview }: { needsReview: boolean }) { return <Tag bordered={false} color={needsReview ? 'warning' : 'success'}>{needsReview ? '待核对' : '已核对'}</Tag>; }
export function safeSourceUrl(value?: string | null): string | undefined {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password && !/[\u0000-\u001f]/.test(value) ? value : undefined;
  } catch { return undefined; }
}
export function ProductImage({ url, name, size = 56, preview = false }: { url?: string | null; name: string; size?: number; preview?: boolean }) {
  const source = safeSourceUrl(url);
  const [failedSource, setFailedSource] = useState<string | null>(null);
  if (!source || failedSource === source) return <span className="product-image-placeholder" style={{ width: size, height: size }} role="img" aria-label="暂无商品图片"><PictureOutlined /></span>;
  return <Image className="product-image" src={source} alt={name} width={size} height={size} preview={preview} onError={() => setFailedSource(source)} />;
}
export function money(value: string | null | undefined, currency: string) {
  if (value === null || value === undefined || value === '') return '未确认';
  return `${currency} ${value}`;
}
export const taxLabels: Record<TaxStatus, string> = { unknown: '税况待确认', included: '含税', excluded: '不含税', mixed: '不同档位或来源税况不一' };
export const inclusionLabel = (value: boolean | null) => value === null ? '待确认' : value ? '已包含' : '未包含';
export const multilineToArray = (value: string | undefined) => (value ?? '').split(/\r?\n/).map(line => line.trim()).filter(Boolean);
export const amountRule = { pattern: /^\d{1,14}(\.\d{1,4})?$/, message: '请输入非负金额，整数最多 14 位、小数最多 4 位' };
export const multilineRule = (maxItems: number, maxLength: number) => ({
  validator: (_: unknown, value: string) => {
    const lines = multilineToArray(value);
    return lines.length <= maxItems && lines.every(line => line.length <= maxLength) ? Promise.resolve() : Promise.reject(new Error(`最多 ${maxItems} 项，每项最多 ${maxLength} 字符`));
  },
});
export const urlRule = { validator: (_: unknown, value: string) => !value || safeSourceUrl(value) ? Promise.resolve() : Promise.reject(new Error('仅支持完整的 http 或 https 链接')) };
