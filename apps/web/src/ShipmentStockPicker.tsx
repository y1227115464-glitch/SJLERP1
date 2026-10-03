import { useState } from 'react';
import { Alert, Button, Input, Modal, Table } from 'antd';
import { ErrorNotice, usePagedList } from './common';
import { queryPath, useDebouncedValue } from './CatalogShared';
import type { ShipmentDraftLine } from './ShipmentSourceRows';

interface StockSource {
  id: string; purchase_line_id: string; product_id: string; internal_sku: string; product_name: string;
  purchase_number: string; supplier_name: string; remaining_quantity: number; units_per_carton: number | null;
}
export const stockSourceLabel = (stock: { supplier_name: string; purchase_number: string; id: string }) =>
  `供应商库存 · ${stock.supplier_name} · ${stock.purchase_number} · 批次 ${stock.id.slice(0, 8)}`;

export function StockPicker({ storeId, selected, onAdd, onClose }: {
  storeId: string; selected: string[]; onAdd: (line: ShipmentDraftLine) => void; onClose: () => void;
}) {
  const [search, setSearch] = useState('');
  const q = useDebouncedValue(search);
  const resource = usePagedList<StockSource>(queryPath('/supplier-stock', { store_id: storeId, q }));
  return <Modal open title="从供应商库存添加 SKU" width={920} footer={null} onCancel={onClose}>
    <Alert className="page-notice" type="info" title="选择 SKU 对应的库存批次，默认填入该批次全部可用余量。发货数量不能超过余量，保存后扣减所选批次；移除或减少时退回原批次。" />
    <Input allowClear placeholder="搜索 SKU、商品、供应商或采购单" value={search} onChange={event => setSearch(event.target.value)} style={{ marginBottom: 16 }} />
    <ErrorNotice error={resource.error} retry={resource.reload} />
    <Table<StockSource> rowKey="id" size="small" loading={resource.loading} dataSource={resource.data?.items ?? []} pagination={resource.pagination} columns={[
      { title: '商品 / SKU', render: (_, stock) => <>{stock.internal_sku}<div className="cell-secondary">{stock.product_name}</div></> },
      { title: '数量来源', render: (_, stock) => stockSourceLabel(stock) },
      { title: '可用数量', dataIndex: 'remaining_quantity' },
      { title: '操作', render: (_, stock) => <Button disabled={selected.includes(stock.id)} onClick={() => {
        onAdd({ supplier_stock_id: stock.id, purchase_line_id: stock.purchase_line_id, product_id: stock.product_id,
          quantity: stock.remaining_quantity, units_per_carton: stock.units_per_carton, available_quantity: stock.remaining_quantity,
          source_label: `${stock.internal_sku} · ${stock.product_name}｜${stockSourceLabel(stock)}` }); onClose();
      }}>{selected.includes(stock.id) ? '已添加' : '添加'}</Button> },
    ]} />
  </Modal>;
}

