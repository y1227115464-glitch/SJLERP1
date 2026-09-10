import { useState } from 'react';
import { Alert, Modal, Table } from 'antd';
import { api, errorText } from './api';
import { ErrorNotice } from './common';
import { requestId } from './SupplyShared';
import type { Shipment } from './supply-types';

export function ShipmentMerge({ records, onClose, onMerged }: { records: Shipment[]; onClose: () => void; onMerged: (id: string) => void }) {
  const [token] = useState(requestId);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const target = records[0];
  return <Modal open title={`合并 ${records.length} 张待发货件`} width={760} onCancel={saving ? undefined : onClose} closable={!saving} mask={{ closable: false }} confirmLoading={saving} okText="确认合并" onOk={async () => {
    setSaving(true); setError('');
    try {
      const result = await api<Shipment>('/shipments/merge', { method: 'POST', body: { request_id: token,
        shipment_ids: records.map(row => row.id), expected_versions: Object.fromEntries(records.map(row => [row.id, row.lines_version])) } });
      onMerged(result.id);
    } catch (cause) { setError(errorText(cause)); } finally { setSaving(false); }
  }}>
    <Alert type="info" showIcon title={`合并后保留货件 ${target.number}`} description="须为同店铺、同采购单或发货仓、同收货仓的待发货件。同商品箱规、物流资料和预计日期须一致。商品数量合计，原货件保留合并记录，库存占用总量保持不变。" style={{ marginBottom: 16 }} />
    <ErrorNotice error={error} />
    <Table<Shipment> rowKey="id" dataSource={records} pagination={{ pageSize: 5 }} columns={[
      { title: '货件', dataIndex: 'number' }, { title: '店铺', dataIndex: 'store_name' },
      { title: '路线', render: (_, row) => `${row.source_name} → ${row.destination_name}` },
      { title: '数量', render: (_, row) => row.lines.reduce((sum, line) => sum + line.quantity, 0) },
    ]} />
  </Modal>;
}
