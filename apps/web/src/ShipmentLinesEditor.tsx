import { useEffect, useRef, useState } from 'react';
import { Alert, Col, Form, Input, Modal, Row } from 'antd';
import { allocatedShipmentRows } from './shipment-grid';
import { api, errorText } from './api';
import { ErrorNotice } from './common';
import { requestId } from './SupplyShared';
import { ShipmentSourceRows, stockSourceLabel, type ShipmentDraftLine } from './ShipmentSourceRows';
import { PurchaseMultiSelect, useShipmentPurchases } from './ShipmentPurchases';
import type { Shipment } from './supply-types';

interface Values { purchase_order_ids?: string[]; reason?: string; lines: ShipmentDraftLine[] }

export function ShipmentLinesEditor({ shipment, onClose, onSaved }: { shipment: Shipment; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm<Values>();
  const [token] = useState(requestId);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const supplier = !!shipment.purchase_order_id;
  const selectedIds = Form.useWatch('purchase_order_ids', form) ?? shipment.purchase_order_ids;
  const purchase = useShipmentPurchases(supplier ? selectedIds : []);
  const previousOrders = useRef(shipment.purchase_order_ids);
  const lockedIds = shipment.purchase_orders.filter(order => shipment.lines.some(line => line.purchase_number === order.number && line.received_quantity > 0)).map(order => order.id);
  const purchaseLines = purchase.orders.flatMap(order => order.lines.map(line => ({ ...line, purchase_number: order.number, supplier_name: order.supplier_name,
    available_quantity: (line.unallocated_quantity ?? 0) + (shipment.lines.find(original => !original.supplier_stock_id && original.purchase_line_id === line.id)?.quantity ?? 0),
  })).filter(line => line.available_quantity > 0));
  useEffect(() => {
    if (!supplier || purchase.loading || purchase.error) return;
    const current: Values['lines'] = form.getFieldValue('lines') || [];
    const allowed = new Set(purchase.orders.flatMap(order => order.lines.map(line => line.id)));
    const retained = current.filter(line => line.supplier_stock_id || (line.purchase_line_id && allowed.has(line.purchase_line_id)));
    const added = purchase.orders.filter(order => !previousOrders.current.includes(order.id)).flatMap(order => order.lines.flatMap(line => {
      const original = shipment.lines.find(item => !item.supplier_stock_id && item.purchase_line_id === line.id);
      const quantity = (line.unallocated_quantity ?? 0) + (original?.quantity ?? 0);
      return quantity > 0 ? [{ purchase_line_id: line.id, product_id: line.product_id, quantity, units_per_carton: original?.units_per_carton ?? line.units_per_carton }] : [];
    }));
    form.setFieldValue('lines', [...retained, ...added]);
    previousOrders.current = purchase.orders.map(order => order.id);
  }, [purchase.orders, purchase.loading, purchase.error, form, supplier, shipment.lines]);
  return <Modal open title="修改发货产品及数量（不建议操作）" width={1200} onCancel={saving ? undefined : onClose} closable={!saving} mask={{ closable: false }} onOk={() => form.submit()} confirmLoading={saving} okText="保存修改" okButtonProps={{ danger: true, disabled: !!shipment.purchase_order_id && (purchase.loading || !!purchase.error) }}>
    <Alert className="page-notice" type="warning" showIcon title="不建议操作：仅在确认发货记录有误时修改" description="保存会调整采购分配、库存占用或已发出数量，并写入跟进记录。已接收的商品不能移除或替换，数量不得低于已接收数。请核对实际发货和 Amazon 货件资料。" />
    <ErrorNotice error={error || purchase.error} />
    <Form form={form} layout="vertical" initialValues={{ purchase_order_ids: shipment.purchase_order_ids, lines: shipment.lines.map(line => ({ supplier_stock_id: line.supplier_stock_id, purchase_line_id: line.purchase_line_id, product_id: line.product_id, quantity: line.quantity, units_per_carton: line.units_per_carton,
        available_quantity: line.supplier_stock_id ? (line.supplier_stock_remaining_quantity || 0) + line.quantity : undefined,
        source_label: line.supplier_stock_id ? `${line.internal_sku} · ${line.product_name}｜${stockSourceLabel({ id: line.supplier_stock_id, supplier_name: line.supplier_name || '', purchase_number: line.purchase_number || '' })}` : undefined })) }} onFinish={async values => {
      if (supplier && (purchase.loading || purchase.error)) return;
      setSaving(true); setError('');
      try { await api(`/shipments/${shipment.id}/lines`, { method: 'PATCH', body: {
        request_id: token, expected_version: shipment.lines_version, reason: values.reason || '',
        ...(supplier ? { purchase_order_ids: values.purchase_order_ids } : {}),
        lines: allocatedShipmentRows(values.lines).map(line => ({ supplier_stock_id: line.supplier_stock_id, purchase_line_id: line.purchase_line_id, product_id: line.product_id, quantity: line.quantity, units_per_carton: line.units_per_carton })),
      } }); onSaved(); } catch (cause) { setError(errorText(cause)); } finally { setSaving(false); }
    }}>
      <Row gutter={16}><Col span={12}><Form.Item label="所属店铺"><Input value={shipment.store_name} readOnly /></Form.Item></Col>
        <Col span={12}><Form.Item label="发货来源"><Input value={supplier ? '供应商发货' : shipment.source_name} readOnly /></Form.Item></Col></Row>
      <Row gutter={16}><Col span={12}>{supplier ? <Form.Item name="purchase_order_ids" label="采购单（可多选）" extra={lockedIds.length ? '已有接收记录的采购单不可移除。' : '新增采购单会自动带入全部可发商品，取消选择会移除对应采购余量行；供应商库存行需单独移除。'}>
        <PurchaseMultiSelect storeId={shipment.store_id} selectedOrders={[...shipment.purchase_orders, ...purchase.orders]} lockedIds={lockedIds} disabled={saving} />
      </Form.Item> : <Form.Item label="发货仓库"><Input value={shipment.source_name} readOnly /></Form.Item>}</Col>
        <Col span={12}><Form.Item label="目的仓库"><Input value={shipment.destination_name} readOnly /></Form.Item></Col></Row>
      {supplier && <Alert className="page-notice" type="info" title={purchase.loading ? '正在载入采购商品…' : `已选择 ${selectedIds.length} 个采购单；原有商品数量保留，新增采购单默认带入全部可发商品。`} />}
      <ShipmentSourceRows form={form} supplier={supplier} storeId={shipment.store_id} purchaseLines={purchaseLines} purchaseOrders={purchase.orders} loading={purchase.loading || !!purchase.error} shipment={shipment} warehouseLabel={shipment.source_name} />
      <Form.Item name="reason" label="修改说明" style={{ marginTop: 20 }}><Input.TextArea rows={2} maxLength={1000} placeholder="说明实际发货与原记录的差异，供后续跟进核对" /></Form.Item>
    </Form>
  </Modal>;
}
