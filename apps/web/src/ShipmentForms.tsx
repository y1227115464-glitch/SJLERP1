import { useEffect, useRef, useState } from 'react';
import { Alert, Col, Form, Input, Modal, Row, Select } from 'antd';
import { allocatedShipmentRows } from './shipment-grid';
import { api, errorText } from './api';
import { ErrorNotice } from './common';
import { activeWarehousesPath, options, QuantityInput, RemoteSelect, requestId, required, stageLabels, StoreField, storeParam } from './SupplyShared';
import { PurchaseMultiSelect, useShipmentPurchases } from './ShipmentPurchases';
import { ShipmentSourceRows, type ShipmentDraftLine } from './ShipmentSourceRows';
import type { PurchaseOrder, Shipment } from './supply-types';
import type { Store, User } from './types';

interface ShipmentValues { store_id: string; purchase_order_ids?: string[]; source_warehouse_id?: string; destination_warehouse_id?: string; carrier?: string; tracking_number?: string; amazon_shipment_id?: string; expected_date?: string; planned_ship_date?: string; notes?: string; lines: ShipmentDraftLine[] }
export function ShipmentEditor({ user, stores, selectedStore, purchase, onClose, onSaved }: { user: User; stores: Store[]; selectedStore: string; purchase?: PurchaseOrder; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm<ShipmentValues>();
  const [mode, setMode] = useState(purchase || user.permissions.includes('purchases.view') ? 'supplier' : 'warehouse');
  const [token] = useState(requestId);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [warehouseLabel, setWarehouseLabel] = useState('');
  const watchedStore = Form.useWatch('store_id', form);
  const watchedPurchases = Form.useWatch('purchase_order_ids', form) || [];
  const detail = useShipmentPurchases(mode === 'supplier' ? watchedPurchases : []);
  const previousOrders = useRef<string[]>([]);
  const remaining = detail.orders.flatMap(order => order.lines.filter(line => (line.unallocated_quantity ?? 0) > 0).map(line => ({ ...line, purchase_number: order.number, supplier_name: order.supplier_name, available_quantity: line.unallocated_quantity! })));
  useEffect(() => {
    if (mode !== 'supplier' || detail.loading || detail.error) return;
    const current: ShipmentValues['lines'] = form.getFieldValue('lines') || [];
    const allowed = new Set(detail.orders.flatMap(order => order.lines.map(line => line.id)));
    const retained = current.filter(line => line.supplier_stock_id || (line.purchase_line_id && allowed.has(line.purchase_line_id)));
    const added = detail.orders.filter(order => !previousOrders.current.includes(order.id)).flatMap(order =>
      order.lines.filter(line => (line.unallocated_quantity ?? 0) > 0).map(line => ({ purchase_line_id: line.id,
        product_id: line.product_id, quantity: line.unallocated_quantity!, units_per_carton: line.units_per_carton })));
    form.setFieldValue('lines', [...retained, ...added]);
    previousOrders.current = detail.orders.map(order => order.id);
  }, [detail.orders, detail.loading, detail.error, form, mode]);
  const changeMode = (value: string) => { setMode(value); previousOrders.current = []; form.setFieldsValue({ purchase_order_ids: [], source_warehouse_id: undefined, lines: value === 'supplier' ? [] : [{ product_id: '', quantity: 1 }] }); };
  const save = async (values: ShipmentValues) => {
    if (mode === 'supplier' && (detail.loading || detail.error)) return;
    setSaving(true); setError('');
    const body = { request_id: token, store_id: values.store_id, destination_warehouse_id: values.destination_warehouse_id,
      ...(mode === 'supplier' ? { purchase_order_ids: values.purchase_order_ids } : { source_warehouse_id: values.source_warehouse_id }),
      carrier: values.carrier || '', tracking_number: values.tracking_number || '', amazon_shipment_id: values.amazon_shipment_id || '',
      expected_date: values.expected_date || null, planned_ship_date: values.planned_ship_date || null, notes: values.notes || '', lines: allocatedShipmentRows(values.lines).map(line => ({ supplier_stock_id: line.supplier_stock_id, purchase_line_id: line.purchase_line_id, product_id: line.product_id, quantity: line.quantity, units_per_carton: line.units_per_carton })) };
    try { await api('/shipments', { method: 'POST', body }); onSaved(); }
    catch (cause) { setError(errorText(cause)); } finally { setSaving(false); }
  };
  return <Modal open title={purchase ? '安排供应商发货' : '新建发货计划'} width={1200} onCancel={saving ? undefined : onClose} closable={!saving} mask={{ closable: false }} onOk={() => form.submit()} confirmLoading={saving} okText="保存发货计划" okButtonProps={{ disabled: mode === 'supplier' && (detail.loading || !!detail.error) }}>
    <ErrorNotice error={error || detail.error} />
    <Alert type="info" showIcon className="page-notice" title={mode === 'supplier' ? '支持采购余量和供应商库存混合发货。同一 SKU 合并为一行，按采购单和供应商库存分列填写，共计自动汇总。' : '保存计划时占用可用库存；确认发出时扣减实物，接收后增加 FBA 仓库库存。'} />
    {!purchase && <Select aria-label="发货来源" value={mode} onChange={changeMode} style={{ width: '100%', marginBottom: 20 }} options={[{ value: 'warehouse', label: '已有仓库库存 → FBA仓库' }, ...(user.permissions.includes('purchases.view') ? [{ value: 'supplier', label: '供应商发货 → FBA仓库' }] : [])]} />}
    <Form form={form} layout="vertical" onFinish={save} initialValues={{ store_id: purchase?.store_id || storeParam(selectedStore), purchase_order_ids: purchase ? [purchase.id] : [], lines: mode === 'supplier' ? [] : [{ quantity: 1 }] }}
      onValuesChange={changes => { if ('store_id' in changes) { previousOrders.current = []; form.setFieldsValue({ purchase_order_ids: [], lines: mode === 'supplier' ? [] : [{ product_id: '', quantity: 1 }] }); } }}>
      <StoreField stores={stores} fixed={!!purchase} />
      <Row gutter={16}><Col span={12}>{mode === 'supplier' ? <Form.Item name="purchase_order_ids" label="采购单（可多选）" extra="也可不选采购单，直接从供应商库存添加 SKU。"><PurchaseMultiSelect storeId={watchedStore} selectedOrders={[...(purchase ? [purchase] : []), ...detail.orders]} /></Form.Item> : <Form.Item name="source_warehouse_id" label="发货仓库" rules={required}><RemoteSelect path={activeWarehousesPath} onRecord={warehouse => setWarehouseLabel(warehouse.name || warehouse.code || warehouse.id)} /></Form.Item>}</Col>
        <Col span={12}><Form.Item label="目的仓库"><Input value="FBA仓库" readOnly /></Form.Item></Col></Row>
      {mode === 'supplier' && watchedPurchases.length > 0 && <Alert className="page-notice" type={remaining.length || detail.loading ? 'info' : 'warning'} title={detail.loading ? '正在载入采购商品…' : `已选择 ${watchedPurchases.length} 个采购单，共 ${new Set(remaining.map(line => line.product_id)).size} 个可发 SKU；每个采购单对应一列。`} />}
      <ShipmentSourceRows form={form} supplier={mode === 'supplier'} storeId={watchedStore} purchaseLines={remaining} purchaseOrders={detail.orders} loading={detail.loading || !!detail.error} warehouseLabel={warehouseLabel} />
      <p className="catalog-field-help">本单箱规独立保存，后续商品箱规变更不会影响本单。采购余量不足整箱时，可调整本批数量或维护实际箱规。</p><LogisticsFields />
    </Form>
  </Modal>;
}

function LogisticsFields() {
  return <><Row gutter={16} style={{ marginTop: 20 }}><Col span={12}><Form.Item name="carrier" label="承运商 / 货代"><Input maxLength={120} /></Form.Item></Col><Col span={12}><Form.Item name="tracking_number" label="物流运单号"><Input maxLength={120} /></Form.Item></Col></Row>
    <Row gutter={16}><Col span={12}><Form.Item name="amazon_shipment_id" label="Amazon Shipment ID"><Input maxLength={120} /></Form.Item></Col><Col span={12}><Form.Item name="expected_date" label="预计到货日期"><Input type="date" /></Form.Item></Col></Row><Form.Item name="planned_ship_date" label="预计发货日" extra="关联采购单时，留空表示跟随所选采购单中最早的预计发货日。"><Input type="date" /></Form.Item><Form.Item name="notes" label="物流备注"><Input.TextArea rows={2} maxLength={5000} /></Form.Item></>;
}

export function LogisticsEditor({ shipment, onClose, onSaved }: { shipment: Shipment; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm(); const [saving, setSaving] = useState(false); const [error, setError] = useState('');
  return <Modal open title="维护物流资料" onCancel={saving ? undefined : onClose} closable={!saving} mask={{ closable: false }} onOk={() => form.submit()} confirmLoading={saving}>
    <ErrorNotice error={error} /><Form form={form} layout="vertical" initialValues={{ carrier: shipment.carrier, tracking_number: shipment.tracking_number, amazon_shipment_id: shipment.amazon_shipment_id, expected_date: shipment.expected_date || '', planned_ship_date: shipment.planned_ship_date || '', notes: shipment.notes }} onFinish={async values => {
      setSaving(true); setError(''); try { await api(`/shipments/${shipment.id}`, { method: 'PATCH', body: { ...values, expected_date: values.expected_date || null, planned_ship_date: values.planned_ship_date || null } }); onSaved(); }
      catch (cause) { setError(errorText(cause)); } finally { setSaving(false); }
    }}><LogisticsFields /></Form>
  </Modal>;
}

export function EventEditor({ shipment, onClose, onSaved }: { shipment: Shipment; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm(); const [token] = useState(requestId); const [saving, setSaving] = useState(false); const [error, setError] = useState('');
  return <Modal open title="登记发货进度" onCancel={saving ? undefined : onClose} closable={!saving} mask={{ closable: false }} onOk={() => form.submit()} confirmLoading={saving}>
    <ErrorNotice error={error} /><Form form={form} layout="vertical" initialValues={{ stage: shipment.stage in { customs: 1, delivered: 1, delayed: 1 } ? shipment.stage : 'in_transit' }} onFinish={async values => {
      setSaving(true); setError(''); try { await api(`/shipments/${shipment.id}/events`, { method: 'POST', body: { ...values, request_id: token } }); onSaved(); }
      catch (cause) { setError(errorText(cause)); } finally { setSaving(false); }
    }}><Form.Item name="stage" label="当前物流节点" rules={required}><Select options={options(Object.fromEntries(['in_transit', 'customs', 'delivered', 'delayed'].map(key => [key, stageLabels[key]])))} /></Form.Item><Form.Item name="notes" label="跟进说明" rules={required}><Input.TextArea rows={4} maxLength={2000} placeholder="记录运输节点、异常原因或下一步跟进事项" /></Form.Item></Form>
  </Modal>;
}

export function ReceiptEditor({ shipment, onClose, onSaved }: { shipment: Shipment; onClose: () => void; onSaved: () => void }) {
  const remaining = shipment.lines.filter(line => line.quantity > line.received_quantity);
  const [form] = Form.useForm<{ lines: { quantity: number }[]; notes?: string }>(); const [token] = useState(requestId); const [saving, setSaving] = useState(false); const [error, setError] = useState('');
  return <Modal open title="登记本次接收" width={760} onCancel={saving ? undefined : onClose} closable={!saving} mask={{ closable: false }} onOk={() => form.submit()} confirmLoading={saving} okText="确认接收并入库">
    <Alert type="info" showIcon className="page-notice" title={`接收到 ${shipment.destination_name}。仅填写本次实际收到的数量，未到货的行保留 0。`} />
    <ErrorNotice error={error} /><Form form={form} layout="vertical" initialValues={{ lines: remaining.map(() => ({ quantity: 0 })) }} onFinish={async values => {
      const lines = remaining.map((line, index) => ({ line_id: line.id, quantity: values.lines[index].quantity })).filter(line => line.quantity > 0);
      if (!lines.length) { setError('至少一行接收数量需要大于 0。'); return; }
      setSaving(true); setError(''); try { await api(`/shipments/${shipment.id}/receive`, { method: 'POST', body: { request_id: token, notes: values.notes || '', lines } }); onSaved(); }
      catch (cause) { setError(errorText(cause)); } finally { setSaving(false); }
    }}>{remaining.map((line, index) => <Row key={line.id} gutter={20} align="middle"><Col span={16}><strong>{line.product_name}</strong><p className="cell-secondary">{line.purchase_number ? `${line.purchase_number} · ` : ''}{line.internal_sku} · 已收 {line.received_quantity} / 发出 {line.quantity}</p></Col><Col span={8}><Form.Item name={['lines', index, 'quantity']} label={`本次接收（待收 ${line.quantity - line.received_quantity}）`} rules={required}><QuantityInput min={0} max={line.quantity - line.received_quantity} /></Form.Item></Col></Row>)}<Form.Item name="notes" label="接收备注"><Input.TextArea rows={2} maxLength={2000} /></Form.Item></Form>
  </Modal>;
}
