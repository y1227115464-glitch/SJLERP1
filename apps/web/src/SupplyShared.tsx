import { useState } from 'react';
import { Alert, Form, InputNumber, Select, Tag } from 'antd';
import { useResource } from './common';
import { queryPath, useDebouncedValue } from './CatalogShared';
import type { ListResult, Store } from './types';

export const purchaseStatuses: Record<string, string> = { draft: '草稿', ordered: '待交付', partially_received: '部分到货', received: '全部到货', cancelled: '已取消', closed: '余量已取消' };
export const shipmentStatuses: Record<string, string> = { planned: '待发货', in_transit: '运输中', partially_received: '部分接收', received: '已收齐', cancelled: '已取消' };
export const stageLabels: Record<string, string> = { preparing: '备货中', in_transit: '运输中', customs: '清关中', delivered: '已送达待接收', delayed: '异常 / 延误', partially_received: '部分接收', received: '已收齐', cancelled: '已取消', note: '资料更新' };
export const warehouseKinds: Record<string, string> = { domestic: '国内仓', overseas: '海外仓', fba: 'FBA 接收账面仓' };
export const movementKinds: Record<string, string> = { opening: '期初入库', adjustment: '库存调整', reserve: '计划占用', release: '取消释放', dispatch: '发货出库', receipt: '接收入库' };
export const options = (labels: Record<string, string>) => Object.entries(labels).map(([value, label]) => ({ value, label }));
export const storeParam = (selectedStore: string) => selectedStore === 'all' ? undefined : selectedStore;
export const required = [{ required: true, message: '请填写或选择此项' }];
export const displayMoney = (amount?: string, currency?: string) => amount === undefined ? '—' : `${currency} ${amount}`;
export function StatusTag({ status, labels, overdue = false }: { status: string; labels: Record<string, string>; overdue?: boolean }) {
  const color = ['received', 'closed'].includes(status) ? 'success' : status === 'cancelled' ? 'default' : status === 'draft' || status === 'planned' ? 'gold' : 'processing';
  return <><Tag color={color} bordered={false}>{labels[status] ?? status}</Tag>{overdue && <Tag color="error" bordered={false}>已逾期</Tag>}</>;
}
export function StoreField({ stores, fixed }: { stores: Store[]; fixed?: boolean }) {
  return <Form.Item name="store_id" label="所属店铺" rules={required}><Select disabled={fixed} placeholder="选择货权所属店铺" options={stores.filter(item => item.is_active).map(item => ({ value: item.id, label: item.name }))} /></Form.Item>;
}
export function QuantityInput({ value, onChange, min = 1, max = 1000000000 }: { value?: number; onChange?: (value: number | null) => void; min?: number; max?: number }) {
  return <InputNumber aria-label="数量" style={{ width: '100%' }} value={value} onChange={onChange} min={min} max={max} precision={0} />;
}
export function requestId(): string {
  // randomUUID is unavailable on ordinary LAN HTTP origins; getRandomValues works there.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
interface OptionRecord { id: string; name?: string; display_name?: string; internal_sku?: string; code?: string; number?: string; supplier_name?: string }
export function RemoteSelect({ path, value, onChange, initialLabel, placeholder = '输入名称搜索并选择', disabled = false }: {
  path: string | null; value?: string; onChange?: (id: string) => void; initialLabel?: string; placeholder?: string; disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [selection, setSelection] = useState<{ value: string; label: string }>();
  const q = useDebouncedValue(search);
  const resource = useResource<ListResult<OptionRecord>>(open && path ? `${path}${path.includes('?') ? '&' : '?'}limit=30&q=${encodeURIComponent(q)}` : null);
  const choices = (resource.data?.items ?? []).map(item => ({ value: item.id, label: [item.internal_sku || item.code || item.number, item.name || item.display_name || item.supplier_name].filter(Boolean).join(' · ') }));
  if (value && !choices.some(item => item.value === value)) choices.unshift({ value, label: selection?.value === value ? selection.label : initialLabel || value });
  return <Select showSearch={{ filterOption: false, onSearch: setSearch }} value={value} disabled={disabled || !path} placeholder={placeholder} loading={resource.loading}
    options={choices} onOpenChange={setOpen} onChange={id => { setSelection(choices.find(item => item.value === id)); onChange?.(id); }}
    notFoundContent={resource.error ? <Alert type="error" title={resource.error} /> : resource.loading ? '加载中…' : '没有匹配档案，请先新增或调整搜索词'} />;
}
export const activeWarehousesPath = queryPath('/warehouses', { is_active: true });
