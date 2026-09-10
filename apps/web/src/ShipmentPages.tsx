import { useState } from 'react';
import { App as AntApp, Button, Card, Descriptions, Drawer, Input, Progress, Select, Space, Table, Tag, Timeline } from 'antd';
import { PlusOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import { api, errorText } from './api';
import { dateTime, EmptyState, ErrorNotice, PageHeading, usePagedList, useResource } from './common';
import { queryPath, useDebouncedValue } from './CatalogShared';
import { options, requestId, shipmentStatuses, stageLabels, StatusTag, storeParam } from './SupplyShared';
import { ShipmentLinesEditor } from './ShipmentLinesEditor';
import { ShipmentPackingEditor } from './ShipmentPackingEditor';
import { EventEditor, LogisticsEditor, ReceiptEditor, ShipmentEditor } from './ShipmentForms';
import { SourceTasks, useLinkedDetail } from './TaskShared';
import type { Shipment, ShipmentLine } from './supply-types';
import type { Store, User } from './types';

export function ShipmentsPage({ user, stores, selectedStore }: { user: User; stores: Store[]; selectedStore: string }) {
  const [q, setQ] = useState(''); const [status, setStatus] = useState<string>(); const query = useDebouncedValue(q);
  const resource = usePagedList<Shipment>(queryPath('/shipments', { store_id: storeParam(selectedStore), q: query, status }));
  const [creating, setCreating] = useState(false); const [detail, setDetail] = useLinkedDetail(); const [version, setVersion] = useState(0);
  return <><PageHeading eyebrow="SHIPMENT TRACKING" title="发货进度" description="跟进供应商来货与仓库发货，记录运单、运输节点、延期原因和分批接收。" extra={user.permissions.includes('shipments.manage') && <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>新建发货计划</Button>} />
    <ErrorNotice error={resource.error} retry={resource.reload} />
    <Card className="section-card" title="货件跟进" extra={<Button icon={<ReloadOutlined />} onClick={resource.reload}>刷新</Button>}>
      <div className="catalog-filter-bar"><Input className="catalog-search" prefix={<SearchOutlined />} placeholder="搜索货件号、物流运单或 Shipment ID" value={q} onChange={event => setQ(event.target.value)} allowClear /><Select placeholder="全部状态" value={status} onChange={setStatus} allowClear options={options(shipmentStatuses)} style={{ width: 170 }} /></div>
      <Table<Shipment> rowKey="id" dataSource={resource.data?.items ?? []} loading={resource.loading} pagination={resource.pagination} scroll={{ x: 1250 }} locale={{ emptyText: <EmptyState text="暂无货件。可从采购单安排供应商发货，或为已有库存建立仓库发货计划。" /> }} columns={[
        { title: '货件 / 店铺', width: 250, render: (_, item) => <><button className="catalog-title-link" onClick={() => setDetail(item.id)}>{item.number}</button><small className="cell-secondary">{item.store_name}</small></> },
        { title: '发货 → 接收', width: 190, render: (_, item) => <>{item.source_name}<small className="cell-secondary">→ {item.destination_name}</small></> },
        { title: '运单 / 承运商', width: 170, render: (_, item) => <>{item.tracking_number || '尚未登记'}<small className="cell-secondary">{item.carrier || '承运商未填写'}</small></> },
        { title: '物流节点', width: 130, render: (_, item) => <Tag color={item.stage === 'delayed' ? 'error' : 'default'}>{stageLabels[item.stage]}</Tag> },
        { title: '预计发货', dataIndex: 'planned_ship_date', width: 125, render: value => value || '未定日期' },
        { title: '预计到货', dataIndex: 'expected_date', width: 125, render: value => value || '—' },
        { title: '接收进度', width: 150, render: (_, item) => { const quantity = item.lines.reduce((sum, line) => sum + line.quantity, 0); const received = item.lines.reduce((sum, line) => sum + line.received_quantity, 0); return <><Progress size="small" percent={Math.round(received / quantity * 100)} /><small>{received} / {quantity} 件</small></>; } },
        { title: '状态', width: 170, render: (_, item) => <StatusTag status={item.status} labels={shipmentStatuses} overdue={item.overdue} /> },
        { title: '操作', width: 90, render: (_, item) => <Button type="link" onClick={() => setDetail(item.id)}>跟进</Button> },
      ]} />
    </Card>
    {creating && <ShipmentEditor user={user} stores={stores} selectedStore={selectedStore} onClose={() => setCreating(false)} onSaved={() => { setCreating(false); resource.reload(); }} />}
    {detail && <ShipmentDetails key={`${detail}:${version}`} id={detail} user={user} onClose={() => setDetail(null)} onChanged={() => { resource.reload(); setVersion(value => value + 1); }} />}
  </>;
}

function ShipmentDetails({ id, user, onClose, onChanged }: { id: string; user: User; onClose: () => void; onChanged: () => void }) {
  const resource = useResource<Shipment>(`/shipments/${id}`); const record = resource.data;
  const [packingLine, setPackingLine] = useState<ShipmentLine>();
  const [editing, setEditing] = useState<'logistics' | 'event' | 'receipt' | 'lines' | null>(null); const [error, setError] = useState('');
  const { modal, message } = AntApp.useApp();
  const canManage = user.permissions.includes('shipments.manage');
  const [actionTokens] = useState(() => ({ dispatch: requestId(), cancel: requestId() }));
  const action = (kind: 'dispatch' | 'cancel') => modal.confirm({ title: kind === 'dispatch' ? '确认货物已发出？' : '取消此待发货件？', content: kind === 'dispatch' ? '仓库发货将扣减实物库存，并开始计算在途数量。' : '未发出的货件会释放库存占用或采购分配数量。', onOk: async () => {
    try { await api(`/shipments/${id}/${kind}`, { method: 'POST', body: { request_id: actionTokens[kind] } }); message.success('货件已更新'); onChanged(); }
    catch (cause) { setError(errorText(cause)); throw cause; }
  } });
  return <Drawer open title="发货跟进详情" size={1080} onClose={onClose} loading={resource.loading}>
    <ErrorNotice error={resource.error || error} retry={resource.reload} />{record && <>
      <div className="supply-detail-heading"><div><h2>{record.number}</h2><StatusTag status={record.status} labels={shipmentStatuses} overdue={record.overdue} /></div><Space wrap>{canManage && <>
        {['planned', 'in_transit', 'partially_received'].includes(record.status) && <Button danger onClick={() => setEditing('lines')}>修改产品及数量（不建议操作）</Button>}
        {!['received', 'cancelled'].includes(record.status) && <Button onClick={() => setEditing('logistics')}>物流资料</Button>}
        {record.status === 'planned' && <><Button type="primary" onClick={() => action('dispatch')}>确认发出</Button><Button danger onClick={() => action('cancel')}>取消计划</Button></>}
        {['in_transit', 'partially_received'].includes(record.status) && <><Button onClick={() => setEditing('event')}>登记进度</Button><Button type="primary" onClick={() => setEditing('receipt')}>登记接收</Button></>}
      </>}</Space></div>
      <Descriptions bordered column={2} size="small" items={[
        { key: 'store', label: '所属店铺', children: record.store_name }, { key: 'route', label: '运输路线', children: `${record.source_name} → ${record.destination_name}` },
        { key: 'carrier', label: '承运商', children: record.carrier || '—' }, { key: 'tracking', label: '物流运单', children: record.tracking_number || '—' },
        { key: 'amazon', label: 'Shipment ID', children: record.amazon_shipment_id || '—' }, { key: 'expected', label: '预计到货', children: record.expected_date || '—' },
        { key: 'planned', label: '预计发货', children: record.planned_ship_date || (record.purchase_order_id ? '跟随采购单' : '未定日期'), span: 2 },
        { key: 'dispatch', label: '实际发出', children: dateTime(record.shipped_at) }, { key: 'receive', label: '收齐时间', children: dateTime(record.received_at) },
        { key: 'notes', label: '物流备注', children: record.notes || '—', span: 2 },
      ]} />
      <h3 className="catalog-section-title">本批商品</h3><Table rowKey="id" dataSource={record.lines} pagination={false} columns={[
        { title: '商品', render: (_, line) => <>{line.product_name}<small className="cell-secondary">{line.internal_sku}</small></> }, { title: '箱规（件/箱）', render: (_, line) => <>{line.units_per_carton ?? '未维护'}{canManage && record.status === 'planned' && <Button type="link" size="small" onClick={() => setPackingLine(line)}>修改箱规</Button>}</> }, { title: '箱数', render: (_, line) => line.carton_count ?? '未维护' }, { title: '本批数量', dataIndex: 'quantity' }, { title: '已接收', dataIndex: 'received_quantity' }, { title: '待接收', render: (_, line) => record.status === 'cancelled' ? '已取消' : line.quantity - line.received_quantity },
      ]} />
      <h3 className="catalog-section-title">物流跟进记录（最近 200 条）</h3><Timeline items={(record.events || []).map(item => ({ key: item.id, color: item.stage === 'delayed' ? 'red' : 'blue', content: <><strong>{stageLabels[item.stage] || item.stage}</strong><p className="catalog-prewrap">{item.notes}</p><small className="cell-secondary">{dateTime(item.created_at)} · {item.actor_name}</small></> }))} />
      <SourceTasks source={{ kind: 'shipment', id, number: record.number, store_id: record.store_id }} user={user} />
      {packingLine && <ShipmentPackingEditor shipment={record} line={packingLine} onClose={() => setPackingLine(undefined)} onSaved={onChanged} />}
      {editing === 'lines' && <ShipmentLinesEditor shipment={record} onClose={() => setEditing(null)} onSaved={onChanged} />}
      {editing === 'logistics' && <LogisticsEditor shipment={record} onClose={() => setEditing(null)} onSaved={onChanged} />}
      {editing === 'event' && <EventEditor shipment={record} onClose={() => setEditing(null)} onSaved={onChanged} />}
      {editing === 'receipt' && <ReceiptEditor shipment={record} onClose={() => setEditing(null)} onSaved={onChanged} />}
    </>}
  </Drawer>;
}
