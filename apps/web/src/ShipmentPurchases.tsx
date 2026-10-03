import { useEffect, useState } from 'react';
import { Alert, Select } from 'antd';
import { api, errorText } from './api';
import { useDebouncedValue } from './CatalogShared';
import { useResource } from './common';
import type { ListResult } from './types';
import type { PurchaseOrder } from './supply-types';

const emptyOrders: PurchaseOrder[] = [];
export function useShipmentPurchases(ids: string[]) {
  const key = JSON.stringify(ids);
  const [state, setState] = useState({ key: '', orders: emptyOrders, loading: false, error: '' });
  useEffect(() => {
    const selected: string[] = JSON.parse(key);
    const controller = new AbortController();
    if (!selected.length) { setState({ key, orders: emptyOrders, loading: false, error: '' }); return; }
    setState({ key, orders: emptyOrders, loading: true, error: '' });
    Promise.all(selected.map(id => api<PurchaseOrder>(`/purchase-orders/${id}`, { signal: controller.signal })))
      .then(orders => { if (!controller.signal.aborted) setState({ key, orders, loading: false, error: '' }); })
      .catch(cause => { if (!controller.signal.aborted) setState({ key, orders: emptyOrders, loading: false, error: errorText(cause) }); });
    return () => controller.abort();
  }, [key]);
  return state.key === key ? state : { key, orders: emptyOrders, loading: ids.length > 0, error: '' };
}

export function PurchaseMultiSelect({ storeId, value = [], onChange, selectedOrders }: {
  storeId?: string; value?: string[]; onChange?: (ids: string[]) => void; selectedOrders: { id: string; number: string }[];
}) {
  const [search, setSearch] = useState('');
  const [open, setOpen] = useState(false);
  const q = useDebouncedValue(search);
  const resource = useResource<ListResult<PurchaseOrder>>(open && storeId ? `/purchase-orders?store_id=${storeId}&shippable=true&limit=100&q=${encodeURIComponent(q)}` : null);
  const options = [...new Map([...selectedOrders, ...(resource.data?.items ?? [])].map(order => [order.id, { value: order.id, label: order.number }])).values()];
  return <Select mode="multiple" value={value} onChange={onChange} disabled={!storeId} maxCount={100}
    showSearch={{ filterOption: false, onSearch: setSearch }} onOpenChange={setOpen} options={options}
    placeholder="选择一个或多个采购单，自动带入全部可发商品" loading={resource.loading}
    notFoundContent={resource.error ? <Alert type="error" title={resource.error} /> : resource.loading ? '加载中…' : '没有可发货采购单'} />;
}
