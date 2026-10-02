import { Alert, Descriptions, Spin } from 'antd';
import { ActiveTag, EmptyState, ErrorNotice, useResource } from './common';

interface SaleStore { store_id: string; store_name: string; store_active: boolean }
export function ProductStores({ productId }: { productId: string }) {
  const resource = useResource<{ brand: string; items: SaleStore[] }>(`/products/${productId}/stores`);
  const store = resource.data?.items[0];
  return <>
    <Alert type="info" showIcon title="商品的售卖店铺" description="每个商品仅归属一个店铺，按商品品牌与店铺绑定的品牌自动对应。" style={{ marginBottom: 16 }} />
    <ErrorNotice error={resource.error} retry={resource.reload} />
    {resource.loading ? <div className="page-loading"><Spin /></div> : !resource.error && (store ?
      <Descriptions bordered size="small" column={1} items={[
        { key: 'store', label: '售卖店铺', children: store.store_name },
        { key: 'brand', label: '绑定品牌', children: resource.data?.brand },
        { key: 'status', label: '店铺状态', children: <ActiveTag active={store.store_active} /> },
      ]} /> : <EmptyState text={resource.data?.brand.trim()
        ? '暂无可展示的归属店铺，请核对店铺绑定的品牌及店铺访问权限。'
        : '商品尚未填写品牌，请完善商品品牌后查看归属店铺。'} />)}
  </>;
}
