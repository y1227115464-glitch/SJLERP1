import { useState } from 'react';
import { Alert, Form, Modal } from 'antd';
import { api, errorText } from './api';
import { ErrorNotice } from './common';
import { QuantityInput, required } from './SupplyShared';
import { cartonText } from './packing';
import type { Shipment, ShipmentLine } from './supply-types';

export function ShipmentPackingEditor({ shipment, line, onClose, onSaved }: { shipment: Shipment; line: ShipmentLine; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const size = Form.useWatch('units_per_carton', form);
  return <Modal open title={`修改本单箱规 · ${line.internal_sku}`} onCancel={saving ? undefined : onClose} closable={!saving} mask={{ closable: false }} onOk={() => form.submit()} confirmLoading={saving} okText="保存箱规">
    <Alert type="info" showIcon title={`本批 ${line.quantity} 件；仅修改此发货单的商品行。`} />
    <ErrorNotice error={error} /><Form form={form} layout="vertical" initialValues={{ units_per_carton: line.units_per_carton }} onFinish={async values => {
      setSaving(true); setError('');
      try { await api(`/shipments/${shipment.id}/lines/${line.id}`, { method: 'PATCH', body: values }); onSaved(); }
      catch (cause) { setError(errorText(cause)); } finally { setSaving(false); }
    }}><Form.Item name="units_per_carton" label="本单箱规（件/箱）" extra={cartonText(line.quantity, size)} rules={[...required, { validator: async (_, value) => { if (value && line.quantity % value !== 0) throw new Error('箱规必须能整除本批数量'); } }]}><QuantityInput /></Form.Item></Form>
  </Modal>;
}
