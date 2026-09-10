import { useState } from 'react';
import { Alert, Button, Col, Form, Input, Modal, Row, Select } from 'antd';
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons';
import { api, errorText } from './api';
import { cartonText } from './packing';
import { ErrorNotice, useResource } from './common';
import { activeWarehousesPath, options, QuantityInput, RemoteSelect, requestId, required, stageLabels, StoreField, storeParam } from './SupplyShared';
import type { PurchaseOrder, Shipment } from './supply-types';
import type { Store, User } from './types';

interface ShipmentValues { store_id: string; purchase_order_id?: string; source_warehouse_id?: string; destination_warehouse_id: string; carrier?: string; tracking_number?: string; amazon_shipment_id?: string; expected_date?: string; planned_ship_date?: string; notes?: string; lines: { product_id: string; quantity: number; units_per_carton?: number | null }[] }
export function ShipmentEditor({ user, stores, selectedStore, purchase, onClose, onSaved }: { user: User; stores: Store[]; selectedStore: string; purchase?: PurchaseOrder; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm<ShipmentValues>();
  const [mode, setMode] = useState(purchase ? 'supplier' : 'warehouse');
  const [token] = useState(requestId);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const rows = Form.useWatch('lines', form) || [];
  const watchedStore = Form.useWatch('store_id', form);
  const watchedPurchase = Form.useWatch('purchase_order_id', form);
  const detail = useResource<PurchaseOrder>(mode === 'supplier' && watchedPurchase && !purchase ? `/purchase-orders/${watchedPurchase}` : null);
  const chosenPurchase = purchase || detail.data;
  const remaining = chosenPurchase?.lines.filter(line => (line.unallocated_quantity ?? 0) > 0) ?? [];
  const changeMode = (value: string) => { setMode(value); form.setFieldsValue({ purchase_order_id: undefined, source_warehouse_id: undefined, lines: [{ product_id: '', quantity: 1 }] }); };
  const save = async (values: ShipmentValues) => {
    setSaving(true); setError('');
    const body = { request_id: token, store_id: values.store_id, destination_warehouse_id: values.destination_warehouse_id,
      ...(mode === 'supplier' ? { purchase_order_id: values.purchase_order_id } : { source_warehouse_id: values.source_warehouse_id }),
      carrier: values.carrier || '', tracking_number: values.tracking_number || '', amazon_shipment_id: values.amazon_shipment_id || '',
      expected_date: values.expected_date || null, planned_ship_date: values.planned_ship_date || null, notes: values.notes || '', lines: values.lines };
    try { await api('/shipments', { method: 'POST', body }); onSaved(); }
    catch (cause) { setError(errorText(cause)); } finally { setSaving(false); }
  };
  return <Modal open title={purchase ? '安排供应商发货' : '新建发货计划'} width={960} onCancel={saving ? undefined : onClose} closable={!saving} mask={{ closable: false }} onOk={() => form.submit()} confirmLoading={saving} okText="保存发货计划">
    <ErrorNotice error={error || detail.error} />
    <Alert type="info" showIcon className="page-notice" title={mode === 'supplier' ? '从采购余量中安排本批发货，接收后计入目的仓库存。' : '保存计划时占用可用库存；确认发出时扣减实物，接收后增加目的仓库存。'} />
    {!purchase && <Select aria-label="发货来源" value={mode} onChange={changeMode} style={{ width: '100%', marginBottom: 20 }} options={[{ value: 'warehouse', label: '仓库发货 → FBA / 其他仓' }, ...(user.permissions.includes('purchases.view') ? [{ value: 'supplier', label: '供应商发货 → 仓库 / FBA' }] : [])]} />}
    <Form form={form} layout="vertical" onFinish={save} initialValues={{ store_id: purchase?.store_id || storeParam(selectedStore), purchase_order_id: purchase?.id,
      lines: purchase ? purchase.lines.filter(line => (line.unallocated_quantity ?? 0) > 0).map(line => ({ product_id: line.product_id, quantity: line.unallocated_quantity, units_per_carton: line.units_per_carton })) : [{ quantity: 1 }] }}
      onValuesChange={changes => { if ('store_id' in changes || 'purchase_order_id' in changes) form.setFieldsValue({ ...('store_id' in changes ? { purchase_order_id: undefined } : {}), lines: [{ product_id: '', quantity: 1 }] }); }}>
      <StoreField stores={stores} fixed={!!purchase} />
      <Row gutter={16}><Col span={12}>{mode === 'supplier' ? <Form.Item name="purchase_order_id" label="采购单" rules={required}><RemoteSelect path={watchedStore ? `/purchase-orders?store_id=${watchedStore}&shippable=true` : null} disabled={!!purchase} initialLabel={purchase?.number} placeholder="选择已提交且有可分配余量的采购单" /></Form.Item> : <Form.Item name="source_warehouse_id" label="发货仓库" rules={required}><RemoteSelect path={activeWarehousesPath} /></Form.Item>}</Col>
        <Col span={12}><Form.Item name="destination_warehouse_id" label="目的仓库" rules={required}><RemoteSelect path={activeWarehousesPath} /></Form.Item></Col></Row>
      {mode === 'supplier' && chosenPurchase && <Alert className="page-notice" type={remaining.length ? 'info' : 'warning'} title={remaining.length ? `采购单 ${chosenPurchase.number}：选择商品并填写本批发货数量。` : '此采购单没有可安排数量，请检查状态或已有货件。'} />}
      <Form.List name="lines" rules={[{ validator: async (_, lines) => { if (!lines?.length) throw new Error('至少添加一行商品'); } }]}>{(fields, { add, remove }, { errors }) => <>
        {fields.map(field => <Row key={field.key} gutter={12} align="middle"><Col span={10}><Form.Item name={[field.name, 'product_id']} label="商品 / SKU" rules={required}>{mode === 'supplier' ? <Select showSearch optionFilterProp="label" onChange={id => form.setFieldValue(['lines', field.name, 'units_per_carton'], remaining.find(line => line.product_id === id)?.units_per_carton)} placeholder="从采购余量选择商品" options={remaining.map(line => ({ value: line.product_id, label: `${line.internal_sku} · ${line.product_name_zh || line.product_name}（可安排 ${line.unallocated_quantity}）` }))} /> : <RemoteSelect path="/products?is_active=true" onRecord={product => form.setFieldValue(['lines', field.name, 'units_per_carton'], product.units_per_carton)} />}</Form.Item></Col><Col span={6}><Form.Item name={[field.name, 'units_per_carton']} label="本单箱规（件/箱）" rules={required}><QuantityInput /></Form.Item></Col><Col span={6}><Form.Item name={[field.name, 'quantity']} label="本批数量（件）" dependencies={[['lines', field.name, 'units_per_carton']]} extra={cartonText(rows[field.name]?.quantity || 0, rows[field.name]?.units_per_carton)} rules={[...required, { validator: async (_, value) => { const size = form.getFieldValue(['lines', field.name, 'units_per_carton']); if (size && value % size !== 0) throw new Error(`数量须为 ${size} 的整数倍`); } }]}><QuantityInput /></Form.Item></Col><Col span={2}><Button aria-label="移除发货行" type="text" icon={<MinusCircleOutlined />} onClick={() => remove(field.name)} /></Col></Row>)}
        <Form.ErrorList errors={errors} /><Button block type="dashed" icon={<PlusOutlined />} disabled={fields.length >= 100} onClick={() => add({ quantity: 1 })}>添加发货商品</Button>
      </>}</Form.List>
      <p className="catalog-field-help">本单箱规独立保存，后续商品箱规变更不会影响本单。采购余量不足整箱时，可调整本批数量或维护实际箱规。</p><LogisticsFields />
    </Form>
  </Modal>;
}

function LogisticsFields() {
  return <><Row gutter={16} style={{ marginTop: 20 }}><Col span={12}><Form.Item name="carrier" label="承运商 / 货代"><Input maxLength={120} /></Form.Item></Col><Col span={12}><Form.Item name="tracking_number" label="物流运单号"><Input maxLength={120} /></Form.Item></Col></Row>
    <Row gutter={16}><Col span={12}><Form.Item name="amazon_shipment_id" label="Amazon Shipment ID"><Input maxLength={120} /></Form.Item></Col><Col span={12}><Form.Item name="expected_date" label="预计到货日期"><Input type="date" /></Form.Item></Col></Row><Form.Item name="planned_ship_date" label="预计发货日" extra="关联采购单时，留空表示跟随采购单的预计发货日。"><Input type="date" /></Form.Item><Form.Item name="notes" label="物流备注"><Input.TextArea rows={2} maxLength={5000} /></Form.Item></>;
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
    }}>{remaining.map((line, index) => <Row key={line.id} gutter={20} align="middle"><Col span={16}><strong>{line.product_name}</strong><p className="cell-secondary">{line.internal_sku} · 已收 {line.received_quantity} / 发出 {line.quantity}</p></Col><Col span={8}><Form.Item name={['lines', index, 'quantity']} label={`本次接收（待收 ${line.quantity - line.received_quantity}）`} rules={required}><QuantityInput min={0} max={line.quantity - line.received_quantity} /></Form.Item></Col></Row>)}<Form.Item name="notes" label="接收备注"><Input.TextArea rows={2} maxLength={2000} /></Form.Item></Form>
  </Modal>;
}
