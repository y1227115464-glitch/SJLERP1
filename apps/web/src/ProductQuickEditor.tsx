import { Modal } from 'antd';
import { ErrorNotice, useResource } from './common';
import { ProductEditor } from './ProductEditor';
import type { Product } from './catalog-types';

export function ProductQuickEditor({ id, onClose, onSaved }: { id: string; onClose: () => void; onSaved: (product: Product) => void }) {
  const resource = useResource<Product>(`/products/${id}`);
  return resource.data ? <ProductEditor product={resource.data} onClose={onClose} onSaved={onSaved} /> :
    <Modal open title="加载商品档案" onCancel={onClose} footer={null} loading={resource.loading}><ErrorNotice error={resource.error} retry={resource.reload} /></Modal>;
}
