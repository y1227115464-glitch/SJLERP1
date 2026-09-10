import { useState } from 'react';
import { Alert, Switch, Table } from 'antd';
import { api, errorText } from './api';
import { ErrorNotice, useResource } from './common';

interface SaleStore { store_id: string; store_name: string; store_active: boolean; is_active: boolean }
export function ProductStores({ productId, canManage }: { productId: string; canManage: boolean }) {
  const resource = useResource<{ items: SaleStore[] }>(`/products/${productId}/stores`);
  const [saving, setSaving] = useState<string>();
  const [error, setError] = useState('');
  return <>
    <Alert type="info" showIcon title="维护此商品的售卖店铺" description="采购时仅显示当前店铺售卖、且关联所选供应商启用报价的商品。未维护的商品不会出现在采购选择中。" style={{ marginBottom: 16 }} />
    <ErrorNotice error={resource.error || error} retry={resource.reload} />
    <Table<SaleStore> rowKey="store_id" loading={resource.loading} dataSource={resource.data?.items || []} pagination={{ pageSize: 10 }} columns={[
      { title: '店铺', dataIndex: 'store_name' },
      { title: '售卖状态', render: (_, store) => <Switch checked={store.is_active} checkedChildren="售卖中" unCheckedChildren="未售卖" loading={saving === store.store_id} disabled={!canManage || !store.store_active || !!saving} onChange={async checked => {
        setSaving(store.store_id); setError('');
        try { await api(`/products/${productId}/stores/${store.store_id}`, { method: 'PUT', body: { is_active: checked } }); resource.reload(); }
        catch (cause) { setError(errorText(cause)); } finally { setSaving(undefined); }
      }} /> },
    ]} />
  </>;
}
